# CSV validation and daily preprocessing

Upload products, daily sales and end-of-day inventory. Receipts are optional. Downloads and the upload screen both provide the agreed header-only templates. Files use UTF-8 (a BOM is accepted), comma delimiters and case-sensitive column names. Product IDs are text and retain leading zeros. Row numbers refer to CSV records, with the header as row 1.

## Blocking errors

- Missing required columns or files, empty required tables, duplicate/blank headers, malformed quoting or rows with the wrong number of fields.
- Blank required dates/quantities/names, impossible or incorrectly formatted dates, and sales dated today or later. Sales must represent complete days before the current store date, using Asia/Kolkata.
- IDs that are blank, have surrounding spaces, or are absent from products.csv. IDs are case-sensitive and are not trimmed or remapped.
- Negative, fractional, nonnumeric or missing quantities. Whole-number fields accept digits only and are bounded by signed 64-bit integer storage. Receipt quantities, lead times, review intervals and pack sizes must be positive.
- Duplicate product IDs, daily product/date sales keys, inventory product rows or receipt IDs. No duplicate is automatically dropped or summed.
- Inventory dates that differ from the final complete sales date. All supplied inventory rows must therefore share that date.
- Receipt dates at or before the inventory cutoff. Correct overdue receipts before planning.
- Invalid supplier parameters, service levels outside 0.80–0.99, or stockout flags other than true/false/blank. Boolean flags are case-insensitive.

Invalid uploads show the issues and raw previews but never replace the last accepted dataset. Read/CSV parser errors identify the offending file and keep current data unchanged. Extra columns are reported and ignored in normalized data; original uploaded tables remain available to the validation report.

## Missing dates

For each product, establish the daily grid from its first sales record through the latest sales date across the store. Do not infer sales before its first record: this may be a newly introduced product. Warn when its history begins later than other products.

Any missing date on that grid blocks forecasting for the affected product. The dashboard lists and exports those dates. The user can correct the upload or select products and press **Confirm listed dates as zero sales**. That action confirms every currently listed gap for those selected products. For mixed cases, correct the CSV instead of confirming all gaps.

Only explicitly confirmed gaps get zero units. Each inserted row has `is_zero_filled=true` and unknown stock availability. Existing rows are unchanged. The validation report records the confirmation, the quality summary counts the inserted days, and the prepared dataset fingerprint changes. A fresh upload resets all confirmations. No missing required value is converted to zero by this action.

## Missing values and defaults

Blank required values are errors. Optional product settings absent or blank use the configured review interval (initially seven days), 95% reserved service level, pack size one and minimum order zero. Explicit product review intervals override the global default; changing the default refreshes readiness and warnings. Empty optional category is allowed. Missing or blank stockout flags mean unknown availability, not false. Strings such as `NA` remain text: an ID of `NA` is preserved, while `NA` in a quantity is an error.

Missing inventory rows are warnings and disable planning only for the affected products. Products with no sales remain in the catalogue, have no forecast, and receive a warning. A lead-time-plus-review period over 28 days disables inventory recommendations without disabling a valid forecast.

## Known stockouts and training windows

Observed sales on known stockout days are retained. The separate training helper marks them ineligible as evaluation targets and leaves fitting values missing by default. A model requiring a complete series can explicitly request substitution. It uses the mean of non-stockout sales on the same weekday inside that training window, or the overall non-stockout training mean when no matching weekday exists. If every training day is flagged, substitution fails with a clear error.

Training windows are sliced at the supplied cutoff before computing any means. Future observations and the synthetic sample's latent demand never enter training preprocessing. The helper exposes observed units, fitting units, scoring eligibility and a substitution flag separately. Gaps and missing quantities cause it to fail rather than invent a training series.

Unknown-availability days remain usable observed sales with a warning. Neither imputation nor zero-filling estimates lost demand. Forecasts based on stockout-affected sales must still be qualified in the forecasting phase.

## Quality summary and warnings

The screen and downloadable CSV show recorded/expected days, unresolved gaps, confirmed zero days, known stockouts, unknown-availability days, forecast readiness and inventory readiness per product. Readiness requires at least 14 non-stockout usable days and no unresolved daily gaps. Histories below 56 days are provisional.

Warnings cover old data (more than seven days behind the store date), short/no history, missing inventory, stockouts, unknown availability, long zero runs (at least 14 consecutive recorded days), and unusually high sales. Spikes require at least 28 ordinary observations and exceed the largest of `Q3 + 3×IQR`, three times the median, and five units. Warnings preserve all values and are not automatic outlier treatment.

Normalized tables contain typed dates, nullable integer quantities, nullable boolean stockout flags and explicit zero-fill provenance. The original upload is kept unchanged in session memory. Loading alone does not write uploads to disk; running analysis in the default local profile saves normalized inputs under `outputs/runs/`. Clearing session data does not delete those runs. The public sample profile disables uploads and run persistence. Quality CSV exports escape text that could be interpreted as spreadsheet formulas.
