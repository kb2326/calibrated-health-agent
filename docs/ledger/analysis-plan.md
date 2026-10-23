# Forecast ledger: pre-registered analysis plan

Version 1, fixed 2026-10-23 before the first locked forecast. The sha256 of this file
(LF line endings) is the first entry of the ledger's hash chain, and that chain's daily
hashes are published at https://github.com/kb2326/cha-ledger-log. Any change to this plan
after the first lock changes the genesis hash and is therefore visible.

## Question

Can an AI agent predict one person's evening self-ratings better than simple rules, and
(from Phase 3) does reading its own notes on past misses make it better?

## Targets

The owner's evening journal for civil day D (Asia/Kolkata): mood, energy and soreness,
each an integer 1..10. Every forecast is a probability distribution over 1..10.

## Timing and outcome rules

- The lock for day D happens at the first run on D after last night's sleep record
  arrives, or at the first run at or after 12:00 owner time (a deadline lock, which records
  the missing inputs). Only the current day is locked; a missed lock is a missed day.
- Forecasts for D may use wearable data through the sleep that ended on the morning of D
  and journal outcomes through D-1. Nothing later.
- The scored outcome for D is the first valid journal submission for D. If it was
  submitted before D's lock, the day is void. If no valid outcome exists by D+1 06:00
  owner time, the day is recorded as no outcome. Neither void nor missing days are scored.
- Unscored forecasts are hidden from the owner (blinding) until the day is settled.

## Forecasters (live from the first lock)

1. climatology: Dirichlet-smoothed distribution of all past outcomes (prior 1 per score).
2. persistence: latest outcome from D-1..D-3, spread by the empirical distribution of
   day-to-day changes (prior weights: -1: 1, 0: 2, +1: 1).
3. seasonal_naive: outcome on D-7, same spread.
4. statistical: least squares of outcome on the open readiness score (at least 14 pairs),
   discretized normal with the residual sd (floored at 0.5).
5. timesfm: TimesFM via BigQuery AI.FORECAST on the outcome history (at least 14
   outcomes), 80% interval mapped to a discretized normal.
6. gemini:<model>: Gemini on Vertex AI, temperature 0, given exactly the shared feature
   snapshot. A model change is a new forecaster.

A forecaster that cannot bet abstains with a reason. Abstentions are recorded, never
filled in, and a day where a forecaster abstained is excluded from its comparisons.

## Scores

- Ranked probability score (RPS), primary; log score, secondary. Probabilities are
  floored at 1e-4.
- Skill vs a reference = 1 - mean score / mean reference score, over days both scored.

## Primary endpoint

Energy: RPS skill of the Gemini forecaster vs persistence, with a 95% interval from a
paired moving-block bootstrap (block length 7 days, 2000 resamples, seed 20261023).
Reported only once at least 10 paired days exist; until then the scoreboard says so.

## Secondary endpoints

- Mood and soreness: the same comparison.
- Every forecaster's RPS skill vs climatology and vs persistence, per target.
- Log scores.
- Calibration: randomized PIT histograms in 5 bins.
- From Phase 3: forecaster 7 (Gemini plus the investigator's hypotheses, otherwise
  identical to 6) vs forecaster 6, on energy RPS, same interval method.

## Honesty rules

- Results are published as they are, including forecasters that lose to persistence.
- The real number of scored days is shown next to every number.
- Live locked forecasts only; any backtest appears separately and labelled.
- Public outputs carry aggregates and hashes only, never daily values.
