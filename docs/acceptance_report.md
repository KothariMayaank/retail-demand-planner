# End-to-end verification — 10 October 2026

Updated after the full project review: **120 automated tests passed**, with future warnings treated as errors. Dependency consistency and both entry-point startup checks passed. The separate acceptance script completed sample and upload analyses, ZIP verification, independent arithmetic and saved-run retraining reproduction. All verification data was synthetic; actual store performance remains unverified. The earlier phase-11/12 runs passed 105/110 tests respectively; this review reused the installed Windows environment. See the [project review](project_review.md) for detailed findings and the ML internship roadmap.

## Issues found and fixed

1. Data quality used seven review days even when the sidebar default differed. Validation now uses the configured default; changing it refreshes readiness and warnings while preserving explicit product overrides and confirmed-zero provenance.
2. A mixed upload with products lacking backtest windows could stop model comparison because empty date columns had object types while other products had datetime types. Backtest outputs now retain datetime types even when empty. New mixed-history tests prevent recurrence.
3. The full-project review found inconsistent lost-sales replenishment. Orders now exclude pre-arrival lost sales and account for the timing of later receipts. An independent exhaustive stock-ledger test verifies minimum feasible supplier orders.
4. Saved-run CSV replay now preserves literal IDs such as `NA`; cache keys include source provenance; release packaging requires an explicit true synthetic declaration.
5. Selected-model audit metrics remain available when the other candidate is unavailable. Numeric result types are explicit; an audit scorecard adds RMSE, bias and horizon-specific policy comparisons.

## Acceptance coverage

| Requirement | Evidence |
|---|---|
| Local Python/Streamlit, one store, 7/14/28 days | Sample: 20 products, 980 all-horizon forecast rows, 560 daily stock rows; startup and screen checks. |
| Reproducible sample | Two years, 14,600 nonnegative integer sales rows; weekday, seasonal and promotion patterns, intermittent products and nine identifiable stockout days. Generator/schema tests verify files and exclusion of synthetic truth from model inputs. |
| CSV validation | Required files/columns, encoding, malformed rows, duplicate headers/keys, dates, quantities, leading-zero IDs, matching products, inventory snapshots and overdue receipts. Rejected replacements preserve accepted data. |
| Missing data and stockouts | Gaps remain gaps and block affected forecasts. Explicit confirmations insert marked zeros. Known stockout targets are excluded; substitutions required by ML use prior information. |
| Historical dashboard | Totals, daily averages, zero percentages, weekday/rolling/product charts checked against source data. Uploaded product 001 showed 450 units over 90 days, 5 units/day, 0% zero days. |
| Baseline and time evaluation | Weekday/fallback arithmetic, rolling origins, date alignment, MAE, pooled WAPE and zero-actual handling. Mutating later actuals leaves earlier forecasts unchanged. |
| ML leakage and selection | Prior-only lag/rolling features, cutoff-isolated scaling/fitting, causal stockout substitution and recursive use of predictions; identical baseline/ML dates. Older development folds select models; later audit outcomes cannot change selection. |
| Uncertainty | Independent empirical rank calculation; development-only calibration and separate observed audit coverage; selected-model errors, stockout exclusions, clipping, unavailable calibration and zero-width cases. |
| Inventory | Demand/buffer/reorder/target/order/shortage arithmetic; zero demand, sufficient stock, exact exhaustion, pack/minimum orders, long lead times, unsupported windows, timely/late/multiple receipts and receipt boundaries. |
| Exports and reproduction | CSV precision and IDs, formula-safe text, ZIP contents/settings, saved hashes, JSON replay, complete retraining, prediction bounds/coverage and recommendation/projection reproduction. |
| Workflow and cache | Empty/completed/error states, data/settings invalidation, full-row hashing, code changes and independent cached copies. |
| Excluded scope | No billing integrations, multiple stores, automatic ordering, price optimization or chatbot; no paid services/API keys. |

## Uploaded scenario and visual review

The ten-product fixture has 2,479 sales rows: 001 has a stable weekday pattern and receipt; 002 has 350 zero-sales days; 003 has ten days; 004 has twenty days; 005 has one unresolved gap; 006–009 have intermittent sales; 010 has no history. The earlier browser acceptance used the actual file choosers for all four CSVs. This review reran the fixture through the engine and automated screen checks. Data quality reports seven forecast-ready products. Corrected inventory shows two products to order, **72 suggested units** (42 and 30) and three unavailable products.

Zero-sales forecasts/orders remain zero, with WAPE undefined when actual totals are zero. Twenty-day history yields a provisional 3-unit/day recent-mean forecast without full selection/range history. Ten-day, gapped and absent histories show unavailable values, rather than fabricated zeros. A separate explicit-zero confirmation resolves the gap while preserving provenance. The script rejects a negative-quantity upload; validation and UI tests cover additional malformed files and preservation of accepted data.

Desktop browser review covered upload controls, Forecasts, Inventory Planning, Sales History and Model Performance. Limited-history warnings, units, charts and priorities were readable. Wide tables require horizontal scrolling. Screenshots are in `outputs/verification`; automated screen tests also cover Overview and Export Results. Mobile layouts and other browsers were not separately certified.

## Independent representative calculation

P006 (Bottled water 1 L), sample cutoff 9 October 2026, uses the weekday baseline at 28 days.

- Recent Saturday observations: **57, 60, 40, 41**. Next-day forecast on 10 October: `198 / 4 = 49.5` units.
- Lead time **3 days**, review **7 days**, protection **10 days**. Unrounded demand is **100.00** units over lead time and **303.25** over protection.
- Two-day buffer: `(303.25 / 10) × 2 = 60.65` units.
- Reorder point: `100 + 60.65 = 160.65`; target: `303.25 + 60.65 = 363.90` units.
- Stock is **0**. A listed **300-unit** delivery arrives on **12 October**, inside protection.
- Expected lost sales before a new order can arrive: **78.25** units. These are lost, not backordered. Remaining protection-period demand is `303.25 − 78.25 = 225` units. The listed 300-unit receipt leaves **75** units, above the **60.65**-unit buffer. Raw gap and suggested order are therefore **zero**. Pack/minimum constraints do not create an order when no gap exists. This supersedes the earlier incorrect 63.90-unit gap and 72-unit order.
- First estimated shortage: **10 October**, before that receipt. A hypothetical new order would arrive **13 October**. The dashboard flags expedited-supply attention; adding a normal order cannot prevent those earlier lost sales. P003 illustrates a positive order: **336 units**.
- Range calibration has **81** eligible errors; rank `ceil((81 + 1) × 0.8) = 66`. The 66th sorted absolute error is **19.75** units, matching the generated range radius.

All 28 daily predictions and inventory fields were independently recomputed directly from normalized rows, without calling production forecast/inventory helpers.

## Performance evidence and remaining limitations

Of 60 synthetic sample product/horizon comparisons, development selects **39 ML** and **21 baseline**. In **five of the 39 ML selections**, ML has worse MAE than baseline in the reserved audit. Selection remains frozen and audit failures are flagged. These results do not establish universal ML superiority or real-store performance.

All 60 sample ranges have sufficient calibration, but **29 have audit coverage below the 80% target**. These are empirical estimated daily prediction ranges, with undercoverage warnings, not confidence guarantees. Small audits, correlated errors, shared selection/calibration windows and synthetic patterns limit generalization.

- Observed sales proxy demand; stockouts censor demand. Unknown lost demand is not recovered. Historical price/promotions are excluded because future schedules are not supplied.
- Buffers are deterministic choices. Legacy service-level/simulation settings are reserved, not used to promise service probabilities.
- Lead time plus review must fit 28 days. No extrapolation. All calendar days are selling days; lead times are fixed, listed receipts arrive in full at day start, unmet demand is lost sales without backorders.
- Delays, forecast errors and unrecorded receipts can cause stockouts. Recommendations are advisory, with no automatic ordering.
- Short/intermittent histories can yield weak forecasts, unavailable ranges or zero-width empirical ranges. Real operating calendar, receipt conventions and safety-buffer choices still need store-owner confirmation before operational use.
- Desktop local use was verified. Production authentication, multi-user isolation, deployments, mobile browsers, backups and operational monitoring were not tested.
- Explicit numeric types resolve the previously observed pandas concatenation future warnings. All 120 tests pass with these warnings treated as errors. Streamlit's bare-mode test harness still emits expected context warnings.

## Reproduce

From the project folder in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/verify_startup.py
.\.venv\Scripts\python.exe scripts/verify_end_to_end.py
```

The last command regenerates upload fixtures, saves both analyses, retrains the sample run and writes `outputs/verification/acceptance_results.json`. Corrected sample run: `outputs/runs/20261010T080011Z-187c0036`; uploaded script run: `outputs/runs/20261010T075952Z-eb791d7e`. The latest paths are always recorded in the generated JSON. Future code/dependency changes require rerunning verification; past code snapshots remain saved with each run.
