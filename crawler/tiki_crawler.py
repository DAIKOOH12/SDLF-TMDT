"""Crawler for Tiki.vn product listings, used to track potential-product
signals (sales volume, review growth, rating) over time.

Hits Tiki's public but unofficial listing API directly (JSON, no HTML
parsing needed) — much more stable than scraping rendered HTML, but the
response shape is undocumented and can change without notice. Inspect a
live response (browser devtools -> Network -> XHR on a category page)
before relying on the field names in RESPONSE_FIELDS below.

Each run captures one *snapshot* per product: the same product_id will
appear again in tomorrow's crawl with updated quantity_sold/review_count/
rating_average. The Glue jobs downstream rely on having multiple snapshots
per product over time to compute growth — this script does not dedupe
across days, only within a single run.
"""

import argparse
import logging
import time
from datetime import datetime, timezone

import requests

from config import (
    LOCAL_OUTPUT_DIR,
    REQUEST_DELAY_SECONDS,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT_SECONDS,
    SOURCES,
)
from utils import safe_get, upload_ndjson_s3, write_ndjson_local

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("tiki_crawler")

SOURCE_NAME = "tiki"
LISTING_URL = SOURCES[SOURCE_NAME]["listing_url"]
CATEGORIES = SOURCES[SOURCE_NAME]["categories"]

PAGE_SIZE = 40


def fetch_listing_page(category_id: int, page: int) -> dict | None:
    params = {
        "limit": PAGE_SIZE,
        "page": page,
        "category": category_id,
        "sort": "top_seller",  # bias toward products worth tracking for "potential"
    }
    try:
        resp = requests.get(
            LISTING_URL,
            params=params,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Failed to fetch category=%s page=%s: %s", category_id, page, exc)
        return None


def parse_product(item: dict, category_label: str) -> dict:
    crawled_at = datetime.now(timezone.utc)
    return {
        "product_id": str(item.get("id")),
        "source": SOURCE_NAME,
        "name": item.get("name"),
        "category": category_label,
        "price": item.get("price"),
        "original_price": item.get("list_price") or item.get("original_price"),
        "rating_average": item.get("rating_average"),
        "review_count": item.get("review_count"),
        "quantity_sold": safe_get(item, ["quantity_sold", "value"]),
        "seller_name": item.get("seller_name") or item.get("brand_name"),
        "badges_new": bool(item.get("badges_new")),
        "crawled_at": crawled_at.isoformat(),
        "crawl_date": crawled_at.strftime("%Y-%m-%d"),
    }


def crawl_category(category_id: int, category_label: str, pages: int) -> list[dict]:
    records = []
    for page in range(1, pages + 1):
        logger.info("Fetching %s page %d (category_id=%d)", category_label, page, category_id)
        payload = fetch_listing_page(category_id, page)
        if not payload:
            continue

        items = payload.get("data", [])
        logger.info("Got %d products", len(items))
        if not items:
            break  # ran out of pages for this category

        for item in items:
            try:
                records.append(parse_product(item, category_label))
            except Exception as exc:  # keep crawling even if one product is malformed
                logger.warning("Failed to parse product %s: %s", item.get("id"), exc)

        time.sleep(REQUEST_DELAY_SECONDS)

    return records


def crawl(pages_per_category: int) -> list[dict]:
    all_records = []
    for category_id, category_label in CATEGORIES.items():
        all_records.extend(crawl_category(category_id, category_label, pages_per_category))
    return all_records


def main():
    parser = argparse.ArgumentParser(description="Crawl Tiki.vn product listings")
    parser.add_argument("--pages", type=int, default=2, help="Pages to crawl per category")
    parser.add_argument("--upload", action="store_true", help="Upload output to S3 instead of local disk")
    parser.add_argument("--bucket", type=str, help="S3 bucket for raw output (required with --upload)")
    args = parser.parse_args()

    if args.upload and not args.bucket:
        parser.error("--bucket is required when using --upload")

    records = crawl(args.pages)
    logger.info("Crawled %d records across %d categories", len(records), len(CATEGORIES))

    if not records:
        logger.warning("No records scraped — check the Tiki listing API response shape")
        return

    if args.upload:
        location = upload_ndjson_s3(records, SOURCE_NAME, args.bucket)
    else:
        location = write_ndjson_local(records, SOURCE_NAME, LOCAL_OUTPUT_DIR)

    logger.info("Wrote output to %s", location)


if __name__ == "__main__":
    main()
