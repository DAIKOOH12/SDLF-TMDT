from aws_cdk import Duration, Stack
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_glue as glue
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct


class PipelineStack(Stack):
    """Crawler Lambda (on an EventBridge schedule) + Step Functions state
    machine that chains the two Glue jobs: raw_to_stage -> stage_to_analytics.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        raw_bucket: s3.Bucket,
        raw_to_stage_job: glue.CfnJob,
        stage_to_analytics_job: glue.CfnJob,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        crawler_fn = lambda_.Function(
            self,
            "CrawlerFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_handler.handler",
            code=lambda_.Code.from_asset(
                "../crawler",
                bundling={
                    "image": lambda_.Runtime.PYTHON_3_12.bundling_image,
                    "command": [
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                },
            ),
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
            schedule=events.Schedule.cron(hour="18", minute="0"),
            targets=[targets.LambdaFunction(crawler_fn)],
        )
