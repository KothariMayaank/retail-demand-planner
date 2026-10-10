# Regression forecasting, comparison and reproduction

## Model choice

Use one deterministic **ridge regression** per product. This is regularized least squares with an unpenalized intercept, suitable as a small, fast regression challenger to the weekday baseline. Its penalty limits unstable coefficients among correlated lag and rolling features. It is implemented with NumPy, so this phase adds no dependencies or paid services. The objective is `sum((y - intercept - Z @ coefficients)**2) + 10 * sum(coefficients**2)`; alpha is fixed at 10 before evaluation, with no full-history parameter search. See the [ridge definition](https://scikit-learn.org/1.8/modules/generated/sklearn.linear_model.Ridge.html).

Each training target uses 18 features: sales lags 1/7/14/28 days, prior 7/28-day means, prior 28-day standard deviation and zero-sales fraction, seven weekday indicators, annual sine/cosine and a linear trend measured in years from that product's first observation. All rolling calculations end on the previous day. The first 28 days warm up features; require at least 90 eligible target rows afterward (at least 118 calendar days without exclusions). Missing dates block fitting. Negative predicted units are clipped to zero; fractional point predictions are retained.

Fit feature means/scales exclusively on eligible training rows at that origin. Constant feature scales become 1; the intercept is the mean training target. Neither fitting nor feature creation accesses observations beyond the origin. Known stockout targets are excluded. For lag/rolling inputs on stockout days, substitute the expanding mean of strictly earlier usable observations, or zero if none exist yet. That zero is a documented stockout signal substitution, not a conversion of missing records to zero. Original sales are preserved, unknown stock availability remains usable and no lost demand is reconstructed.

## Multi-day forecasts and external features

Train once at each forecast origin. Predict origin + 1, append that prediction to the lag signal, and repeat for all 7/14/28 days. Days after the origin use previous predictions wherever a lag or rolling window reaches into the forecast period. They never use future actual sales, future stockout flags or future fitted imputations. Recursive errors can accumulate; multi-day backtests exercise this exact process.

Calendar dates are known in advance. Price and promotion features are **excluded** because current CSV schemas have no future plan table or plan publication timestamps. Historical values and synthetic reference promotion/demand files are not treated as advance knowledge. Adding these features later requires a dated plan with product/date/value and availability-at timestamp, an explicit missing-plan policy, and a snapshot filtered to what was available at each backtest origin. A retrospectively assembled future promotion schedule would not meet that requirement.

## Fair comparison and selection

Use exactly the baseline's rolling origins, 56-calendar-day initial-history threshold, horizons and up-to-six non-overlapping test windows. ML can be unavailable at earlier origins because its usable-history threshold is higher. Preserve unavailable predictions and target exclusions.

For a product/horizon with six folds:

1. The **oldest three** folds are development. Compare both models on the same dates where both predictions and actual sales are available and the target is not a known stockout.
2. Each development fold must have predictions for every target and at least 80% paired scoring coverage. Otherwise retain the baseline. Fewer than six folds also retain it.
3. Select ML only when pooled development MAE is at least **5% lower** than baseline MAE. A zero-error baseline, ties, unavailable comparisons and smaller gains retain the baseline. On identical pairs, WAPE has the same denominator, so it gives the same ranking when actual totals are positive. Zero-total WAPE remains unavailable and MAE determines selection.
4. Freeze that decision before the **newest three audit folds** begin. Report paired audit MAE/WAPE, RMSE and signed bias for both candidates. Separately report the selected model's own eligible audit days, so a usable baseline still has scores when ML is unavailable. Audit outcomes never change this run's choice. Display a warning if selected ML performs worse in the audit. This prevents presenting selection data as an independent test, but development improvement does not guarantee future improvement.

The same choice applies to future forecasts for that product/horizon, refitting its chosen model at the current store cutoff. If final ML refitting is unavailable, retain the baseline with a reason in daily exports. All-horizon selection decisions remain visible even when only one forward horizon is requested. No pooled-store model or cross-product features are used.

The dashboard comparison table separates development and audit. The existing baseline summary still covers all baseline folds and is labeled accordingly. The fold chart overlays both forecasts and observed sales; exports include `partition`, `paired_eligible` and origin. Never compare the all-fold baseline metric directly with paired audit ML metrics.

## Saved local artifacts

**Run analysis** saves a unique directory under `outputs/runs/`. Uploaded data remains in session memory until analysis; each saved run then persists normalized input CSVs, including explicit zero-fill provenance. Runs do not overwrite each other and are excluded from version control. Saved data is local, not sent to a service. Clear loaded data resets the session but does not delete saved runs.

Each run contains:

- `trained_models.json`: final fitted ML candidate for every eligible product, or an explicit unavailable reason. Includes feature order, scaling means/scales, coefficients, intercept, alpha, training-row count, origin, first date and the 28-day lag signal needed for recursion. It uses JSON rather than executable pickle. Baseline choices are in the comparison and forecast CSVs.
- `daily_forecasts.csv`, `model_comparison.csv`, `candidate_predictions.csv`, baseline summaries, folds and predictions. Candidate rows join baseline/ML predictions on origin and target date and retain eligibility.
- `inputs/`: the exact normalized four input tables used; synthetic truth is absent.
- `code/`: snapshots of project module source, configuration and dependency pins/lock file.
- `manifest.json`: UTC creation time, input fingerprint, forecast cutoff, settings/seed, model/selection versions, hyperparameters, split policy, Python/package versions, source hashes and SHA-256 hashes for saved files. The estimator itself uses no randomness.

The following verifies saved checksums and reproduces chosen future forecasts from the saved model and inputs, without retraining:

```powershell
.\.venv\Scripts\python.exe scripts/reproduce_run.py "outputs/runs/<run-directory>"
```

Add `--retrain` to rerun both candidates and verify decisions plus development/audit MAE. It checks that current module code matches the recorded run; use the saved code snapshot and dependency versions if the project has since changed. Numerical comparisons tolerate floating-point differences of 1e-10. The manifest's source snapshots make past logic reviewable; absolute paths are not embedded in model files.

Tests check prior-day feature alignment, cutoff-isolated scalers/fits, prior-only stockout substitutions, recursive use of predictions, exact baseline/ML fold alignment, selection thresholds and audit isolation, JSON reloads, literal IDs such as `NA`, checksum tampering, complete replay/retraining, and dashboard comparison/downloads. Uncertainty and inventory calculations live in separate modules. Here, prior-only or causal feature construction refers to time ordering, not causal inference about promotions or business outcomes.
