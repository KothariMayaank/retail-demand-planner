# Retail Demand Planner — project presentation

## Portfolio summary

Built a local Python and Streamlit dashboard that turns daily retail sales, stock snapshots and expected deliveries into 7-, 14- and 28-day sales forecasts and explainable replenishment suggestions. The application validates CSVs, preserves data gaps, flags stockouts, compares a matching-weekday baseline with causal ridge regression, and evaluates both using rolling time-based tests. It reports empirical prediction ranges and observed coverage, then calculates stock projections and orders using configurable safety buffers, supplier lead times, pack sizes and incoming stock. A synthetic-only hosting profile supports safe portfolio demonstrations. Automated checks cover leakage, metrics, uncertainty, inventory arithmetic, uploads, caching, exports and deployment behavior.

All reported performance uses reproducible synthetic data. ML is selected in 39 of 60 product/horizon comparisons, but underperforms baseline in five selected audits. At 28 days, the selected policy reduces pooled audit MAE from 4.410 to 4.157 units, a 5.73% reduction on 1,677 eligible product-days. No business savings, real-store accuracy or stockout-prevention guarantee is claimed. The [project review](project_review.md) provides resume bullets and a prioritized real-data research plan.

## Six-slide college presentation outline

| Slide | Main point | Demonstration or evidence |
|---|---|---|
| 1. Problem and scope | Small retailers need understandable demand and restocking estimates. One store, approximately 10–30 products. | Show Overview; state excluded integrations and automatic ordering. |
| 2. Data and validation | Reliable inputs precede reliable forecasts. Missing records are not zeros. | Show four schemas, stockout flags and a rejected negative quantity; identify every dataset as synthetic. |
| 3. Forecasting design | Compare a simple weekday baseline with per-product ridge regression. | Explain lag/calendar features, cutoff-only training, recursive multi-day predictions and baseline fallback. |
| 4. Evaluation and uncertainty | Test forecasts in the order data becomes available. | Older folds select models; newer folds audit them. Define MAE/WAPE. Show 39 ML selections, five audit failures and 29 ranges below their coverage target. |
| 5. Inventory decisions | Convert fractional demand into traceable stock projections and whole-pack orders. | P006: 49.5 next-day units, 78.25 pre-arrival lost units, zero normal order because listed supply covers subsequent demand and buffer. P003: 336-unit order. |
| 6. Engineering and limitations | A modular, reproducible demonstration with cautious interpretation. | 120 automated tests, input/source/code/settings cache keys, CSV/ZIP exports and sample-only hosting. Prior fresh installation passed 110 tests; real-store validation and hosted Linux build remain future checks. |

## Three-minute demo walkthrough

1. **0:00–0:25 — Scope and data.** Explain that this is a one-store planning demo using 20 fictional products and two years of synthetic records. Open Data & Setup and load sample data.
2. **0:25–0:50 — Data quality and history.** Show warnings and known stockout examples. In Sales History, inspect a daily pattern and seven-day rolling average. Explain that observed stockout sales can hide demand.
3. **0:50–1:20 — Forecasts.** Run analysis, then choose P006 and 28 days. Its selected model is baseline. The first forecast is 49.5 units, the mean of four recent Saturdays. Explain estimated daily ranges and observed coverage.
4. **1:20–1:45 — Model Performance.** Show per-product/horizon choices and a reserved-audit warning. Explain that ML must improve development MAE by at least 5%; it is not automatically better.
5. **1:45–2:30 — Inventory Planning.** Choose P006. The 300 incoming units cover demand after the early shortage and leave 75 units against a 60.65-unit buffer. A normal order is zero because the 78.25 pre-arrival lost units cannot be recovered by later stock. Explain that the estimated 10 October shortage needs expedited attention. Switch to P003 for a positive supplier-rounded order of 336 units.
6. **2:30–3:00 — Export and limits.** Download the combined ZIP. Show the synthetic label. State that daily forecasts are fractional estimates, orders are rounded, and neither intervals nor buffers guarantee outcomes. Conclude with real-store testing as the next step.

First analysis can take longer on a hosted machine. For a live presentation, load and analyze the sample before the session; rerun only if demonstrating loading states. Keep the locally prepared demo available as a fallback until the cloud build is verified.

## Questions to be ready for

- **Why ridge regression?** It is practical for small per-product datasets, regularizes correlated lag features and needs no paid service. The baseline remains when development improvement is insufficient.
- **How is leakage avoided?** Features only use prior sales; fitting/scaling stop at the origin; multi-step forecasts feed back predictions; audit actuals cannot influence selection or calibration.
- **Why can a recommendation still show a shortage?** The displayed projection excludes unplaced orders. Replenishment covers only demand from its assumed arrival onward; a normal order cannot serve earlier lost sales. Later receipts cannot cover an earlier sale, so the order calculation checks cumulative deficits by date.
- **What would improve this project?** Actual store validation, a confirmed operating calendar, reliable future promotion/price schedules, better interval coverage and a separately designed authenticated production deployment.
