# Retail Demand Planner

A Python and Streamlit dashboard for one retail store with approximately 10–30 products. It forecasts daily sales for **7, 14 or 28 days** and explains stock risks and replenishment suggestions. No paid APIs or external integrations are required.

**Status:** deployment preparation completed; no public app has been published. The recommended hosting entry point is `cloud_app.py`. [Deployment guide](docs/deployment.md) · [Project presentation and demo script](docs/project_presentation.md) · [Acceptance report](docs/acceptance_report.md).

Source: [KothariMayaank/retail-demand-planner](https://github.com/KothariMayaank/retail-demand-planner). [GitHub verification](https://github.com/KothariMayaank/retail-demand-planner/actions/workflows/verify.yml) checks fresh installation, tests, startup and acceptance on Ubuntu/Python 3.12.

**Project review, 10 October 2026:** corrected delivery-aware lost-sales replenishment, saved-run ID handling, cache provenance and audit reporting. **120 tests pass**, including independent stock-ledger checks. Read the [technical review and ML internship roadmap](docs/project_review.md) for the findings, evidence and next experiments.

All included data and reported scores are **synthetic**. They do not establish real-store accuracy, business savings or guaranteed stockout prevention.

## Setup and run

Use **Python 3.12** and run from the project root. The tested fresh installation used Windows/Python 3.12.14. Direct runtime dependencies and transitive versions are pinned in `requirements.txt` and `requirements-lock.txt`; no virtual environment is shipped.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

macOS/Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

Open http://localhost:8501; stop with Ctrl+C. If the port is occupied, add `--server.port 8502`. Installation needs network access to the Python package registry; subsequent local use needs no API keys. Recreate environments on each machine instead of copying `.venv`.

To preview the hosting profile locally:

```powershell
.\.venv\Scripts\python.exe -m streamlit run cloud_app.py --server.address 127.0.0.1
```

This uses synthetic data only, disables uploads and saves no analysis files. The full `app.py` local profile accepts uploads and saves reproducible runs under `outputs/runs/`. The hosted profile still supports downloadable synthetic CSVs and ZIP results. Hosting settings control the server bind; `.streamlit/config.toml` does not force localhost.

## Workflow and concise demo

1. **Data & Setup:** Load sample data, or upload the required CSVs locally. Review quality warnings and correct gaps; confirm zero sales only when known to be true.
2. **Sales History:** Choose a product/date range; inspect daily sales, rolling averages, weekday patterns and product totals. Gaps and known stockouts are identified.
3. Click **Run analysis** in Data & Setup. The dashboard compares models at all horizons and calculates inventory. Progress/error messages explain the state.
4. **Overview / Forecasts:** Review priorities, choose a product and horizon, inspect totals, selected model, daily ranges and audit coverage.
5. **Inventory Planning:** Check receipts, effective lead/review periods and the explanation before acting on suggested orders. A positive future stockout estimate is not a guarantee.
6. **Model Performance / Export Results:** Inspect development and audit comparisons. Download individual reports or the complete results ZIP.

For a three-minute demonstration, use P006, Bottled water 1 L, at 28 days. Its first baseline forecast is **49.5** units. **78.25** expected sales are lost before the listed delivery, and the existing **300** incoming units cover subsequent protection-period demand plus the buffer, so the standard order is **zero**. Explain why the early shortage still needs attention. P003 provides a positive-order example: **336 units**. [Walkthrough and six-slide outline](docs/project_presentation.md).

## Input schemas

UTF-8 CSV; dates are `YYYY-MM-DD`, IDs are case-sensitive text (leading zeros preserved), and quantities must be nonnegative integers. Maximum upload size: 10 MB per file.

| File | Required columns | Optional columns / rules |
|---|---|---|
| `products.csv` | `product_id`, `product_name`, `lead_time_days` | `category`, `review_period_days`, `service_level`, `pack_size`, `minimum_order_qty`. Lead 1–28 days; review 1–27; pack >=1; minimum >=0. |
| `sales.csv` | `date`, `product_id`, `units_sold` | `stockout_flag`: true, false or blank (unknown). One product/date record; complete days before today. |
| `inventory.csv` | `snapshot_date`, `product_id`, `on_hand_units` | One row per product; end-of-day snapshot matching final store sales date. Missing product stock disables that product's planning. |
| `receipts.csv` (optional) | `receipt_id`, `product_id`, `expected_date`, `quantity_units` | Unique receipt IDs; positive quantities; dates after the snapshot. No file means no incoming deliveries assumed. |

All IDs must match the product catalogue. Duplicate records, invalid dates and blank required values are errors. Unknown columns are reported and ignored. Failed uploads preserve accepted data. Missing dates remain gaps and block affected forecasts; only explicit confirmation inserts marked zeros. Known stockout sales remain visible but are excluded from ordinary fitting/evaluation targets. [Detailed validation policy](docs/data_validation.md).

Optional product review intervals override the configurable global default (initially seven days). Blank review values use that default. Defaults for pack/minimum are one/zero. Legacy service level (default 0.95) is reserved and does not determine safety stock. Templates are under `data/templates/` and downloadable in the app.

Sample files cover 2024-10-10 through 2026-10-09: 20 fictional products and 14,600 daily rows, with weekday/seasonal/promotion effects, four intermittent products and nine known stockout days. Reference latent demand and promotion schedules are separate and excluded from forecasting. [Sample generation guide](data/sample/README.md).

## Architecture

```text
app.py / cloud_app.py       Full local app / sample-only hosting entry
requirements*.txt           Pinned runtime and transitive constraints
.streamlit/config.toml      Theme, upload limit and server configuration
config/settings.toml        Planning defaults and relative data locations
demand_planner/
  ui/                       Screens, state, formatting and computation cache
  data/                     Schemas, strict CSV validation and exports
  analytics/                Historical metrics and comparisons
  forecasting/              Weekday baseline, causal ridge features, ranges
  evaluation/               Rolling backtests, metrics and model selection
  inventory/                Daily stock and periodic-review order calculations
  analysis.py               Orchestration across products and horizons
  artifacts.py              Local JSON models, input/code snapshots and hashes
data/sample, data/templates Synthetic data and upload templates
scripts/                    Generation, acceptance, startup, replay, packaging
tests/                      Calculation, leakage, interface and deployment checks
docs/                       Policies, acceptance, deployment and presentation
.github/workflows/verify.yml Ubuntu/Python 3.12 verification after an approved push
```

Calculation modules are independent of Streamlit. Resource paths resolve from the project root. Analysis caching is memory-only, bounded to eight entries with one-hour expiry. Keys include every normalized input row, confirmation provenance, settings and source code; results are copied on retrieval. Changed data/settings clear visible results until analysis runs again.

## Forecasting, evaluation and uncertainty

The baseline averages recent matching weekdays in a 28-calendar-day window, excluding known stockouts. With insufficient weekday matches it uses the recent usable mean; fewer than 14 usable observations or unresolved gaps yield unavailable forecasts.

Per-product ridge regression uses lags 1/7/14/28, prior rolling statistics, weekday and calendar features. Scaling/fitting use only information through each forecast origin. Multi-day forecasts recursively feed back predictions, not future actuals. Ridge uses NumPy with regularization alpha 10; historical prices/promotions are excluded without reliable future schedules. [Baseline policy](docs/baseline_forecasts.md) · [ML policy](docs/regression_model.md).

Rolling backtesting uses up to six non-overlapping windows per product/horizon, with at least 56 initial calendar training days. ML requires at least 5% lower MAE on three older development folds with sufficient paired coverage; otherwise baseline remains. Three newer folds form a reserved audit and cannot change selection.

- **MAE:** mean absolute daily prediction error in units; lower is better.
- **WAPE:** total absolute error divided by total actual sales, percent; unavailable for zero actual totals.
- **RMSE and signed bias:** exported diagnostics for large errors and systematic over/underforecasting; positive bias means overforecasting. MAE still determines the frozen model choice.
- **Observed range coverage:** proportion of eligible audit days inside the estimated daily range.

Ranges use the selected model's earlier out-of-sample absolute errors: rank `ceil((N+1) × 0.8)`, capped at N, with three development folds and at least 20 errors. Bounds are nonnegative. These target 80% daily coverage without claiming statistical confidence or a guarantee; daily ranges cannot be summed into a total-demand range. [Range policy](docs/prediction_ranges.md).

**Synthetic evaluation:** 39 of 60 product/horizon choices select ML, 21 retain baseline. Five ML selections perform worse than baseline on the reserved audit. Twenty-nine of 60 sample ranges have coverage below the 80% target and are flagged. These results do not justify a universal claim of ML superiority.

The selected policy (ML where development qualified it, baseline elsewhere) has pooled audit MAE of **3.981 / 4.116 / 4.157 units** at 7 / 14 / 28 days, versus **4.389 / 4.484 / 4.410** for baseline. Relative reductions are **9.30% / 8.19% / 5.73%** on identical eligible dates within each horizon. Horizons overlap and must not be pooled into one independent sample. The results ZIP contains `audit_scorecard.csv`; regenerate it from a saved run with `scripts/summarize_evaluation.py "outputs/runs/<run-directory>"`.

## Inventory formulas

Let `L` be lead time, `R` review days, `P=L+R`, and `f[t]` unrounded daily demand. Planning always uses the selected **28-day** forecast, regardless of the display horizon.

| Quantity | Formula |
|---|---|
| Lead-time demand | `D_L = sum(f[1] ... f[L])` |
| Protection demand | `D_P = sum(f[1] ... f[P])` |
| Safety buffer B | Default `(D_P/P) × 2 days`; configurable demand days, fixed units, or zero |
| Reorder point | `D_L + B` |
| Target stock | `D_P + B` |
| Inventory position | Current stock + listed receipts arriving within P days |
| Raw order gap G | Minimum added stock arriving on day `L+1` that serves demand through `P` and leaves buffer `B`, accounting for each receipt date |
| Suggested order | Zero if G=0; else `ceil(max(G, minimum_order)/pack_size) × pack_size` |
| Estimated stockout | First future day where forecast demand exceeds opening stock plus that day's listed receipts |

This is a deterministic periodic-review policy with delivery-aware lost-sales sizing. The reorder-point alert compares stock plus receipts within L days with the reorder point. Receipts arrive in full at the start of the expected day. Sales lost before day L+1 are not added to the order; later receipts cannot cover earlier shortages. Nominal target and inventory position are context, not sufficient statistics for the order. Suggested orders are excluded from the displayed projection until recorded as receipts. Lead plus review above 28 days yields unavailable planning. Daily forecasts retain fractional units; only orders round upward to whole packs. [Full formulas and assumptions](docs/inventory_planning.md).

## Verification and exports

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe scripts/verify_startup.py
.\.venv\Scripts\python.exe scripts/verify_startup.py --entrypoint cloud_app.py --port 8766
.\.venv\Scripts\python.exe scripts/verify_end_to_end.py
.\.venv\Scripts\python.exe scripts/prepare_deployment.py
```

The current Windows environment passes **120 tests**, with pandas future warnings treated as errors. The earlier fresh-environment deployment check passed 110 tests; this review reused the installed environment. Acceptance covers sample and uploaded fixtures, malformed files, short/zero/gapped histories, time alignment, leakage, metrics, range ranks, inventory arithmetic, exports and retraining. [Acceptance report](docs/acceptance_report.md). On 10 October 2026, [GitHub's Ubuntu/Python 3.12 verification passed](https://github.com/KothariMayaank/retail-demand-planner/actions/runs/38057606699) for code commit `54f2e3c`, including a fresh dependency installation, all 120 tests, startup, end-to-end acceptance and release packaging. No actual Streamlit hosting build has run.

CSV and ZIP exports preserve calculation precision and label known synthetic sample results. Local runs save normalized inputs, trained JSON artifacts, evaluation and inventory tables, settings, dependency/source snapshots and hashes. Replay with `scripts/reproduce_run.py "outputs/runs/<run-directory>"`; add `--retrain` to verify the complete analysis with matching source code. Uploaded inputs and runs are excluded from the source release.

## Deployment and presentation

The [deployment guide](docs/deployment.md) provides current official-documentation links, Python selection, entry point, repository contents, privacy behavior and post-deployment checks. Build the allowlisted source ZIP under `outputs/deployment/`; review its manifest before putting it in an approved GitHub repository. `.gitignore` excludes uploads, generated outputs, virtual environments and credential files; it cannot remove secrets already committed to another repository.

**Obtain approval before publishing either the source or app publicly.** No repository, commit, push or hosted app was created during preparation. The public entry is `cloud_app.py`, Python 3.12, with no secrets required.

Portfolio summary: Built a modular retail planning dashboard that validates daily CSVs, compares forecasts using prior information through rolling evaluation, reports empirical uncertainty and produces explainable inventory recommendations. Reproducible synthetic data, 120 automated checks and a sample-only hosting profile support demonstration without claiming unverified business outcomes. [Presentation outline and speaker walkthrough](docs/project_presentation.md).

## Limitations

One store and 28 days maximum; fixed calendar-day lead times and daily operation; deterministic buffers; censored demand during stockouts; no promised future promotion/price schedule; small audits and sometimes poor range coverage. MAE alone does not establish inventory utility, especially for intermittent products. Confirm operating calendar, delivery timing and buffer policy before real use. Authentication, production data retention, actual-store accuracy, multi-user operation and hosted resource performance remain unverified. Re-run checks before dependency upgrades.

Billing, multiple stores, automatic ordering, price optimization and chatbots remain outside this version. The public sample profile does not accept business uploads; use the full local app for your own data.
