---
name: publish-github
description: GitHub の Issue・PR を作成するときに使う．指示で確定した本文だけで作成し，作成後に本文を取得して一致を確認する．PR は帰属フッタを削除して確認する．
---

# Issue・PR の作成と確認

## 共通

- タイトル・本文は指示で確定したものを使い，書き足さない．本文はまず
  `/tmp/publish_body.md` に書く（末尾は改行1つ）．
- 作成は，GitHub MCP の作成用ツールがあればそれを使う．なければ
  `gh api -X POST` で `repos/giant-shrimp/comic_checker/` 以下の
  エンドポイント（REST）を使う．
- 本文の更新（PR の帰属フッタの削除を含む）は，GitHub MCP の更新用ツール
  （PR は PR 更新用のツール，Issue は Issue 更新用のツール）で行う．
  GitHub MCP のツールがある環境では `gh api -X PATCH` を使わない
  （PATCH で更新してもフッタが付き直した．Issue #350・PR #351）．
  GitHub MCP のツールがない環境に限り `gh api -X PATCH` を使う．
- 確認のための取得は，常に `gh api repos/giant-shrimp/comic_checker/...`
  （REST の GET）で行う．GraphQL を使う gh のサブコマンド（`gh issue view`・
  `gh pr view` 等）は使わない（クラウドでは 403 になる．ADR-030）．
  `--paginate` は使わない．
- 本文の比較は，両側の末尾の改行を取り除いてから行う（`--jq .body` の出力は
  末尾に改行が1つ加わるため）．末尾の改行の差だけを理由に本文を更新しない．
- ブランチ名は，指示がなければ環境の既定に従う．

## 本文の比較

```bash
diff <(printf '%s\n' "$(cat /tmp/publish_body.md)") \
     <(printf '%s\n' "$(gh api repos/giant-shrimp/comic_checker/<issues|pulls>/<番号> --jq .body)"); echo "exit=$?"
```

## Issue の作成

1. 指示のタイトル・本文で作成する．ラベル等は指示があるときだけ付ける．
2. 「本文の比較」で一致を確認する（`issues/<番号>`）．
3. exit が 0 でなければ，Issue 更新用のツールで本文を指示どおりに更新し，
   もう一度比較する．それでも 0 でなければ，停止して事実だけを報告する．

## PR の作成

1. ブランチを push 済みで，pre-push-check を通したことを確認する．
2. 指示の本文で作成する（通常は `Closes #<Issue番号>` の1行だけ）．
3. 作成直後に「本文の比較」を行う（`pulls/<番号>`）．
4. 帰属フッタなど指示にない行が付いていれば，PR 更新用のツールで本文を
   指示どおりに更新し，もう一度比較する．それでも 0 でなければ，
   停止して事実（使ったツール・取得した本文）を報告する．フッタの削除は
   ユーザが Web 画面で行う．

## Issue コメント

- 本文は指示どおりにする．自動で付く帰属フッタは許容する（ADR-030）．

## しないこと

- PR のマージ，Issue のクローズ，リモートブランチの削除（ユーザが行う）．
- 取得して確認する前に「作成した」「一致した」「削除した」と報告しない．
- 更新と比較を3回以上繰り返さない．
