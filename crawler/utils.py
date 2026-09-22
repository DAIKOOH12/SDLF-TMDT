"""I/O helpers shared across site-specific crawlers.

Tiki's listing API returns already-typed JSON fields (numeric price, rating,
etc.), so unlike a pure-HTML scrape there's little free-text parsing to do
here — these helpers focus on writing crawl output consistently to local
disk or S3.
"""

import json
import os
from datetime import datetime, timezone


def safe_get(d: dict, path: list[str], default=None):
    """Navigate a nested dict without raising on a missing key at any level.

    Tiki's JSON responses nest fields inconsistently across product types
    (e.g. quantity_sold is sometimes a nested {"value": N}, sometimes absent
    entirely) — use this instead of chained .get() calls.
    """
    current = d
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def write_ndjson_local(records: list[dict], source: str, output_dir: str) -> str:
    dt = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = datetime.now(timezone.utc).strftime("%H%M%S")
    out_dir = os.path.join(output_dir, f"source={source}", f"dt={dt}")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{run_id}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return out_path


def upload_ndjson_s3(records: list[dict], source: str, bucket: str) -> str:
    import boto3

    from config import S3_RAW_PREFIX_TEMPLATE

    dt = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = datetime.now(timezone.utc).strftime("%H%M%S")
    key = S3_RAW_PREFIX_TEMPLATE.format(source=source, dt=dt, run_id=run_id)

    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))
    return f"s3://{bucket}/{key}"
