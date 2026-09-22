# QuickSight Dashboard

QuickSight is console-configured (CDK/IaC coverage for full dashboard
definitions is limited). Steps to build it manually:

## 1. Data source
- QuickSight → Datasets → New dataset → **Athena**
- Data source name: `product-analytics-athena`
- Workgroup: the one Athena queries against (uses `<prefix>-athena-results`
  for query output, from `infra/infra/storage_stack.py`)

## 2. Dataset
- Table: `product_analytics.products` (created/updated by
  `glue_jobs/clean_transform/stage_to_analytics.py`)
- Import mode: SPICE (for demo-scale data) or direct query if the table
  grows past SPICE limits
- Set a refresh schedule matching the crawl cadence (e.g. daily, shortly
  after the Step Functions pipeline finishes)

## 3. Recommended analyses / visuals

| Visual | Type | Fields |
|---|---|---|
| Top potential products (this period) | Table, sorted desc | `name`, `category`, `sold_growth_rate`, `review_growth`, `potential_score` |
| Sales growth trend by category | Line chart | X: `crawl_date`/`year_month`, Value: avg(`sold_growth_rate`), group by `category` |
| Price vs. rating | Scatter plot | X: `price`, Y: `rating_average`, color: `category`, size: `quantity_sold` |
| Distribution of growth rates | Histogram | `sold_growth_rate` (helps justify the top-quantile threshold used in `ml/train_potential_model.py`) |
| Discount vs. sales growth | Scatter plot | X: `discount_pct`, Y: `sold_growth_rate` — sanity-checks whether "potential" is just discounting, not organic demand |
| Predicted potential vs. actual outcome | Table/scatter | Requires a small export from `ml/train_potential_model.py` (predicted probability vs. the realized `is_potential` label on a held-out period) — export as CSV and load as a second QuickSight dataset |

## 4. Filters / parameters
- Add a `category` filter control and a `year_month`/`crawl_date` range
  control so the dashboard doubles as an exploration tool, not just static
  charts.

## 5. Sharing
- Publish as a QuickSight **dashboard** (not just an analysis) and share
  with the course reviewers/teammates as needed.
