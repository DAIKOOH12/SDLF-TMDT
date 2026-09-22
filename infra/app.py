#!/usr/bin/env python3
import os

import aws_cdk as cdk

from infra.storage_stack import StorageStack
from infra.glue_stack import GlueStack
from infra.pipeline_stack import PipelineStack

app = cdk.App()

# Change to something globally-unique to you before deploying (S3 bucket
# names must be unique across all of AWS).
PREFIX = app.node.try_get_context("prefix") or "product-analytics-demo"

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "ap-southeast-1"),
)

storage = StorageStack(app, "ProductStorageStack", prefix=PREFIX, env=env)

glue_stack = GlueStack(
    app,
    "ProductGlueStack",
    raw_bucket=storage.raw_bucket,
    stage_bucket=storage.stage_bucket,
    analytics_bucket=storage.analytics_bucket,
    scripts_bucket=storage.scripts_bucket,
    env=env,
)
glue_stack.add_dependency(storage)

pipeline = PipelineStack(
    app,
    "ProductPipelineStack",
    raw_bucket=storage.raw_bucket,
    raw_to_stage_job=glue_stack.raw_to_stage_job,
    stage_to_analytics_job=glue_stack.stage_to_analytics_job,
    env=env,
)
pipeline.add_dependency(glue_stack)

app.synth()
