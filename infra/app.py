#!/usr/bin/env python3
import os
import aws_cdk as cdk
from stacks.pipeline_stack import PipelineStack

app = cdk.App()

PipelineStack(
    app,
    "CanchaPipelineStack",
    env=cdk.Environment(
        account=os.environ["CDK_DEFAULT_ACCOUNT"],
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
)

app.synth()
