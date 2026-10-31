# ADR 0008: Detail tables from raw payloads, 13 more API types, and weather

**Status:** accepted (Phase 4.5), 2026-10-31.

## Context

A crawl of the Google Health API documentation (research 11) found 44 data types, of which
we synced 21. Each synced type was also flattened to one number a day:

- **Sleep** was stored as time in bed, including time awake, which overstated sleep by
  over half an hour a night.
- **Workouts** kept only their total minutes.
- **Heart-rate zones** were summed into roughly the time the watch was worn.
- **Nightly vitals** lost their sub-fields (blood-oxygen lows, deep-sleep HRV, breathing per
  stage, skin temperature against its baseline).

The owner also asked for weather.

## Decision

1. **Schema v5 detail tables, derived from the stored `raw_json`** (no new API calls) on
   every sync:
   - `sleep_sessions`: minutes asleep, stages, efficiency, naps;
   - `exercise_sessions`: type, active duration, calories, heart rate, zones;
   - `night_vitals`;
   - `activity_breakdown`;
   - `hr_zone_thresholds`.

   `health_data.derive.rebuild` replaces them in one transaction and turns a missing
   sub-field into NULL, never a guess.
2. **13 more types** under the existing read-only scopes: active energy, activity level,
   altitude, swim laps, calories per zone, VO2 max (any method and from runs), zone
   thresholds, body fat, height, blood glucose, core temperature. A live probe showed each
   type's list filter must match its time kind (sample, daily or interval). No new OAuth
   scopes: nutrition, hydration, ECG and IRN were declined by the owner.
3. **The frozen ledger is untouched.** `daily_metrics` keeps its old values (sleep stays time
   in bed), because the pre-registered forecasting plan reads them. The corrected measures sit
   next to them.
4. **Weather from Open-Meteo** (free, no key): `weather_daily` for the home location (Erode by
   default), backfilled from the archive and kept current by the nightly job. A `weather` tool
   covers the forecast. Coordinates come from settings, or from the front end's live location
   (Phase 5), never from the model, so the only outbound call carries no health data. An
   outage is "skipped", never a failed run.

## Consequences

- Questions about sleep stages, workouts, night blood oxygen, zones and weather become
  answerable. The agent finds the tables through `data_catalog` (ADR 0007).
- **Deploy order matters:** older job images refuse a v5 database, so the new image is
  deployed before any v5 database reaches the bucket.
- The laptop's v5 copy was built with `--local-only` and is never pushed.
