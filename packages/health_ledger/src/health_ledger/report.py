"""The forecasting results page, computed exactly as `docs/ledger/analysis-plan.md` fixes it.

Builds on the scoreboard (skill with the paired moving-block bootstrap, randomized PIT bins)
and adds what a results page needs:

- **DM-HLN**: Diebold-Mariano test on the daily RPS loss differential with the
  Harvey-Leybourne-Newbold small-sample correction and Student-t p-values (h = 1, one-day
  ahead). A negative statistic means the forecaster's loss is lower than the reference's.
- **Reliability with a consistency band**: the 5 PIT bin counts next to the 95% range those
  counts would have if the forecaster were perfectly calibrated (seeded multinomial draws).
- **Sharpness**: the mean standard deviation of each forecaster's distributions.

Comparisons with fewer than 10 paired days say "not yet" with the real n. The page carries
aggregates only, rounded to 2 decimals like the public board: no dates and no daily values.
No scipy: the t distribution comes from the regularized incomplete beta function.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from collections.abc import Sequence

import numpy as np

from . import dist, scoreboard

SEED = 20261023
BINS = 5
MIN_N = scoreboard.PRIMARY_MIN_N


# --- Student t via the regularized incomplete beta (Numerical Recipes continued fraction) ---

def _betacf(a: float, b: float, x: float) -> float:
    tiny, qab, qap, qam = 1e-300, a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_sf(t: float, df: float) -> float:
    """P(T > t) for Student's t with `df` degrees of freedom."""
    tail = 0.5 * betainc(df / 2.0, 0.5, df / (df + t * t))
    return tail if t >= 0 else 1.0 - tail


def dm_hln(d: Sequence[float], h: int = 1) -> tuple[float, float]:
    """(statistic, two-sided p) of the DM test with the HLN correction on loss differences d."""
    x = np.asarray(d, dtype=float)
    n = len(x)
    if n < 2:
        return 0.0, 1.0
    mean = float(x.mean())
    dev = x - mean
    gamma = [float((dev[k:] * dev[:n - k]).sum() / n) for k in range(h)]
    var = (gamma[0] + 2 * sum(gamma[1:])) / n
    if var <= 0:
        return (0.0, 1.0) if mean == 0 else (math.copysign(math.inf, mean), 0.0)
    stat = mean / math.sqrt(var) * math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    return stat, min(1.0, 2.0 * t_sf(abs(stat), n - 1))


def reliability(pairs: Sequence[tuple[dist.Dist, int]], bins: int = BINS, sims: int = 2000,
                seed: int = SEED) -> list[dict]:
    """PIT bin counts with the 95% band each count would have under perfect calibration."""
    counted = dist.calibration_bins(pairs, bins=bins, seed=seed)
    n = len(pairs)
    draws = np.random.default_rng(seed).multinomial(n, [1 / bins] * bins, size=sims)
    lo, hi = np.percentile(draws, [2.5, 97.5], axis=0)
    return [{**b, "band_lo": int(math.floor(lo[i])), "band_hi": int(math.ceil(hi[i]))}
            for i, b in enumerate(counted)]


def _sd(p: Sequence[float]) -> float:
    ks = range(1, len(p) + 1)
    mu = sum(k * q for k, q in zip(ks, p, strict=True))
    return math.sqrt(sum(q * (k - mu) ** 2 for k, q in zip(ks, p, strict=True)))


def build(conn: sqlite3.Connection) -> dict:
    board = scoreboard.build(conn)
    rps: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    pairs: dict[tuple[str, str], list] = defaultdict(list)
    sds: dict[tuple[str, str], list[float]] = defaultdict(list)
    for day, forecaster, target, outcome, score, probs_json in conn.execute(
            """SELECT s.day, s.forecaster, s.target, s.outcome, s.rps, f.probs_json
               FROM scores s JOIN forecasts f USING (day, forecaster, target)
               ORDER BY s.day, s.forecaster, s.target"""):
        p = dist.normalize(json.loads(probs_json))
        rps[(forecaster, target)][day] = score
        pairs[(forecaster, target)].append((p, outcome))
        sds[(forecaster, target)].append(_sd(p))

    def with_dm(comparison: dict) -> dict:
        mine = rps.get((comparison["forecaster"], comparison["target"]), {})
        ref = rps.get((comparison["reference"], comparison["target"]), {})
        days = sorted(set(mine) & set(ref))
        dm = list(dm_hln([mine[d] - ref[d] for d in days])) if len(days) >= MIN_N else None
        return {**comparison, "dm": dm}

    primary = with_dm({**board["primary"],
                       "skill_vs_reference": board["primary"]["skill_vs_persistence"]})
    return {
        "days_locked": board["days_locked"], "days_scored": board["days_scored"],
        "days_voided": board["days_voided"], "days_no_outcome": board["days_no_outcome"],
        "primary": primary,
        "secondary": [with_dm(c) for c in board["secondary"]],
        "forecasters": board["forecasters"],
        "sharpness": [{"id": f, "target": t, "n": len(v), "sd": sum(v) / len(v)}
                      for (f, t), v in sorted(sds.items())],
        "reliability": [{"id": f, "target": t, "n": len(v), "bins": reliability(v)}
                        for (f, t), v in sorted(pairs.items())],
    }


# --- rendering: Markdown with inline SVG, aggregates only, 2 decimals ---

def _f(x: float | None) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.2f}"


def _p(p: float) -> str:
    return "< 0.01" if p < 0.01 else f"{p:.2f}"


def _comparison_line(c: dict) -> str:
    n = c["n"]
    if c.get("skill_vs_reference") is None:
        return f"not yet: n = {n} paired days (the plan reports from {MIN_N})"
    point, lo, hi = c["skill_vs_reference"]
    line = f"RPS skill {_f(point)} (95% CI {_f(lo)} to {_f(hi)}), n = {n}"
    if c.get("dm"):
        stat, p = c["dm"]
        line += f"; DM-HLN {_f(stat)}, p {_p(p)}"
    return line


def _svg(bins: list[dict], n: int) -> str:
    w, h, pad, bw = 250, 110, 20, 40
    top = max([b["count"] for b in bins] + [b["band_hi"] for b in bins] + [1])
    scale = (h - 2 * pad) / top
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
             f'role="img" aria-label="PIT histogram, n = {n}">']
    for i, b in enumerate(bins):
        x = pad + i * (bw + 4)
        y_lo, y_hi = h - pad - round(b["band_lo"] * scale), h - pad - round(b["band_hi"] * scale)
        bar = round(b["count"] * scale)
        parts.append(f'<rect x="{x}" y="{y_hi}" width="{bw}" height="{max(1, y_lo - y_hi)}" '
                     f'fill="#9aa7b8" fill-opacity="0.35"/>')
        parts.append(f'<rect x="{x + 8}" y="{h - pad - bar}" width="{bw - 16}" height="{bar}" '
                     f'fill="#3366aa"/>')
        parts.append(f'<text x="{x + bw // 2}" y="{h - 5}" font-size="10" '
                     f'text-anchor="middle">{b["count"]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def render(rep: dict) -> str:
    out = ["# Forecasting results", "",
           "Live locked forecasts only, scored by the pre-registered plan "
           "(`docs/ledger/analysis-plan.md`, its hash is the ledger's genesis entry). Aggregates "
           "only, rounded to 2 decimals; the real number of days is next to every number. "
           "Skill is 1 − mean RPS / reference mean RPS (positive is better); the interval is the "
           "paired moving-block bootstrap (block 7, 2000 resamples). DM-HLN is the "
           "Diebold-Mariano test with the Harvey-Leybourne-Newbold correction on the daily RPS "
           "difference (negative favours the forecaster).", "",
           f"Days locked: {rep['days_locked']} · scored: {rep['days_scored']} · void: "
           f"{rep['days_voided']} · no outcome: {rep['days_no_outcome']}", "",
           "## Primary endpoint", "",
           f"Energy, `{rep['primary']['forecaster']}` vs persistence: "
           f"{_comparison_line(rep['primary'])}.", "",
           "## Secondary comparisons", "", "| Target | Forecaster | Reference | Result |",
           "|---|---|---|---|"]
    for c in rep["secondary"]:
        out.append(f"| {c['target']} | `{c['forecaster']}` | `{c['reference']}` | "
                   f"{_comparison_line(c)} |")
    out += ["", "## Every forecaster", "",
            "| Forecaster | Target | n | Mean RPS | Skill vs climatology | Skill vs persistence |"
            " Mean log score |", "|---|---|---|---|---|---|---|"]
    # Below MIN_N days a "mean" is close to a daily value (and with the bet, the outcome),
    # so rows show their n and "not yet" instead of numbers.
    wait = f"not yet (from {MIN_N} days)"
    for r in rep["forecasters"]:
        def sk(ref: str, row: dict = r) -> str:
            s = row.get(f"skill_vs_{ref}")
            if not s:
                return "–"
            return f"{_f(s['skill'])} (n = {s['n']})" if s["n"] >= MIN_N else f"not yet (n = {s['n']})"
        if r["n"] < MIN_N:
            out.append(f"| `{r['id']}` | {r['target']} | n = {r['n']} | {wait} | – | – | – |")
            continue
        out.append(f"| `{r['id']}` | {r['target']} | n = {r['n']} | {_f(r['mean_rps'])} | "
                   f"{sk('climatology')} | {sk('persistence')} | {_f(r['mean_log_score'])} |")
    out += ["", "## Sharpness", "", "Mean standard deviation of the forecast distributions "
            "(lower is sharper; sharp is only good when calibrated).", "",
            "| Forecaster | Target | n | Mean sd |", "|---|---|---|---|"]
    out += [f"| `{s['id']}` | {s['target']} | n = {s['n']} | "
            f"{_f(s['sd']) if s['n'] >= MIN_N else wait} |" for s in rep["sharpness"]]
    out += ["", "## Calibration", "", "Randomized PIT histograms in 5 bins (blue), with the "
            "range a perfectly calibrated forecaster would fall in 95% of the time (grey).", ""]
    for r in rep["reliability"]:
        if r["n"] < MIN_N:
            out.append(f"- `{r['id']}` {r['target']}: not yet (n = {r['n']})")
        else:
            out += [f"### `{r['id']}` {r['target']} (n = {r['n']})", "", _svg(r["bins"], r["n"]), ""]
    if not rep["reliability"]:
        out.append("No scored days yet (n = 0).")
    return "\n".join(out) + "\n"
