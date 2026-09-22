"""Train a classifier that predicts whether a product is "potential"
(demand accelerating) from the Analytics Iceberg table.

Label definition: within each (category, year_month) group, a product is
labeled potential=1 if its sold_growth_rate falls in the top quantile
(--top-quantile, default top 20%) for that group. This is a *relative*
definition on purpose — "top seller" means different absolute growth in
"Điện thoại" vs "Thời trang nữ", so ranking within category/time avoids
comparing unrelated categories directly.

Features: price, discount_pct, rating_average, review_count, review_growth,
category, source — i.e. everything observable *before* knowing next-period
sales, so the model is usable for forecasting on newly-seen snapshots.

Run locally against real AWS credentials, or adapt `main()` into a
SageMaker training script / Glue Python shell job — the feature engineering
and model code don't need to change either way.

Usage:
    python train_potential_model.py --database product_analytics --table products
"""

import argparse
import logging

import awswrangler as wr
import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_potential_model")

NUMERIC_FEATURES = ["price", "discount_pct", "rating_average", "review_count", "review_growth"]
CATEGORICAL_FEATURES = ["category", "source"]
LABEL = "is_potential"


def load_data(database: str, table: str, athena_output: str | None) -> pd.DataFrame:
    query = f"""
        SELECT category, source, price, discount_pct, rating_average,
               review_count, review_growth, sold_growth_rate, year_month
        FROM {table}
        WHERE sold_growth_rate IS NOT NULL
    """
    logger.info("Querying Athena: database=%s table=%s", database, table)
    return wr.athena.read_sql_query(sql=query, database=database, s3_output=athena_output)


def label_potential(df: pd.DataFrame, top_quantile: float) -> pd.DataFrame:
    """Flag the top `top_quantile` of sold_growth_rate within each
    (category, year_month) group as potential=1.
    """

    def flag_group(group: pd.DataFrame) -> pd.DataFrame:
        threshold = group["sold_growth_rate"].quantile(1 - top_quantile)
        group[LABEL] = (group["sold_growth_rate"] >= threshold).astype(int)
        return group

    return df.groupby(["category", "year_month"], group_keys=False).apply(flag_group)


def build_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ],
        remainder="passthrough",
    )

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=42,
    )

    return Pipeline(steps=[("preprocess", preprocessor), ("model", model)])


def main():
    parser = argparse.ArgumentParser(description="Train potential-product classifier")
    parser.add_argument("--database", required=True, help="Glue database, e.g. product_analytics")
    parser.add_argument("--table", required=True, help="Glue table, e.g. products")
    parser.add_argument("--athena-output", default=None, help="s3:// path for Athena query results")
    parser.add_argument("--top-quantile", type=float, default=0.2, help="Top fraction labeled potential")
    parser.add_argument("--output", default="potential_model.joblib", help="Path to save trained model")
    args = parser.parse_args()

    df = load_data(args.database, args.table, args.athena_output)
    logger.info("Loaded %d rows", len(df))

    feature_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    df = df.dropna(subset=feature_cols + ["sold_growth_rate"])

    df = label_potential(df, args.top_quantile)
    logger.info("Label balance:\n%s", df[LABEL].value_counts(normalize=True))

    X = df[feature_cols]
    y = df[LABEL]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    proba = pipeline.predict_proba(X_test)[:, 1]
    preds = pipeline.predict(X_test)

    logger.info("ROC-AUC=%.3f", roc_auc_score(y_test, proba))
    logger.info("\n%s", classification_report(y_test, preds))

    joblib.dump(pipeline, args.output)
    logger.info("Saved model to %s", args.output)


if __name__ == "__main__":
    main()
