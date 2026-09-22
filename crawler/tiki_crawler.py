"""Crawler for Tiki.vn product listings, used to track potential-product
signals (sales volume, review growth, rating) over time.

Hits Tiki's public but unofficial listing API directly (JSON, no HTML
parsing needed). Endpoint and field names were confirmed against a live
DevTools capture on 2026-09-22 for category 1789 (Điện thoại - Máy tính
bảng) — see config.py for the exact URL/params. This is undocumented and
can change without notice; re-check via devtools if data stops looking
right.

Each run captures one *snapshot* per product: the same product_id will
appear again in tomorrow's crawl with updated quantity_sold/review_count/
rating_average. The Glue jobs downstream rely on having multiple snapshots
per product over time to compute growth — this script does not dedupe
across days, only within a single run.
"""

import argparse
import logging
import time
import uuid
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
TRACKITY_ID = str(uuid.uuid4())  # one session id per crawler run is enough


def fetch_listing_page(category_id: int, url_key: str, page: int) -> dict | None:
    params = {
        "limit": PAGE_SIZE,
        "include": "advertisement",
        "aggregations": 2,
        "version": "home-personalized",
        "trackity_id": TRACKITY_ID,
        "category": category_id,
        "page": page,
        "urlKey": url_key,
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

    quantity_sold = safe_get(item, ["quantity_sold", "value"])
    if quantity_sold is None:
        # Ads/new listings often omit quantity_sold entirely — the amplitude
        # block is more consistently present (defaults to 0 rather than null).
        quantity_sold = safe_get(item, ["visible_impression_info", "amplitude", "all_time_quantity_sold"], 0)

    original_price = item.get("original_price") or item.get("price")
    seller_type = safe_get(item, ["visible_impression_info", "amplitude", "seller_type"])

    return {
        "product_id": str(item.get("id")),
        "source": SOURCE_NAME,
        "name": item.get("name"),
        "category": category_label,
        "brand_name": item.get("brand_name"),
        "price": item.get("price"),
        "original_price": original_price,
        "discount_rate": item.get("discount_rate"),
        "rating_average": item.get("rating_average"),
        "review_count": item.get("review_count"),
        "quantity_sold": quantity_sold,
        "seller_id": item.get("seller_id"),
        "is_official_store": seller_type == "OFFICIAL_STORE",
        "crawled_at": crawled_at.isoformat(),
        "crawl_date": crawled_at.strftime("%Y-%m-%d"),
    }


def crawl_category(category_id: int, category_label: str, url_key: str, pages: int) -> list[dict]:
    records = []
    for page in range(1, pages + 1):
        logger.info("Fetching %s page %d (category_id=%d)", category_label, page, category_id)
        payload = fetch_listing_page(category_id, url_key, page)
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
    for category_id, meta in CATEGORIES.items():
        all_records.extend(
            crawl_category(category_id, meta["label"], meta["url_key"], pages_per_category)
        )
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
