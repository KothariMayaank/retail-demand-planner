# Historical sales exploration

Open **Sales History** after loading data in Data & Setup. Select a product and an inclusive date range. The initial range is the latest 90 days, or all available dates for a shorter history. Change the range to explore the complete two-year sample. Choose a seven-, fourteen- or twenty-eight-day rolling average. Product names and IDs appear together to distinguish similar names.

## Metric definitions

All quantities are observed selling units, not estimated unconstrained demand or revenue. A product pack is one selling unit. Metrics are scoped to the selected product and date range.

- **Total units sold:** sum of recorded daily units, including known stockout days and explicitly confirmed zero rows. If every selected day is unrecorded, the total is unavailable rather than zero.
- **Average daily sales:** recorded units divided by the number of recorded or explicitly confirmed days. Missing days are excluded; no value is substituted.
- **Days with zero sales:** recorded days with exactly zero units divided by recorded/confirmed days, multiplied by 100. Stockout zeros and confirmed zeros are included. Missing records do not enter the numerator or denominator.

The screen shows the recorded-day denominator and established-day count beside the metrics. Average sales are displayed to two decimals and percentages to one decimal. Tables and CSV downloads retain the calculation values. A warning labels totals as incomplete whenever a missing record occurs in the established history.

## Daily chart and rolling average

The daily chart uses the selected calendar dates, sorted chronologically. Missing values are blank and break the sales line. Red diamonds and pale red shading identify known stockouts. Gray shading identifies missing records. Purple squares identify explicitly confirmed zero-sales records. Pale blue shading identifies dates before the selected product's first observed record; these dates do not become gaps or zeros.

The rolling average is a trailing full-calendar-window mean computed only within the selected range. It requires all seven, fourteen or twenty-eight daily values. The first `window − 1` days have no rolling estimate. A gap interrupts the rolling line until a complete window becomes available again. The average uses recorded stockout sales and confirmed zeros, so it describes observed sales rather than reconstructed demand.

An expandable table lists contiguous inclusive periods for stockouts, gaps, confirmed zeros and dates outside established history. Daily values expose flags, statuses and zero-fill provenance for checking the charts.

## Weekday patterns and product comparisons

Weekdays always appear Monday through Sunday. Each average uses the number of available recorded days for that weekday. The accompanying table shows totals, counts, gaps, zero-sales rates and stockout counts. A weekday with no recorded observations has no estimate. Promotions and stockouts can influence these observed averages.

Product comparisons use the same selected date range. Choose any subset of products. Bars are sorted by recorded totals, largest first; amber identifies incomplete coverage, teal highlights the selected product when coverage is complete. Product IDs are included in chart labels.

The comparison table shows totals, average sales, zero-sales percentages, recorded/established days, missing days, coverage, stockouts and confirmed zeros. A product's established history starts at its first sales record and extends to the store's latest sales date. Coverage is recorded days divided by established days within the selected range. A newer product can have 100% coverage but fewer established days, so compare its duration as well as its total. Products without established history retain unavailable totals and coverage.

The filtered daily table and comparison table are downloadable as CSVs. Source observations are not modified by exploration. Synthetic latent demand and promotion reference files never enter these calculations.

## Verification

Focused tests independently check inclusive filters, sums, denominator choices, weekday arithmetic, zero confirmation, missing values, stockout markers, period grouping and rolling-window behavior. Chart traces are compared with the calculation tables. Streamlit tests change product/date filters and compare rendered metrics against manually computed fixture results.
