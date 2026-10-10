"""Synthetic retail CSVs and separate demonstration truth; standard library only.

Fixed dates and seed prevent daily drift. See data/sample/README.md.
"""
import csv
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from hashlib import sha256
import json
import math
from pathlib import Path
import random

START_DATE = date(2024, 10, 10)
END_DATE = date(2026, 10, 9)
SEED = 42
GENERATOR_VERSION = 2
WEEKDAY_FACTORS = {
    "everyday": (0.92, 0.94, 0.96, 1.00, 1.08, 1.18, 1.12),
    "weekend": (0.80, 0.82, 0.85, 0.95, 1.15, 1.50, 1.35),
    "weekday": (1.15, 1.10, 1.10, 1.10, 1.05, 0.80, 0.75),
}


@dataclass(frozen=True)
class ProductProfile:
    product_id: str
    product_name: str
    category: str
    base_daily_demand: float
    weekday_pattern: str
    seasonal_amplitude: float
    peak_day_of_year: int
    two_year_growth: float
    purchase_probability: float
    lead_time_days: int
    pack_size: int
    minimum_order_qty: int


PROFILES = (
    ProductProfile("P001", "Rice 1 kg", "Pantry", 18, "everyday", .08, 300, .10, 1, 5, 6, 12),
    ProductProfile("P002", "Wheat flour 1 kg", "Pantry", 13, "everyday", .12, 330, .05, 1, 5, 6, 12),
    ProductProfile("P003", "Milk 1 L", "Dairy", 36, "weekday", .06, 20, .08, 1, 1, 12, 24),
    ProductProfile("P004", "Bread loaf", "Bakery", 24, "weekday", .08, 30, .05, 1, 1, 6, 12),
    ProductProfile("P005", "Eggs 6 pack", "Dairy", 15, "weekend", .10, 345, .06, 1, 2, 6, 12),
    ProductProfile("P006", "Bottled water 1 L", "Drinks", 28, "weekend", .55, 160, .12, 1, 3, 12, 24),
    ProductProfile("P007", "Cola 750 ml", "Drinks", 12, "weekend", .45, 170, .02, 1, 4, 12, 12),
    ProductProfile("P008", "Fruit juice 1 L", "Drinks", 8, "weekend", .35, 170, .05, 1, 4, 6, 6),
    ProductProfile("P009", "Tea 250 g", "Pantry", 7, "everyday", .28, 15, .06, 1, 7, 6, 6),
    ProductProfile("P010", "Coffee 100 g", "Pantry", 5, "weekday", .30, 10, .10, 1, 7, 6, 6),
    ProductProfile("P011", "Biscuits 200 g", "Snacks", 20, "weekend", .16, 340, .08, 1, 5, 12, 12),
    ProductProfile("P012", "Potato chips 100 g", "Snacks", 16, "weekend", .14, 320, .06, 1, 5, 12, 12),
    ProductProfile("P013", "Instant noodles 4 pack", "Pantry", 10, "weekend", .12, 290, .04, 1, 6, 6, 6),
    ProductProfile("P014", "Cooking oil 1 L", "Pantry", 9, "everyday", .12, 310, .03, 1, 8, 6, 12),
    ProductProfile("P015", "Laundry detergent 1 kg", "Household", 11, "weekend", .12, 200, .05, 1, 10, 6, 12),
    ProductProfile("P016", "Bath soap 3 pack", "Household", 6, "everyday", .10, 170, .02, 1, 8, 6, 6),
    ProductProfile("P017", "AA batteries 4 pack", "Household", 2.5, "weekend", .15, 345, .02, .22, 12, 4, 4),
    ProductProfile("P018", "Shoe polish 50 g", "Household", 1.5, "weekday", .12, 240, 0, .15, 14, 6, 6),
    ProductProfile("P019", "Birthday candles", "Household", 2, "weekend", .08, 180, .03, .18, 12, 12, 12),
    ProductProfile("P020", "Specialty spice 50 g", "Pantry", 1.5, "weekend", .25, 310, .04, .25, 10, 6, 6),
)


def poisson(rng: random.Random, mean: float) -> int:
    """Knuth sampler; the sample means are small enough for this algorithm."""
    threshold = math.exp(-mean)
    probability, count = 1.0, 0
    while probability > threshold:
        probability *= rng.random()
        count += 1
    return max(0, count - 1)


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def promotion_events() -> list[dict]:
    events = []
    campaigns = ((5, 10, "Summer drinks", ("P006", "P007", "P008"), 1.60),
                 (9, 15, "Pantry promotion", ("P001", "P014"), 1.45),
                 (12, 15, "Winter snacks", ("P011", "P012"), 1.70))
    for year in range(START_DATE.year, END_DATE.year + 1):
        for month, day, label, ids, multiplier in campaigns:
            start = date(year, month, day)
            end = start + timedelta(days=6)
            if start < START_DATE or end > END_DATE:
                continue
            for product_id in ids:
                events.append({"promotion_id": f"PROMO-{year}-{month:02d}-{product_id}",
                               "product_id": product_id, "start_date": start.isoformat(),
                               "end_date": end.isoformat(), "label": label,
                               "demand_multiplier": multiplier})
    return events


def stockout_events() -> list[dict]:
    events = []
    for product_id, start in (("P003", date(2025, 2, 10)),
                              ("P006", date(2026, 6, 13)),
                              ("P015", date(2026, 9, 22))):
        for offset, available in enumerate((0, 3, 0)):
            events.append({"stockout_event_id": f"SO-{product_id}-{offset + 1}",
                           "product_id": product_id,
                           "date": (start + timedelta(days=offset)).isoformat(),
                           "available_units": available})
    return events


def generate(destination: Path) -> dict:
    rng = random.Random(SEED)
    promotions, stockouts = promotion_events(), stockout_events()
    stockout_lookup = {(event["product_id"], event["date"]): event for event in stockouts}
    tables = {"products": [], "sales": [], "inventory": [], "receipts": []}
    reference = []
    total_days = (END_DATE - START_DATE).days + 1
    for profile in PROFILES:
        product_id = profile.product_id
        tables["products"].append([product_id, profile.product_name, profile.category,
                                   profile.lead_time_days, 7, .95, profile.pack_size,
                                   profile.minimum_order_qty])
        observed = []
        for day in range(total_days):
            current = START_DATE + timedelta(days=day)
            weekday_factor = WEEKDAY_FACTORS[profile.weekday_pattern][current.weekday()]
            days_in_year = (date(current.year + 1, 1, 1) - date(current.year, 1, 1)).days
            season = 1 + profile.seasonal_amplitude * math.cos(
                2 * math.pi * (current.timetuple().tm_yday - profile.peak_day_of_year) / days_in_year)
            trend = 1 + profile.two_year_growth * day / (total_days - 1)
            promo = next((event for event in promotions if event["product_id"] == product_id
                          and event["start_date"] <= current.isoformat() <= event["end_date"]), None)
            multiplier = promo["demand_multiplier"] if promo else 1.0
            conditional_mean = profile.base_daily_demand * weekday_factor * season * trend * multiplier
            if profile.purchase_probability < 1 and rng.random() >= profile.purchase_probability:
                latent_demand = 0
            else:
                latent_demand = poisson(rng, rng.gammavariate(18, conditional_mean / 18))
            stockout = stockout_lookup.get((product_id, current.isoformat()))
            units = min(latent_demand, stockout["available_units"]) if stockout else latent_demand
            observed.append(units)
            tables["sales"].append([current.isoformat(), product_id, units,
                                     "true" if stockout else "false"])
            reference.append([current.isoformat(), product_id, latent_demand, units,
                              latent_demand - units, round(conditional_mean * profile.purchase_probability, 4),
                              promo["promotion_id"] if promo else "", multiplier,
                              stockout["stockout_event_id"] if stockout else "",
                              stockout["available_units"] if stockout else ""])
        daily_mean = sum(observed[-28:]) / 28
        # A planning snapshot, not a reconstruction of a purchasing ledger.
        cover_days = 60 if product_id in ("P001", "P002") else 10 + profile.lead_time_days
        on_hand = math.ceil(daily_mean * cover_days)
        if product_id in ("P003", "P006", "P015"):
            on_hand = {"P003": 2, "P006": 0, "P015": 3}[product_id]
        tables["inventory"].append([END_DATE.isoformat(), product_id, on_hand])
        if product_id in ("P006", "P009", "P015", "P018"):
            receipt_qty = profile.pack_size * max(1, math.ceil(daily_mean * 10 / profile.pack_size))
            tables["receipts"].append([f"R-{product_id}", product_id,
                                       (END_DATE + timedelta(days=profile.lead_time_days)).isoformat(), receipt_qty])
    templates = Path(__file__).resolve().parents[1] / "data/templates"
    for name, rows in tables.items():
        with (templates / f"{name}.csv").open(encoding="utf-8", newline="") as source:
            header = next(csv.reader(source))
        write_csv(destination / f"{name}.csv", header, rows)
    reference_dir = destination / "reference"
    write_csv(reference_dir / "demand_reference.csv",
              ["date", "product_id", "latent_demand_units", "observed_sales_units", "lost_sales_units",
               "mean_demand_units", "promotion_id", "promotion_multiplier", "stockout_event_id",
               "available_units_on_stockout_day"], reference)
    for name, events in (("promotions", promotions), ("stockout_events", stockouts)):
        write_csv(reference_dir / f"{name}.csv", list(events[0]), [list(event.values()) for event in events])
    profiles = [asdict(profile) for profile in PROFILES]
    write_csv(reference_dir / "product_profiles.csv", list(profiles[0]), [list(profile.values()) for profile in profiles])
    generated_files = [destination / f"{name}.csv" for name in tables] + [
        reference_dir / f"{name}.csv" for name in ("demand_reference", "promotions", "stockout_events", "product_profiles")]
    manifest = {
        "is_synthetic": True, "store_count": 1, "generator_version": GENERATOR_VERSION,
        "seed": SEED, "start_date": START_DATE.isoformat(), "end_date": END_DATE.isoformat(),
        "snapshot_date": END_DATE.isoformat(), "product_count": len(PROFILES),
        "days_per_product": total_days, "sales_rows": len(tables["sales"]),
        "intermittent_product_ids": [p.product_id for p in PROFILES if p.purchase_probability < 1],
        "stockout_days": len(stockouts), "promotion_product_events": len(promotions),
        "observed_sales_units": sum(row[3] for row in reference),
        "latent_demand_units": sum(row[2] for row in reference),
        "lost_sales_units": sum(row[4] for row in reference),
        "weekday_factors_monday_to_sunday": WEEKDAY_FACTORS, "gamma_shape": 18,
        "sha256": {path.relative_to(destination).as_posix(): sha256(path.read_bytes()).hexdigest()
                   for path in generated_files},
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    summary = generate(Path(__file__).resolve().parents[1] / "data/sample")
    print(f"Generated synthetic sample: {summary['sales_rows']:,} rows, "
          f"{summary['product_count']} products, {summary['stockout_days']} flagged days.")
