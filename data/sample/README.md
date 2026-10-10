# Synthetic retail sample

All records in this folder are generated demonstration data for one fictional store. They contain no actual customer, supplier or store records. Quantities are whole selling units: a listed pack is one selling unit, and `pack_size` describes supplier order multiples in those units.

## Period and files

The fixed two-year period runs from **2024-10-10 through 2026-10-09**, inclusive: 730 consecutive calendar days for each of 20 products, or 14,600 sales records. The inventory snapshot is end-of-day 2026-10-09. Fixed dates keep regeneration reproducible; the snapshot will not advance automatically.

`products.csv`, `sales.csv`, `inventory.csv` and `receipts.csv` exactly follow the application's agreed templates. Those are the only files loaded as store inputs. `manifest.json` labels the entire dataset as synthetic and records the seed, period, summary counts and SHA-256 hashes of the generated CSVs.

The `reference/` folder contains demonstration evidence, excluded from forecasting inputs:

| File | Purpose |
| --- | --- |
| demand_reference.csv | Date/product, simulated latent demand, observed sales, lost units, expected demand mean, promotion ID/multiplier and stockout event ID/availability. One row per sales row. |
| product_profiles.csv | Product-specific demand level, weekday pattern, seasonal amplitude/peak, growth, purchase probability and supplier parameters. |
| promotions.csv | One row per promotion/product, with unique ID, inclusive start/end dates, label and demand multiplier. |
| stockout_events.csv | Nine unique product-date events with an event ID and available units. |

Blank reference event IDs mean no event. Blank stockout-day availability means unconstrained stock availability in the simulation, not zero inventory. `mean_demand_units` is the expected unconditional demand before observation limits, not the realized demand count.

## Generation method

Run from the project root:

```powershell
.\.venv\Scripts\python.exe scripts/generate_sample_data.py
```

The generator uses Python's standard library, fixed seed **42**, fixed product/event ordering and explicit LF CSV line endings. It writes only the named generated CSVs and manifest, preserving this guide. Repeated runs in the tested Python 3.12 environment produce byte-identical files. Cross-version random-number implementations and math behavior are not promised to be identical.

Each product has a base demand level, one of three Monday-to-Sunday patterns, and a smooth annual cosine seasonal effect. Summer peaks emphasize drinks; winter peaks emphasize tea, coffee and snacks. Product-specific gradual growth ranges from 0% to 12% over the two years. These are illustrative shopping patterns, not a fitted regional calendar or an actual festival model.

The conditional daily demand mean is:

```text
base demand × weekday factor × annual seasonal factor × growth factor × promotion multiplier
```

Random demand is drawn from a Gamma-Poisson mixture with gamma shape 18, allowing variance above a simple Poisson count. All realized demand and observed sales are nonnegative integers.

Four intermittent products (P017–P020) first receive a Bernoulli purchase opportunity, with probabilities 0.15–0.25 per day. Days without an opportunity have genuine zero demand. Their base demand describes the count mean conditional on an opportunity. Their unconditional mean is the conditional mean multiplied by the opportunity probability.

Seven-day promotions boost targeted drinks in May, pantry products in September, and snacks in December. Only campaigns fully inside the sample period are included. Promotion multipliers range from 1.45 to 1.70. Noise means a promotion does not guarantee every day's realized sales exceed an ordinary day. Promotions are historical data patterns; promotion-aware forecasting remains outside version 1.

## Identifiable stockouts

| Product | Dates | Daily availability |
| --- | --- | --- |
| P003 — Milk 1 L | 2025-02-10 to 2025-02-12 | 0, 3, 0 units |
| P006 — Bottled water 1 L | 2026-06-13 to 2026-06-15 | 0, 3, 0 units |
| P015 — Laundry detergent 1 kg | 2026-09-22 to 2026-09-24 | 0, 3, 0 units |

For these events, observed sales equal `min(latent demand, available units)`, and `stockout_flag` is `true`. Lost sales equal latent demand minus observed sales. Every other day has observed sales equal latent demand and `stockout_flag=false`.

The dashboard's sample tab shows these events after loading the sample. Known latent demand is available because this dataset is simulated. Real store sales do not reveal lost demand by themselves. The reference truth must never be used as a model feature or to fill training data.

## Inventory and receipts

Lead times range from 1–14 calendar days. All products use a seven-day review interval and a legacy `service_level` value of 0.95, with varied supplier pack sizes and minimum orders. That field is reserved and does not establish a 95% service guarantee or determine the buffer. Every lead-time-plus-review period remains within the agreed 28-day planning limit.

The current inventory snapshot is deliberately constructed for planning demonstrations. P003, P006 and P015 have very little or no stock. P001 and P002 carry approximately 60 days of recent mean sales; other products have roughly `10 + lead time` days of stock. Inventory is rounded up to whole selling units. This snapshot does not claim to reconstruct a historical stock or purchasing ledger.

Four pending receipts (P006, P009, P015 and P018) arrive after the snapshot, at their lead-time dates. Receipt quantities represent about ten days of recent sales rounded to supplier packs. Receipt timing follows the specification's start-of-day availability convention.

## Verification

Automated checks verify exact input headers, complete dates, unique product/date keys, valid IDs, nonnegative integer quantities, boolean flags, supplier bounds, aligned inventory dates, future receipts, promotion links, stockout reconciliation, intermittent zeros, file hashes and byte-for-byte reproducibility. Sample loading also uses the application's full upload validator. See [the upload validation policy](../../docs/data_validation.md) for missing dates, defaults and stockout preprocessing.
