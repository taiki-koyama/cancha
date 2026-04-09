---
name: branch-naming
description: ブランチ名の命名規則を表示する
---

# ブランチ命名規則

## フォーマット

```
<type>/<kebab-case-description>
```

## タイプ一覧

| type | 用途 |
|------|------|
| `feature/` | 新機能の追加 |
| `fix/` | バグ修正 |
| `refactor/` | リファクタリング（機能変更なし） |
| `chore/` | ビルド・CI・依存関係などの雑務 |
| `docs/` | ドキュメントのみの変更 |
| `test/` | テストの追加・修正 |

## ルール

- 説明部分は **英語・ケバブケース**（小文字、ハイフン区切り）
- 動詞から始める（add / fix / update / remove など）
- 簡潔に（3〜5単語程度）
- GitHub Issue 番号がある場合は末尾に付ける（例: `fix/chat-send-on-ime-#12`）

## 例

```
feature/add-bedrock-chat
fix/ime-enter-key-send
refactor/extract-chat-handler
chore/update-boto3-version
docs/add-api-endpoint-spec
test/add-chat-endpoint-tests
```
