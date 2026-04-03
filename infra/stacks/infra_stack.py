import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_autoscaling as autoscaling,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_rds as rds,
    aws_ecr as ecr,
    aws_iam as iam,
    RemovalPolicy,
    CfnOutput,
)
from constructs import Construct


class InfraStack(Stack):
    """
    cancha インフラ一式。
    POC のため単一スタック構成。
    本番化する際に Stateful / Stateless に分割する。
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ----------------------------------------
        # VPC
        # ----------------------------------------
        vpc = ec2.Vpc(
            self, "Vpc",
            vpc_name="cancha-vpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # ----------------------------------------
        # セキュリティグループ
        # ----------------------------------------
        alb_sg = ec2.SecurityGroup(
            self, "AlbSg",
            vpc=vpc,
            security_group_name="cancha-alb-sg",
            description="ALB inbound HTTP",
        )
        alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80))

        ecs_sg = ec2.SecurityGroup(
            self, "EcsSg",
            vpc=vpc,
            security_group_name="cancha-ecs-sg",
            description="ECS tasks: from ALB only",
        )
        # BRIDGE モードは動的ポート（32768-65535）を使うため全範囲を許可
        ecs_sg.add_ingress_rule(alb_sg, ec2.Port.all_traffic())

        rds_sg = ec2.SecurityGroup(
            self, "RdsSg",
            vpc=vpc,
            security_group_name="cancha-rds-sg",
            description="RDS: from ECS only",
        )
        rds_sg.add_ingress_rule(ecs_sg, ec2.Port.tcp(5432))

        # ----------------------------------------
        # ECR リポジトリ
        # ----------------------------------------
        ecr_repo = ecr.Repository(
            self, "EcrRepo",
            repository_name="cancha-backend",
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
            lifecycle_rules=[
                ecr.LifecycleRule(max_image_count=5, description="最新5件保持")
            ],
        )

        # ----------------------------------------
        # S3：動画保存
        # ----------------------------------------
        video_bucket = s3.Bucket(
            self, "VideoBucket",
            bucket_name=f"cancha-videos-{self.account}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.GET],
                    allowed_origins=["*"],
                    allowed_headers=["*"],
                    max_age=3000,
                )
            ],
        )

        # ----------------------------------------
        # S3：フロントエンド配信
        # ----------------------------------------
        frontend_bucket = s3.Bucket(
            self, "FrontendBucket",
            bucket_name=f"cancha-frontend-{self.account}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ----------------------------------------
        # RDS PostgreSQL t3.micro（無料枠）
        # ----------------------------------------
        db = rds.DatabaseInstance(
            self, "Database",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.MICRO
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[rds_sg],
            database_name="cancha",
            instance_identifier="cancha-db",
            allocated_storage=20,
            removal_policy=RemovalPolicy.DESTROY,
            deletion_protection=False,
            backup_retention=cdk.Duration.days(1),
            multi_az=False,
        )

        # ----------------------------------------
        # ECS クラスター（EC2 t3.micro・無料枠）
        # ----------------------------------------
        cluster = ecs.Cluster(
            self, "Cluster",
            cluster_name="cancha-cluster",
            vpc=vpc,
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
            security_group=ecs_sg,
            role=ecs_instance_role,
            user_data=user_data,
        )

        asg = autoscaling.AutoScalingGroup(
            self, "DefaultAsg",
            vpc=vpc,
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
        # ECS タスク実行ロール
        # ----------------------------------------
        execution_role = iam.Role(
            self, "TaskExecutionRole",
            role_name="cancha-task-execution-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ],
        )
        ecr_repo.grant_pull(execution_role)
        db.secret.grant_read(execution_role)

        # ----------------------------------------
        # FastAPI タスク定義
        # ----------------------------------------
        task_def = ecs.Ec2TaskDefinition(
            self, "TaskDef",
            family="cancha-backend",
            network_mode=ecs.NetworkMode.BRIDGE,
            execution_role=execution_role,
        )

        container = task_def.add_container(
            "FastApiContainer",
            container_name="cancha-backend",
            # 初回デプロイ用プレースホルダー。CodePipeline が ECR イメージに更新する
            image=ecs.ContainerImage.from_registry("python:3.12-alpine"),
            command=["python3", "-m", "http.server", "8000"],
            memory_reservation_mib=400,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="cancha-backend"),
            environment={
                "AWS_REGION": self.region,
                "S3_VIDEO_BUCKET": video_bucket.bucket_name,
            },
            secrets={
                "DB_HOST": ecs.Secret.from_secrets_manager(db.secret, "host"),
                "DB_PORT": ecs.Secret.from_secrets_manager(db.secret, "port"),
                "DB_NAME": ecs.Secret.from_secrets_manager(db.secret, "dbname"),
                "DB_USER": ecs.Secret.from_secrets_manager(db.secret, "username"),
                "DB_PASS": ecs.Secret.from_secrets_manager(db.secret, "password"),
            },
        )
        container.add_port_mappings(ecs.PortMapping(container_port=8000))

        # タスクロールに S3・Bedrock 権限付与
        video_bucket.grant_read_write(task_def.task_role)
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
            self, "Alb",
            load_balancer_name="cancha-alb",
            vpc=vpc,
            internet_facing=True,
            security_group=alb_sg,
        )

        service = ecs.Ec2Service(
            self, "Service",
            service_name="cancha-service",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            min_healthy_percent=0,  # 削除時にタスクを即座に停止
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
                healthy_http_codes="200-404",  # プレースホルダーは 404 を返す
            ),
        )

        # ----------------------------------------
        # CloudFront（単一スタックなので循環参照なし）
        # ----------------------------------------
        oac = cloudfront.S3OriginAccessControl(
            self, "OAC",
            signing=cloudfront.Signing.SIGV4_NO_OVERRIDE,
        )

        distribution = cloudfront.Distribution(
            self, "Distribution",
            comment="cancha-cdn",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    frontend_bucket, origin_access_control=oac
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            additional_behaviors={
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
                "/videos/*": cloudfront.BehaviorOptions(
                    origin=origins.S3BucketOrigin.with_origin_access_control(
                        video_bucket, origin_access_control=oac
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                ),
            },
        )

        # ----------------------------------------
        # Outputs（デプロイ後に表示される重要な値）
        # ----------------------------------------
        CfnOutput(self, "CloudFrontUrl",
            value=f"https://{distribution.domain_name}",
            description="アプリの URL")
        CfnOutput(self, "AlbDnsName",
            value=alb.load_balancer_dns_name,
            description="ALB DNS（直接アクセス確認用）")
        CfnOutput(self, "FrontendBucketName",
            value=frontend_bucket.bucket_name,
            description="フロントエンド S3 バケット名")
        CfnOutput(self, "EcrRepoUri",
            value=ecr_repo.repository_uri,
            description="ECR リポジトリ URI（Docker push 先）")
        CfnOutput(self, "DbSecretArn",
            value=db.secret.secret_arn,
            description="DB 認証情報 Secret ARN")
