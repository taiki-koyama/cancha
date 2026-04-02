# サッカーチーム練習管理アプリ - インフラ設計・実装計画

## アプリ概要

サッカーチームに登録している選手が以下を行えるプラットフォーム：

- 日々の練習動画のアップロード
- Zoom 練習配信への参加
- コーチからのコメント・フィードバック受け取り
- AI による練習内容の管理・分析

---

## 技術スタック

| レイヤー | 採用技術 | 理由 |
|---|---|---|
| Frontend | React + Vite | 現在最も流行・軽量・高速 |
| Backend | FastAPI (Python) | 軽量・高速・自動 API ドキュメント生成 |
| DB | RDS PostgreSQL t3.micro | 無料枠あり・構造化データに最適 |
| 動画ストレージ | S3 | 大容量ファイル向け・安価 |
| 動画配信 | S3 + CloudFront | VOD 配信のベストプラクティス（AWS MCP 確認済み） |
| AI | Amazon Bedrock (Claude) | AWS 内完結・練習管理・コメント支援 |
| Zoom 連携 | Zoom API | FastAPI から呼び出してミーティング URL 発行 |
| IaC | AWS CDK (Python) | インフラをコードで管理（AWS MCP 推奨） |
| CI/CD | GitHub → CodePipeline → CodeBuild | テスト・ビルド・デプロイ自動化 |

---

## AWS アーキテクチャ

```
[ユーザー (ブラウザ)]
        ↓
[CloudFront]  ← CDN・キャッシュ・動画配信
        ↓
[S3]  ← React + Vite ビルド済み静的ファイル
        ↓ API リクエスト
[ALB]  ← Application Load Balancer
        ↓
[ECS on EC2 t3.micro]
  └─ FastAPI コンテナ (Docker)
        ↓              ↓              ↓
  [RDS            [S3              [Bedrock]
  PostgreSQL       動画保存]        AI 練習管理
  t3.micro]        ↑
                Presigned URL
                で直接アップロード
```

### ポイント

- **動画アップロード**：FastAPI が S3 の Presigned URL を発行 → ブラウザから S3 へ直接アップロード（EC2 負荷軽減）
- **動画再生**：S3 + CloudFront で VOD 配信（AWS 公式推奨構成）
- **Zoom 連携**：FastAPI から Zoom API を叩いてミーティング URL を発行
- **AI**：Amazon Bedrock (Claude) で練習内容の分析・コーチコメント支援

---

## CDK スタック構成（MCP ベストプラクティス準拠）

```
StatefulStack（削除保護あり）
  ├─ RDS PostgreSQL t3.micro
  └─ S3（動画保存）

StatelessStack
  ├─ VPC
  ├─ ECS Cluster + EC2 t3.micro
  ├─ FastAPI タスク定義
  ├─ ALB
  └─ CloudFront + S3（フロントエンド配信）
```

### CDK 重要ルール

- L2 Construct を優先使用（セキュアな設定が自動適用）
- `grant()` メソッドで IAM 権限付与（手動ポリシー不要）
- DB パスワードは **Secrets Manager** に保存
- リソース名はハードコードしない（CDK 自動生成）

---

## CI/CD フロー

```
① PR 作成・更新
        ↓
② GitHub Actions：CI（テスト）← PR 上で結果表示
   - pytest（FastAPI 単体テスト）
   - Vitest（React 単体テスト）
   - Playwright（E2E テスト）
        ↓ 全テスト通過 → マージ可能に
③ main ブランチへマージ
        ↓
④ CodePipeline が自動検知
        ↓
⑤ CodeBuild：ビルドのみ（テストなし）
   - React：npm run build → S3 アップロード
   - FastAPI：Docker イメージビルド → ECR プッシュ
        ↓
⑥ ECS サービス更新（ローリングデプロイ）
⑦ CloudFront キャッシュ無効化
        ↓
⑧ デプロイ完了
```

### 役割分担

| ツール | 責務 | テスト実行 |
|---|---|---|
| GitHub Actions | CI（品質ゲート） | ✅ する |
| CodePipeline + CodeBuild | CD（ビルド・デプロイ） | ❌ しない |

---

## コスト試算（月額・POC 規模）

| サービス | 無料枠 | 超過後 |
|---|---|---|
| EC2 t3.micro (ECS ホスト) | **750h 無料**（12ヶ月） | ~$8/月 |
| RDS PostgreSQL t3.micro | **750h 無料**（12ヶ月） | ~$15/月 |
| S3 | **5GB 無料** | $0.023/GB |
| CloudFront | **1TB 無料**（12ヶ月） | 微量 |
| ECR | **500MB 無料** | $0.10/GB |
| CodePipeline | **1本無料** | $1/本 |
| CodeBuild | **100分/月無料** | $0.005/分 |
| Amazon Bedrock | 従量課金のみ | POC なら数百円程度 |

> **無料枠期間中はほぼ $0、超過後も ~$25/月 程度**
>
> ⚠️ ECS Fargate は無料枠なし（vCPU $0.05056/h・東京）。  
> POC では **ECS on EC2 t3.micro** で無料枠を活用する。

---

## 実装タスク一覧

### 0. 事前準備

- [ ] AWS アカウント作成・IAM ユーザー設定（AdministratorAccess）
- [ ] AWS CLI インストール・認証設定（`aws configure`）
- [ ] AWS CDK CLI インストール（`npm install -g aws-cdk`）
- [ ] Docker インストール
- [ ] GitHub リポジトリ作成（frontend / backend / infra をモノレポ or 分割）

---

### 1. CDK インフラ構築

#### 1-1. CDK プロジェクト初期化

- [ ] CDK プロジェクト作成（`cdk init app --language python`）
- [ ] `cdk bootstrap` でデプロイ環境を初期化
- [ ] StatefulStack / StatelessStack の2スタック構成を定義

#### 1-2. ネットワーク（VPC）

- [ ] VPC 作成（パブリック・プライベートサブネット）
- [ ] セキュリティグループ設定（ALB / ECS / RDS それぞれ）

#### 1-3. データベース（RDS）

- [ ] RDS PostgreSQL t3.micro 作成（プライベートサブネット配置）
- [ ] Secrets Manager に DB 認証情報を保存
- [ ] ECS タスクから DB へのアクセス権限付与（`grant()`）

#### 1-4. ストレージ（S3）

- [ ] 動画保存用 S3 バケット作成
- [ ] フロントエンド配信用 S3 バケット作成（静的ウェブサイトホスティング）
- [ ] Presigned URL 発行用 IAM ポリシー設定

#### 1-5. コンテナ基盤（ECS）

- [ ] ECR リポジトリ作成（FastAPI イメージ保存用）
- [ ] ECS クラスター作成（EC2 起動タイプ・t3.micro）
- [ ] FastAPI 用タスク定義作成（CPU / メモリ・環境変数・Secrets Manager 参照）
- [ ] ECS サービス作成

#### 1-6. ロードバランサー・CDN

- [ ] ALB 作成・ECS サービスにターゲットグループ紐付け
- [ ] CloudFront ディストリビューション作成
  - オリジン1：S3（フロントエンド）
  - オリジン2：ALB（API `/api/*`）
  - オリジン3：S3（動画配信）

#### 1-7. CDK デプロイ・確認

- [ ] `cdk synth` で CloudFormation テンプレート生成・確認
- [ ] `cdk deploy --all` で全スタックデプロイ
- [ ] ALB エンドポイントへのアクセス確認
- [ ] CloudFront URL でフロントエンド表示確認

---

### 2. アプリケーション実装（最小構成）

#### 2-1. FastAPI バックエンド

- [ ] FastAPI プロジェクト初期化（`pyproject.toml` / `requirements.txt`）
- [ ] PostgreSQL 接続設定（SQLAlchemy + alembic）
- [ ] 選手・動画・コメントの基本 CRUD API 実装
- [ ] S3 Presigned URL 発行エンドポイント実装
- [ ] Zoom API 連携（ミーティング URL 発行）
- [ ] Bedrock API 連携（練習内容分析）
- [ ] Dockerfile 作成

#### 2-2. React + Vite フロントエンド

- [ ] Vite + React プロジェクト初期化
- [ ] 動画アップロード画面実装（S3 直接アップロード）
- [ ] 動画一覧・再生画面実装（CloudFront URL で再生）
- [ ] コーチコメント画面実装
- [ ] Zoom 参加ボタン実装
- [ ] `npm run build` → S3 アップロードの動作確認

---

### 3. テスト実装

- [ ] pytest セットアップ（FastAPI 単体テスト）
- [ ] Vitest セットアップ（React 単体テスト）
- [ ] Playwright セットアップ（E2E テスト）
- [ ] 主要フローの E2E テストシナリオ作成（動画アップロード・コメント投稿）

---

### 4. CI/CD パイプライン構築

#### 4-1. GitHub Actions（CI）

- [ ] `.github/workflows/ci.yml` 作成
- [ ] PR トリガー設定（main ブランチへの PR で発火）
- [ ] バックエンド CI ジョブ設定（Python 環境・pytest 実行）
- [ ] フロントエンド CI ジョブ設定（Node 環境・Vitest 実行）
- [ ] E2E CI ジョブ設定（Playwright 実行）
- [ ] PR マージ条件に CI 通過を必須化（GitHub Branch Protection Rules）

#### 4-2. AWS 事前設定

- [ ] AWS CodeStar Connections で GitHub リポジトリを AWS に接続
- [ ] 接続の承認（GitHub 側で OAuth 認可）
- [ ] CodeBuild 用 IAM ロール作成（ECR / S3 / ECS / CloudFront 権限）

#### 4-3. CodeBuild（ビルド専用）

- [ ] `buildspec.yml` 作成（ビルドのみ・テストなし）
  - React：`npm run build` → S3 アップロード
  - FastAPI：Docker ビルド → ECR プッシュ
  - ECS サービス更新
  - CloudFront キャッシュ無効化
- [ ] CodeBuild プロジェクト作成・`buildspec.yml` 紐付け

#### 4-4. CodePipeline（CD）

- [ ] パイプライン作成（無料枠：1本）
- [ ] Source ステージ：GitHub（main ブランチ・マージをトリガー）
- [ ] Build ステージ：CodeBuild（`buildspec.yml`）
- [ ] 環境変数設定（ECR URI / S3 バケット名 / ECS クラスター名など）

#### 4-5. 動作確認

- [ ] PR 作成 → GitHub Actions が自動実行されることを確認
- [ ] テスト失敗時にマージブロックされることを確認
- [ ] main マージ後に CodePipeline が自動起動することを確認
- [ ] ECS に新イメージがデプロイされることを確認

---

### 5. 動作確認・仕上げ

- [ ] 選手登録 → 動画アップロード → 再生の一連フロー確認
- [ ] コーチコメント機能確認
- [ ] Zoom ミーティング URL 発行確認
- [ ] Bedrock AI 練習分析機能確認
- [ ] コスト確認（AWS Cost Explorer で想定内か確認）
