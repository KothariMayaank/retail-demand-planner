# Project review and data science internship roadmap

Reviewed 10 October 2026. Scope: current application source, data generation and schemas, forecasting, evaluation, uncertainty, inventory, UI, tests, exports, saved-run reproduction, packaging, workflow and documentation. Generated historical snapshots were treated as past evidence, not independently reviewed versions of the application.

## Assessment

This is a credible end-to-end student project and can already be listed honestly on a resume. It demonstrates more than model fitting: data validation, forecasting under realistic information constraints, baseline selection, uncertainty diagnostics, business decision logic, software separation and reproducibility. For a data science/ML internship, its main weakness is the experimental evidence. The only dataset is synthetic, the model family comparison is narrow, and there is no measured operational outcome. It is currently stronger as a forecasting application demonstration than as evidence of generalizable ML performance.

Keep the modular Python package and Streamlit interface. Develop a reproducible research benchmark alongside them, with a short case study explaining the problem, choices, results and failures. A notebook is useful for exploration and interpretation; the tested package should remain the source of forecasting and evaluation logic. Rewriting everything in a notebook, adding a chatbot or introducing microservices would not address the main weakness.

## Corrections made

| Finding | Consequence | Correction and evidence |
|---|---|---|
| Aggregate order-up-to arithmetic conflicted with the documented lost-sales assumption | Orders could replace sales already lost before arrival; late receipts could also suppress stock needed earlier | Replenishment now uses stock remaining at arrival, maximum subsequent cumulative deficits and an ending buffer. Independent enumeration of legal orders checks the result against a separate daily stock ledger. |
| Replay used pandas' default missing-value vocabulary | Valid IDs such as `NA` could disappear or fail retraining comparisons | Only empty cells are interpreted as missing when reading saved CSVs; regression test includes literal `NA` and an unknown stockout flag. |
| Cache key omitted the data-source label | Identical content could reuse incorrect source/synthetic metadata | Source provenance is now included in the full-data digest. |
| Selected-model audit metrics inherited the paired-candidate subset | A working baseline could have no selected-model score when ML was unavailable | Selected-model metrics now use that model's own eligible audit dates and expose their denominator; head-to-head metrics remain paired. |
| Release check searched for the word “synthetic” | A manifest explicitly declaring `is_synthetic: false` could pass | Release requires the actual boolean `is_synthetic: true`. This check is a declaration check, not a proof of data origin. |
| Missing numeric results relied on pandas concatenation inference | Future library behavior could change output types | Numeric fold and range metadata are explicitly typed; the complete suite passes with future warnings treated as errors. |
| Documentation retained old page names, a misleading upload-retention statement and the incorrect P006 order | A reader could misunderstand navigation, persistence and the business calculation | Updated policies, README, acceptance notes and presentation. |

Added an audit scorecard, RMSE and signed bias, and included the scorecard, fold details and interval audit rows in the results ZIP. No point-forecast model or selection threshold was tuned to improve the displayed audit scores.

## Important inventory example

For sample P006, the first forecast is still 49.5 units. There are 78.25 expected units lost before a new order could arrive. A listed 300-unit delivery covers the remaining 225 units of protection-period demand, leaving 75 units against a 60.65-unit buffer. The corrected standard order is **zero**, while the early shortage still requires attention. The previously documented 72-unit order incorrectly replenished already-lost demand. P003 provides a positive-order example of 336 units.

The revised policy is deterministic and uses fixed delivery dates. It has not been shown to minimize expected business cost. It handles timing consistently with the stated assumptions, which is different from proving an optimal inventory policy.

## Reproduced forecasting evidence

All figures below use the same synthetic sample: 20 products, 14,600 sales observations and nine known stockout days. “Selected” means the policy frozen from older development folds: use ridge where it qualifies, otherwise retain the weekday baseline. It does not mean retrospectively choosing the best audit model.

| Forecast horizon | Eligible audit product-days | Baseline MAE | Selected MAE | Relative MAE reduction | Baseline WAPE | Selected WAPE | Products better / worse / tied |
|---|---:|---:|---:|---:|---:|---:|---|
| 7 days | 417 | 4.389 | 3.981 | 9.30% | 32.59% | 29.56% | 10 / 2 / 8 |
| 14 days | 837 | 4.484 | 4.116 | 8.19% | 33.19% | 30.47% | 11 / 3 / 6 |
| 28 days | 1,677 | 4.410 | 4.157 | 5.73% | 32.46% | 30.60% | 13 / 0 / 7 |

MAE is in units per product-day. Errors are pooled before division, so these results give more influence to high-volume error contributions. They are not an average of per-product percentage improvements. Audit periods run from 19 September, 29 August and 18 July respectively through 9 October 2026. Each horizon excludes three known stockout targets. Horizons share dates and must not be counted as independent experiments.

Ridge is selected in 39 of 60 product/horizon cases; five selected cases lose to baseline in the audit. Twenty-nine of 60 prediction ranges fall below their 80% coverage target. The scorecard additionally records RMSE and signed bias; positive bias means overforecasting. These results establish behavior on this simulation, not real-store accuracy, statistical significance or financial savings.

Reproduce the evidence:

```powershell
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest discover -s tests -q
.\.venv\Scripts\python.exe scripts/verify_end_to_end.py
$reviewRun = (Get-Content outputs/verification/acceptance_results.json -Raw | ConvertFrom-Json).sample_run
.\.venv\Scripts\python.exe scripts/summarize_evaluation.py $reviewRun
```

The scorecard is saved to `outputs/project-review/audit_scorecard.csv`. The acceptance run verifies sample and uploaded fixtures, independent arithmetic, exports and complete saved-run retraining. Current tests: **120 passed** in the working project and in a clean extraction of the release source using the existing deployment-check environment. Both entry-point HTTP startup checks and dependency consistency passed. The browser sample workflow confirmed the revised inventory explanation and audit labels. This review reused installed Windows environments; it did not claim a fresh installation or completed Linux/cloud deployment.

## Is the forecasting approach right?

The foundation is sound. A weekday baseline is appropriate for checking whether ML adds value. Prior-only lag features, origin-specific fitting/scaling, recursive forecasts and chronological development/audit windows address the main leakage risks. Multi-step rolling evaluation matches the intended forecast task; this is the approach described in [Forecasting: Principles and Practice](https://otexts.com/fpp3/tscv.html).

The next version should address these limitations:

1. **Observed sales are not unconstrained demand.** Excluding known stockout targets avoids scoring censored values as true demand, but does not recover lost demand and can exclude particularly difficult periods. Unknown availability remains unknown. Use availability records when possible and describe real benchmark results as sales forecasting unless latent demand is supported by evidence.
2. **The simulation resembles the model's features.** It deliberately contains smooth annual patterns, weekday effects and trends. Success against this generator is useful for testing the system, but weak evidence that the model will handle a new retailer, changing promotions or structural breaks.
3. **MAE is not an inventory objective.** Absolute-error optimization favors a conditional median; squared-error optimization favors a conditional mean. Sparse demand can reward predictions near zero under MAE even when those forecasts understate expected stock needs. Keep MAE/WAPE for continuity, but assess RMSSE or RMSE, bias and inventory outcomes before changing the selection rule. [Metric interpretation](https://otexts.com/fpp3/accuracy.html).
4. **The audit is small and seasonally narrow.** Each horizon has only three audit origins. Evaluate more origins across different seasons, show results by origin and demand segment, and reserve a final untouched time block. Once audit results influence feature or threshold choices, treat that audit as development evidence for future work.
5. **Model selection and range calibration share observations.** The current ranges correctly avoid coverage guarantees, but selected models can have optimistic development errors. Use separate chronological tuning, calibration and final test periods; compare coverage together with interval width and interval score. Never add daily marginal bounds to claim an 80% total-demand range.
6. **Recursive ridge is a reasonable first challenger, not a complete model comparison.** Add a small set of justified alternatives and test them under the same information constraints. A pooled model may learn from other products; it is a hypothesis to evaluate, not an automatic improvement.
7. **Different horizons may select different models.** The first seven days in a 7-day forecast can differ from the first seven in a 28-day forecast. Inventory consistently uses 28 days. Document this for users; if consistency becomes a requirement, evaluate one common forecast trajectory or a reconciliation rule.

The sample's service-level and simulation settings are legacy reserved fields. They do not provide a 95% service level or a stochastic inventory simulation. Remove them in a versioned schema cleanup, or implement and validate their meaning before exposing them as functional capabilities. Likewise, “causal features” here means past-information-only construction, not causal inference about promotions.

## Highest-value next work

| Priority | Work | Concrete completion evidence |
|---|---|---|
| 1 | Add a real retail-sales benchmark | Dataset provenance and allowed-use notes; deterministic adapter; fixed SKU selection; missing/zero/availability rules; chronological split file; reproducible metrics. |
| 2 | Compare a compact model suite | Seasonal naive, existing weekday mean, ridge and one pooled gradient-boosted tree model on identical origins. Add an intermittent-demand baseline for sparse products. Record parameters, runtime and memory. |
| 3 | Explain where gains come from | Ablations removing calendar, lag and rolling features; results for regular/intermittent/high/low-volume products; errors by lead day and origin; examples where baseline wins. |
| 4 | Improve uncertainty | Separate calibration data; report 80%/95% coverage, width and interval score by segment/lead band on a fresh final test. Do not widen ranges on the same test and call them validated. |
| 5 | Evaluate inventory decisions | An event-driven historical simulation with identical demand, initial stock, supplier rules and review dates across policies. Report fill rate, lost units, mean stock, order count and cost sensitivity. |
| 6 | Package the evidence for reviewers | Concise case study, one exploration notebook importing the package, reproducible benchmark command, version control, passing CI, a synthetic demonstration link and a short video. |

A suitable next dataset is a defined subset of **M5**, such as one store and 20–50 products chosen by a rule fixed before inspecting test performance. It contains daily retail sales and a 28-day forecasting task. Keep any invented stock, lead times or supplier constraints explicitly marked as simulation assumptions; they are not observed business outcomes. Full M5 competition results use a weighted scaled metric, so a subset MAE result must not be described as a comparable competition score. [Official M5 task and evaluation](https://www.kaggle.com/c/m5-forecasting-accuracy/overview).

For the nonlinear challenger, a histogram gradient-boosted model with lag/calendar features is a practical experiment. Choose recursive or direct-horizon prediction explicitly and evaluate the same multi-day procedure that will run in production. The [scikit-learn lagged-feature example](https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html) demonstrates chronological evaluation and quantile prediction. Do not copy a random train/test split or use future actual lags inside a multi-day test.

For sparse products, compare an intermittent-demand method such as a Croston-family baseline. This addresses a pattern present in four sample products; it does not guarantee an improvement, and uncertainty needs separate treatment. [Intermittent counts and Croston's method](https://otexts.com/fpp3/counts.html).

In the inventory experiment, zero recorded sales must not automatically be treated as zero underlying demand. Benchmark sales can be used as a clearly labeled demand proxy, or the existing synthetic latent-demand series can support controlled simulation experiments while remaining excluded from fitting. Define fill rate as fulfilled units divided by demand units, with an explicit zero-denominator rule. Label financial costs as assumed unless supplied by a retailer. The new replenishment fix alone is not evidence of realized savings.

## Suggested four-week sequence

- **Week 1:** finish the real-data adapter, EDA and frozen experiment protocol; reserve the final test before model exploration.
- **Week 2:** compare baselines, ridge and the pooled challenger; record per-origin results and feature ablations on development data.
- **Week 3:** evaluate interval calibration and inventory policies; run the untouched test after all decisions are fixed.
- **Week 4:** write the case study, prepare reproducible release/CI and record a three-minute demonstration; publish only when the destination and visibility are chosen.

This is a prioritization guide, not a deadline commitment. Start with the real-data benchmark before spending effort on additional UI screens or infrastructure.

## Resume and interview presentation

Suggested title: **Retail Sales Forecasting and Inventory Decision Support**.

Safe current resume bullets:

- Built a modular Python/Streamlit forecasting and replenishment application for 20 synthetic retail products, with CSV validation, 7/14/28-day forecasts and reproducible model/input snapshots.
- Evaluated weekday and ridge forecasts using chronological development and audit windows; reduced pooled audit MAE by 5.7% at the 28-day horizon on synthetic data, while retaining baselines where ML failed the development threshold.
- Implemented empirical range diagnostics and delivery-aware lost-sales inventory planning, verified by 120 automated checks including leakage, replay and independent stock-ledger scenarios.

After real-data evaluation, replace the synthetic performance bullet with the real dataset, precise metric, baseline, horizon and held-out improvement. Do not claim an accuracy percentage from WAPE by subtracting it from 100, a 95% service level, causal promotion effects, business savings or production scale without the corresponding evidence.

Be able to explain the stockout censoring problem, why random splitting is inappropriate, how a forecast for day 14 obtains lagged inputs, why ridge can lose to the baseline, why MAE can mislead for intermittent demand, why daily intervals do not sum into a total interval, and why P006 can need urgent attention while receiving a zero standard-order suggestion. Those explanations will be more persuasive than simply listing libraries or a test count.

## Delivery and remaining limits

The approved source repository is [KothariMayaank/retail-demand-planner](https://github.com/KothariMayaank/retail-demand-planner); the app has no verified public deployment. The allowlisted source package excludes uploads, generated runs and virtual environments. Original source/doc copies from this review are retained locally under `outputs/project-review/original`; historical run snapshots retain their original logic and should not be presented as results of the corrected version.

Real-store accuracy, cost savings, multi-user privacy, production retention, cloud capacity, mobile behavior and external supplier behavior remain unverified. No review can establish that all possible defects are absent. The fixes and test evidence above cover the concrete issues reproduced during this review.
