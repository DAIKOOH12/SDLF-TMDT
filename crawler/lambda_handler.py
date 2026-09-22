"""EventBridge-scheduled Lambda entrypoint for the daily Tiki crawl.

Deploy this as the handler for a Lambda triggered by an EventBridge rule
(see infra/infra/pipeline_stack.py). Tiki's listing API is lightweight
JSON, so a full run across all configured categories comfortably fits
within Lambda's 15-minute timeout.
"""

import os

from tiki_crawler import crawl
from utils import upload_ndjson_s3

RAW_BUCKET = os.environ.get("RAW_BUCKET")
PAGES_PER_CATEGORY = int(os.environ.get("PAGES_PER_CATEGORY", "3"))


def handler(event, context):
    records = crawl(PAGES_PER_CATEGORY)
    if not records:
        return {"status": "no_records"}

    location = upload_ndjson_s3(records, "tiki", RAW_BUCKET)
    return {"status": "ok", "location": location, "count": len(records)}
