---
name: ship
description: ブランチ作成・コミット・プッシュ・PR作成を一括で行う
---

# /ship — Git ワークフロー自動化

ステージングされた変更（または現在の変更）を元に、ブランチ作成・コミット・プッシュ・PR作成を順番に実行する。

## 実行ステップ

以下を **1ステップずつユーザーの確認を取りながら** 実行する。

### 1. ブランチ名の決定

- `git diff` と `git status` で変更内容を把握する
- [branch-naming](branch-naming.md) の規則に従ってブランチ名を提案する
- ユーザーに確認・修正を求めてから `git checkout -b <branch>` を実行する

### 2. ファイルのステージング

- `git status` で未ステージのファイルを確認する
- 関係するファイルを提示し、ユーザーの承認後に `git add` を実行する

### 3. コミット

- [conventional-commits](conventional-commits.md) の規則に従ってコミットメッセージを提案する
- ユーザーに確認・修正を求めてから `git commit` を実行する
- `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>` をトレーラーに付ける

### 4. プッシュ

- `git push -u origin <branch>` を実行する（ユーザー確認後）

### 5. PR 作成

- [pr-template](pr-template.md) の形式で PR 本文を生成する
- タイトルとボディをユーザーに提示し、確認後に `gh pr create` を実行する
- 作成後に PR の URL を表示する

## 注意事項

- 各ステップでユーザーが内容を修正できるようにする
- `main` ブランチへの直接コミットは行わない
- 変更がない場合は中断してユーザーに伝える
