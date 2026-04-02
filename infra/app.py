#!/usr/bin/env python3
import os
import aws_cdk as cdk
from stacks.pipeline_stack import PipelineStack
from stacks.infra_stack import InfraStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ["CDK_DEFAULT_ACCOUNT"],
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

# インフラ一式（VPC・ECS・RDS・S3・CloudFront）
# POC のため単一スタック構成。本番化時に Stateful / Stateless に分割する。
InfraStack(app, "CanchaInfraStack", env=env)

# CI/CD パイプライン
PipelineStack(app, "CanchaPipelineStack", env=env)

app.synth()
