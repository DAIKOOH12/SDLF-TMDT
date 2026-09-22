"""Glue job: S3 Raw (NDJSON) -> Stage Iceberg table.

Responsibilities: schema validation/typing, basic cleaning, and dedup.

Unlike a "current state" table, Stage here is a **snapshot history**: the
same product_id is expected to reappear on every crawl run with updated
quantity_sold/review_count/rating_average. We keep one row per
(product_id, crawl_date) rather than collapsing to the latest value —
downstream (stage_to_analytics.py) needs multiple snapshots per product to
compute growth, which is the whole point of tracking "potential" products.
Dedup only guards against the same product being crawled twice on the same
day (e.g. a retried run).

Job parameters (set via Glue job arguments / Step Functions input):
  --RAW_S3_PATH        s3://<prefix>-raw/raw/
  --STAGE_DATABASE     product_stage
  --STAGE_TABLE        products
  --WAREHOUSE_PATH     s3://<prefix>-stage/
"""

import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

args = getResolvedOptions(
    sys.argv,
    ["JOB_NAME", "RAW_S3_PATH", "STAGE_DATABASE", "STAGE_TABLE", "WAREHOUSE_PATH"],
)

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

STAGE_DB = args["STAGE_DATABASE"]
STAGE_TABLE = args["STAGE_TABLE"]
STAGE_FQN = f"glue_catalog.{STAGE_DB}.{STAGE_TABLE}"

RAW_SCHEMA = StructType(
    [
        StructField("product_id", StringType()),
        StructField("source", StringType()),
        StructField("name", StringType()),
        StructField("category", StringType()),
        StructField("price", DoubleType()),
        StructField("original_price", DoubleType()),
        StructField("rating_average", DoubleType()),
        StructField("review_count", IntegerType()),
        StructField("quantity_sold", IntegerType()),
        StructField("seller_name", StringType()),
        StructField("badges_new", BooleanType()),
        StructField("crawled_at", StringType()),
        StructField("crawl_date", StringType()),
    ]
)


def ensure_stage_table():
    spark.sql(f"CREATE DATABASE IF NOT EXISTS glue_catalog.{STAGE_DB}")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {STAGE_FQN} (
            product_id      STRING,
            source          STRING,
            name            STRING,
            category        STRING,
            price           DOUBLE,
            original_price  DOUBLE,
            rating_average  DOUBLE,
            review_count    INT,
            quantity_sold   INT,
            seller_name     STRING,
            badges_new      BOOLEAN,
            crawl_date      DATE,
            crawled_at      TIMESTAMP
        )
        USING iceberg
        PARTITIONED BY (source)
        LOCATION '{args["WAREHOUSE_PATH"]}{STAGE_TABLE}'
        """
    )


def clean(df):
    df = df.withColumn("crawled_at", F.to_timestamp("crawled_at"))
    df = df.withColumn("crawl_date", F.to_date("crawl_date"))

    # drop rows missing the fields growth metrics depend on downstream
    df = df.filter(F.col("product_id").isNotNull())
    df = df.filter(F.col("price").isNotNull() & (F.col("price") > 0))
    df = df.filter(F.col("crawl_date").isNotNull())

    # quantity_sold/review_count are sometimes absent for brand-new listings —
    # treat missing as 0 rather than dropping the row, since a 0 baseline is
    # meaningful for growth calculations (a product going from 0 to N sold is
    # exactly the "potential" signal we want to catch).
    df = df.withColumn("quantity_sold", F.coalesce(F.col("quantity_sold"), F.lit(0)))
    df = df.withColumn("review_count", F.coalesce(F.col("review_count"), F.lit(0)))

    df = df.withColumn("name", F.trim(F.col("name")))
    df = df.withColumn("category", F.trim(F.col("category")))

    return df.select(
        "product_id",
        "source",
        "name",
        "category",
        "price",
        "original_price",
        "rating_average",
        "review_count",
        "quantity_sold",
        "seller_name",
        "badges_new",
        "crawl_date",
        "crawled_at",
    )


def main():
    ensure_stage_table()

    raw_df = spark.read.schema(RAW_SCHEMA).json(args["RAW_S3_PATH"])
    cleaned_df = clean(raw_df)

    # dedup: at most one row per (product_id, crawl_date), keep the latest
    # crawl timestamp of that day
    cleaned_df = (
        cleaned_df.withColumn(
            "_rn",
            F.row_number().over(
                Window.partitionBy("product_id", "crawl_date").orderBy(F.col("crawled_at").desc())
            ),
        )
        .filter(F.col("_rn") == 1)
        .drop("_rn")
    )

    cleaned_df.createOrReplaceTempView("staging_batch")

    spark.sql(
        f"""
        MERGE INTO {STAGE_FQN} t
        USING staging_batch s
        ON t.product_id = s.product_id AND t.crawl_date = s.crawl_date
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )

    job.commit()


if __name__ == "__main__":
    main()
