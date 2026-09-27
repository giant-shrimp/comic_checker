---
name: publish-github
description: GitHub の Issue・PR を作成するときに使う．指示で確定した本文だけで作成し，作成後に本文を取得して一致を確認する．PR は帰属フッタを削除して確認する．
---

# Issue・PR の作成と確認

## 共通

- タイトル・本文は指示で確定したものを使い，書き足さない．本文はまず
  `/tmp/publish_body.md` に書く（末尾は改行1つ）．
- 作成・更新は，GitHub MCP のツールがあればそれを使う．なければ
  `gh api -X POST`・`gh api -X PATCH` で `repos/giant-shrimp/comic_checker/`
  以下のエンドポイント（REST）を使う．
- 確認のための取得は，常に `gh api repos/giant-shrimp/comic_checker/...`
  （REST の GET）で行う．GraphQL を使う gh のサブコマンド（`gh issue view`・
  `gh pr view` 等）は使わない（クラウドでは 403 になる．ADR-030）．
  `--paginate` は使わない．
- ブランチ名は，指示がなければ環境の既定に従う．

## Issue の作成

1. 指示のタイトル・本文で作成する．ラベル等は指示があるときだけ付ける．
2. 取得して一致を確認する．

```bash
gh api repos/giant-shrimp/comic_checker/issues/<番号> --jq .body > /tmp/publish_got.md
diff /tmp/publish_body.md /tmp/publish_got.md; echo "exit=$?"
```

3. exit が 0 でなければ，本文を指示どおりに更新して手順2に戻る．

## PR の作成

1. ブランチを push 済みで，pre-push-check を通したことを確認する．
2. 指示の本文で作成する（通常は `Closes #<Issue番号>` の1行だけ）．
3. 作成直後に取得する．

```bash
gh api repos/giant-shrimp/comic_checker/pulls/<番号> --jq .body > /tmp/publish_got.md
diff /tmp/publish_body.md /tmp/publish_got.md; echo "exit=$?"
```

4. 帰属フッタなど指示にない行が付いていれば，本文を指示どおりに更新して
   削除し，手順3に戻る．exit が 0 になるまで繰り返す．

## Issue コメント

- 本文は指示どおりにする．自動で付く帰属フッタは許容する（ADR-030）．

## しないこと

- PR のマージ，Issue のクローズ，リモートブランチの削除（ユーザが行う）．
- 取得して確認する前に「作成した」「一致した」「削除した」と報告しない．
