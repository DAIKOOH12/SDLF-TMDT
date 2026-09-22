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

# Confirmed against a live DevTools capture on 2026-09-22:
#   https://tiki.vn/api/personalish/v1/blocks/listings
#     ?limit=40&include=advertisement&aggregations=2
#     &version=home-personalized&trackity_id=<uuid>
#     &category=<id>&page=<n>&urlKey=<slug>
# This is an unofficial API — field names/params can change; re-verify via
# devtools if the crawler starts returning empty/malformed data.
TIKI_LISTING_URL = "https://tiki.vn/api/personalish/v1/blocks/listings"

# category_id -> {label used in our own data, url_key as it appears on tiki.vn}
# Only "dien_thoai_may_tinh_bang" (1789) has been verified against a live
# request so far. Verify the other two the same way (open the category page,
# check the "listings" request in DevTools) before trusting their data.
TIKI_CATEGORIES = {
    1789: {"label": "dien_thoai_may_tinh_bang", "url_key": "dien-thoai-may-tinh-bang"},
    1846: {"label": "do_gia_dung", "url_key": "do-gia-dung"},
    931: {"label": "thoi_trang_nu", "url_key": "thoi-trang-nu"},
}

SOURCES = {
    "tiki": {
        "listing_url": TIKI_LISTING_URL,
        "categories": TIKI_CATEGORIES,
    },
    # "shopee": {...},   # add later for cross-source variety if needed
    # "lazada": {...},
}
