"""Upload the Glue PySpark scripts to the CDK-managed scripts bucket.

infra/infra/glue_stack.py defines Glue Jobs that reference
s3://<prefix>-scripts/scripts/{raw_to_stage,stage_to_analytics}.py but does
not upload the files itself — that used to be handled by CDK's
`BucketDeployment` construct, which was removed because it currently fails
on some accounts/regions with a Python 3.9/urllib3 incompatibility inside
AWS's own bundled awscli Lambda layer (an upstream CDK bug).

Run this once after `cdk deploy`, and again any time you edit a script
under glue_jobs/clean_transform/ — Glue always reads the script fresh from
S3 each time a job run starts, so there's no need to redeploy the CDK stack
for script-only changes.

Usage:
    python upload_scripts.py --bucket <prefix>-scripts
"""

import argparse
from pathlib import Path

import boto3

SCRIPTS_DIR = Path(__file__).resolve().parent / "clean_transform"
SCRIPT_FILES = ["raw_to_stage.py", "stage_to_analytics.py"]


def main():
    parser = argparse.ArgumentParser(description="Upload Glue job scripts to S3")
    parser.add_argument("--bucket", required=True, help="Scripts bucket, e.g. <prefix>-scripts")
    args = parser.parse_args()

    s3 = boto3.client("s3")
    for filename in SCRIPT_FILES:
        local_path = SCRIPTS_DIR / filename
        key = f"scripts/{filename}"
        print(f"Uploading {local_path} -> s3://{args.bucket}/{key}")
        s3.upload_file(str(local_path), args.bucket, key)

    print("Done.")


if __name__ == "__main__":
    main()
