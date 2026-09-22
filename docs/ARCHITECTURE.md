# Architecture Notes

## Data flow (SDLF-style stages)

| Stage | Storage | Format | Purpose |
|---|---|---|---|
| Raw (landing) | `s3://<prefix>-raw/raw/source=<site>/dt=<yyyy-mm-dd>/*.json` | NDJSON, as-crawled | Immutable capture, one file per crawl run |
| Stage | Glue Catalog `product_stage.products` | Apache Iceberg | Cleaned, typed, deduped **snapshot history** — one row per (product_id, crawl_date) |
| Analytics | Glue Catalog `product_analytics.products` | Apache Iceberg | Growth metrics derived from consecutive snapshots, partitioned for BI/ML |

## Why Stage is a snapshot history, not a "current state" table

A single snapshot of a product (price, rating, sold count *today*) says
nothing about whether it's "potential" — that requires comparing to its
*previous* snapshot. So unlike a typical SCD-1 "latest state" table, Stage
intentionally keeps every daily observation per product
(`MERGE ... ON product_id AND crawl_date`, not `ON product_id` alone).
Analytics then uses a window function (`LAG(...) OVER (PARTITION BY
product_id ORDER BY crawl_date)`) to compute deltas between consecutive
snapshots. This is the central design difference from a plain "clean and
store" pipeline — the whole point of the crawl-history approach.

## Canonical schema (Stage)

```
product_id        string   -- source-prefixed id from the crawl
source            string   -- tiki | shopee | lazada
name              string
category          string
price             double   -- current selling price, VND
original_price    double   -- list price before discount, VND
rating_average    double
review_count      int
quantity_sold     int      -- cumulative units sold, as reported by the site
seller_name       string
badges_new        boolean
crawl_date        date     -- one row per product per day
crawled_at        timestamp
```

## Canonical schema (Analytics — adds growth features)

```
discount_pct        double  -- (original_price - price) / original_price
days_since_prev      int     -- days between this snapshot and the product's previous one
sold_growth          int     -- quantity_sold - previous quantity_sold
sold_growth_rate     double  -- sold_growth / days_since_prev
review_growth        int     -- review_count - previous review_count
rating_change        double  -- rating_average - previous rating_average
potential_score      double  -- heuristic ranking score for dashboards
                               (0.7 * sold_growth_rate + 0.3 * review_growth);
                               NOT the ML model's prediction — see ml/train_potential_model.py
year_month           string  -- yyyy-MM, partition column
```

Partitioning: `year_month` — keeps Athena scans cheap as history grows, and
lines up with Iceberg's hidden partitioning so partition columns don't need
to be duplicated in query predicates.

## Why Iceberg specifically

- **Schema evolution**: sites change their API/HTML fields; Iceberg lets the
  Glue job add/rename columns without rewriting historical snapshots or
  breaking Athena.
- **ACID / upserts**: `MERGE INTO` on `(product_id, crawl_date)` avoids
  duplicate rows if a crawl run is retried on the same day.
- **Time travel**: query the table `AS OF` a past snapshot to reproduce a
  week-old leaderboard of potential products, or compare before/after a
  change to the growth-calculation logic.
- **Partition pruning**: Athena only scans relevant `year_month` partitions
  instead of the full snapshot history.

## Step Functions state machine (`product-pipeline`)

```
StartState
  └─ RawToStage (Glue job: raw_to_stage.py)
       └─ StageToAnalytics (Glue job: stage_to_analytics.py)
            └─ Succeed
```
Both states are `Glue: StartJobRun` with `.sync` integration so the state
machine waits for job completion; failures go to a `Fail` state (see
`infra/infra/pipeline_stack.py`). EventBridge triggers the crawler Lambda on
a schedule; a second (or the same) EventBridge rule can start the state
machine shortly after, or the crawler Lambda can call `StartExecution`
directly once it finishes uploading.

## Defining "potential" — why a relative, per-category label

`ml/train_potential_model.py` labels a product `is_potential=1` if its
`sold_growth_rate` is in the top quantile **within its own
(category, year_month) group** rather than using a single global growth
threshold. Absolute sales growth is not comparable across categories (a
"fast-growing" phone and a "fast-growing" fashion item have very different
baseline volumes), so ranking within category avoids the model just
learning "category X always wins."

## Storage volume estimate — how to fill it in

1. After the first crawl, check object sizes in `<prefix>-raw`:
   `aws s3 ls s3://<prefix>-raw/raw/ --recursive --summarize`
2. `rows/day ≈ products per category × pages crawled × categories`
3. `raw GB/day ≈ rows/day × avg_record_bytes / 1e9`
4. Multiply by intended retention (e.g. 90 days for the demo) for target raw
   size. Note: unlike a "current state" table, Stage grows roughly linearly
   with retention since every day adds a full new snapshot per product.
5. Analytics/Iceberg size after compaction is typically smaller (columnar +
   dedup) — estimate 30–50% of raw for the demo dataset.
