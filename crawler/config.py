"""Shared crawler configuration."""

import os

# Default output when not uploading to S3
LOCAL_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# S3 layout: raw/source=<site>/dt=<yyyy-mm-dd>/<run_id>.jsonl
S3_RAW_PREFIX_TEMPLATE = "raw/source={source}/dt={dt}/{run_id}.jsonl"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
}

REQUEST_TIMEOUT_SECONDS = 15
REQUEST_DELAY_SECONDS = 1.0  # polite delay between page/API requests

# Tiki's public (unofficial) listing API. Endpoint shape and field names are
# NOT officially documented and can change — verify with a live request
# (e.g. via browser devtools network tab on a category page) before relying
# on this for real data collection.
TIKI_LISTING_URL = "https://tiki.vn/api/personalish/v1/blocks/listings"

# category_id -> human-readable label, used for tagging + the dashboard.
# Find category ids from a category page URL on tiki.vn, e.g.
# https://tiki.vn/dien-thoai-may-tinh-bang/c1789 -> category_id = 1789
TIKI_CATEGORIES = {
    1789: "dien_thoai_may_tinh_bang",
    1846: "do_gia_dung",
    931: "thoi_trang_nu",
}

SOURCES = {
    "tiki": {
        "listing_url": TIKI_LISTING_URL,
        "categories": TIKI_CATEGORIES,
    },
    # "shopee": {...},   # add later for cross-source variety if needed
    # "lazada": {...},
}
