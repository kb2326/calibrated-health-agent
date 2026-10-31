# 11 — Google Health API catalog and gap analysis

Crawled 2026-10-31 from https://developers.google.com/health (docs nav from
https://developers.google.com/health/get-started). Base URL below = `https://developers.google.com/health`.
API service: `https://health.googleapis.com`, versions `v4` (stable) and `v4beta` (public preview since 2026-10-01).
Discovery: `https://health.googleapis.com/$discovery/rest?version=v4` (not fetched; reference pages used instead).

Legend: **Synced** = listed in `config/health.yaml` today. "UNVERIFIED" = stated on one page only, contradicted
elsewhere, or not documented field-by-field.

---

## 1. Data types

Sources: data types index `/health/data-types`; category pages `/health/data-types/{calories,vitals,skin-temperature,workouts,nutrition,steps,sleep,womens-health}`;
field schemas from the DataPoint reference `/health/reference/rest/v4/users.dataTypes.dataPoints` (read in full,
three offsets) and `/health/reference/rest/v4beta/users.dataTypes.dataPoints` (union list only); rollup value types
`/health/reference/rest/v4/{Type}RollupValue`; device list `/health/data-types/device-compatibility`.

The index documents **44 data types**. Scope column is the suffix after
`https://www.googleapis.com/auth/googlehealth.`; "r" = has a `.readonly` read path, "w-only" = only write methods exist.
Methods: L=list, G=get, Rc=reconcile, R=rollUp, D=dailyRollUp, C/U/X=create/update(patch)/batchDelete. W = webhook supported.
int64 fields come back as JSON strings.

### 1a. Activity and fitness (`activity_and_fitness`)

| data type id | measures | value fields / units | granularity | sub-structure | methods | read | Synced |
|---|---|---|---|---|---|---|---|
| `steps` | step count | `count` (int64); rollup `countSum` | interval, 1 min storage | — | L Rc R D, W, true zeros | r | **yes** |
| `distance` | distance | `millimeters` (int64); rollup `millimetersSum` | interval, 1 min | — | L Rc R D, W, true zeros | r | **yes** |
| `floors` | floors climbed | `count`; rollup `countSum` (assumed, page not fetched) | interval, 1 min | — | Rc R D (no list), W, true zeros | r | **yes** |
| `altitude` | elevation gain | `gainMillimeters` (int64, may be negative); rollup `gainMillimetersSum` | interval, 1 min | — | L Rc R D, W, true zeros | r | no |
| `total-calories` | total energy (BMR + active) | rollup `kcalSum` (kcal) | interval, 1 min | — | R D only; 14-day range cap; true zeros | r | **yes** |
| `active-energy-burned` | active energy, excludes basal | `kcal` (0–1e6); rollup value type exists | interval, 1 min | — | L Rc R D | r | no |
| `basal-energy-burned` | basal energy | `kcal` | interval | — | not in index; present in DataPoint union (`basalEnergyBurned`) and migration mapping (legacy `caloriesBMR`). Calories page says "the API does not provide basal energy burned" — UNVERIFIED/contradictory | ? | no |
| `active-minutes` | minutes by intensity | `activeMinutesByActivityLevel[]{activityLevel: LIGHT/MODERATE/VIGOROUS, activeMinutes}`; rollup `activeMinutesRollupByActivityLevel[]{activityLevel, activeMinutesSum}` | interval, 1 min | **per-level breakdown** | L Rc R D, W; 14-day range cap | r | **yes** (levels summed) |
| `active-zone-minutes` | AZM | `heartRateZone` (FAT_BURN/CARDIO/PEAK), `activeZoneMinutes` (1/min fat burn, 2/min cardio+peak); rollup `sumInFatBurnHeartZone`, `sumInCardioHeartZone`, `sumInPeakHeartZone` | interval, 1 min | **per-zone** | L Rc R D, W | r | **yes** (zones summed) |
| `time-in-heart-rate-zone` | time in HR zone | `heartRateZoneType` (LIGHT/MODERATE/VIGOROUS/PEAK); rollup `timeInHeartRateZones[]{heartRateZone, duration}` | interval, 1 min | **per-zone** | L Rc R D, W | r | **yes** (all zones summed, incl. LIGHT) |
| `calories-in-heart-rate-zone` | kcal by HR zone | rollup only: `caloriesInHeartRateZones[]{heartRateZone, kcal}` | interval, 1 min | per-zone | R D only; 14-day cap; W | r | no |
| `activity-level` | activity intensity timeline | `activityLevelType` SEDENTARY/LIGHTLY_ACTIVE/MODERATELY_ACTIVE/VERY_ACTIVE; rollup `activityLevelRollupsByActivityLevelType[]{activityLevelType, totalDuration}` | interval | per-level | L Rc (index) — but rollup value type exists and rollUp/dailyRollUp list `activityLevel` (UNVERIFIED which is right), W | r | no |
| `sedentary-period` | sedentary intervals | `interval` only; rollup `durationSum` (Duration) | interval | — | L Rc R D, W | r | **yes** |
| `exercise` | workout session | `exerciseType` (≈190-value enum), `displayName`, `activeDuration`, `notes`, `metricsSummary{caloriesKcal, distanceMillimeters, steps, averageHeartRateBeatsPerMinute, activeZoneMinutes, averageSpeedMillimetersPerSecond, averagePaceSecondsPerMeter, elevationGainMillimeters, runVo2Max, totalSwimLengths, heartRateZoneDurations{lightTime, moderateTime, vigorousTime, peakTime}, mobilityMetrics{avgCadenceStepsPerMinute, avgStrideLengthMillimeters, avgGroundContactTimeDuration, avgVerticalOscillationMillimeters, avgVerticalRatio}}`, `exerciseMetadata{hasGps, poolLengthMillimeters}`, `exerciseEvents[]{eventTime, exerciseEventType START/STOP/PAUSE/RESUME/AUTO_PAUSE/AUTO_RESUME}`, `splitSummaries[]{start/end, activeDuration, metricsSummary, splitType MANUAL/DURATION/DISTANCE/CALORIES}` | session | **type, metrics summary, HR-zone durations, splits/laps, pause events, GPS via TCX** | L G Rc C U X, W; page size 25 | r | **yes** (flattened to interval minutes) |
| `swim-lengths-data` | swim laps | `swimStrokeType` FREESTYLE/BACKSTROKE/BREASTSTROKE/BUTTERFLY, `strokeCount`; rollup `strokeCountSum` | interval | — | L Rc R D | r | no |
| `run-vo2-max` | VO2 max from runs | `runVo2Max` (ml/kg/min, 0–100); rollup `rateMin/rateMax/rateAvg` | sample | — | L Rc R D, W | r | no |
| `vo2-max` | VO2 max (any method) | `vo2Max` (ml/kg/min), `measurementMethod` (FITBIT_RUN, GOOGLE_DEMOGRAPHIC, COOPER_TEST, … 12 values) | sample | method | L Rc | r | no |
| `daily-vo2-max` | daily cardio fitness | `vo2Max` (ml/kg/min), `estimated` (bool), `cardioFitnessLevel` POOR…EXCELLENT, `vo2MaxCovariance` | daily | fitness level | L Rc | r | **yes** (vo2Max only). Index puts it under `activity_and_fitness`; our config labels it `health_metrics_and_measurements` (harmless: both scopes granted) |

### 1b. Health metrics and measurements (`health_metrics_and_measurements`)

| data type id | measures | value fields / units | granularity | sub-structure | methods | read | Synced |
|---|---|---|---|---|---|---|---|
| `heart-rate` | heart rate | `beatsPerMinute` (1–300), `metadata{motionContext ACTIVE/SEDENTARY, sensorLocation CHEST/WRIST/FINGER/HAND/EAR_LOBE/FOOT}`; rollup `beatsPerMinuteAvg/Min/Max` | sample, 1 s storage | motion context | L Rc R D, W; 14-day rollup cap | r | **yes** (mean only) |
| `daily-resting-heart-rate` | resting HR | `beatsPerMinute`, `dailyRestingHeartRateMetadata.calculationMethod` WITH_SLEEP / ONLY_WITH_AWAKE_DATA | daily | calc method | L Rc, W | r | **yes** |
| `heart-rate-variability` | HRV samples | `rootMeanSquareOfSuccessiveDifferencesMilliseconds` (1–200), `standardDeviationMilliseconds` (SDNN), `metadata{highFrequencyPower, lowFrequencyPower}` | sample | RMSSD vs SDNN, LF/HF | L Rc, W | r | **yes** (RMSSD only) |
| `daily-heart-rate-variability` | nightly HRV | `averageHeartRateVariabilityMilliseconds` (RMSSD), `deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds`, `nonRemHeartRateBeatsPerMinute`, `entropy` | daily | deep-sleep RMSSD, non-REM HR | L Rc, W | r | **yes** (average only) |
| `daily-heart-rate-zones` | user's HR zone thresholds | `heartRateZones[]{heartRateZoneType LIGHT/MODERATE/VIGOROUS/PEAK, minBeatsPerMinute, maxBeatsPerMinute}` | daily | zone bounds | L Rc, W | r | no |
| `oxygen-saturation` | SpO2 | `percentage` (0–100); invalid minutes filtered out, sparse | sample, 1 min | — | L Rc (no webhook) | r | **yes** |
| `daily-oxygen-saturation` | nightly SpO2 | `averagePercentage`, `lowerBoundPercentage`, `upperBoundPercentage`, `standardDeviationPercentage` | daily | range | L Rc, W | r | **yes** (average only) |
| `respiratory-rate-sleep-summary` | breathing during sleep | `fullSleepStats`, `deepSleepStats`, `lightSleepStats`, `remSleepStats`, each `{breathsPerMinute, standardDeviation, signalToNoise}` | sample (stamped at wake) | **per sleep stage** | L Rc, W | r | **yes** (full-sleep only) |
| `daily-respiratory-rate` | breathing rate, main sleep | `breathsPerMinute` | daily | — | L Rc, W | r | **yes** |
| `respiratory-rate` | sample breathing rate | — mentioned in sleep guide text only; not in index or schema — UNVERIFIED | sample | — | — | ? | no |
| `daily-sleep-temperature-derivations` | nightly skin temp | `nightlyTemperatureCelsius`, `baselineTemperatureCelsius` (30-day median), `relativeNightlyStddev30dCelsius`; docs recommend showing nightly − baseline | daily | **baseline** | L Rc, W | r | **yes** (absolute nightly only) |
| `skin-temperature-sensors` (**v4beta**) | raw minutely skin + internal temp | `temperatureCelsius`, `metadata{measurementLocation, sensorType SKIN_TEMPERATURE_SENSOR / INTERNAL_DEVICE_TEMPERATURE_SENSOR}` | sample, minutely | two sensors | L only; Pixel Watch 4/5 only | r | no |
| `core-body-temperature` | thermometer readings | `temperatureCelsius` (0–100), `measurementLocation` (18 values), `id`; rollup avg/min/max °C | sample | — | L G Rc R D | r | no |
| `blood-glucose` | glucose | `bloodGlucoseMilligramsPerDeciliter` (0–900), `measurementSource` SMBG/CGM/LAB_TEST, `mealType`, `measurementTiming` (FASTING, AFTER_MEAL…), `specimen`, `notes`; rollup `…Avg` | sample | meal context | L G Rc R D, W | r | no |
| `weight` | body mass | `weightGrams`, `notes`; rollup `weightGramsAvg` | sample | — | L G Rc R D C U X, W | r | **yes** |
| `body-fat` | body fat % | `percentage` (0–100); rollup value exists | sample | — | L G Rc R D C U X, W | r | no |
| `height` | height | `heightMillimeters` (0–3000) | sample | — | L G Rc C U X, W | r | no |

### 1c. Sleep (`sleep`)

| data type id | measures | value fields / units | granularity | sub-structure | methods | read | Synced |
|---|---|---|---|---|---|---|---|
| `sleep` | sleep session | `type` CLASSIC/STAGES; `stages[]{start,end,type AWAKE/LIGHT/DEEP/REM/ASLEEP/RESTLESS}` (contiguous partition); `shortAwakenings[]`; `outOfBedSegments[]`; `summary{minutesInSleepPeriod, minutesAsleep, minutesAwake, minutesToFallAsleep, minutesAfterWakeUp, stagesSummary[]{type, minutes, count}}`; `metadata{mainSleep, nap, manuallyEdited, processed, externalId, stagesStatus (SUCCEEDED, REJECTED_NAP <3h, REJECTED_COVERAGE, …)}`; `createTime/updateTime`. Efficiency = round(minutesAsleep / minutes in bed × 100), computed client-side | session | **stages, stage summary, main sleep vs nap, latency, awakenings** | L G Rc C U X, W; page size 25; list filter on end time only; `dataSourceFamily` not allowed on list (use reconcile) | r | **yes** (flattened to interval minutes = time in bed, naps included) |

### 1d. Nutrition (`nutrition`) — scope not requested today

| data type id | measures | value fields / units | granularity | methods | read | Synced |
|---|---|---|---|---|---|---|
| `nutrition-log` | food log entry | `energy{kcal}`, `energyFromFat`, `totalCarbohydrate{grams}`, `totalFat`, `nutrients[]{nutrient (40 values: PROTEIN, SODIUM, CAFFEINE, …), quantity{grams}}`, `mealType` (10 values), `serving{amount, foodMeasurementUnit}`, `food`, `foodDisplayName`; rollup sums per nutrient | session | L G Rc R D C U X, W | r | no |
| `hydration-log` | water intake | `amountConsumed{milliliters, userProvidedUnit}`; rollup `amountConsumed.millilitersSum` | session (short) | L G Rc R D C U X, W | r | no |
| `food` | food database item | `displayName, brand, nutrients[], energyMin/Avg/Max, defaultServing, servings[]` | food record | L G | r | no |
| `food-measurement-unit` | serving unit catalog | `displayName, pluralDisplayName` | food record | L G | r | no |

### 1e. ECG / IRN (own scopes) — not requested today

| data type id | scope | value fields | granularity | methods | Synced |
|---|---|---|---|---|---|
| `electrocardiogram` | `ecg.readonly` | `resultClassification` NORMAL_SINUS_RHYTHM / ATRIAL_FIBRILLATION / INCONCLUSIVE(_HIGH/_LOW_HEART_RATE) / UNREADABLE / NOT_ANALYZED; `beatsPerMinuteAvg`, `waveformSamples[]` (lead I), `samplingFrequencyHertz`, `millivoltsScalingFactor`, `leadNumber`, `medicalDeviceInfo` | session (start = end) | L only; filter start_time `>=` only | no |
| `irregular-rhythm-notification` | `irn.readonly` | `alertWindows[]{start,end, positive, heartBeats[]{physicalTime, beatsPerMinute}}`, `medicalDeviceInfo` | session | L only | no |

### 1f. Women's health — write-only (no read path documented)

| data type id | scope | fields | Synced |
|---|---|---|---|
| `menstrual-period` | `reproductive_health.writeonly` | `interval`, `notes` | no (not readable) |
| `ovulation-test` | `reproductive_health.writeonly` | `result` NEGATIVE/LH_SURGE/ESTROGEN_SURGE/POSITIVE/INDETERMINATE | no |
| `symptoms` | `logged_symptoms.writeonly` | `symptoms[]` (≈65 values: HEADACHE, FATIGUE, INSOMNIA, …) | no |
| `moods` | `mindfulness.writeonly` | `moods[]` (≈70 values), `valences[]` UNPLEASANT/BASELINE/PLEASANT | no |

Note: the list/get/rollUp method pages list `reproductive_health.readonly`, `logged_symptoms.readonly`, `mindfulness.readonly` as accepted scopes, but the Scopes page and data types index document only `.writeonly` for these, and no read method exists for the four types. Treat read access as **not available** (UNVERIFIED either way).

### 1g. Rollup-only values (no own data type)

From `/health/reference/rest/v4/users.dataTypes.dataPoints/dailyRollUp`: `restingHeartRatePersonalRange{beatsPerMinuteMin, beatsPerMinuteMax}` and
`heartRateVariabilityPersonalRange{averageHeartRateVariabilityMillisecondsMin, …Max}` are returned by `dailyRollUp`.
Which `dataTypes/{id}` path to call them on is **not documented** (presumably `daily-resting-heart-rate` / `daily-heart-rate-variability`, though the index lists only list/reconcile for those) — UNVERIFIED, needs a live probe.

### 1h. Common envelope

`DataPoint{name, dataSource, <one union field>}`. `dataSource{recordingMethod MANUAL/PASSIVELY_MEASURED/DERIVED/ACTIVELY_MEASURED/UNKNOWN, device{formFactor WATCH/FITNESS_BAND/PHONE/RING/CHEST_STRAP/SCALE/…, manufacturer, displayName}, application{packageName, webClientId, googleWebClientId}, platform FITBIT/HEALTH_CONNECT/HEALTH_KIT/FIT/FITBIT_WEB_API/NEST/GOOGLE_WEB_API/GOOGLE_PARTNER_INTEGRATION}`.
Time: samples `sampleTime{physicalTime, utcOffset, civilTime}`; intervals/sessions `interval{startTime, startUtcOffset, endTime, endUtcOffset, civilStartTime, civilEndTime}`; daily `date{year,month,day}`.

Devices (`/health/data-types/device-compatibility`): Fitbit trackers/watches, Pixel Watch 1–5, Aria scales (weight/body fat only). Fitbit Ace not supported. Per-type device lists not transcribed.

---

## 2. REST resources and methods

Sources: `/health/reference/rest`, method pages under `/health/reference/rest/v4/users.dataTypes.dataPoints/*`, `/health/reference/rest/v4/users`,
`/health/reference/rest/v4/users.pairedDevices`, `/health/webhooks`, `/health/rate-limits`, `/health/aggregate-data`, `/health/filters`, `/health/endpoints`, `/health/reference/rest/v4/errors`.
v4beta has the identical method surface.

### `users.dataTypes.dataPoints`

| method | HTTP | returns | limits / notes | we call |
|---|---|---|---|---|
| `list` | GET `/v4/users/me/dataTypes/{type}/dataPoints` | `dataPoints[]`, `nextPageToken`; raw stored points incl. overlaps, newest first | pageSize default 1440, max 10000; exercise/sleep default=max 25. AIP-160 `filter`, only `>=`, `<`, `AND` (sleep end-time also allows OR per list page, but Filters guide says OR is rejected). Fields: `{t}.interval.start_time|civil_start_time`, `{t}.sample_time.physical_time|civil_time`, `{t}.date`, `sleep.interval.end_time|civil_end_time`, `electrocardiogram.interval.start_time` (`>=` only). No max history window. `dataSourceFamily` query param, not for sleep/food/food-measurement-unit | yes |
| `get` | GET `…/dataPoints/{id}` | one `DataPoint` | identifiable types only (which ones: not listed) | allow-listed, not used for sync |
| `reconcile` | GET `…/dataPoints:reconcile` | `dataPoints[]` of `ReconciledDataPoint{dataPointName, <union>}`; one deduplicated stream, picks a winning record (does not merge intervals), excludes off-wrist wearable data | same page sizes and filter as list; `dataSourceFamily` allowed (incl. sleep) | yes (parity checks) |
| `rollUp` | POST `…:rollUp` | `rollupDataPoints[]{startTime, endTime, <RollupValue>}` newest first | body `range` (physical), `windowSize` ≥ 1s (recommend ≥ 60s for 1-min types); range max 14 days for heart-rate, active-minutes, total-calories, calories-in-heart-rate-zone, else 90; pageSize default 1440, max 10000. Unset value = not worn; 0 = worn, nothing recorded | yes (heart-rate windows) |
| `dailyRollUp` | POST `…:dailyRollUp` | `rollupDataPoints[]{civilStartTime, civilEndTime, <RollupValue>}` | body `range` (civil, no zero-padded month/day), `windowSizeDays` default 1; pageSize default/max 90 (14 for the four 14-day types); `INVALID_ROLLUP_QUERY_DURATION` if windowSizeDays × pageSize > cap. Handles DST/travel with per-point offsets | yes (steps, distance, total-calories, active-minutes, floors, AZM, sedentary, time-in-HR-zone) |
| `exportExerciseTcx` | GET `…/exercise/dataPoints/{id}:exportExerciseTcx?alt=media` | TCX XML (laps, trackpoints with lat/long/altitude/distance); without `alt=media` JSON `{tcxData}` | needs `activity_and_fitness.readonly` **and** `location.readonly`; `partialData=true` returns points without GPS | allow-listed, not used |
| `create` / `patch` / `batchDelete` | POST / PATCH / POST `:batchDelete` | `Operation` wrapping the DataPoint | write scopes; batchDelete ≤ 10000 names, parent `-` wildcard allowed; only the creating client can modify a point | no (read-only client gate) |

Rollup value types (all fetched): Steps `countSum`; Distance `millimetersSum`; Altitude `gainMillimetersSum`; TotalCalories `kcalSum`;
HeartRate `beatsPerMinuteAvg/Min/Max`; ActiveMinutes per-level `activeMinutesSum`; ActiveZoneMinutes per-zone sums; TimeInHeartRateZone per-zone `duration`;
CaloriesInHeartRateZone per-zone `kcal`; ActivityLevel per-level `totalDuration`; SedentaryPeriod `durationSum`; Weight `weightGramsAvg`;
RunVO2Max `rateMin/Max/Avg`; CoreBodyTemperature avg/min/max; BloodGlucose avg; SwimLengths `strokeCountSum`; NutritionLog sums per nutrient + energy;
HydrationLog `millilitersSum`. Not individually fetched: Floors, BodyFat, ActiveEnergyBurned rollup pages.

### `users`

| method | returns | scope |
|---|---|---|
| `getIdentity` GET `/v4/users/me/identity` | `healthUserId`, `legacyUserId` (Fitbit); 400 `ACCOUNT_NOT_LINKED` if no Google Health profile | any read scope |
| `getProfile` GET `/v4/users/me/profile` | `age` (years), `membershipStartDate`, `userConfiguredWalking/RunningStrideLengthMm`, `autoWalking/RunningStrideLengthMm` | `profile.readonly` (stride fields also need activity_and_fitness) |
| `getSettings` GET `/v4/users/me/settings` | `timeZone` (IANA), `utcOffset`, `languageLocale`, units (`distanceUnit`, `weightUnit`, `heightUnit`, `temperatureUnit`, `glucoseUnit`, `waterUnit`, `swimUnit`), stride types, `autoStrideEnabled`, `foodLanguageCode`. No goals field | `settings.readonly` |
| `getIrnProfile` | `onboardingStatus`, `enrollmentStatus`, `updateTime` | `irn.readonly` |
| `updateProfile` / `updateSettings` | PATCH | `.writeonly` |

Biological sex, BMI and BMR are **not** exposed (`/health/migration/api-specifications`); birthday only via People API (`/health/profile`).

### `users.pairedDevices`
`list` / `get`: `PairedDevice{name, deviceType TRACKER/SCALE, batteryStatus High/Medium/Low/Empty, batteryLevel, lastSyncTime, deviceVersion (model name), macAddress, features[] (STEPS, SPO2, SKIN_TEMPERATURE, GPS, …)}`. Scope not stated on the page (our config assumes `settings.readonly`). Page size not documented.

### `projects.subscribers` and `projects.subscribers.subscriptions` (webhooks)
`create/list/patch/delete` subscribers; `create/list/patch/delete` per-user subscriptions (MANUAL policy only). See section 4.

### Quotas (`/health/rate-limits`)
Per project 86.4M/day and 120,000/min; **per user 300 requests/min (~5 QPS)**; unverified apps capped at 100 users. Exceeded → 429 `RESOURCE_EXHAUSTED`; retry with exponential backoff on 429/504 (`/health/endpoints`). No per-method quotas published.

### Errors
63 reasons in `/health/reference/rest/v4/errors`, e.g. `INVALID_ROLLUP_QUERY_DURATION`, `INVALID_ROLLUP_WINDOW`, `INVALID_DATA_POINT_FILTER_*`, `INVALID_TIME_RANGE_INTERVAL_FORMAT` (civil vs physical mismatch), `UNSUPPORTED_DATA_TYPE_ACTION`, `ACCOUNT_NOT_LINKED`, `MISSING_OAUTH_SCOPE`, `DATA_ACCESS_DENIED`, `SLEEP_ALREADY_EXISTS` (409).

---

## 3. OAuth scopes

Source: `/health/scopes`, release notes `/health/release-notes` (2026-05-26 rename). Prefix `https://www.googleapis.com/auth/googlehealth.`
All Google Health scopes are classified **Restricted** (`/health/about`, `/health/app-verification`): >100 users requires OAuth verification + annual CASA assessment.

| read-only scope | covers | requested today |
|---|---|---|
| `activity_and_fitness.readonly` | steps, distance, floors, altitude, total-calories, active-energy-burned, active-minutes, active-zone-minutes, time-in-heart-rate-zone, calories-in-heart-rate-zone, activity-level, sedentary-period, exercise, swim-lengths-data, run-vo2-max, vo2-max, daily-vo2-max; profile stride fields | yes |
| `health_metrics_and_measurements.readonly` | heart-rate, HRV (+daily), resting HR, daily-heart-rate-zones, SpO2 (+daily), respiratory types, sleep-temperature derivations, skin-temperature-sensors (beta), core-body-temperature, blood-glucose, weight, body-fat, height | yes |
| `sleep.readonly` | sleep | yes |
| `nutrition.readonly` | nutrition-log, hydration-log, food, food-measurement-unit | **no** |
| `ecg.readonly` | electrocardiogram | **no** |
| `irn.readonly` | irregular-rhythm-notification, getIrnProfile | **no** |
| `location.readonly` | GPS route in exportExerciseTcx | **no** |
| `profile.readonly` | getProfile | yes (pending owner re-consent) |
| `settings.readonly` | getSettings (and presumably pairedDevices) | yes (pending owner re-consent) |

Write-only scopes (not used): `activity_and_fitness`, `health_metrics_and_measurements`, `nutrition`, `sleep`, `profile`, `settings`, `reproductive_health`, `logged_symptoms`, `mindfulness` — each `.writeonly`. Unsuffixed read/write scopes were removed on 2026-05-26.

---

## 4. Profiles, devices/sources, settings, timezones, deletions, webhooks

Sources: `/health/profile`, `/health/reference/rest/v4/Profile`, `/health/reference/rest/v4/Settings`, `/health/reference/rest/v4/users.pairedDevices`,
`/health/data-management`, `/health/filters`, `/health/aggregate-data`, `/health/webhooks`, `/health/reference/rest/v4/Subscription`, `/health/platform-logging`, `/health/audit-logging`, `/health/troubleshooting`, `/health/setup`.

- **Sources.** `dataSourceFamily` on list/reconcile (query) and rollUp/dailyRollUp (body), full resource name required: `users/me/dataSourceFamilies/all-sources` (default), `google-wearables` (Fitbit/Pixel trackers, no manual or phone data), `google-sources` (first-party incl. manual + Health Connect), `self-sources` (added 2026-10-14). Per-point `dataSource.platform` can be `HEALTH_KIT`/`HEALTH_CONNECT`, which is why HealthKit SDNN shows up in HRV.
- **Reconciliation.** `list` returns overlapping re-bucketed uploads unmodified; `reconcile`/rollups dedupe and exclude off-wrist time. Stored timestamps can change (owner patch, Health Connect propagation), so caches must handle updated intervals.
- **Timezone.** Every point carries UTC offsets and civil times; `dailyRollUp` buckets by the user's civil day using each point's offset (DST/travel safe); `rollUp` is fixed-UTC. `Settings.timeZone` (IANA) and `utcOffset` give the current zone. Don't mix civil and physical bounds in one filter.
- **Deletions/changes.** There is **no change feed or modified-since filter** (`/health/filters`, `/health/endpoints`). Changes are seen only by re-reading a window or via webhooks (`operation: UPSERT|DELETE`, `recordId` on identifiable deletes). DELETE notifications are sent for user deletes (app or batchDelete), not for revocation or account deletion; system tokens `user-deleted`, `user-revoked-access` exist but their payloads are undocumented.
- **Webhooks.** Subscriber = HTTPS endpoint + `subscriberConfigs[]{dataTypes[], subscriptionCreatePolicy AUTOMATIC|MANUAL}` + `endpointAuthorization.secret`. Verified by two POSTs (authorized → 200/201, unauthorized → 401/403). Payload `data{version, clientProvidedSubscriptionName, healthUserId, operation, dataType, intervals[]{physicalTimeInterval, civilDateTimeInterval, civilIso8601TimeInterval}, recordId}`; batches up to 99; signed with Tink ECDSA P-256 in `GOOGLE-HEALTH-API-SIGNATURE` (keys rotate every 30 days, keyset at `https://www.gstatic.com/googlehealthapi/webhooks/webhooks_public_keyset.json`); reply 204; retried with backoff for 7 days; no backfill. 28 data types supported (not oxygen-saturation, ECG, IRN, food, skin-temperature-sensors, vo2-max, daily-vo2-max, swim, active-energy-burned, core temp). Use the project **number**. Delivery logs: `health.googleapis.com/webhook_notification` in Cloud Logging.
- **Auth lifecycle.** Testing-mode refresh tokens expire after 7 days; access tokens last 1 h; call `getIdentity` after consent to detect `ACCOUNT_NOT_LINKED`. No sandbox; no sample data.
- **Missing data.** Troubleshooting recommends checking `pairedDevices.list` `lastSyncTime` before blaming the API.

---

## 5. Release notes (`/health/release-notes`)

| date | change |
|---|---|
| 2026-03-24 | Launch as successor to Fitbit Web API. v4 endpoints getIdentity/getProfile/getSettings/update*, dataPoints list/reconcile/rollUp/dailyRollUp/patch/batchDelete. ~28 read types |
| 2026-04-14 | New types `swim-lengths-data`, `height`; `dataPoints.get`; `projects.subscribers` delete/get/list/patch; automatic subscriptions; webhooks for 17 types; client libraries |
| 2026-05-26 | Scope rename: read/write scopes replaced by explicit `.writeonly`; new `ecg.readonly`, `irn.readonly`. New types `active-energy-burned`, `electrocardiogram`, `core-body-temperature`, `blood-glucose`, `irregular-rhythm-notification`, `food`, `food-measurement-unit`, `nutrition-log`. New `getIrnProfile`, `pairedDevices.get/list`, manual subscriptions; 7-day webhook retry; rate limits published |
| 2026-06-17 | Parity tool covers the May types and exportExerciseTcx |
| 2026-06-22 | Status dashboard |
| 2026-08-14 | Migration guide rewrite; Promote page |
| 2026-08-17 | Write-only scopes `logged_symptoms`, `mindfulness`, `reproductive_health`; types `menstrual-period`, `moods`, `ovulation-test`, `symptoms` |
| 2026-10-01 | `v4beta` channel; `skin-temperature-sensors` (beta) |
| 2026-10-14 | `dataSourceFamily` on list (all but sleep/food/food-measurement-unit); `self-sources` family |

Deprecations: legacy Fitbit Web API support ended 2026-09-30; Fitbit Web API and Fitbit OAuth return 410 from **2026-11-02**. Roadmap per `/health/about` (Q4 2026): granular skin temperature and basal metabolic rate read/write, more Health Connect parity types into Q1 2027, webhook statistics endpoint.

---

## 6. Gap analysis

Sources: sections above plus `packages/health_data/src/health_data/client.py` (`VALUE_FIELD`, `DURATION_TYPES`, `extract_rollup_value`) and `config/health.yaml`.
Raw JSON is kept in `raw_points` for listed types, so items marked "(in raw_json)" can be backfilled from local data without new API calls. Rollup types keep only the bucket.

Ranked by usefulness for a personal health Q&A agent:

1. **Sleep summary and stages (flattened, high).** `extract_value` stores sleep as `endTime − startTime`, which is *time in bed incl. awake time*, and sums naps into the day. The API gives `summary.minutesAsleep`, `minutesAwake`, `minutesToFallAsleep`, `stagesSummary[]` (deep/light/REM/awake minutes and counts), `metadata.mainSleep`/`nap`, and efficiency can be derived. Answers "how much deep sleep", "did I sleep worse", "sleep efficiency". (in raw_json.) No new scope.
2. **Exercise sessions (flattened, high).** Stored as total interval minutes per day. Missing `exerciseType`, `activeDuration` (pauses excluded), `metricsSummary` (kcal, distance, avg HR, AZM, pace, elevation, `heartRateZoneDurations`, `runVo2Max`), splits. Answers "what workouts did I do", "how was my run pace trending". (in raw_json.) GPS route would need `location.readonly`; low value for Q&A.
3. **Per-zone and per-level breakdowns (flattened, high).** `time-in-heart-rate-zone` sums all zones *including LIGHT*, so the daily figure is close to total worn time, not exertion. `active-zone-minutes` sums fat-burn+cardio+peak (fine as a total; zone split lost). `active-minutes` sums LIGHT+MODERATE+VIGOROUS, so it isn't the "active minutes" a user sees in the app (moderate+vigorous). Store each zone/level as its own metric. Rollup buckets aren't kept raw, so this needs a re-pull (dailyRollUp, 14-day chunks for active-minutes).
4. **Nightly temperature delta (flattened, high).** We store absolute `nightlyTemperatureCelsius`; the docs say to show `nightly − baselineTemperatureCelsius`, which is the clinically meaningful signal (illness, cycle). (in raw_json.)
5. **Personal ranges and daily HR extremes (medium-high).** `dailyRollUp` returns `restingHeartRatePersonalRange` and `heartRateVariabilityPersonalRange` (min/max), i.e. Google's own "normal for you" band, which helps calibrated answers. HR rollups give min/max too; we keep the mean only. Calling path for personal ranges is UNVERIFIED (needs a probe).
6. **Richer nightly vitals (medium).** `daily-heart-rate-variability`: deep-sleep RMSSD, non-REM HR, entropy; `daily-oxygen-saturation`: lower/upper bounds; `respiratory-rate-sleep-summary`: per-stage rates; `daily-resting-heart-rate.calculationMethod`; `daily-vo2-max.cardioFitnessLevel` and `estimated`. (all in raw_json.)
7. **Unsynced types under scopes we already have (medium).** `daily-heart-rate-zones` (zone thresholds, context for zone answers), `body-fat`, `height` (BMI), `run-vo2-max`/`vo2-max`, `active-energy-burned`, `calories-in-heart-rate-zone`, `activity-level`, `altitude`, `swim-lengths-data`, `blood-glucose`, `core-body-temperature`. Value depends on the owner's devices; the 2026-10-20 probe covered only the 10 types added then.
8. **Device and settings context (medium).** `pairedDevices.lastSyncTime` lets the agent say "your watch last synced Tuesday" instead of treating a gap as low activity; `Settings.timeZone` and units; `Profile.age`. Already in config, pending re-consent.
9. **Source metadata (medium, data quality).** Keep `dataSource.platform`/`device.formFactor`/`recordingMethod` as columns; HealthKit SDNN vs Fitbit RMSSD is already a known trap.
10. **Nutrition and hydration (situational).** Needs **new scope `nutrition.readonly`**. Only useful if the owner logs food/water.
11. **ECG and IRN (low for Q&A, high sensitivity).** Needs **`ecg.readonly`** and **`irn.readonly`**. On-demand recordings and AFib alerts; answers must stay non-diagnostic.
12. **Skin temperature sensors (low).** v4beta, Pixel Watch 4/5 only, raw minutely, needs your own algorithms.
13. Not available to read: menstrual-period, ovulation-test, symptoms, moods (write-only). Our manual journal already covers mood.

**New scopes needed:** none for items 1–9. `nutrition.readonly` (item 10), `ecg.readonly` + `irn.readonly` (item 11), `location.readonly` only for GPS routes. Each new restricted scope means re-consent and must be justified at verification.

---

## Coverage and what was not fetched or verified

Fetched: get-started, about, release-notes, setup, developer-checklist, all 10 data-type pages, data-management, profile, scopes, libraries, endpoints, filters,
aggregate-data, rate-limits, universal-app-links, webhooks, troubleshooting, app-verification, audit-logging, platform-logging, migration (+ data-access,
api-specifications, parity-tool), REST index, the full v4 DataPoint reference, list/get/reconcile/rollUp/dailyRollUp/batchDelete/exportExerciseTcx,
users, getIdentity, getIrnProfile, Profile, Settings, pairedDevices, Subscription, errors, and 17 of 21 rollup value types.

Not fetched / not verified:
- Codelabs (3), promote, launch, support pages; `create`/`patch` method pages; Subscriber type; pairedDevices `list`/`get` method pages (page size, scope); Floors/BodyFat/ActiveEnergyBurned/Steps rollup type pages (field names inferred); Shared.Types pages.
- v4beta DataPoint read only for its union list (skinTemperatureSensors schema taken from the skin-temperature guide).
- Parity tool content is interactive and did not render.
- Contradictions flagged above: `basal-energy-burned` (in schema, missing from index), `respiratory-rate` (text only), `activity-level` rollup support, women's-health `.readonly` scopes listed on method pages, personal-range rollup call path, `sleep` filter OR support, scope for pairedDevices.
- Fetches went through a summarizing fetcher; enum lists were requested verbatim, but spot-check any field name against the reference before coding.
