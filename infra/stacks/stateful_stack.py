import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_s3 as s3,
    aws_ecr as ecr,
    RemovalPolicy,
)
from constructs import Construct


class StatefulStack(Stack):
    """
    削除保護あり。データを持つリソース一式。
    - VPC（ECS・RDS 共通ネットワーク）
    - RDS PostgreSQL t3.micro
    - S3（動画保存）
    - ECR（FastAPI コンテナイメージ）
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ----------------------------------------
        # VPC
        # ----------------------------------------
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
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
        self.alb_sg = ec2.SecurityGroup(
            self, "AlbSg",
            vpc=self.vpc,
            security_group_name="cancha-alb-sg",
            description="ALB security group",
        )
        self.alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80))

        self.ecs_sg = ec2.SecurityGroup(
            self, "EcsSg",
            vpc=self.vpc,
            security_group_name="cancha-ecs-sg",
            description="ECS tasks security group",
        )
        # ALB からのトラフィックのみ許可
        self.ecs_sg.add_ingress_rule(self.alb_sg, ec2.Port.tcp(8000))

        self.rds_sg = ec2.SecurityGroup(
            self, "RdsSg",
            vpc=self.vpc,
            security_group_name="cancha-rds-sg",
            description="RDS security group",
        )
        # ECS からのみ 5432 許可
        self.rds_sg.add_ingress_rule(self.ecs_sg, ec2.Port.tcp(5432))

        # ----------------------------------------
        # ECR リポジトリ
        # ----------------------------------------
        self.ecr_repo = ecr.Repository(
            self,
            "EcrRepo",
            repository_name="cancha-backend",
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                ecr.LifecycleRule(
                    max_image_count=5,
                    description="最新5件だけ保持",
                )
            ],
        )

        # ----------------------------------------
        # S3：動画保存バケット
        # ----------------------------------------
        self.video_bucket = s3.Bucket(
            self,
            "VideoBucket",
            bucket_name=f"cancha-videos-{self.account}",
            removal_policy=RemovalPolicy.RETAIN,
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
        # RDS PostgreSQL t3.micro（無料枠）
        # ----------------------------------------
        self.db = rds.DatabaseInstance(
            self,
            "Database",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.MICRO
            ),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[self.rds_sg],
            database_name="cancha",
            instance_identifier="cancha-db",
            allocated_storage=20,
            removal_policy=RemovalPolicy.RETAIN,
            deletion_protection=True,
            backup_retention=cdk.Duration.days(1),
            multi_az=False,
        )
