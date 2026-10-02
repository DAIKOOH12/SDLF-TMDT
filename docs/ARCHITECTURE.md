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
product_id          string   -- source-prefixed id from the crawl
source              string   -- tiki | shopee | lazada
name                string
category            string
brand_name          string
price               double   -- current selling price, VND
original_price      double   -- list price before discount, VND (falls back to price if missing)
discount_rate       double   -- 0-100, as reported by the site
rating_average      double
review_count        int
quantity_sold       int      -- cumulative units sold; falls back to the
                               amplitude.all_time_quantity_sold field when
                               the primary field is null (new/ad listings)
seller_id           bigint
is_official_store   boolean
crawl_date          date     -- one row per product per day
crawled_at          timestamp
```

## Canonical schema (Analytics — adds growth features)

```
brand_name           string  -- carried through from Stage, unchanged
is_official_store    boolean -- carried through from Stage, unchanged
discount_pct         double  -- discount_rate/100, falls back to computing
                               from price/original_price if discount_rate is null
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

### Known limitation: `potential_score` reads as `0`, not "unknown", on a product's first snapshot

`sold_growth_rate` and `review_growth` need a *previous* snapshot
(`LAG(...) OVER (PARTITION BY product_id ORDER BY crawl_date)`) to compute
anything. For a product's first-ever crawl, there is no previous row, so
both are `NULL` — and the formula above wraps them in `COALESCE(..., 0.0)`,
turning "no history yet" into `0`. This means a brand-new product and a
genuinely stagnant product (demand truly flat) both show
`potential_score = 0`, with no way to tell them apart from this column
alone. Confirmed in practice: a fresh environment's first Athena query
after one crawl shows `potential_score = 0.0` across every row — this is
expected, not a bug, and resolves itself once a product has ≥ 2 snapshots
on different `crawl_date` values.

If this distinction matters for your analysis (e.g. you want to filter out
"not enough history yet" from a leaderboard), change the `COALESCE(...,
0.0)` calls in `stage_to_analytics.py` to leave `potential_score` as `NULL`
instead when `prev_quantity_sold` is null, and filter/handle `NULL`
explicitly in Athena/QuickSight.

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
`infra/stacks/pipeline_stack.py`). EventBridge triggers the crawler Lambda on
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

## Cost estimate (ap-southeast-1, demo scale)

| Service | Driver | Rough cost |
|---|---|---|
| AWS Glue | 2 jobs × 2 workers (G.1X) × ~5-8 min/run (mostly Spark startup, not data volume) | **~$0.15–0.25 per `start-execution`** — the dominant cost; scales with how many times you run the pipeline, not with data size |
| Lambda, S3, Step Functions, EventBridge, Athena, CloudWatch | Demo-scale usage (KB–MB data, 1 crawl/day) | Effectively **$0**, within free tier |
| QuickSight | Not deployed yet | $0 until you create a dashboard (Reader: ~$0.30/session, Author: $9+/month) |
| SageMaker | Not used (`ml/train_potential_model.py` runs locally) | $0 |

No VPC/NAT Gateway is used anywhere in this stack, which avoids the most
common "surprise" AWS bill for small projects. `number_of_workers=2` on
both Glue jobs (the Spark minimum) keeps each pipeline run as cheap as
possible — raise it only if you scale up categories/pages enough that jobs
start queuing on CPU. Expect a full month of iterative testing (tens of
`start-execution` calls) to land well under $10-15 total.
