"""Glue job: Stage Iceberg table (product snapshot history) -> Analytics
Iceberg table (growth metrics per snapshot).

"Potential" is not visible from a single snapshot — it's a *rate of change*.
This job compares each snapshot to the product's previous snapshot (via a
window function ordered by crawl_date) to derive growth signals, then adds a
simple composite `potential_score` for quick dashboard ranking. The ML step
(ml/train_potential_model.py) builds a proper trained model on top of these
same features instead of relying on the heuristic score alone.

Job parameters:
  --STAGE_DATABASE       product_stage
  --STAGE_TABLE          products
  --ANALYTICS_DATABASE   product_analytics
  --ANALYTICS_TABLE      products
  --WAREHOUSE_PATH       s3://<prefix>-analytics/
"""

import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.window import Window

args = getResolvedOptions(
    sys.argv,
    [
        "JOB_NAME",
        "STAGE_DATABASE",
        "STAGE_TABLE",
        "ANALYTICS_DATABASE",
        "ANALYTICS_TABLE",
        "WAREHOUSE_PATH",
    ],
)

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

STAGE_FQN = f"glue_catalog.{args['STAGE_DATABASE']}.{args['STAGE_TABLE']}"
ANALYTICS_DB = args["ANALYTICS_DATABASE"]
ANALYTICS_TABLE = args["ANALYTICS_TABLE"]
ANALYTICS_FQN = f"glue_catalog.{ANALYTICS_DB}.{ANALYTICS_TABLE}"


def ensure_analytics_table():
    spark.sql(f"CREATE DATABASE IF NOT EXISTS glue_catalog.{ANALYTICS_DB}")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {ANALYTICS_FQN} (
            product_id           STRING,
            source                STRING,
            name                  STRING,
            category              STRING,
            brand_name            STRING,
            is_official_store     BOOLEAN,
            price                 DOUBLE,
            original_price        DOUBLE,
            discount_pct          DOUBLE,
            rating_average        DOUBLE,
            review_count          INT,
            quantity_sold         INT,
            days_since_prev       INT,
            sold_growth           INT,
            sold_growth_rate      DOUBLE,
            review_growth         INT,
            rating_change         DOUBLE,
            potential_score       DOUBLE,
            crawl_date            DATE,
            year_month            STRING,
            crawled_at            TIMESTAMP
        )
        USING iceberg
        PARTITIONED BY (year_month)
        LOCATION '{args["WAREHOUSE_PATH"]}{ANALYTICS_TABLE}'
        """
    )


def enrich(df):
    by_product_over_time = Window.partitionBy("product_id").orderBy("crawl_date")

    df = df.withColumn("prev_crawl_date", F.lag("crawl_date").over(by_product_over_time))
    df = df.withColumn("prev_quantity_sold", F.lag("quantity_sold").over(by_product_over_time))
    df = df.withColumn("prev_review_count", F.lag("review_count").over(by_product_over_time))
    df = df.withColumn("prev_rating_average", F.lag("rating_average").over(by_product_over_time))

    df = df.withColumn(
        "days_since_prev", F.datediff(F.col("crawl_date"), F.col("prev_crawl_date"))
    )
    df = df.withColumn(
        "sold_growth",
        F.when(
            F.col("prev_quantity_sold").isNotNull(),
            F.col("quantity_sold") - F.col("prev_quantity_sold"),
        ),
    )
    df = df.withColumn(
        "sold_growth_rate",
        F.when(
            (F.col("days_since_prev").isNotNull()) & (F.col("days_since_prev") > 0),
            F.col("sold_growth") / F.col("days_since_prev"),
        ),
    )
    df = df.withColumn(
        "review_growth",
        F.when(
            F.col("prev_review_count").isNotNull(),
            F.col("review_count") - F.col("prev_review_count"),
        ),
    )
    df = df.withColumn(
        "rating_change",
        F.when(
            F.col("prev_rating_average").isNotNull(),
            F.col("rating_average") - F.col("prev_rating_average"),
        ),
    )

    # Tiki already provides discount_rate as a 0-100 percentage; fall back to
    # computing it from price/original_price only if that field is missing.
    df = df.withColumn(
        "discount_pct",
        F.when(F.col("discount_rate").isNotNull(), F.col("discount_rate") / F.lit(100.0))
        .when(
            (F.col("original_price").isNotNull()) & (F.col("original_price") > 0),
            (F.col("original_price") - F.col("price")) / F.col("original_price"),
        )
        .otherwise(F.lit(0.0)),
    )

    # Heuristic ranking score for the dashboard — a normalized blend of sold
    # and review growth rate, weighted toward sold_growth_rate since that's
    # the strongest direct signal of demand. The ML model uses the raw
    # features (not this score) as inputs rather than treating it as ground
    # truth.
    df = df.withColumn(
        "potential_score",
        F.coalesce(F.col("sold_growth_rate"), F.lit(0.0)) * F.lit(0.7)
        + F.coalesce(F.col("review_growth"), F.lit(0.0)) * F.lit(0.3),
    )

    df = df.withColumn("year_month", F.date_format("crawl_date", "yyyy-MM"))

    return df.select(
        "product_id",
        "source",
        "name",
        "category",
        "brand_name",
        "is_official_store",
        "price",
        "original_price",
        "discount_pct",
        "rating_average",
        "review_count",
        "quantity_sold",
        "days_since_prev",
        "sold_growth",
        "sold_growth_rate",
        "review_growth",
        "rating_change",
        "potential_score",
        "crawl_date",
        "year_month",
        "crawled_at",
    )


def main():
    ensure_analytics_table()

    stage_df = spark.table(STAGE_FQN)
    enriched_df = enrich(stage_df)

    enriched_df.createOrReplaceTempView("analytics_batch")

    spark.sql(
        f"""
        MERGE INTO {ANALYTICS_FQN} t
        USING analytics_batch s
        ON t.product_id = s.product_id AND t.crawl_date = s.crawl_date
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )

    job.commit()


if __name__ == "__main__":
    main()
