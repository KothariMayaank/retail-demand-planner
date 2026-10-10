"""Plotly figures built from the same tables used by the dashboard metrics."""
from html import escape
import pandas as pd
import plotly.graph_objects as go
from demand_planner.analytics.history import flagged_periods

TEAL = "#167568"
AMBER = "#B66313"
RED = "#C23934"
PURPLE = "#7554A3"


def values(series) -> list:
    return [None if pd.isna(value) else float(value) for value in series]


def daily_chart(daily: pd.DataFrame, rolling_days: int) -> go.Figure:
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=daily.date, y=values(daily.units_sold), name="Daily sales",
                               mode="lines+markers", line={"color": TEAL, "width": 1.5}, marker={"size": 3},
                               connectgaps=False, customdata=daily.status.tolist(),
                               hovertemplate="%{x|%d %b %Y}<br>Sales: %{y:,.0f} units<br>%{customdata}<extra></extra>"))
    figure.add_trace(go.Scatter(x=daily.date, y=values(daily.rolling_average), name=f"{rolling_days}-day average",
                               mode="lines", line={"color": AMBER, "width": 2.5}, connectgaps=False,
                               hovertemplate="%{x|%d %b %Y}<br>Rolling average: %{y:.2f} units/day<extra></extra>"))
    for status, color, symbol in (("Known stockout", RED, "diamond"), ("Confirmed zero", PURPLE, "square")):
        subset = daily.loc[daily.status == status]
        if not subset.empty:
            figure.add_trace(go.Scatter(x=subset.date, y=values(subset.units_sold), name=status,
                                       mode="markers", marker={"color": color, "symbol": symbol, "size": 9},
                                       hovertemplate="%{x|%d %b %Y}<br>Observed sales: %{y:,.0f} units<extra>%{fullData.name}</extra>"))
    colors = {"Known stockout": RED, "Missing record": "#737D8C", "Outside product history": "#A6BBD0"}
    for period in flagged_periods(daily).itertuples():
        if period.status in colors:
            figure.add_vrect(x0=period.start_date - pd.Timedelta(hours=12),
                             x1=period.end_date + pd.Timedelta(hours=12),
                             fillcolor=colors[period.status], opacity=.13, line_width=0, layer="below")
    figure.update_layout(height=400, margin={"l": 20, "r": 20, "t": 15, "b": 55},
                         legend={"orientation": "h", "y": -0.20}, template="plotly_white", hovermode="x unified",
                         xaxis={"title": "Date", "range": [daily.date.min() - pd.Timedelta(hours=12),
                                                            daily.date.max() + pd.Timedelta(hours=12)]},
                         yaxis={"title": "Units sold", "rangemode": "tozero"})
    return figure


def weekday_chart(weekdays: pd.DataFrame) -> go.Figure:
    custom = weekdays[["recorded_days", "missing_days", "stockout_days"]].values.tolist()
    figure = go.Figure(go.Bar(x=weekdays.weekday, y=values(weekdays.average_daily_units),
                             marker_color=TEAL, customdata=custom,
                             hovertemplate="%{x}<br>Average: %{y:.2f} units/day<br>Recorded days: %{customdata[0]}"
                                           "<br>Missing days: %{customdata[1]}<br>Stockout days: %{customdata[2]}<extra></extra>"))
    figure.update_layout(height=310, margin={"l": 20, "r": 20, "t": 10, "b": 35}, template="plotly_white",
                         xaxis_title="Weekday", yaxis={"title": "Average units / recorded day", "rangemode": "tozero"})
    return figure


def comparison_chart(comparison: pd.DataFrame, selected_product: str) -> go.Figure:
    labels = [escape(f"{row.product_name} ({row.product_id})") for row in comparison.itertuples()]
    colors = [AMBER if row.missing_days else TEAL if row.product_id == selected_product else "#668982"
              for row in comparison.itertuples()]
    custom = [[row.recorded_days, row.expected_days, row.missing_days, row.stockout_days]
              for row in comparison.itertuples()]
    figure = go.Figure(go.Bar(y=labels, x=values(comparison.total_units), orientation="h",
                             marker_color=colors, text=values(comparison.total_units), texttemplate="%{text:,.0f}",
                             textposition="outside", cliponaxis=False, customdata=custom,
                             hovertemplate="%{y}<br>Recorded total: %{x:,.0f} units<br>Recorded days: %{customdata[0]}"
                                           " / %{customdata[1]}<br>Missing days: %{customdata[2]}"
                                           "<br>Stockout days: %{customdata[3]}<extra></extra>"))
    figure.update_layout(height=max(300, 28 * len(comparison) + 110), template="plotly_white",
                         margin={"l": 20, "r": 65, "t": 40, "b": 35},
                         yaxis={"autorange": "reversed", "automargin": True},
                         xaxis={"title": "Total recorded units in selected date range", "rangemode": "tozero"})
    return figure
