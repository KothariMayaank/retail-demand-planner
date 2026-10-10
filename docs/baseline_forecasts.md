# Baseline forecasts and rolling evaluation

This module implements the fixed baseline point forecast. Run analysis in **Data & Setup**, then open **Forecasts** for the next selected 7, 14 or 28 days, or **Model Performance** for tests at all three horizons. **Export Results** includes point forecasts, evaluation summaries and individual backtest predictions. Changing data or planning settings invalidates visible results; run analysis again. Previously saved run files remain on disk.

## Matching-weekday rule and fallback

The forecast origin is the last complete sales date across the store. Targets run from the next calendar day through origin + horizon, inclusive. Expected daily units may be fractional; predictions are not rounded.

For each product, use the latest **28 calendar days ending at the origin**. Exclude known stockout observations; unknown availability remains usable. With at least 28 calendar days of established history and at least two usable observations of the target weekday in that recent window, predict their arithmetic mean. For example, next Monday uses the recent usable Mondays. The same weekday estimate repeats across the forecast horizon.

If established history is shorter than 28 days, or fewer than two usable matching weekdays remain, use the mean of all usable observations in that same recent window. Every fallback row identifies its method and reason. Require at least **14 usable non-stockout training observations** overall and at least one usable recent observation. Otherwise predictions are unavailable, with an explanation. All-zero observations are valid and produce zero forecasts.

An unresolved calendar gap from a product's first observation through the origin blocks that forecast. Missing records are never silently converted to zero. Explicitly confirmed zero records are usable observations. Known stockout sales are preserved for display but excluded from baseline fitting; this model does not reconstruct lost demand or use the synthetic reference demand. Promotions and annual seasonality are not separately modeled in this baseline. Prediction ranges and inventory recommendations are added by separate modules.

## Rolling time-based backtests

Each product is evaluated independently for horizons **7, 14 and 28**. Use up to **six** of the most recent complete, non-overlapping test windows per horizon. Origins step backward by that horizon from the common evaluation end date; the first forecasted date is always origin + 1. Require at least **56 calendar days** between the product's first observation and each origin, inclusive. A single fold therefore needs at least 56 + horizon calendar days of history. Short histories produce fewer folds or an unavailable summary rather than invented results.

At each origin, rebuild the forecast from sales dated on or before that origin. Later sales and stockout flags cannot affect fitting. Actual sales are joined to predictions by target date only after forecasting. Training gaps and insufficient usable observations can make individual folds unavailable. Missing target sales, known stockout targets and unavailable predictions are excluded from scoring, retained in exports and labeled with reasons. Unknown target availability is scored, so results measure observed sales rather than uncensored demand.

The baseline is fixed in advance; its own metrics do not select or tune its parameters. Regression comparison uses an explicit development/audit split described in [the model selection policy](regression_model.md). Folds do not overlap within a product/horizon; different horizons can evaluate overlapping dates and their metrics should be interpreted separately.

## Metric definitions

For the eligible actual/predicted pairs, let N be the number of scored days, E the sum of absolute errors and A the sum of actual units:

- **MAE (units/day)** = E / N.
- **WAPE (%)** = 100 × E / A.
- **RMSE (units/day)** = square root of the mean squared error; exported as an additional diagnostic.
- **Signed bias (units/day)** = mean(prediction − actual); positive means overforecasting, negative means underforecasting.

The audit scorecard compares the baseline with the development-selected policy on identical eligible dates separately for each horizon. It pools unit errors before calculating WAPE and reports per-product wins, losses and ties. It never selects the better model using audit outcomes. Run `scripts/summarize_evaluation.py` against a saved run, or download `audit_scorecard.csv` inside the results ZIP. No reported improvement is a business-savings estimate.

Product/horizon summaries pool all eligible days across folds. They do not average fold percentages. When A = 0, WAPE is unavailable even if the forecast also equals zero; MAE remains defined when N > 0. When N = 0, both metrics are unavailable. Nonfinite values, mismatched arrays and negative units are rejected by the metric function. Display rounding does not change exported metric precision.

`complete` means six folds with every target scored. `partial` means fewer folds or some excluded targets. `unavailable` means no eligible pairs. Summary and fold tables expose counts of stockout targets, missing actuals, unavailable predictions and fallback predictions; exclusion counts can overlap.

## Verification

Focused tests cover exact target alignment at every horizon, the recent window, fallback thresholds, stockout exclusions, all-zero histories, gaps, capped folds, insufficient history, pooled metrics and dashboard filters. Leakage tests change future sales and flags while holding an origin fixed and require identical predictions. Chart tests compare plotted arrays with the underlying fold data.

Implementation: `demand_planner/forecasting/baseline.py`, `demand_planner/evaluation/backtesting.py`, `demand_planner/evaluation/metrics.py` and `demand_planner/analysis.py`. These modules have no Streamlit dependency; the interface is in `demand_planner/ui/baseline_results.py`.
