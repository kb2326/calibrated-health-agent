# Data notes

Percentages and counts only; no personal values.

## Rollup vs reconcile parity (2026-10-20, last 14 civil days)

The stored daily value is `dailyRollUp`; `dataPoints.reconcile` is the independent
re-derivation. A worn day is one where reconcile returned data; agreement is within 2%.

| type | worn days compared | agreement |
|---|---|---|
| steps | 7 | 100% |
| distance | 7 | 100% |
| active-minutes | 1 | 100% |
| active-zone-minutes | 1 | 100% |
| floors | 6 | 100% |
| total-calories | n/a | the API does not support reconcile for this type (rollup and dailyRollUp only) |

No disagreements. Active-minutes and active-zone-minutes have a single worn day in the
window, so their 100% is weak evidence; re-run when more days accumulate.

## Notes

- `floors` rejects `dataPoints.list`; it is read through dailyRollUp.
- The daily-summary types filter on `<name>.date`; `respiratory-rate-sleep-summary`
  filters on `sample_time.physical_time`. Earlier HTTP 400s were a wrong filter field,
  not missing data.
- The 30-day probe found at least one point for every candidate type; all ten were added
  to `config/health.yaml`.
