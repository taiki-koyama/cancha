import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_elasticloadbalancingv2 as elbv2,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_autoscaling as autoscaling,
    aws_iam as iam,
    RemovalPolicy,
    CfnOutput,
)
from constructs import Construct
from stacks.stateful_stack import StatefulStack


class StatelessStack(Stack):
    """
    削除・再作成が自由なリソース一式。
    - ECS クラスター（EC2 t3.micro）
    - FastAPI タスク定義 & サービス
    - ALB
    - S3（フロントエンド配信）
    - CloudFront
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        stateful: StatefulStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ----------------------------------------
        # ECS クラスター（EC2 起動タイプ・t3.micro）
        # ----------------------------------------
        cluster = ecs.Cluster(
            self,
            "Cluster",
            cluster_name="cancha-cluster",
            vpc=stateful.vpc,
        )

        # ECS インスタンスロール
        ecs_instance_role = iam.Role(
            self, "EcsInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonEC2ContainerServiceforEC2Role"
                ),
            ],
        )

        # Launch Template（Launch Configuration は新規アカウントで利用不可）
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            f"echo ECS_CLUSTER={cluster.cluster_name} >> /etc/ecs/ecs.config"
        )
        launch_template = ec2.LaunchTemplate(
            self, "EcsLt",
            instance_type=ec2.InstanceType("t3.micro"),
            machine_image=ecs.EcsOptimizedImage.amazon_linux2(),
            security_group=stateful.ecs_sg,
            role=ecs_instance_role,
            user_data=user_data,
        )

        asg = autoscaling.AutoScalingGroup(
            self, "DefaultAsg",
            vpc=stateful.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            launch_template=launch_template,
            min_capacity=1,
            max_capacity=1,
        )

        capacity_provider = ecs.AsgCapacityProvider(
            self, "CapacityProvider",
            auto_scaling_group=asg,
            enable_managed_termination_protection=False,
        )
        cluster.add_asg_capacity_provider(capacity_provider)

        # ----------------------------------------
        # FastAPI タスク定義
        # ----------------------------------------
        # ECS タスク実行ロール（ECR pull・Secrets Manager 読み取りに必要）
        execution_role = iam.Role(
            self,
            "TaskExecutionRole",
            role_name="cancha-task-execution-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ],
        )
        stateful.ecr_repo.grant_pull(execution_role)

        task_def = ecs.Ec2TaskDefinition(
            self,
            "TaskDef",
            family="cancha-backend",
            network_mode=ecs.NetworkMode.BRIDGE,
            execution_role=execution_role,
        )

        # DB 接続情報を Secrets Manager から取得
        db_secret = stateful.db.secret

        container = task_def.add_container(
            "FastApiContainer",
            container_name="cancha-backend",
            # 初回デプロイ用プレースホルダー。CodePipeline が ECR イメージに更新する
            image=ecs.ContainerImage.from_registry("amazon/amazon-ecs-sample"),
            memory_reservation_mib=400,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="cancha-backend"),
            environment={
                "AWS_REGION": self.region,
                "S3_VIDEO_BUCKET": stateful.video_bucket.bucket_name,
            },
            secrets={
                "DB_HOST": ecs.Secret.from_secrets_manager(db_secret, "host"),
                "DB_PORT": ecs.Secret.from_secrets_manager(db_secret, "port"),
                "DB_NAME": ecs.Secret.from_secrets_manager(db_secret, "dbname"),
                "DB_USER": ecs.Secret.from_secrets_manager(db_secret, "username"),
                "DB_PASS": ecs.Secret.from_secrets_manager(db_secret, "password"),
            },
        )
        container.add_port_mappings(ecs.PortMapping(container_port=8000))

        # ECS タスクに S3・Bedrock・Secrets Manager のアクセス権を付与
        stateful.video_bucket.grant_read_write(task_def.task_role)
        db_secret.grant_read(task_def.task_role)
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=["*"],
            )
        )

        # ----------------------------------------
        # ALB
        # ----------------------------------------
        alb = elbv2.ApplicationLoadBalancer(
            self,
            "Alb",
            load_balancer_name="cancha-alb",
            vpc=stateful.vpc,
            internet_facing=True,
            security_group=stateful.alb_sg,
        )

        # ----------------------------------------
        # ECS サービス
        # ----------------------------------------
        service = ecs.Ec2Service(
            self,
            "Service",
            service_name="cancha-service",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            capacity_provider_strategies=[
                ecs.CapacityProviderStrategy(
                    capacity_provider=capacity_provider.capacity_provider_name,
                    weight=1,
                )
            ],
        )

        listener = alb.add_listener("Listener", port=80)
        listener.add_targets(
            "EcsTarget",
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service],
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=cdk.Duration.seconds(30),
            ),
        )

        # ----------------------------------------
        # S3：フロントエンド配信バケット
        # ----------------------------------------
        frontend_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"cancha-frontend-{self.account}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ----------------------------------------
        # CloudFront
        # ----------------------------------------
        oac = cloudfront.S3OriginAccessControl(
            self, "OAC", signing=cloudfront.Signing.SIGV4_NO_OVERRIDE
        )

        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment="cancha-cdn",
            default_behavior=cloudfront.BehaviorOptions(
                # デフォルト：フロントエンド（React）
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    frontend_bucket, origin_access_control=oac
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            additional_behaviors={
                # /api/* → ALB（FastAPI）
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.LoadBalancerV2Origin(
                        alb,
                        protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
                # /videos/* → S3（動画）
                "/videos/*": cloudfront.BehaviorOptions(
                    origin=origins.S3BucketOrigin.with_origin_access_control(
                        stateful.video_bucket, origin_access_control=oac
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                ),
            },
        )

        # ----------------------------------------
        # Outputs
        # ----------------------------------------
        CfnOutput(self, "CloudFrontUrl",
            value=f"https://{distribution.domain_name}",
            description="CloudFront URL")
        CfnOutput(self, "AlbDnsName",
            value=alb.load_balancer_dns_name,
            description="ALB DNS name")
        CfnOutput(self, "FrontendBucketName",
            value=frontend_bucket.bucket_name,
            description="Frontend S3 bucket name")
        CfnOutput(self, "EcrRepoUri",
            value=stateful.ecr_repo.repository_uri,
            description="ECR repository URI")
