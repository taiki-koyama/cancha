import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as actions,
    aws_codebuild as codebuild,
    aws_iam as iam,
    aws_ecr as ecr,
    aws_s3 as s3,
)
from constructs import Construct


class PipelineStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ----------------------------------------
        # 既存リソースの参照（他スタックでデプロイ済みのもの）
        # 実際の値は cdk.json の context に設定する
        # ----------------------------------------
        ecr_repo_name = self.node.try_get_context("ecrRepoName") or "cancha-backend"
        frontend_bucket_name = self.node.try_get_context("frontendBucketName")
        ecs_cluster_name = self.node.try_get_context("ecsClusterName")
        ecs_service_name = self.node.try_get_context("ecsServiceName")
        cf_distribution_id = self.node.try_get_context("cfDistributionId")
        github_owner = self.node.try_get_context("githubOwner")
        github_repo = self.node.try_get_context("githubRepo")
        # CodeStar Connections で作成した接続の ARN
        codestar_connection_arn = self.node.try_get_context("codestarConnectionArn")

        # ----------------------------------------
        # ECR リポジトリ参照
        # ----------------------------------------
        repo = ecr.Repository.from_repository_name(
            self, "EcrRepo", ecr_repo_name
        )

        # ----------------------------------------
        # S3 フロントエンドバケット参照
        # ----------------------------------------
        frontend_bucket = s3.Bucket.from_bucket_name(
            self, "FrontendBucket", frontend_bucket_name
        )

        # ----------------------------------------
        # CodeBuild：ビルド専用（テストなし）
        # ----------------------------------------
        build_project = codebuild.PipelineProject(
            self,
            "BuildProject",
            project_name="cancha-build",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,  # Docker ビルドに必要
            ),
            build_spec=codebuild.BuildSpec.from_source_filename("buildspec.yml"),
            environment_variables={
                "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(
                    value=self.account
                ),
                "AWS_REGION": codebuild.BuildEnvironmentVariable(
                    value=self.region
                ),
                "ECR_REPO_NAME": codebuild.BuildEnvironmentVariable(
                    value=ecr_repo_name
                ),
                "S3_BUCKET_FRONTEND": codebuild.BuildEnvironmentVariable(
                    value=frontend_bucket_name
                ),
                "ECS_CLUSTER": codebuild.BuildEnvironmentVariable(
                    value=ecs_cluster_name
                ),
                "ECS_SERVICE": codebuild.BuildEnvironmentVariable(
                    value=ecs_service_name
                ),
                "CF_DISTRIBUTION_ID": codebuild.BuildEnvironmentVariable(
                    value=cf_distribution_id
                ),
            },
        )

        # CodeBuild に必要な IAM 権限を付与
        repo.grant_pull_push(build_project)
        frontend_bucket.grant_read_write(build_project)

        build_project.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:UpdateService",
                    "ecs:DescribeServices",
                ],
                resources=["*"],
            )
        )
        build_project.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudfront:CreateInvalidation"],
                resources=["*"],
            )
        )

        # ----------------------------------------
        # パイプライン アーティファクト用バケット
        # ----------------------------------------
        artifact_bucket = s3.Bucket(
            self,
            "ArtifactBucket",
            bucket_name=f"cancha-pipeline-artifacts-{self.account}",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ----------------------------------------
        # CodePipeline
        # ----------------------------------------
        source_output = codepipeline.Artifact("SourceOutput")
        build_output = codepipeline.Artifact("BuildOutput")

        pipeline = codepipeline.Pipeline(
            self,
            "Pipeline",
            pipeline_name="cancha-pipeline",
            artifact_bucket=artifact_bucket,
            stages=[
                # Stage 1: GitHub からソース取得
                codepipeline.StageProps(
                    stage_name="Source",
                    actions=[
                        actions.CodeStarConnectionsSourceAction(
                            action_name="GitHub_Source",
                            owner=github_owner,
                            repo=github_repo,
                            branch="main",
                            connection_arn=codestar_connection_arn,
                            output=source_output,
                            trigger_on_push=True,
                        )
                    ],
                ),
                # Stage 2: ビルド＆デプロイ
                codepipeline.StageProps(
                    stage_name="Build",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="Build_and_Deploy",
                            project=build_project,
                            input=source_output,
                            outputs=[build_output],
                        )
                    ],
                ),
            ],
        )
