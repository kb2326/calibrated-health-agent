# Forecasting results

Live locked forecasts only, scored by the pre-registered plan (`docs/ledger/analysis-plan.md`, its hash is the ledger's genesis entry). Aggregates only, rounded to 2 decimals; the real number of days is next to every number. Skill is 1 − mean RPS / reference mean RPS (positive is better); the interval is the paired moving-block bootstrap (block 7, 2000 resamples). DM-HLN is the Diebold-Mariano test with the Harvey-Leybourne-Newbold correction on the daily RPS difference (negative favours the forecaster).

Days locked: 2 · scored: 1 · void: 0 · no outcome: 0

## Primary endpoint

Energy, `gemini:gemini-3.5-flash-lite` vs persistence: not yet: n = 1 paired days (the plan reports from 10).

## Secondary comparisons

| Target | Forecaster | Reference | Result |
|---|---|---|---|
| mood | `gemini:gemini-3.5-flash-lite` | `persistence` | not yet: n = 1 paired days (the plan reports from 10) |
| soreness | `gemini:gemini-3.5-flash-lite` | `persistence` | not yet: n = 1 paired days (the plan reports from 10) |
| energy | `gemini_notes:gemini-3.5-flash-lite` | `gemini:gemini-3.5-flash-lite` | not yet: n = 0 paired days (the plan reports from 10) |

## Every forecaster

| Forecaster | Target | n | Mean RPS | Skill vs climatology | Skill vs persistence | Mean log score |
|---|---|---|---|---|---|---|
| `climatology` | energy | n = 1 | not yet (from 10 days) | – | – | – |
| `climatology` | mood | n = 1 | not yet (from 10 days) | – | – | – |
| `climatology` | soreness | n = 1 | not yet (from 10 days) | – | – | – |
| `gemini:gemini-3.5-flash-lite` | energy | n = 1 | not yet (from 10 days) | – | – | – |
| `gemini:gemini-3.5-flash-lite` | mood | n = 1 | not yet (from 10 days) | – | – | – |
| `gemini:gemini-3.5-flash-lite` | soreness | n = 1 | not yet (from 10 days) | – | – | – |
| `persistence` | energy | n = 1 | not yet (from 10 days) | – | – | – |
| `persistence` | mood | n = 1 | not yet (from 10 days) | – | – | – |
| `persistence` | soreness | n = 1 | not yet (from 10 days) | – | – | – |

## Sharpness

Mean standard deviation of the forecast distributions (lower is sharper; sharp is only good when calibrated).

| Forecaster | Target | n | Mean sd |
|---|---|---|---|
| `climatology` | energy | n = 1 | not yet (from 10 days) |
| `climatology` | mood | n = 1 | not yet (from 10 days) |
| `climatology` | soreness | n = 1 | not yet (from 10 days) |
| `gemini:gemini-3.5-flash-lite` | energy | n = 1 | not yet (from 10 days) |
| `gemini:gemini-3.5-flash-lite` | mood | n = 1 | not yet (from 10 days) |
| `gemini:gemini-3.5-flash-lite` | soreness | n = 1 | not yet (from 10 days) |
| `persistence` | energy | n = 1 | not yet (from 10 days) |
| `persistence` | mood | n = 1 | not yet (from 10 days) |
| `persistence` | soreness | n = 1 | not yet (from 10 days) |

## Calibration

Randomized PIT histograms in 5 bins (blue), with the range a perfectly calibrated forecaster would fall in 95% of the time (grey).

- `climatology` energy: not yet (n = 1)
- `climatology` mood: not yet (n = 1)
- `climatology` soreness: not yet (n = 1)
- `gemini:gemini-3.5-flash-lite` energy: not yet (n = 1)
- `gemini:gemini-3.5-flash-lite` mood: not yet (n = 1)
- `gemini:gemini-3.5-flash-lite` soreness: not yet (n = 1)
- `persistence` energy: not yet (n = 1)
- `persistence` mood: not yet (n = 1)
- `persistence` soreness: not yet (n = 1)
