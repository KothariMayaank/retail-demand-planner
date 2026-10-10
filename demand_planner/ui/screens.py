import json
import pandas as pd
import streamlit as st
from demand_planner.config import load_config, public_demo_mode, save_local_runs
from demand_planner.data.loading import load_csv_bundle
from demand_planner.data.exporting import csv_bytes, results_zip
from demand_planner.data.schemas import SCHEMAS
from demand_planner.data.validation import ValidationReport, validate_dataset
from demand_planner.ui.state import clear_data, current_settings, invalidate_results
from demand_planner.ui.cache import cached_analysis
from demand_planner.ui.presentation import inventory_columns
from demand_planner.artifacts import save_analysis
from demand_planner.ui.baseline_results import active_results, evaluation_screen, product_forecast


def _load(files: dict[str, bytes], source: str) -> None:
    if public_demo_mode() and source != "Synthetic sample":
        st.session_state.upload_error = "Uploads are disabled in the synthetic public demo. Use the local app for your own data."
        return
    try:
        dataset = load_csv_bundle(files, source, load_config().max_upload_mb)
        report = validate_dataset(dataset, default_review_period_days=current_settings().review_period_days)
        st.session_state.upload_error = None
        if report.has_errors:
            st.session_state.upload_attempt = report
            return
        st.session_state.dataset = report.dataset
        st.session_state.validation_report = report
        st.session_state.upload_attempt = None
        invalidate_results()
        st.success("Data loaded and checked. Review warnings and forecasting readiness below.")
    except (ValueError, OSError) as exc:
        st.session_state.upload_error = str(exc)
        st.session_state.upload_attempt = None


def _quality(report: ValidationReport, *, rejected: bool = False) -> None:
    label = "Rejected upload" if rejected else "Data quality summary"
    st.subheader(label)
    errors = sum(issue.severity == "error" for issue in report.issues)
    warnings = sum(issue.severity == "warning" for issue in report.issues)
    columns = st.columns(3)
    columns[0].metric("Errors", errors)
    columns[1].metric("Warnings", warnings)
    columns[2].metric("Sales rows uploaded", len(report.raw.tables.get("sales", [])))
    if rejected:
        st.error("Correct the errors and upload again. This upload has not replaced the current data.")
    else:
        ready = int(report.summary.forecast_ready.sum()) if not report.summary.empty else 0
        st.success(f"File and value checks passed. {ready} of {len(report.summary)} products are ready for future forecasting.")
    issue_frame = report.issue_frame()
    if not issue_frame.empty:
        with st.expander(f"Data quality issues to review ({len(report.issues)})", expanded=rejected):
            for issue in report.issues[:10]:
                location = f"{issue.table}.csv" + (f", row {issue.row}" if issue.row is not None else "")
                if issue.product_id:
                    location += f", product {issue.product_id}"
                (st.error if issue.severity == "error" else st.warning)(f"{location}: {issue.message}")
            if len(report.issues) > 10:
                st.caption("Showing the first 10 messages. The table and report include every issue.")
            st.dataframe(issue_frame, hide_index=True)
    st.download_button("Download validation report", csv_bytes(issue_frame), file_name="validation_report.csv",
                       mime="text/csv", key=f"validation_{'attempt' if rejected else 'current'}")
    if rejected:
        with st.expander("Preview of rejected upload"):
            for name, table in report.raw.tables.items():
                st.caption(f"{name}.csv")
                st.dataframe(table.head(20), hide_index=True)
        return
    st.dataframe(report.summary, hide_index=True)
    st.download_button("Download data quality summary", csv_bytes(report.summary),
                       file_name="data_quality_summary.csv", mime="text/csv")
    unresolved = report.missing_dates.loc[~report.missing_dates.confirmed_zero] if not report.missing_dates.empty else report.missing_dates
    if not unresolved.empty:
        with st.expander("Resolve missing sales dates", expanded=True):
            st.write("These dates have no record. They are not zero sales. Correct and re-upload your CSV, "
                     "or explicitly confirm zero sales for the selected products' listed dates.")
            st.dataframe(unresolved, hide_index=True)
            st.download_button("Download missing dates", csv_bytes(unresolved),
                               file_name="missing_sales_dates.csv", mime="text/csv")
            selected = st.multiselect("Products whose listed missing dates truly had zero sales",
                                      sorted(unresolved.product_id.unique()), key=f"confirm_{report.raw.fingerprint}")
            if st.button("Confirm listed dates as zero sales", disabled=not selected):
                replacement = validate_dataset(report.raw, zero_fill_products=tuple(set(report.zero_fill_products) | set(selected)),
                                               default_review_period_days=current_settings().review_period_days)
                st.session_state.validation_report = replacement
                st.session_state.dataset = replacement.dataset
                invalidate_results()
                st.rerun()
    st.caption("Readiness is a data check. Missing inventory disables that product's "
               "inventory planning. Confirmed zeros are marked is_zero_filled; their stock availability remains unknown.")


def data_setup() -> None:
    st.title("Data & Setup")
    st.write("Start with synthetic sample data or upload your store's daily CSVs.")
    st.caption("1. Load data → 2. Review data quality and resolve gaps → 3. Run analysis → 4. Review Inventory Planning → 5. Export Results.")
    st.info("Baseline and regression forecasts, estimated prediction ranges, model comparison and rolling evaluation are available. "
            "Inventory projections and reorder suggestions are available in Inventory Planning.")
    sample, upload = st.tabs(["Sample data", "Upload CSVs"])
    with sample:
        config = load_config()
        try:
            manifest = json.loads((config.sample_directory / "manifest.json").read_text(encoding="utf-8"))
            st.write(f"{manifest['product_count']} fictional products, two years of daily sales "
                     f"({manifest['sales_rows']:,} rows), inventory and expected receipts.")
            st.caption(f"Synthetic demonstration period: {manifest['start_date']} to {manifest['end_date']}. "
                       "Includes weekday and seasonal patterns, promotions and four intermittent products.")
        except (OSError, ValueError, KeyError):
            manifest = None
            st.warning("Sample metadata is unavailable. Regenerate the sample files using the README instructions.")
        if st.button("Load sample data", type="primary", disabled=manifest is None):
            config = load_config()
            try:
                _load({name: (config.sample_directory / f"{name}.csv").read_bytes()
                       for name in SCHEMAS}, "Synthetic sample")
            except OSError as exc:
                st.error(f"Sample data could not be read: {exc}")
        dataset = st.session_state.dataset
        if dataset is not None and dataset.source == "Synthetic sample":
            with st.expander("Stockout demonstration: observed sales and simulated demand"):
                truth = pd.read_csv(config.sample_directory / "reference/demand_reference.csv",
                                    keep_default_na=False, dtype={"product_id": str})
                examples = truth.loc[truth.stockout_event_id != "", ["date", "product_id",
                                     "latent_demand_units", "observed_sales_units", "lost_sales_units"]]
                names = dataset.tables["products"][["product_id", "product_name"]]
                st.dataframe(examples.merge(names, on="product_id").rename(columns={
                    "date": "Date", "product_id": "Product ID", "product_name": "Product",
                    "latent_demand_units": "Simulated demand", "observed_sales_units": "Observed sales",
                    "lost_sales_units": "Lost units"}), hide_index=True)
                st.caption("Simulated demand is known only for this synthetic sample. Stockouts hide demand "
                           "in real sales records. This reference table is excluded from model inputs.")
    with upload:
        if public_demo_mode():
            st.info("This hosted demo uses synthetic sample data only. Run app.py locally to upload your own CSVs.")
        else:
            _upload_controls()
    _setup_results()


def _upload_controls():
    st.caption(f"UTF-8 CSVs, up to {load_config().max_upload_mb} MB each. "
               "Required: products, sales and inventory. Receipts are optional.")
    files = {}
    for name in SCHEMAS:
        value = st.file_uploader(f"{name}.csv" + (" (optional)" if name == "receipts" else ""),
                                 type=["csv"], key=f"upload_{name}_{st.session_state.upload_revision}")
        if value is not None:
            files[name] = value.getvalue()
    if st.button("Load uploaded data"):
        _load(files, "Uploaded CSVs")
    st.caption("A successful load replaces the whole current dataset. " +
               ("Analysis saves normalized inputs and results locally under outputs/runs." if save_local_runs() else "Analysis does not save files on the server."))
    with st.expander("Download CSV templates"):
        for name in SCHEMAS:
            path = load_config().template_directory / f"{name}.csv"
            st.download_button(f"Download {name} template", path.read_bytes(), file_name=f"{name}.csv",
                               mime="text/csv", key=f"upload_template_{name}")
    with st.expander("How missing data and stockouts are handled"):
        st.write("Blank required quantities and dates are errors. Missing daily records remain gaps until corrected "
                 "or explicitly confirmed as zero sales. Dates before a product's first record are outside its "
                 "established history. Stockout flags may be true, false or blank (unknown). Known stockout sales "
                 "are preserved and excluded from evaluation targets. Optional model fitting substitutions use "
                 "only non-stockout observations within the training window; lost demand is not reconstructed.")

def _setup_results():
    if st.session_state.upload_error:
        st.error(st.session_state.upload_error + " Current data has not been replaced.")
    if st.session_state.upload_attempt is not None:
        _quality(st.session_state.upload_attempt, rejected=True)
    if st.session_state.validation_report is not None:
        _quality(st.session_state.validation_report)
    dataset = st.session_state.dataset
    if dataset is None:
        st.info("No data loaded. Choose the sample dataset or upload the three required CSVs.")
    else:
        st.subheader("Current data")
        st.caption(f"Source: {dataset.source}. Preview of current data, sorted by product and date where applicable.")
        for name, table in dataset.tables.items():
            with st.expander(f"{name}.csv — {len(table):,} rows"):
                st.dataframe(table.head(20), hide_index=True)
        st.button("Clear loaded data", on_click=clear_data)
    settings = current_settings()
    st.caption(f"Planning defaults: {settings.horizon_days}-day forecast, "
               f"{settings.review_period_days}-day review, safety policy: {settings.safety_stock_policy}. "
               "Explicit product review intervals override the default; buffers do not guarantee service levels.")
    can_run = dataset is not None and pd.api.types.is_datetime64_any_dtype(dataset.tables["sales"].date)
    st.caption("Analysis reuses matching computations for up to one hour. Data, planning settings or calculation-code changes require a fresh computation. "
               "Changing settings clears the visible results until you run analysis again.")
    if st.button("Run analysis", disabled=not can_run, help="Generate all forecast horizons, evaluate models and calculate restocking recommendations."):
        with st.status("Generating forecasts, evaluating models and planning stock…", expanded=True) as progress:
            try:
                st.write("Calculating results or retrieving a matching cached analysis. This can take a moment for all products.")
                st.session_state.results = cached_analysis(dataset, current_settings())
                if save_local_runs():
                    st.write("Saving reproducible results locally…")
                    try:
                        save_analysis(dataset, st.session_state.results)
                    except OSError as exc:
                        st.warning(f"Analysis completed, but local artifacts could not be saved: {exc}")
                progress.update(label="Analysis complete", state="complete", expanded=False)
            except ValueError as exc:
                invalidate_results()
                progress.update(label="Analysis needs attention", state="error", expanded=True)
                st.error(str(exc))
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Analysis failed")
                invalidate_results()
                progress.update(label="Analysis could not finish", state="error", expanded=True)
                st.error("Analysis could not finish. Review data quality and try again. Details are recorded in the local application log.")
        if active_results() is not None:
            st.success("Results ready. Open Overview for priorities, Forecasts for demand, Inventory Planning for restocking, and Export Results to download.")
            if save_local_runs() and not st.session_state.results.artifact_directory:
                st.warning("Results are available in this session, but the reproducible local files were not saved. You can still export the results below.")
    result = active_results()
    if result is not None:
        ready_products = result.daily_forecasts.loc[result.daily_forecasts.predicted_units.notna(), "product_id"].nunique()
        st.caption(f"Current results: {ready_products} products forecast for {result.settings.horizon_days} days; "
                   "historical evaluation includes 7-, 14- and 28-day horizons.")
        if result.artifact_directory:
            st.caption(f"Models, inputs and evaluation saved to: {result.artifact_directory}")


def _empty(message: str) -> None:
    if st.session_state.dataset is None:
        st.info("No data loaded. Open Data & Setup to load sample data or upload your CSVs.")
    else:
        st.info(message)


def overview() -> None:
    st.title("Overview")
    st.write("Review expected sales, products at risk and suggested replenishment quantities.")
    st.caption("Load data in Data & Setup, inspect Sales History, then run analysis. Review Forecasts and Inventory Planning before exporting results. "
               "Model Performance explains how well forecasts worked on past sales.")
    result = active_results()
    if result is None:
        _empty("Open Data & Setup, review data quality and run analysis. Changed data or settings require another analysis before results appear.")
    else:
        available = result.daily_forecasts.loc[result.daily_forecasts.predicted_units.notna()]
        st.metric("Forecast units — available products", f"{available.predicted_units.sum():,.2f}" if len(available) else "Unavailable")
        total_products = st.session_state.dataset.tables["products"].product_id.nunique()
        st.caption(f"{available.product_id.nunique()} of {total_products} products have forecasts for {result.settings.horizon_days} days. "
                   "Totals sum unrounded daily predictions for available products only; open Forecasts to inspect unavailable products.")
        if available.product_id.nunique() < total_products:
            st.warning("The forecast total is incomplete because some products have unavailable predictions.")
        st.caption(f"Data source: {st.session_state.dataset.source}. Last observed day: {st.session_state.dataset.tables['sales'].date.max().date()}.")
    if result is not None and not result.reorder_suggestions.empty:
        st.subheader("Inventory attention priorities")
        ready = result.reorder_suggestions.loc[result.reorder_suggestions.status == "ready"]
        metrics = st.columns(3)
        metrics[0].metric("Products with projected shortages", int(ready.estimated_stockout_date.notna().sum()))
        metrics[1].metric("Products to restock", int(ready.suggested_order_units.gt(0).sum()))
        metrics[2].metric("Planning unavailable", len(result.reorder_suggestions) - len(ready))
        st.dataframe(result.reorder_suggestions[["product_id", "product_name", "attention", "estimated_stockout_date", "suggested_order_units"]], hide_index=True, column_config=inventory_columns())
        st.caption("Stock planning always uses 28 days. Priorities include future shortages even beyond the next review. "
                   "Suggested orders are not included in the projection; stockouts cannot be guaranteed against. Open Inventory Planning for explanations.")


def product_detail() -> None:
    st.title("Product Detail")
    st.write("Inspect one product's history, forecast range and projected stock.")
    dataset = st.session_state.dataset
    if dataset is not None:
        products = dataset.tables["products"]
        ids = products["product_id"].tolist()
        selected = st.selectbox("Product", ids)
        row = products.loc[products.product_id == selected].iloc[0]
        st.caption(f"{row['product_name']} · {selected}")
        history = dataset.tables["sales"]
        st.subheader("Uploaded history preview")
        st.dataframe(history.loc[history.product_id == selected].tail(20), hide_index=True)
        if product_forecast(selected):
            st.caption("Open Forecasts for estimated ranges and Inventory Planning for this product's stock projection and order explanation.")
            return
    _empty("Run analysis in Data & Setup to see forecasts and inventory recommendations.")


def historical_evaluation() -> None:
    evaluation_screen()


def downloads() -> None:
    st.title("Export Results")
    st.write("Download CSV templates to prepare your data.")
    config = load_config()
    for name in SCHEMAS:
        path = config.template_directory / f"{name}.csv"
        st.download_button(f"Download {name} template", path.read_bytes(),
                           file_name=f"{name}.csv", mime="text/csv", key=f"template_{name}")
    st.subheader("Analysis results")
    result = active_results()
    if result is not None:
        st.download_button("Download all results ZIP", results_zip(result), file_name="retail_planning_results.zip", mime="application/zip")
        st.caption("Includes forecasts, stock projections, order suggestions, model evaluations and settings. CSVs preserve calculation precision; displayed orders are whole units.")
        for label, frame, filename in (
            ("Download daily forecasts", result.daily_forecasts, "daily_forecasts.csv"),
            ("Download baseline evaluation", result.evaluation, "baseline_evaluation.csv"),
            ("Download all backtest predictions", result.backtest_predictions, "baseline_backtest_predictions.csv")):
            st.download_button(label, csv_bytes(frame), file_name=filename, mime="text/csv")
        if not result.model_comparison.empty:
            st.download_button("Download model comparison", csv_bytes(result.model_comparison), file_name="model_comparison.csv", mime="text/csv")
            st.download_button("Download both models' predictions", csv_bytes(result.candidate_predictions), file_name="candidate_predictions.csv", mime="text/csv")
            st.caption(f"Reproducible trained artifacts and normalized inputs: {result.artifact_directory or 'Not saved'}")
        if not result.future_forecasts.empty:
            st.download_button("Download forecasts for all horizons", csv_bytes(result.future_forecasts), file_name="future_forecasts.csv", mime="text/csv")
            st.download_button("Download prediction range evaluation", csv_bytes(result.interval_evaluation), file_name="interval_evaluation.csv", mime="text/csv")
        if not result.reorder_suggestions.empty:
            st.download_button("Download reorder suggestions", csv_bytes(result.reorder_suggestions), file_name="reorder_suggestions.csv", mime="text/csv")
        if not result.inventory_projection.empty:
            st.download_button("Download stock projections", csv_bytes(result.inventory_projection), file_name="inventory_projection.csv", mime="text/csv")
    else:
        _empty("Run analysis in Data & Setup to download baseline forecasts and evaluation results.")
