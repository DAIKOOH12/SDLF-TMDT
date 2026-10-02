import os

from aws_cdk import Duration, Stack
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_glue as glue
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

# Prebuilt by crawler/build_lambda.py (plain `pip install -t` + file copy —
# no Docker image bundling). Run that script before `cdk deploy`, and again
# any time crawler/ changes, since this stack just packages whatever is
# already sitting in this folder.
LAMBDA_PACKAGE_DIR = "lambda_build/crawler"


class PipelineStack(Stack):
    """Crawler Lambda (on an EventBridge schedule) + Step Functions state
    machine that chains the two Glue jobs: raw_to_stage -> stage_to_analytics.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        prefix: str,
        raw_bucket: s3.Bucket,
        raw_to_stage_job: glue.CfnJob,
        stage_to_analytics_job: glue.CfnJob,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if not os.path.isdir(LAMBDA_PACKAGE_DIR):
            raise RuntimeError(
                f"'{LAMBDA_PACKAGE_DIR}' not found. Run "
                "`python ../crawler/build_lambda.py` first (see docs/RUNBOOK.md)."
            )

        crawler_fn = lambda_.Function(
            self,
            "CrawlerFunction",
            function_name=f"{prefix}-crawler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_handler.handler",
            code=lambda_.Code.from_asset(LAMBDA_PACKAGE_DIR),
            timeout=Duration.minutes(10),
            memory_size=512,
            environment={
                "RAW_BUCKET": raw_bucket.bucket_name,
                "PAGES_PER_CATEGORY": "3",
            },
        )
        raw_bucket.grant_write(crawler_fn)

        raw_to_stage_task = tasks.GlueStartJobRun(
            self,
            "RawToStage",
            glue_job_name=raw_to_stage_job.name,
            integration_pattern=sfn.IntegrationPattern.RUN_JOB,
        )
        stage_to_analytics_task = tasks.GlueStartJobRun(
            self,
            "StageToAnalytics",
            glue_job_name=stage_to_analytics_job.name,
            integration_pattern=sfn.IntegrationPattern.RUN_JOB,
        )

        definition = raw_to_stage_task.next(stage_to_analytics_task)

        self.state_machine = sfn.StateMachine(
            self,
            "ProductPipeline",
            state_machine_name="product-pipeline",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.hours(2),
        )

        # Crawl daily at 18:00 UTC (~01:00 ICT); trigger the crawler only —
        # kick off the state machine separately (console/CLI/EventBridge)
        # once you're ready to also automate the clean/transform stage.
        events.Rule(
            self,
            "DailyCrawlSchedule",
            rule_name=f"{prefix}-daily-crawl",
            schedule=events.Schedule.cron(hour="18", minute="0"),
            targets=[targets.LambdaFunction(crawler_fn)],
        )
