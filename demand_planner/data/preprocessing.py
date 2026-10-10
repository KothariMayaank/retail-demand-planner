"""Prepare one training window without using future observations or hidden demand."""
import pandas as pd


def prepare_training_series(sales: pd.DataFrame, product_id: str, cutoff,
                            *, impute_stockouts: bool = False) -> pd.DataFrame:
    """Return observed sales, optional fitting values and evaluation eligibility.

    Known stockouts are never scoring targets. For models requiring a complete
    series, opt-in imputation uses the same-weekday mean within this training
    window, falling back to its non-stockout mean. No sales are overwritten.
    """
    required = {"date", "product_id", "units_sold", "stockout_flag"}
    if not required <= set(sales):
        raise ValueError("Use validated sales with dates, quantities and stockout flags.")
    history = sales.loc[(sales.product_id == product_id) & (sales.date <= pd.Timestamp(cutoff))].copy()
    if history.empty:
        raise ValueError("No sales are available for this product at the training cutoff.")
    if history.duplicated("date").any():
        raise ValueError("Duplicate daily observations must be corrected before training.")
    history = history.sort_values("date").set_index("date")
    expected = pd.date_range(history.index.min(), pd.Timestamp(cutoff), freq="D")
    if not expected.equals(pd.DatetimeIndex(history.index)):
        raise ValueError("Missing daily sales must be corrected or explicitly confirmed as zero before training.")
    if history.units_sold.isna().any():
        raise ValueError("Missing sales quantities cannot be used for training.")
    flagged = history.stockout_flag.fillna(False).astype(bool)
    history["observed_units"] = history.units_sold.astype(float)
    history["fit_units"] = history.observed_units.mask(flagged)
    history["score_eligible"] = ~flagged
    history["stockout_imputed"] = False
    if impute_stockouts and flagged.any():
        ordinary = history.loc[~flagged, "observed_units"]
        if ordinary.empty:
            raise ValueError("Stockout imputation needs at least one non-stockout training observation.")
        weekday_means = ordinary.groupby(ordinary.index.dayofweek).mean()
        for day in history.index[flagged]:
            history.at[day, "fit_units"] = weekday_means.get(day.dayofweek, ordinary.mean())
            history.at[day, "stockout_imputed"] = True
    return history.reset_index()
