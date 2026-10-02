"""Empty and delete the 5 S3 buckets this project's CDK app creates.

Why this exists: the buckets use RemovalPolicy.RETAIN (see storage_stack.py)
so a real crawl history is never lost to an accidental `cdk destroy`. That
same safety net means `cdk destroy --all` leaves the buckets behind as
*orphans* — and since they're versioned, a plain empty bucket + delete
doesn't work either. The next `cdk deploy` then fails with
"bucket already exists" (bucket names are globally unique).

This script does the full purge (every object version + delete marker,
then the bucket itself) so you can tear down and redeploy from a clean
slate as many times as you need while iterating/testing.

DESTRUCTIVE: permanently deletes everything in these buckets. Only run this
when you actually want to wipe the demo environment — never against a
bucket holding data you still need.

Usage:
    python reset_buckets.py --prefix product-analytics-demo
    python reset_buckets.py --prefix product-analytics-demo --region ap-southeast-1
"""

import argparse

import boto3
from botocore.exceptions import ClientError

SUFFIXES = ["raw", "stage", "analytics", "scripts", "athena-results"]


def main():
    parser = argparse.ArgumentParser(description="Empty and delete this project's S3 buckets")
    parser.add_argument("--prefix", required=True, help="Same PREFIX value as in infra/app.py")
    parser.add_argument("--region", default="ap-southeast-1")
    parser.add_argument(
        "--yes", action="store_true", help="Skip the confirmation prompt (for scripted/CI use)"
    )
    args = parser.parse_args()

    bucket_names = [f"{args.prefix}-{suffix}" for suffix in SUFFIXES]

    print("This will PERMANENTLY delete all data in:")
    for name in bucket_names:
        print(f"  - {name}")
    if not args.yes:
        confirm = input("Type 'yes' to continue: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return

    s3 = boto3.resource("s3", region_name=args.region)

    for name in bucket_names:
        bucket = s3.Bucket(name)
        try:
            print(f"Emptying {name} (all versions + delete markers)...")
            bucket.object_versions.all().delete()
            print(f"Deleting bucket {name}...")
            bucket.delete()
            print(f"Done: {name}")
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "NoSuchBucket":
                print(f"Skipped (already gone): {name}")
            else:
                raise

    print("Reset complete. Safe to `cdk deploy --all` again.")


if __name__ == "__main__":
    main()
