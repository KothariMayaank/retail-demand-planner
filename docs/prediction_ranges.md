# Future forecasts and estimated prediction ranges

Open **Data & Setup**, load data and run analysis, then open **Forecasts**. Choose a product and a 7-, 14- or 28-day horizon. Analysis generates all three horizons, so changing this screen's horizon does not retrain or clear results. The sidebar forecast horizon still controls default views and Overview totals; changing sidebar settings invalidates results as before.

The screen shows up to 84 days of observed history, future daily predictions, the forecast total and daily average, the selected model, its selection reason and reserved historical audit metrics. A dotted boundary marks the last observed day. History gaps are not connected, and known historical stockouts are marked. Future dates start the day after the common store cutoff. Products with unavailable forecasts show their reason, empty values and an unavailable total rather than zero. Point forecasts may be available while ranges are unavailable.

## Range method

For each product, horizon and model actually used for its future forecast:

1. Take eligible out-of-sample predictions from the **three earlier development folds** already created by rolling backtesting. Use that model's own eligible targets, not the paired baseline/ML subset. Exclude known stockout targets, missing actuals and unavailable predictions. Require three folds and at least **20 usable errors**.
2. Compute absolute errors `abs(actual - prediction)`, including the recursive multi-day errors for ML. Pool the forecast lead positions **within that horizon**, never across products or horizons. There are too few folds to estimate a reliable separate quantile for each lead day.
3. Fix the daily-coverage target at **80%** before evaluation. Sort the N absolute errors and use the order statistic at rank `min(N, ceil((N + 1) * 0.8))`, with one-based indexing. This yields radius q in units; it is conservative relative to a simple interpolated sample percentile.
4. For each future point prediction p, use `[max(0, p - q), max(0, p + q)]`. Do not invent a range if calibration is insufficient. All point predictions are also clipped at zero. A zero empirical radius is allowed and explicitly explained.

These are **estimated daily prediction ranges**, not statistical confidence levels or guaranteed probabilities. Using historical forecast errors to approximate future uncertainty requires future errors to resemble earlier errors; [Forecasting: Principles and Practice](https://otexts.com/fpp3/prediction-intervals.html) discusses this general assumption. This implementation uses an empirical absolute-error quantile, rather than the book's bootstrap simulation. It makes no normal-distribution assumption and claims no conformal coverage guarantee.

Model selection and calibration share the development windows, which can make calibration optimistic for the chosen model. Serial dependence, seasonality changes, sparse demand and promotions can affect coverage. The separate audit makes these limitations measurable. Radius is constant across daily targets within a given horizon, so the target concerns pooled daily coverage, not a promise for each particular future lead day.

## Observed coverage and historical evaluation

Freeze q from development errors before the **three newer audit folds** begin. Apply it to each audit prediction made at its original rolling origin. Calibration targets must end no later than the first audit forecast origin; otherwise the function rejects the split.

Observed coverage = covered eligible audit days / all eligible audit days × 100. Use inclusive endpoints with a 1e-9-unit numerical tolerance for reproducible boundary comparisons. The screen exposes the covered-day count and denominator, alongside MAE and WAPE for the model actually used. These metrics use its own available audit pairs, so their denominator can differ from the paired model-comparison table. Known stockouts are excluded because their sales are censored; unknown availability remains usable. Coverage therefore concerns observed sales, not latent uncensored demand.

If no eligible audit dates exist, coverage and audit metrics are unavailable. If ranges cannot be calibrated, coverage is unavailable even when audit MAE/WAPE are available. Zero-total actual sales keep WAPE unavailable, while MAE remains defined. Coverage below the 80% target raises a visible warning; the audit never changes q or the model choice. A final ML-refit failure uses baseline forecasts and baseline range/evaluation errors with an explicit fallback reason.

## Totals, rounding and downloads

Daily forecasts are fractional expected units. UI values display two decimals, but the total sums the unrounded daily predictions. Bounds are calculated and coverage is assessed at full precision. Downloaded CSVs preserve numeric precision. There is no implied whole-unit inventory/order recommendation.

Do **not** sum daily lower/upper bounds and label the sums as an 80% total-demand interval: daily errors are dependent and marginal ranges do not establish joint coverage. This phase displays a point forecast total only.

**Download forecast CSV** exports the selected product/horizon: product ID/name, forecast origin, dates, point predictions, estimated lower/upper units, model/method/status and fallback reasons, calibration size, target daily coverage, empirical radius, observed audit coverage and its denominator. Missing values remain blank. Formula-safe text export handling is retained.

Downloads also offers all-horizon forecasts and range evaluation. Local saved runs add `future_forecasts.csv`, `interval_evaluation.csv` and `interval_audit_predictions.csv`, plus versioned range metadata in the manifest. `scripts/reproduce_run.py --retrain` checks all-horizon point predictions, interval bounds and coverage counts against saved results.

## Verification

Tests check quantile arithmetic, audit coverage, selected-model calibration, zero demand, zero-width ranges, clipping/order, insufficient history, target exclusions, future-audit isolation, split chronology, all three screen horizons, totals and plotted values, CSV precision and complete saved-run reproduction. The implementation is in `demand_planner/forecasting/uncertainty.py` and `demand_planner/ui/forecasting.py`.
