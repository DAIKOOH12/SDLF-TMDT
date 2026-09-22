from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_athena as athena
from aws_cdk import aws_s3 as s3
from constructs import Construct


class StorageStack(Stack):
    """S3 buckets for the raw / stage / analytics zones plus supporting
    buckets for Glue job scripts and Athena query results.

    Buckets use RETAIN removal policy since this is a data lake — destroying
    the CDK stack should not silently delete scraped/curated data. Empty the
    buckets manually (or switch to DESTROY for a throwaway demo) if you need
    `cdk destroy` to fully clean up.
    """

    def __init__(self, scope: Construct, construct_id: str, *, prefix: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        common_kwargs = dict(
            removal_policy=RemovalPolicy.RETAIN,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
        )

        self.raw_bucket = s3.Bucket(self, "RawBucket", bucket_name=f"{prefix}-raw", **common_kwargs)
        self.stage_bucket = s3.Bucket(self, "StageBucket", bucket_name=f"{prefix}-stage", **common_kwargs)
        self.analytics_bucket = s3.Bucket(
            self, "AnalyticsBucket", bucket_name=f"{prefix}-analytics", **common_kwargs
        )
        self.scripts_bucket = s3.Bucket(
            self, "ScriptsBucket", bucket_name=f"{prefix}-scripts", **common_kwargs
        )
        self.athena_results_bucket = s3.Bucket(
            self, "AthenaResultsBucket", bucket_name=f"{prefix}-athena-results", **common_kwargs
        )

        self.athena_workgroup_name = f"{prefix}-athena"
        athena.CfnWorkGroup(
            self,
            "AthenaWorkGroup",
            name=self.athena_workgroup_name,
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=f"s3://{self.athena_results_bucket.bucket_name}/"
                ),
                enforce_work_group_configuration=True,
            ),
        )
