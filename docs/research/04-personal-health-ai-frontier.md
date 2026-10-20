# 04: The Personal Health AI Frontier, and What Would Make a One-Person Wearable Agent Impressive (as of 2026-10-20)

**Scope.** This note goes deeper than `research_notes/Health agent portfolio revamp/health AI landscape.md`. That earlier note already covers PHIA's 22%→84% numbers, the Google Health Coach reviews, the Whoop/Oura memory features, HIPAA, Limited-Use, and the basics of n-of-1 caveats. None of that is repeated here except where newer evidence changes it. The code was read directly (read-only): `scripts/analyze.py`, `scripts/learn.py`, `scripts/correlate.py`, `config/health.yaml`.

**Evidence labels.**
- **[PEER-REVIEWED]**: a journal paper or a main-track conference paper.
- **[PREPRINT]**: arXiv or medRxiv, not yet peer-reviewed.
- **[VENDOR]**: the company's own claims.
- **[PRESS]**: journalists or secondary write-ups.
- **[DOCS]**: official API or policy documentation.
- **[ESTABLISHED]**: textbook statistics or methods.
- **[INFERENCE]**: my own reasoning.

---

## 0. Bottom line

1. The research frontier has settled on one architecture: an orchestrator plus a code-executing data-science agent, a domain expert and a coach. That is Google PHA, and it is also what the Google Health Coach ships. **Building the same three agents on ADK is therefore table stakes, not novelty.** The project's three-agent design copies the frontier. It does not differentiate from it.
2. The newest benchmarks (Aug–Sep 2026) all point to the same open weakness. **Agents are poor at longitudinal and predictive reasoning, and often fail to beat trivial baselines.**
   - BALMS: zero-shot agents "rarely beat a simple mean baseline" when predicting wellbeing scores from long-term wearable data.
   - WearableQA: frontier models score 51–73%.
   - LifeAgentBench: models struggle with long-horizon aggregation.
3. **Nobody publishes calibration.** No product (Google, Whoop, Oura, Bevel) and no frontier paper publishes a running calibration record of its own predictions about one person, scored with proper scoring rules against a naive baseline. That gap is the project's best opening, and the self-learning loop already sits on top of it.
4. The project's current statistics would not survive an expert reviewer. Section 6 lists the specific defects:
   - Hit rate is compared against a fixed 0.5 chance level.
   - A weight can move after only 5 scored predictions.
   - Pearson correlations run on autocorrelated, trending series with n≥10 and no CIs or FDR control.
   - Z-scores use mean/SD with no robustness and no gating for wear time.

   Fixing these is the cheapest way to make the project "scientifically defensible", and it should be the headline of the revamp.

---

## 1. Frontier research: methods, evaluations, and what one person can reproduce

### 1.1 Google's personal-health line

| System | Date / venue | Method | Evaluation | What an individual can reproduce |
|---|---|---|---|---|
| **PH-LLM** | Nature Medicine, Aug 2025 [PEER-REVIEWED] | Gemini fine-tuned on sleep and fitness case studies, plus a multimodal sensor adapter | Multiple-choice exams: sleep 79% vs experts 76%, fitness 88% vs 71%. 857 case studies rated against rubrics. Predicts self-reported sleep quality from sensor encodings. ([Nature Med](https://www.nature.com/articles/s41591-025-03888-0)) | Rubrics and benchmark descriptions were released. Weights were not. The **case-study rubric dimensions** can be reused as an LLM-judge rubric. |
| **PHIA** | Nature Communications, Jan 2026 [PEER-REVIEWED] | ReAct-style agent with code generation (pandas) plus web search | About 4,000 objective and open-ended queries. 84% exact-match accuracy on numerical questions. 650 hours of expert evaluation. ([Nat Comms](https://www.nature.com/articles/s41467-025-67922-y); [arXiv 2406.06464](https://arxiv.org/abs/2406.06464)) | The paper says it "creates and shares" two question sets. I could not confirm a repository link. Its question **taxonomy** (summary, comparison, trend, correlation, anomaly, open-ended) is easy to rebuild with templates over your own SQLite. |
| **PHA ("Anatomy of a Personal Health Agent")** | arXiv 2508.20148, Aug/Sep 2025 [PREPRINT] | Multi-agent system: a data-science agent (two stages, analysis plan then code), a domain-expert agent, a health-coach agent using motivational interviewing, and an orchestrator. Gemini 2.x. | About 1,200 consented Fitbit users with questionnaires and blood tests ([WEAR-ME, arXiv 2505.03784](https://arxiv.org/abs/2505.03784)). 10 benchmark tasks. More than 7,000 annotations and 1,100 expert/user hours. Data-science analysis-plan quality was 75.6% vs 53.7% for base Gemini, scored by an autorater trained on 354 expert plans. Code was checked against 173 unit tests written by data scientists. ([Google Research blog, 2025-09-30](https://research.google/blog/the-anatomy-of-a-personal-health-agent/)). A secondary summary reports a 75.5% first-try code pass rate (79.0% after 5 retries) vs 58.4% for baseline ([Moonlight review](https://www.themoonlight.io/en/review/the-anatomy-of-a-personal-health-agent)) [PRESS, unverified against the paper]. | The paper says an evaluation benchmark was open-sourced. I could not locate the repository (the PDF was too large to fetch). **Reproducible ideas:** plan-then-code with unit-tested analysis functions, and the plan-quality rubric. |
| **Google Health Coach** (product) | Preview Oct 2025, GA May 2026 [VENDOR] | Conversational agent, a data-science agent with code generation, and domain experts. "Compare against personal baselines and population statistics." | **SHARP** (safety, helpfulness, accuracy, relevance, personalization). Google claims more than 1M annotations and more than 100k hours, but has published **no numbers**. ([Google Research blog, 2025-10-27](https://research.google/blog/how-we-are-building-the-personal-health-coach/)) | SHARP's five axes are a good public rubric to borrow. |
| **LSM-2** | arXiv 2506.05321, Jun 2025 [PREPRINT] | Self-supervised wearable foundation model trained with **Adaptive and Inherited Masking (AIM)**. It treats real missing data (device off) as masked tokens instead of imputing it. 40M hours of data. | Classification, regression and generative tasks, with robustness to sensor dropout. ([Google blog](https://research.google/blog/lsm-2-learning-from-incomplete-wearable-sensor-data/)) | Weights are not public. **The lesson transfers:** model missingness explicitly and do not impute it. That directly addresses the "non-wear day read as a recovery day" failure. |
| **SensorLM** | NeurIPS 2025 [PEER-REVIEWED] | Sensor–text contrastive and generative pretraining. 59.7M hours from 103,643 people. Hierarchical captions (statistical, structural, semantic). | Zero-shot activity recognition, retrieval, captioning. ([NeurIPS PDF](https://proceedings.neurips.cc/paper_files/paper/2025/file/42cd98f0e7520d4a63c34891ac1c972f-Paper-Conference.pdf); [code](https://github.com/Google-Health/consumer-health-research/tree/main/sensorlm)) | Code is released. I found no evidence of released weights. Its **three-level caption scheme** (statistical → structural → semantic) is a good template for *deterministic* text summaries that an LLM narrates. |
| **SensorFM** | Google Research blog, 2026-07-09 [VENDOR/PRESS] | Wearable foundation model trained on more than 1 trillion minutes from 5M participants, using 34 one-minute features from 5 sensors. Builds on LSM-2's missingness handling. | Beats bespoke baselines on 34 of 35 tasks. +9% AUC and +21% Pearson on average. ([Metatalks summary](https://www.metatalks.ai/googles-sensorfm-one-wearable-model-beats-bespoke-health-baselines-on-34-of-35-tasks/)) | Not available to individuals. Also note that the Google Health API does **not** expose the minute-level PPG/EDA features it uses. |

### 1.2 Apple, Stanford, academic

- **Apple's Wearable Behavior Model (WBM)**, arXiv 2507.00191, Jul 2025 [PREPRINT]. It is a foundation model over **27 derived HealthKit quantities** (steps, VO2max, HRV and so on) from the Apple Heart and Movement Study, rather than raw sensors. It matches or beats raw-PPG models on many health-state tasks and performs best when combined with them ([arXiv](https://arxiv.org/pdf/2507.00191); [9to5Mac](https://9to5mac.com/2025/07/10/study-apple-ai-model-flags-health-conditions-with-up-to-92-accuracy/)).
  - **This matters most for the project.** WBM's input granularity, daily or hourly *derived* metrics, is exactly what the Google Health API gives you. The frontier now treats "behavioral" aggregates as a first-class signal and not as a poor cousin of raw sensors.
- **OpenMHC**, arXiv 2607.16235, Jun–Aug 2026 [PREPRINT]. Stanford My Heart Counts: 11,894 participants, more than 60M hours, 19 channels, and 169 linked variables including **mood**. It is the first open implementation of WBM, with code and weights. The data is released to "qualified researchers". Three tracks: downstream prediction, imputation, forecasting (Chronos-2 is evaluated). ([arXiv](https://arxiv.org/abs/2607.16235))
  - This is the most reproducible frontier artifact for an individual: an open WBM-style encoder could be run over one person's hourly metrics.
- **"Wearable Foundation Models Should Go Beyond Static Encoders"**, arXiv 2603.19564, 2026 [PREPRINT]. A position paper arguing that foundation models should be dynamic and personal, not frozen encoders ([arXiv](https://arxiv.org/pdf/2603.19564)). Useful framing for a "learning loop" story.

### 1.3 Agent benchmarks from 2026 (the most useful new evidence)

| Benchmark | Date | Key finding | Implication for this project |
|---|---|---|---|
| **WearableQA** (Meta/KAIST) | arXiv 2609.05405, Sep 2026 [PREPRINT] | 4,084 multiple-choice questions over 200 real users and 16 question types (8 data-reasoning, 8 health-reasoning). Gemini 3.1 Pro 72.9%, Claude Opus 4.6 60.2%, GPT-5.4 51.2%. **Python access raised GPT-5.4 from 51.2% to 71.3%.** Image inputs *hurt* (about 35%). Released on GitHub (`facebookresearch/WearableQA`) and HF. ([arXiv](https://arxiv.org/html/2609.05405v1)) | Its 8 data-reasoning types (signed correlation, strongest pair, trend shape, anomaly episodes, excursion count, recovery time, and so on) can be **auto-generated from your own SQLite with deterministic answers**, giving a personal benchmark. |
| **BALMS** (Dartmouth et al.) | arXiv 2608.27219, EMNLP 2026 [PEER-REVIEWED, accepted] | Wellbeing-score prediction from long-term wearable data. **Zero-shot agents rarely beat a simple mean baseline.** Chain-of-thought does not ensure temporal grounding. ([arXiv](https://arxiv.org/abs/2608.27219)) | **The single most important citation for the learning loop.** Any "predicts tomorrow's mood/energy" claim must be scored as *skill against a mean/persistence baseline*, not as raw accuracy. |
| **LifeAgentBench** | arXiv 2601.13880, EMNLP 2026 | 22,573 verifiable questions generated from executable programs. LLMs fail at long-horizon aggregation and cross-dimensional reasoning. A tool-augmented agent with deterministic aggregation wins. ([arXiv](https://arxiv.org/abs/2601.13880)) | Supports "every number is computed by code". |
| **WEQA** | arXiv 2606.18147, Jun 2026 [PREPRINT] | A query-adaptive agent with sensor-native tools is about 24% better than ReAct or multi-agent baselines. Its biggest gains are on predictive questions. ([arXiv](https://arxiv.org/html/2606.18147v1)) | The tool design (domain-specific functions instead of free-form pandas) matters more than the number of agents. |
| **VitalAgent / VitalBench** | arXiv 2605.29483, May 2026 [PREPRINT] | Longitudinal physiological memory plus tools. Covers reactive QA and **proactive** monitoring. More than 25% better than ReAct. ([arXiv](https://arxiv.org/abs/2605.29483)) | Proactive alerting needs its own evaluation, measuring false-alert burden. |
| **Task-oriented multi-agent framework** | arXiv 2609.24107, Sep 2026 [PREPRINT] | Decomposing intent with isolated per-intent state halves query-stage tokens (6,869→3,136) and gives 100% multi-intent coverage. **Advice quality remains unvalidated** ("open challenge"). Uses synthetic data. ([arXiv](https://arxiv.org/abs/2609.24107)) | Advice validation is an open problem. Scoring the advice's *predictions* against outcomes is one concrete answer. |

**I found no 2026 benchmark that tests n-of-1 *causal* reasoning** (for example, "did X cause Y for this person?"). That is a real gap. [INFERENCE, based on targeted searches]

### 1.4 Time-series foundation models for forecasting

- **TimesFM 2.5** (Sep 2025): about 200M parameters, 16k context, decile/quantile outputs. Covariates arrived via XReg in Oct 2025. A **TimesFM 3.0** README update (Aug 2026) reportedly adds native covariates. Secondary sources say the 3.0 weights are non-commercial. ([GitHub](https://github.com/google-research/timesfm)) [DOCS/PRESS]
- **Chronos-2** (Amazon, Oct 2025): 120M parameters, encoder-only, Apache-2.0. Zero-shot univariate, multivariate and covariate forecasting via in-context group attention. Ranked first on fev-bench (90.7% win rate, self-reported). ([arXiv 2510.15821](https://arxiv.org/abs/2510.15821); [Amazon Science](https://www.amazon.science/blog/introducing-chronos-2-from-univariate-to-universal-forecasting)) [PREPRINT/VENDOR]
- **Honest evidence on wearables:**
  - Zero-shot HRV forecasting on 49 people (Galaxy Watch, about 4 weeks): Chronos and TimesFM beat EWMA and mean baselines, but only modestly (MASE 0.81–0.82 vs 0.84). MOIRAI was not better than the mean, and TimesFM vs EWMA was not significant at context 32 (p=0.45). ([arXiv 2607.20027](https://arxiv.org/html/2607.20027v1), Jul 2026) [PREPRINT]
  - SOTER, a wearable-specific foundation model trained on 226B points, was best on 4 of 6 out-of-distribution datasets ([arXiv 2609.16804](https://arxiv.org/pdf/2609.16804)).
  - **Takeaway [INFERENCE]:** at *daily* resolution with a few hundred points, foundation models will probably be only marginally better than seasonal-naive or EWMA. The impressive move is **publishing the backtest, including when the foundation model loses**.

---

## 2. Google Health API (state as of 2026-10-20)

- **What it is [DOCS]:** the Fitbit Web API rebuilt on Google infrastructure with Google OAuth 2.0. More than 100 legacy endpoints became data-type bundles. Fitbit Web API support ended **2026-09-30**, and it will be **turned off 2026-10-30**, ten days from today. ([About](https://developers.google.com/health/about), updated 2026-09-29)
- **Data types [DOCS]:** **44** listed: Activity & Fitness 17, Health Metrics 16, Nutrition 4, Sleep 1, Heart Rhythm 2, Women's Health 2, Mindfulness & Symptoms 2. ([Data types](https://developers.google.com/health/data-types))
  - **Types the project does not yet sync but should:**
    - `daily-sleep-temperature-derivations`, `daily-respiratory-rate`, `respiratory-rate-sleep-summary`: the classic early-illness triad alongside resting HR.
    - `daily-vo2-max`, `sedentary-period`, `time-in-heart-rate-zone`, `active-zone-minutes`.
    - **`symptoms`** and **`moods`**: the API has native mood/symptom types. These are a possible source for the journal, though the vitals guide says moods is writable, and an agent that stays read-only may prefer to keep its own journal table.
  - Webhooks cover most types. Intraday (Interval) types support `rollup` and `dailyRollup`. Roadmap: parity with Health Connect in Q4 2026–Q1 2027, and a webhook-telemetry endpoint in Q4 2026.
- **Rate limits [DOCS]:**
  - Per project: 86.4M/day and 120k/min.
  - Per user: 300/min and 5 QPS.
  - **Unverified apps: capped at 100 users and 2.5 QPS per user.**
  - ([Rate limits](https://developers.google.com/health/rate-limits))
  - A personal, unverified project is therefore *allowed*. The restricted-scope privacy and security review is needed only to go beyond that cap or to publish the app.
- **OAuth gotcha [DOCS]:** with the consent screen in "Testing" status, **refresh tokens expire after 7 days** ([setup](https://developers.google.com/health/setup)). A daily sync job will need re-authentication weekly unless the app is moved to production, which for restricted scopes implies verification. Document this, because it is a real operational constraint for solo developers.
- **Policy constraints on publishing [DOCS]** ([Developer & User Data Policy](https://developers.google.com/health/policies/health-api-developer-user-data-policy)):
  - Limited Use applies even to "aggregated, anonymized, de-identified, or derived" data.
  - No transfers to advertising platforms, data brokers or resellers "even if aggregated or anonymized".
  - No use with products that may qualify as a medical device.
  - Tokens must be encrypted at rest.
  - CASA security assessment applies if data leaves the user's device.
  - Human-subjects research requires the Health Research Policy.
- **[INFERENCE]** Publishing *your own* derived results (charts, effect sizes, calibration scores) with your own consent fits "user-directed sharing". Publishing a reusable raw dataset is greyer. Prefer aggregated or derived artifacts and keep raw data local. This is not legal advice.
- **Health Connect:** the Android on-device store. Medical Records support (FHIR R4 4.0.1/4.3.0) is still marked experimental (`ExperimentalPersonalHealthRecordApi`) ([Android docs](https://developer.android.com/health-and-fitness/guides/medical-records/data-format)). It is only relevant if you add an Android client. The Google Health API is the right server-side path.

---

## 3. Statistically rigorous n-of-1 methods an individual can apply

All are **[ESTABLISHED]** unless labeled otherwise. Each entry gives the method, why it fits, and how it maps to this project.

### 3.1 Proper scoring and calibration (directly upgrades `learn.py`)
- **What to predict.** Emit **probabilities**, not just directions. For example: P(energy tomorrow ≥ your 28-day median) = 0.68. Better still, a full distribution over the 1–10 scale.
- **Scoring rules.**
  - Binary predictions: **Brier score** and **log score**.
  - Ordinal 1–10 journal values: **Ranked Probability Score (RPS)**, the discrete form of CRPS.
  - Continuous wearable forecasts: **CRPS** or pinball loss.
- **Always report skill against baselines.** Use `skill = 1 − score_model / score_baseline`. Baselines:
  1. climatology: the person's empirical distribution over the last 28 days;
  2. persistence: tomorrow equals today;
  3. EWMA.

  BALMS shows why: agents often fail to beat the mean ([arXiv 2608.27219](https://arxiv.org/abs/2608.27219)).
- **Calibration.** Show reliability diagrams and calibration-in-the-large. Use the Murphy decomposition of the Brier score (reliability − resolution + uncertainty) to say *why* a model is good or bad.
- **Signal reliability as a posterior.** Replace `weight = 1 + (hit_rate − 0.5)` with a **Beta-Binomial posterior** per (signal, target, lag), compared against the *empirical base rate*, not 0.5. Report P(hit rate > base rate | data) and a 90% credible interval. This removes the arbitrary n≥5 cutoff, since uncertainty shrinks naturally.
- **Data needed.** At a true hit rate of 0.65 vs a 0.50 base rate, a one-sided test at α=0.05 with 80% power needs **about 67 scored predictions**. At 0.60 vs 0.50 it needs **about 150** [ESTABLISHED arithmetic]. With anomaly-triggered predictions only, that could take a year. Hence the recommendation to **predict every day**, not only on anomaly days.

### 3.2 Conformal prediction for honest ranges
- **Adaptive Conformal Inference (ACI)** (Gibbs & Candès, NeurIPS 2021) and **AgACI** (Zaffran et al., ICML 2022) wrap *any* forecaster, whether EWMA, Chronos-2 or TimesFM. They give long-run coverage guarantees without assuming exchangeability, which matters because personal series drift. ([arXiv 2106.00170](https://arxiv.org/abs/2106.00170); [ICML 2022](https://icml.cc/virtual/2022/spotlight/17818); R package `AdaptiveConformal`, [Susmann et al. 2024](https://computo.sfds.asso.fr/published-202407-susmann-adaptive-conformal/published-202407-susmann-adaptive-conformal.pdf))
- **Use.** Replace "z ≥ 1.5" with "outside your 90% conformal band for tomorrow". Then **track empirical coverage**: a claimed 90% band should contain about 90% of outcomes. That is a verifiable, falsifiable statement the agent can publish about itself.

### 3.3 Change-point and regime detection
- **Methods:**
  - BOCPD (Adams & MacKay 2007), with the robust variant of Altamirano, Briol & Knoblauch (ICML 2023).
  - Offline PELT or binary segmentation via `ruptures`.
  - CUSUM.
- **Precedent:** the Stanford real-time alerting system ran NightSignal, RHRAD and **CuSum** on smartwatch resting HR. It flagged 80% of 84 COVID-positive participants before symptoms or asymptomatically, a median of 3 days before onset. False-positive triggers included stress, alcohol and travel, at 1.15 alert-days per person ([Alavi et al., Nature Medicine 28(1), 2022](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8799466/)) [PEER-REVIEWED].
- **Caveat:** BOCPD struggles when the baseline shifts irreversibly ([ResearchGate](https://www.researchgate.net/publication/328990553_Bayesian_Online_Changepoint_Detection_Of_Physiological_Transitions)). Pair it with a hazard prior tuned to a realistic rate of changes per year.

### 3.4 Observational causal inference on one person (with caveats)
- **Interrupted time series / Bayesian structural time series (CausalImpact).** Use these for *dated* life events such as a new training plan, a job change, a medication or travel. There is an existing biomedical-sensor demonstration ([PMC8412351](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8412351/)).
  - Covariates must be unaffected by the intervention, which is hard with physiology.
  - Report the posterior effect with a CI and a placebo test (fake intervention dates).
- **Person-as-population / g-formula / MoTR** (Daza). These estimate a "recurring individualized treatment effect" from self-tracked data. MoTR (Statistics in Medicine 2025) explicitly simulates randomization over a fitted model of one person's Fitbit sleep and steps. ([arXiv 1901.03423](https://arxiv.org/pdf/1901.03423); [arXiv 2208.00739](https://arxiv.org/pdf/2208.00739v7)) [PEER-REVIEWED/PREPRINT]
- **Declare the DAG.** Write down the assumed graph, for example: day-of-week → exercise → sleep → HRV → energy, plus alcohol and illness as unmeasured confounders. Only adjust for variables the graph licenses. Publishing the DAG is itself a credibility signal.
- **Granger causality and transfer entropy.** These only test *predictive precedence*. They are confounded by shared drivers and by the sampling rate. Use them only as "lead-lag" descriptors, never as causal labels.
- **Fixes the current Pearson approach needs:**
  - Detrend or difference, or use within-week centering, before correlating.
  - Prewhiten, or compute the effective sample size n_eff ≈ n(1−ρ₁ρ₂)/(1+ρ₁ρ₂).
  - Use **block-bootstrap CIs**.
  - Apply **Benjamini–Hochberg FDR** across all pairs × lags. With about 13 nodes, that is roughly 78 pairs × 3 directional tests, so about 230 tests per run, and at α=0.05 you would expect about 12 false edges.
  - Detecting r=0.3 at two-sided α=0.05 with 80% power needs **about 85 independent days**. The current `min_n: 10` is roughly 8 times too small.

### 3.5 Randomized self-experiments (N-of-1 trials): the only route to causal claims
- **Design:** randomized crossover blocks of ABAB or ABBA, with run-in, washout and blinding where possible. A methodological review of 74 trials found a median of 6 periods ([Trials 2024](https://link.springer.com/article/10.1186/s13063-024-08100-1)). The 2026 Experimental Physiology review covers digital N-of-1 trials with Bayesian posteriors, such as "P(effect > clinically meaningful difference)" ([Konigorski et al. 2026](https://physoc.onlinelibrary.wiley.com/doi/10.1113/EP092753)) [PEER-REVIEWED].
- **Anytime-valid inference:** confidence sequences let you peek every day without inflating type-I error ([Malenica, Guo, Gan, Konigorski, arXiv 2309.07353](https://arxiv.org/abs/2309.07353)) [PREPRINT]. This suits an agent that updates daily.
- **Adaptive designs:** "Platform-of-1" Bayesian adaptive N-of-1 designs choose among several candidate interventions ([Stat Biopharm Res 2025](https://www.tandfonline.com/doi/full/10.1080/19466315.2025.2565157)).
- **Existing tools** (StudyU, StudyMe, Self-E, QuantifyMe) are standalone apps. **None is wired to a wearable-plus-LLM agent that pre-registers, randomizes, monitors adherence and analyzes automatically** [INFERENCE from the [StudyMe paper](https://link.springer.com/article/10.1186/s13063-022-06893-7) and the [2026 review](https://arxiv.org/pdf/2412.15076)].

### 3.6 Bayesian state-space and hierarchical models
- **Latent "recovery state" model.** Build a dynamic linear model or Kalman filter with a latent daily state *x_t*. It emits HRV, resting HR, sleep duration and journal energy, each with its own noise. Missing days are handled natively, with no imputation (the same idea as LSM-2's AIM). The model gives forecasts with uncertainty and a principled way to combine sparse journal entries with dense wearable data.
- **Tooling:** `statsmodels` UnobservedComponents / `KalmanFilter`, or PyMC / NumPyro.
- **Hierarchical structure** across *signals* or *weekdays* (partial pooling) instead of across people. This lets a sparse journal borrow strength.

---

## 4. Competitive products: what they do and what they don't

| Product | What it does (2026) | What it does **not** do (verifiable gaps) |
|---|---|---|
| **Google Health Coach** (GA May 2026, Premium) [VENDOR/PRESS] | Data-science agent with code generation, workout plans, conversational food logging, Coach Notes memory, SHARP evaluation ([Google](https://research.google/blog/how-we-are-building-the-personal-health-coach/); [TechRepublic](https://www.techrepublic.com/fr/article/news-google-health-fitbit-app-ai-coach-widget/)) | No published accuracy numbers for SHARP. Reviewers report it treats non-wear days as rest and invents data (see prior note). No calibration of predictions shown to users. No user-visible computation trace. Human reviewers read conversations. |
| **WHOOP AI** [VENDOR] | My Memory (view, edit, delete), Proactive Check-Ins (after poor-sleep streaks, before events), voice/text Journal that suggests items from data patterns, clinician video visits, HealthEx medical records (May 2026) ([BusinessWire, 2026-05-08](https://secure.businesswire.com/news/home/20260508464188/en)) | Journal "impact" insights exist, but there is no randomization, no CI disclosure, and no scored forecasts. Community complaints that it is rule-based and generic (prior note). |
| **Oura Advisor** [VENDOR] | Memories (review and delete), conversation history (app 7.17, Jun 2026), a proprietary women's-health LLM (Apr 2026), charts ([Oura support, updated 2026-10-14](https://support.ouraring.com/hc/en-us/articles/39512345699219-Oura-Advisor)) | No exposed provenance or calibration. Insights are not falsifiable. |
| **Apple** (Project Mulberry / "Health+") [PRESS] | Scaled back in Feb 2026. Not shipped at WWDC 2026. Pieces may arrive later in iOS 27 ([9to5Mac](https://9to5mac.com/2026/08/29/apple-health-revamp-ai-coach-new-apple-watch-next-month/); [Macworld](https://www.macworld.com/article/3055235/apples-ai-powered-health-service-is-reportedly-on-life-support.html)) | No shipped coach as of my searches. I could not confirm any September 2026 announcement. |
| **Bevel** (iOS) [PRESS] | Free tracking. Pro tier ($14.99/mo) adds an AI coach, biological age and records. Praised for data reconciliation. WHOOP sued Bevel in Jul 2026 over data access ([healthappinsider](https://www.healthappinsider.com/en/reviews/bevel-review)) | "Good enough at everything". No scientific transparency layer. |
| **Athlytic, Welltory** | HRV-readiness scores and correlation dashboards (I did not research these in depth this round. Welltory has long marketed "what affects your HRV" correlations.) | Correlations are shown without FDR, autocorrelation correction or causal labels [INFERENCE]. |

**Gaps that are open, and that a solo project can genuinely own [INFERENCE]:**
1. **A public track record.** Every forecast the agent makes is timestamped, scored with proper rules, and plotted against baselines. This is an "agent report card".
2. **Verifiable computation.** Each number in a reply links to the exact SQL or code and its output hash, and can be re-executed.
3. **Statistical honesty labels.** Each claim is tagged association / predictive / randomized-tested, with n, n_eff, CI and FDR status.
4. **User-owned memory plus a portable eval set.** Memory is a local SQLite table. The eval set is generated from the user's own data, so anyone can rerun it on their own export.
5. **Randomized self-experiments run by the agent.** No consumer coach randomizes.

---

## 5. Responsible-AI and medical boundaries

- **FDA General Wellness guidance (revised final, 2026-01-06) [DOCS via law-firm summaries].** It now permits some non-invasive estimates (for example blood pressure) as wellness outputs if the intended use is strictly wellness. A product **loses** wellness status if it does any of the following:
  - references specific diseases or diagnostic thresholds;
  - prompts clinical action through alerts or alarms;
  - gives treatment guidance;
  - claims "clinical accuracy" or "medical grade";
  - reports values for screening or diagnosis.

  It *may* say "evaluation by a healthcare professional may be helpful" when outputs are outside wellness ranges, but it must not call them abnormal. ([Covington, Jan 2026](https://www.cov.com/en/news-and-insights/insights/2026/01/fda-issues-revised-guidance-on-general-wellness-products); [Faegre Drinker](https://www.faegredrinker.com/en/insights/publications/2026/1/key-updates-in-fdas-2026-general-wellness-and-clinical-decision-support-software-guidance)). The CDS guidance was updated the same month. FDA said it would revisit AI device-software policy in FY26.
  - **Design implication:** an "illness early-warning" feature must be framed as "your overnight resting HR, skin temperature and respiration are unusually elevated relative to your baseline; consider rest, and a clinician if you feel unwell". Never "possible infection".
- **EU AI Act.** The Digital Omnibus on AI is Regulation (EU) 2026/1744, in force since 2026-07-27. It moves Annex III high-risk obligations to **2027-12-02** and AI embedded in regulated products (including medical devices) to **2028-08-02**. **Article 50 transparency duties apply from 2026-08-02**: disclose that users are interacting with AI. ([Gibson Dunn](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/); [aiacto](https://www.aiacto.eu/en/blog/digital-omnibus-ai-act-report-2027)) [PRESS/legal commentary]
  - A wellness agent with no medical purpose under the MDR is generally not high-risk. Article 50 disclosure still applies if it is offered to EU users [INFERENCE].
- **Disclaimer best practice.** This builds on the prior note's stack. Additions:
  1. per-claim evidence tier (association / predictive / randomized);
  2. calibration disclosure ("my 'likely low energy' calls have been right 64% of the time over 81 days, against 52% for guessing from your average");
  3. explicit abstention when coverage is insufficient (non-wear, sync gaps).
- **Publishing your own data safely:**
  - Wearable signals are highly re-identifiable. A systematic review found correct re-identification in 86–100% of cases, sometimes from 1–300 seconds of signal, mainly ECG/gait/HR ([PubMed 36797124](https://pubmed.ncbi.nlm.nih.gov/36797124/); [Lancet Digit Health 2023](https://www.thelancet.com/journals/landig/article/PIIS2589-7500(23)00055-9/fulltext)) [PEER-REVIEWED].
  - Since the subject is known (you), the aim is **minimising inferable sensitive facts**: locations, schedules, illnesses, alcohol, relationships.
  - **Practical recipe [INFERENCE + ESTABLISHED SDC practice]:**
    1. Publish derived *results* (effect sizes, calibration curves, backtest tables) rather than raw series.
    2. If you publish series: daily or weekly aggregates only, **a random global date shift** (keep weekday alignment if needed by shifting a multiple of 7 days), dropped GPS and exercise-location fields, rounded values (HR to 1 bpm, steps to 100), and suppression of rare events.
    3. Optionally add Laplace noise to aggregates if you also publish many slices.
    4. Never publish free-text journal entries.
    5. Check Google Health API Limited Use before publishing anything derived (Section 2).

---

## 6. Grounding in the current code: specific defects and upgrades

| File / behaviour | Issue | Upgrade |
|---|---|---|
| `learn.py` `hit = actual > mean` (or `<`) | Ties count as misses for **both** directions. On an integer 1–10 scale, ties with a non-integer mean are rare, but the base rate of "above mean" is not 0.5 for skewed journals. | Compare against the empirical base rate. Better still, emit probabilities and score them with Brier/RPS (Section 3.1). |
| `recompute_weights` with `MIN_SCORED_FOR_WEIGHT = 5` | A 4/5 hit rate is easily chance (p≈0.19). | Beta-Binomial posterior. Weight is a function of P(skill>0) and the size of the credible interval. |
| Predictions are emitted **only on anomaly days** | Selection bias, slow evidence accumulation, and nothing to compare against on normal days. | Forecast **every day**, from the baseline model and from each signal model, and score all of them. Anomaly days become one stratum. |
| `effective_threshold = base_z / weight` | A feedback loop: a lower threshold leads to more predictions, which leads to more evidence for the same signal. It is also not separated from the evaluation data. | Freeze weights per evaluation window (out-of-sample, rolling origin). Report pre-update vs post-update skill. |
| `analyze.py` mean/pstdev z-scores over the last N *rows* | Not robust: one illness week inflates σ. Rows ≠ days when there are gaps. No day-of-week effect. **No wear-time gating**, so a non-wear day reads as a steps anomaly, which is exactly Google's "mummy" failure. | Median/MAD or EWMA baselines on a calendar index, weekday adjustment, and a **coverage gate** (HR-minutes present ≥ X% of the day; exclude or label "not worn"). Conformal bands (Section 3.2). |
| `correlate.py` Pearson, `min_n: 10`, `min_abs_r: 0.3`, no CIs, all pairs | Spurious correlation from trends and autocorrelation, no multiplicity control, about 230 tests per run. `steps`/`distance`/`calories` are mechanically coupled, so trivial edges dominate. | Detrend and prewhiten, n_eff, block-bootstrap CIs, BH-FDR, exclude definitional pairs, and label every edge "association". |
| `PREDICTIVE_SIGNALS` hand-coded with `lag 1` | The priors are fine but hard-coded. | Keep them as *priors* in a Bayesian model and let data update them. Log the prior in the provenance record. |

---

## 7. Ranked signature features

Scoring: 1–5 on each axis. **Score = Novelty × Feasibility × Demo impact × Defensibility** (max 625).

| Rank | Feature | N | F | D | S | Score |
|---|---|---|---|---|---|---|
| 1 | **Calibrated forecast ledger ("the agent's report card")** | 5 | 5 | 5 | 5 | **625** |
| 2 | **Verifiable-computation answers plus a personal benchmark generated from your own data** | 4 | 5 | 5 | 5 | **500** |
| 3 | **Agent-run randomized N-of-1 experiments with anytime-valid analysis** | 5 | 4 | 5 | 5 | **500** |
| 4 | **Wear-aware conformal "expected range" plus change-point regime detection** | 4 | 4 | 4 | 5 | **320** |
| 5 | **Honest association graph (detrended, n_eff, bootstrap CIs, FDR, DAG-labelled)** | 3 | 5 | 4 | 5 | **300** |
| 6 | **Latent recovery-state model (Bayesian state-space fusing wearable plus sparse journal)** | 4 | 3 | 4 | 4 | **192** |
| 7 | **Foundation-model forecasting bake-off (Chronos-2 / TimesFM 2.5 vs EWMA/seasonal naive, CRPS)** | 3 | 4 | 4 | 4 | **192** |
| 8 | **Privacy-safe public artifact (date-shifted aggregates plus results card)** | 3 | 4 | 3 | 4 | **144** |

### Detail per feature

**1. Calibrated forecast ledger**
- **Method:**
  - Every evening the agent writes probabilistic forecasts for tomorrow's journal fields, such as P(energy ≥ personal median) and a full 1–10 distribution. It does this from several competing models: climatology, persistence, signal-rules (today's loop), and later the state-space model and the LLM's own judgment.
  - Each forecast is append-only and timestamped (optionally hash-chained or git-committed). Forecasts are scored with Brier, log and RPS. Skill is computed against climatology and persistence, with reliability diagrams and the Murphy decomposition.
  - Signal weights become Beta-Binomial posteriors.
  - **Include the LLM coach as a forecaster.** Showing whether Gemini beats the mean for *you* turns BALMS's population finding into a live n-of-1 replication.
- **Data:**
  - Wearable data already exists.
  - Journal: about **30 entries** to show a first reliability curve (wide CIs).
  - **60–90 entries** for a defensible skill estimate.
  - About 67+ scored binary calls to detect a 0.65 vs 0.50 hit rate.
- **Evaluation:**
  - Skill score with a block-bootstrap CI.
  - Expected calibration error.
  - Pre-registered baselines.
  - Coverage of the 90% predictive set.
- **Why novel:** no consumer coach or frontier paper publishes a per-user, proper-scored track record (Section 4). It builds directly on the existing `predictions` table.

**2. Verifiable computation plus a personal benchmark**
- **Method:**
  - The data-science agent may only state numbers that come from a tool call. Each tool call stores (SQL/code, inputs hash, output, timestamp) as a "receipt", and replies render receipt IDs.
  - A **claim checker** re-executes receipts and diffs them against the reply text before sending.
  - Auto-generate a **personal benchmark** using WearableQA's 8 data-reasoning templates and PHIA's categories from your SQLite, with deterministic answers. Add **abstention items**: non-wear days, sync gaps, data types you don't have.
  - Run it as an ADK eval set in CI.
- **Data:** none beyond what you have.
- **Evaluation:**
  - Exact match with Wilson CIs, following the WearableQA protocol.
  - Abstention precision and recall.
  - Hallucinated-number rate (numbers in the reply with no receipt).
  - Compare: Gemini without tools vs with tools vs with the full agent, mirroring PHIA's and WearableQA's ablations.

**3. Agent-run randomized N-of-1 experiments**
- **Method:**
  - The user picks a hypothesis, for example caffeine cutoff at 14:00, no alcohol, morning vs evening training, or screen curfew.
  - The agent pre-registers it in an immutable file with a hash covering: the estimand, the primary outcome (for example overnight HRV or next-day energy), block length (≥7 days, so day-of-week is balanced), washout, number of blocks (≥6, i.e. 3 AB pairs, per the median-6 finding), randomization seed, and stopping rule.
  - It then nudges adherence, logs compliance, and analyzes using:
    - a Bayesian model with AR(1) errors, giving P(effect > minimal important difference);
    - confidence sequences for daily peeking.
- **Data:** about 6–8 weeks per experiment. The journal is needed only if the outcome is subjective.
- **Evaluation:**
  - The posterior and CI, plus a pre-specified decision.
  - A simulation-based power check before starting.
  - Report adherence.
- **Defensibility:** this is the *only* feature that licenses causal language for one person.

**4. Wear-aware conformal ranges plus change-points**
- **Method:**
  1. A coverage gate: compute daily wear fraction from heart-rate minutes, and mark days as "not worn" or "partial". The agent must say "no data", never "rest day".
  2. Forecast with EWMA or seasonal naive, wrapped in ACI/AgACI for 80/90% bands.
  3. BOCPD or CUSUM over resting HR, HRV, `daily-sleep-temperature-derivations` and `daily-respiratory-rate`. Add these types to the sync.
  4. Wellness-framed messaging (Section 5).
- **Data:** 28+ days of history for bands. Several months for regime detection.
- **Evaluation:**
  - Empirical coverage vs nominal.
  - Alert-days per month as the false-alert burden (Alavi: 1.15 per person for non-COVID triggers).
  - Retrospective check against journal "sick"/high-soreness days, reported as precision and lead time.

**5. Honest association graph**
- **Method:**
  - Calendar index; detrend with STL or a weekly-centred residual.
  - Prewhiten and compute n_eff.
  - Stationary block bootstrap for the CI on r (or Spearman).
  - BH-FDR at q=0.1 across all tests.
  - Drop definitional pairs (steps↔distance↔calories).
  - Label every edge "association; not tested". Edges promoted by #3 get the label "randomized-tested".
  - Render a DAG the user can edit.
- **Data:** 85+ days for |r|≈0.3. The journal edges remain thin for months.
- **Evaluation:** the number of edges surviving FDR, and stability under a split-half (first vs second half of the data).

**6. Latent recovery-state model**
- **Method:** a dynamic linear model in NumPyro or statsmodels. A latent AR(1) state emits z-scored HRV, resting HR, sleep minutes and journal energy, each with its own loading and noise. It handles missing values natively. Its forecasts become another entrant in the #1 ledger.
- **Data:** about 90 days of wearable data. The journal can be sparse, since partial pooling helps.
- **Evaluation:** out-of-sample RPS/CRPS vs the rule-based signals, and posterior predictive checks.

**7. Foundation-model forecasting bake-off**
- **Method:** Chronos-2 (Apache-2.0, runs on CPU at daily resolution) and TimesFM 2.5 zero-shot, with and without covariates. Rolling-origin backtest at horizons of 1–7 days, scored on CRPS/MASE against EWMA and seasonal naive. Publish the results **including losses**.
- **Evidence:** expect small gains (HRV study: MASE 0.81 vs 0.84).
- **Evaluation:** a Diebold–Mariano-style test or bootstrap CI on the score differences.

**8. Privacy-safe public artifact**
- **Method:** a "results card" (calibration curve, experiment posteriors, backtest table, benchmark scores) plus an optional weekly-aggregate dataset that has been date-shifted and rounded. Include a data statement covering the Limited-Use reading.
- **Evaluation:** a checklist (no GPS, no free text, no daily dates, no rare events). Include a simple linkage-risk self-audit.

### Suggested sequence for a solo developer (8–10 weeks)
1. Weeks 1–2: #2 receipts plus the personal benchmark, and the #4 wear-gating fix (cheap, and kills the most embarrassing failure mode).
2. Weeks 2–4: #1 ledger. Start daily forecasts **now**, because journal days are the binding constraint and every day of delay pushes the first credible skill estimate back.
3. Weeks 3–4: #5 statistical hygiene in `correlate.py`.
4. Weeks 4–10: launch one #3 experiment, which runs in the background while you build #4, #6 and #7.
5. At the end: the #8 results card.

---

## 8. Gaps and uncertainties in this research

- The PHA PDF exceeded the fetch limit. I could not verify the exact list of 10 tasks, the location of the open-sourced benchmark, or the coach's six evaluation dimensions. The 75.5%/58.4% code pass rates come from a secondary summary.
- I could not confirm the PHIA dataset repository link, or whether the SensorLM, SensorFM or LSM-2 weights are public. They are probably not.
- TimesFM 3.0's details and licence come from a secondary source.
- I found no confirmed Apple announcement from Sep/Oct 2026. Athlytic and Welltory were not researched in depth this round.
- I found no peer-reviewed within-person effect sizes for "wearable → next-day self-rated energy" in healthy adults. The available EMA studies are mostly in adolescents or clinical groups, with small or weak effects (for example [Qiao et al., PLoS One 2025](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0329399), β≈0.04). **So expect modest skill, and frame the ledger as an honest measurement, not a promise.**
- Legal points (FDA, EU AI Act, Limited Use applied to self-publication) are summarized from secondary legal commentary. This is not legal advice.
