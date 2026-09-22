from aws_cdk import Stack
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3_deploy
from constructs import Construct


class GlueStack(Stack):
    """Glue Data Catalog databases + the two PySpark/Iceberg jobs
    (raw_to_stage, stage_to_analytics) and the IAM role they run under.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        raw_bucket: s3.Bucket,
        stage_bucket: s3.Bucket,
        analytics_bucket: s3.Bucket,
        scripts_bucket: s3.Bucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.stage_database_name = "product_stage"
        self.analytics_database_name = "product_analytics"

        glue.CfnDatabase(
            self,
            "StageDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(name=self.stage_database_name),
        )
        glue.CfnDatabase(
            self,
            "AnalyticsDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(name=self.analytics_database_name),
        )

        # Upload the PySpark scripts from glue_jobs/clean_transform to the
        # scripts bucket so the CfnJob ScriptLocation stays in sync with repo code.
        deployment = s3_deploy.BucketDeployment(
            self,
            "GlueScriptsDeployment",
            sources=[s3_deploy.Source.asset("../glue_jobs/clean_transform")],
            destination_bucket=scripts_bucket,
            destination_key_prefix="scripts",
        )

        self.glue_role = iam.Role(
            self,
            "GlueJobRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole"),
            ],
        )
        raw_bucket.grant_read(self.glue_role)
        stage_bucket.grant_read_write(self.glue_role)
        analytics_bucket.grant_read_write(self.glue_role)
        scripts_bucket.grant_read(self.glue_role)

        common_default_args = {
            "--job-language": "python",
            "--datalake-formats": "iceberg",
            "--conf": (
                "spark.sql.extensions=org.apache.iceberg.spark.extensions."
                "IcebergSparkSessionExtensions "
                "--conf spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog "
                "--conf spark.sql.catalog.glue_catalog.warehouse=s3://"
                f"{stage_bucket.bucket_name}/ "
                "--conf spark.sql.catalog.glue_catalog.catalog-impl="
                "org.apache.iceberg.aws.glue.GlueCatalog "
                "--conf spark.sql.catalog.glue_catalog.io-impl="
                "org.apache.iceberg.aws.s3.S3FileIO"
            ),
            "--enable-metrics": "true",
            "--enable-continuous-cloudwatch-log": "true",
        }

        self.raw_to_stage_job = glue.CfnJob(
            self,
            "RawToStageJob",
            name="raw-to-stage",
            role=self.glue_role.role_arn,
            glue_version="4.0",
            worker_type="G.1X",
            number_of_workers=5,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=f"s3://{scripts_bucket.bucket_name}/scripts/raw_to_stage.py",
            ),
            default_arguments={
                **common_default_args,
                "--RAW_S3_PATH": f"s3://{raw_bucket.bucket_name}/raw/",
                "--STAGE_DATABASE": self.stage_database_name,
                "--STAGE_TABLE": "products",
                "--WAREHOUSE_PATH": f"s3://{stage_bucket.bucket_name}/",
            },
        )
        self.raw_to_stage_job.node.add_dependency(deployment)

        self.stage_to_analytics_job = glue.CfnJob(
            self,
            "StageToAnalyticsJob",
            name="stage-to-analytics",
            role=self.glue_role.role_arn,
            glue_version="4.0",
            worker_type="G.1X",
            number_of_workers=5,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=f"s3://{scripts_bucket.bucket_name}/scripts/stage_to_analytics.py",
            ),
            default_arguments={
                **common_default_args,
                "--STAGE_DATABASE": self.stage_database_name,
                "--STAGE_TABLE": "products",
                "--ANALYTICS_DATABASE": self.analytics_database_name,
                "--ANALYTICS_TABLE": "products",
                "--WAREHOUSE_PATH": f"s3://{analytics_bucket.bucket_name}/",
            },
        )
        self.stage_to_analytics_job.node.add_dependency(deployment)
