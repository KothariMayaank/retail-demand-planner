"""Periodic review with delivery-aware lost-sales replenishment and stock projection."""
import math
import numpy as np
import pandas as pd

POLICY_VERSION = "periodic-review-lost-sales-v2"


def arrival_order_gap(demand, deliveries, on_hand, lead, protection, safety):
    """Minimum added units on day L+1 to serve days L+1..P and end with B.

    Before arrival, stock is floored at zero: those lost sales cannot be served
    by this order. After arrival, an unfloored ledger gives every cumulative
    deficit. The largest deficit prevents a late receipt hiding an earlier gap.
    This is a deterministic planning rule, not stochastic policy optimization.
    """
    balance, pre_arrival_lost = on_hand, 0.
    for day in demand.iloc[:lead].itertuples(index=False):
        available = balance + float(deliveries.get(day.date, 0))
        pre_arrival_lost += max(0., float(day.predicted_units) - available)
        balance = max(0., available - float(day.predicted_units))
    gap = 0.
    for day in demand.iloc[lead:protection].itertuples(index=False):
        balance += float(deliveries.get(day.date, 0)) - float(day.predicted_units)
        gap = max(gap, -balance)
    return max(gap, safety - balance, 0.), pre_arrival_lost


def plan_inventory(dataset, forecasts, settings):
    if settings.safety_stock_policy not in ("demand_days", "fixed_units", "none"):
        raise ValueError("Unsupported safety-stock policy.")
    if not 0 <= settings.safety_stock_days <= 28 or settings.safety_stock_units < 0:
        raise ValueError("Safety-stock buffers must be nonnegative; demand days cannot exceed 28.")
    cutoff = dataset.tables["sales"].date.max()
    inventory = dataset.tables["inventory"]
    receipts = dataset.tables.get("receipts", pd.DataFrame())
    recommendations, projections = [], []
    for product in dataset.tables["products"].itertuples(index=False):
        product_id = product.product_id
        review_override = getattr(product, "review_period_is_override", hasattr(product, "review_period_days"))
        review = int(product.review_period_days) if review_override else settings.review_period_days
        lead = int(getattr(product, "lead_time_days", 7))
        protection = lead + review
        pack, minimum = int(getattr(product, "pack_size", 1)), int(getattr(product, "minimum_order_qty", 0))
        row = {"product_id": product_id, "product_name": product.product_name, "snapshot_date": cutoff,
               "lead_time_days": lead, "review_period_days": review, "protection_days": protection,
               "planning_forecast_horizon": 28, "policy_version": POLICY_VERSION,
               "safety_stock_policy": settings.safety_stock_policy, "pack_size": pack, "minimum_order_qty": minimum,
               "lead_time_demand_units": np.nan, "protection_demand_units": np.nan, "safety_stock_units": np.nan,
               "reorder_point_units": np.nan, "target_stock_units": np.nan, "on_hand_units": np.nan,
               "incoming_protection_units": np.nan, "inventory_position_units": np.nan,
               "raw_order_units": np.nan, "suggested_order_units": pd.NA, "below_reorder_point": False,
               "pre_arrival_lost_units": np.nan,
               "estimated_stockout_date": pd.NaT, "unmet_demand_units_28d": np.nan,
               "suggested_order_arrival_date": cutoff + pd.Timedelta(days=lead + 1),
               "next_review_date": cutoff + pd.Timedelta(days=review), "priority": 5,
               "attention": "Check data", "status": "unavailable", "explanation": ""}
        stock = inventory.loc[inventory.product_id == product_id] if "product_id" in inventory else pd.DataFrame()
        demand = forecasts.loc[(forecasts.product_id == product_id) & (forecasts.horizon_days == 28)].sort_values("date")
        reason = ("Lead time plus review period exceeds 28 days; extend forecast support or shorten the review interval."
                  if protection > 28 else "Current inventory snapshot is missing."
                  if stock.empty or "on_hand_units" not in stock else "Inventory snapshot does not match the sales cutoff."
                  if "snapshot_date" in stock and stock.snapshot_date.iloc[0] != cutoff else
                  "A complete 28-day planning forecast is unavailable."
                  if len(demand) != 28 or demand.predicted_units.isna().any() else "")
        if reason:
            row["explanation"] = reason
            recommendations.append(row)
            continue
        if lead < 1 or review < 1 or pack < 1 or minimum < 0:
            raise ValueError("Lead/review/pack values must be positive and minimum orders nonnegative.")
        expected = pd.date_range(cutoff + pd.Timedelta(days=1), periods=28)
        if demand.date.tolist() != expected.tolist() or not np.isfinite(demand.predicted_units).all() or demand.predicted_units.lt(0).any():
            raise ValueError("Inventory planning requires aligned, finite, nonnegative forecasts.")
        incoming = receipts.loc[receipts.product_id == product_id].copy() if "product_id" in receipts else pd.DataFrame()
        deliveries = incoming.groupby("expected_date").quantity_units.sum().to_dict() if not incoming.empty else {}
        if any(day <= cutoff for day in deliveries):
            raise ValueError("Overdue receipts must be corrected before inventory planning.")
        on_hand = float(stock.on_hand_units.iloc[0])
        if not np.isfinite(on_hand) or on_hand < 0:
            raise ValueError("On-hand inventory must be finite and nonnegative.")
        lead_demand = float(demand.predicted_units.iloc[:lead].sum())
        protected_demand = float(demand.predicted_units.iloc[:protection].sum())
        safety = (protected_demand / protection * settings.safety_stock_days if settings.safety_stock_policy == "demand_days" else
                  float(settings.safety_stock_units) if settings.safety_stock_policy == "fixed_units" else 0.)
        incoming_protection = float(sum(qty for day, qty in deliveries.items() if day <= cutoff + pd.Timedelta(days=protection)))
        incoming_lead = float(sum(qty for day, qty in deliveries.items() if day <= cutoff + pd.Timedelta(days=lead)))
        position = on_hand + incoming_protection
        target, reorder = protected_demand + safety, lead_demand + safety
        gap, pre_arrival_lost = arrival_order_gap(demand, deliveries, on_hand, lead, protection, safety)
        order = int(math.ceil((max(gap, minimum) - 1e-9) / pack) * pack) if gap > 1e-9 else 0
        balance, lost, first_shortage = on_hand, 0., pd.NaT
        for day in demand.itertuples(index=False):
            received = float(deliveries.get(day.date, 0))
            available = balance + received
            unmet = max(0., float(day.predicted_units) - available)
            fulfilled = min(available, float(day.predicted_units))
            end_balance = max(0., available - float(day.predicted_units))
            if unmet > 1e-9 and pd.isna(first_shortage):
                first_shortage = day.date
            projections.append({"product_id": product_id, "date": day.date, "opening_stock_units": balance,
                                "incoming_units": received, "available_units": available,
                                "forecast_demand_units": float(day.predicted_units), "fulfilled_units": fulfilled,
                                "unmet_demand_units": unmet, "closing_stock_units": end_balance})
            balance, lost = end_balance, lost + unmet
        below = on_hand + incoming_lead < reorder - 1e-9
        if pd.notna(first_shortage) and first_shortage < row["suggested_order_arrival_date"]:
            priority, attention = 1, "Shortage before new order can arrive"
        elif pd.notna(first_shortage) and first_shortage <= cutoff + pd.Timedelta(days=protection):
            priority, attention = 2, "Shortage within protection period"
        elif pd.notna(first_shortage):
            priority, attention = 2, "Shortage beyond protection period; review again"
        elif below:
            priority, attention = 3, "Below reorder point"
        elif order:
            priority, attention = 4, "Replenish at this review"
        else:
            priority, attention = 6, "Monitor"
        explanation = (f"Forecast demand over {protection} days is {protected_demand:.2f} units, with a {safety:.2f}-unit buffer. "
                       f"Current stock is {on_hand:g}; known receipts by the end of that window add {incoming_protection:g}. "
                       f"Expected lost sales before a new order can arrive are {pre_arrival_lost:.2f} units; these are not backordered. "
                       "The order covers forecast demand from its arrival through the protection period and the ending buffer, accounting for each receipt date. "
                       + (f"Suggest {order} units, rounded up for pack size {pack} and minimum order {minimum}. " if order else "No order is suggested at this review. ")
                       + (f"A shortage is estimated on {first_shortage.date()}. " if pd.notna(first_shortage) else "No unmet demand is projected in the 28-day window. ")
                       + ("Consider expediting supply: a new order placed now would arrive after the estimated shortage. " if priority == 1 else "")
                       + ("No incoming receipts are listed for this product; assumes none. " if incoming.empty else "Listed deliveries are assumed to arrive in full at the start of their expected date. ")
                       + "The projection excludes the suggested order until it is recorded as a receipt. Forecasts and delivery timing can change.")
        row.update(on_hand_units=on_hand, lead_time_demand_units=lead_demand, protection_demand_units=protected_demand,
                   safety_stock_units=safety, reorder_point_units=reorder, target_stock_units=target,
                   incoming_protection_units=incoming_protection, inventory_position_units=position,
                   raw_order_units=gap, suggested_order_units=order, below_reorder_point=below,
                   pre_arrival_lost_units=pre_arrival_lost,
                   estimated_stockout_date=first_shortage, unmet_demand_units_28d=lost,
                   priority=priority, attention=attention, status="ready", explanation=explanation)
        recommendations.append(row)
    summary = pd.DataFrame(recommendations).sort_values(["priority", "estimated_stockout_date", "product_id"], na_position="last").reset_index(drop=True)
    summary["suggested_order_units"] = pd.array(summary.suggested_order_units, dtype="Int64")
    return pd.DataFrame(projections), summary
