# Inventory planning

Planning runs at the end of the final complete sales date, using the selected **28-day** model for each product. Changing the sales display horizon does not change the planning horizon. Inventory must be an end-of-day snapshot on that same date. Every calendar day is a selling day; lead times are fixed calendar days. Lead time plus review period must fit within 28 days; otherwise recommendations are unavailable, rather than extrapolated or reported as zero orders.

## Formulas

Let `f[t]` be unrounded predicted demand for future day `t`, `L` supplier lead time, `R` review interval, and `P = L + R` the protection period.

- Demand during lead time: `D_L = sum(f[1:L])` (inclusive).
- Demand through the protection period: `D_P = sum(f[1:P])`.
- Safety stock `B`: under the default policy, `(D_P / P) × buffer_days` (default 2 days). Alternative policies use a fixed configurable number of units or zero buffer.
- Reorder point: `D_L + B`. The below-point alert compares this with current stock plus listed receipts arriving within `L` days.
- Target stock: `D_P + B`.
- Inventory position for this review: current stock plus listed receipts arriving within `P` days.
- Raw replenishment gap: computed from the delivery-date ledger below. It is not generally `max(target − inventory_position, 0)` for lost sales or unevenly timed receipts.
- Suggested order: zero when the gap is zero; otherwise `ceil(max(gap, minimum_order_qty) / pack_size) × pack_size`. A numerical tolerance of `1e-9` avoids floating-point artifacts at exact boundaries.

This is a deterministic periodic-review policy: a positive gap can suggest an order even above the reorder point. Reorder point and nominal target stock are descriptive indicators. Minimum order quantities apply only to positive orders. Forecasts, buffers and projections retain fractional units; only orders round upward to whole packs. Screen formatting uses two decimals without altering calculations or CSV precision.

To size an order arriving at the start of day `L+1`, first project existing stock and receipts through days `1..L`, flooring stock at zero. Let `S_L` be the remaining stock and let `r[t]` be listed receipts. Lost sales in those days are reported as `pre_arrival_lost_units` and never become backorders. For each day `t` from `L+1` through `P`, define the unfloored cumulative balance:

`b[t] = S_L + sum(r[L+1:t]) - sum(f[L+1:t])`.

Then `G = max(0, max(-b[t]), B - b[P])`. The maximum daily deficit ensures that a late listed receipt cannot hide an earlier shortage after the suggested order arrives. The final term leaves the desired ending buffer. After supplier rounding, the suggested order is the smallest legal order meeting those deterministic conditions. Safety stock need not remain untouched on every day. If later committed receipts exceed the buffer target, excess ending stock can be unavoidable; cancellation/deferral optimization is outside this policy.

An explicit product `review_period_days` overrides the sidebar default. Blank or omitted values use the global setting; normalized inputs preserve an internal `review_period_is_override` flag. Supplier lead time, pack size and minimum order come from product metadata. The legacy `service_level` setting is reserved and is not used to calculate these deterministic buffers. Forecast intervals are not converted into a service guarantee or arbitrarily summed to calculate safety stock.

## Receipt timing and shortages

For each day: `available = opening_stock + listed_receipts`; `fulfilled = min(available, forecast)`; `unmet = max(forecast − available, 0)`; `closing_stock = max(available − forecast, 0)`. Closing stock becomes the next day's opening stock. Unmet demand is lost sales, without backorders. The estimated stockout date is the first day with positive unmet demand, rather than merely a zero closing balance. No date means none estimated within 28 days, not unlimited coverage.

Listed receipts arrive **in full at the start** of their expected date. Multiple receipts on a date are added once. Receipts after the protection period do not reduce today's order; those within 28 days still enter the daily projection. Overdue receipts require correction. Missing receipts mean no incoming stock is assumed; this assumption appears in the explanation. Received goods already included in current stock must not also remain in the future receipts file.

A new order placed after today's closing snapshot is assumed to arrive at the start of day `L + 1`, after `L` full selling days. The projection excludes suggested orders until the user records them as expected receipts. A delivery later in the window reduces only requirements that it can actually serve. Shortages before day `L+1` require separate action; increasing an order arriving on day `L+1` cannot recover those sales.

For P006 in the supplied sample, 78.25 expected units are lost before the new-order arrival date. The listed 300-unit receipt covers the remaining 225 units of protection-period demand and leaves 75 units, exceeding the 60.65-unit buffer. The standard order is zero. The earlier 72-unit recommendation incorrectly counted lost sales as outstanding demand. For comparison, with 10 units/day, no stock, lead 3, review 4 and no buffer, the correct raw order is 40 units for days 4–7, not 70 units. If 100 units instead arrive on day 6, an order of 20 units bridges days 4–5.

## Attention order and limitations

Products sort by: shortages before a new order can arrive; other projected shortages (including beyond the protection period); below reorder point; replenish at this review; unavailable data; monitor. Within each priority, the earliest shortage is shown first. Each recommendation explains forecast demand, buffer, available supply, rounded order and delivery assumptions. Early shortages recommend considering expedited supply, not automatic ordering.

Forecast error, censored historical stockout sales, supplier delays, unrecorded receipts and changing demand can affect results. These estimates cannot guarantee stockout prevention. Planning uses point demand, not stochastic stockout probabilities. There are no automatic orders, billing services or paid integrations.

## Outputs and checks

Inventory Planning and Downloads export `reorder_suggestions.csv` and `inventory_projection.csv`. Saved analysis runs include both tables, all settings, policy version `periodic-review-lost-sales-v2` and receipt assumptions. Focused tests cover zero demand, exact exhaustion, sufficient stock, each safety policy, fractional forecasts and pack rounding, long lead times, unsupported windows, timely/late deliveries, receipt window boundaries, review overrides, missing inputs, bad dates and displayed values. An independent exhaustive stock simulation verifies the smallest feasible supplier order across varied receipt scenarios. This is not evidence of optimal financial performance or a guaranteed stochastic service level.
