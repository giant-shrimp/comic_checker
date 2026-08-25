#!/usr/bin/env bash
#
# claude-review.yml のトラッキングコメントを、PRのコメント一覧JSON配列
# から特定する。ネットワーク・gh CLIには一切触れず、渡されたJSONだけで
# 完結する（scripts/check_review_comment.sh と同じ設計方針。ADR-006
# 作業12-2）。
#
# 特定方法は2段階（1次が見つからない場合のみ2次を試す）:
#   1次: 本文に "actions/runs/<run_id>" を含む最新コメント。
#        anthropics/claude-code-action の src/entrypoints/
#        update-comment-link.ts / src/github/operations/comment-logic.ts を
#        確認したところ、この文字列は actionFailed・claudeSuccess の
#        状態や、Claudeが実際に何か書いたかに関わらず、コメント本文へ
#        無条件に組み込まれる（jobUrl経由）。さらに初期プレースホルダ
#        （src/github/operations/comments/common.ts の createCommentBody()）
#        自体も同じrun IDを埋め込む（createJobRunLink経由）ため、
#        「更新後」でも「未更新のまま」でも一致する。
#   2次（フォールバック）: author.login が "github-actions[bot]" である
#        最新コメント。github_token に secrets.GITHUB_TOKEN を明示的に
#        渡している前提に依存する推定であり、1次より弱い。
#
# 依存: jq。GitHub Actions ubuntu-latestランナーには公式に jq 1.7 が
# プリインストールされている（actions/runner-images
# images/ubuntu/Ubuntu2404-Readme.mdのソフトウェア一覧で確認済み）ため、
# ワークフロー側で追加インストールする必要は無い。
#
# 使い方:
#   gh pr view <n> --json comments --jq '.comments' | \
#     scripts/select_review_comment.sh <run_id>
#
# 標準出力: 見つかったコメントのbody（見つからなければ何も出力しない）
# 標準エラー: どちらの経路で見つけたか、または両方失敗したかのログ
# 終了コード:
#   0 = 発見（1次または2次経路）
#   1 = 引数(run_id)が無い（使い方の誤り）
#   2 = どちらの経路でも見つからなかった（fail-closed）

set -euo pipefail

RUN_ID="${1:-}"
if [ -z "$RUN_ID" ]; then
  echo "使い方: $0 <run_id>  (標準入力にコメントのJSON配列を渡す)" >&2
  exit 1
fi

COMMENTS_JSON="$(cat -)"

MATCH_COUNT="$(printf '%s' "$COMMENTS_JSON" | jq --arg run_id "$RUN_ID" \
  '[.[] | select(.body | contains("actions/runs/" + $run_id))] | length')"

if [ "$MATCH_COUNT" -gt 0 ]; then
  BODY="$(printf '%s' "$COMMENTS_JSON" | jq -r --arg run_id "$RUN_ID" \
    '[.[] | select(.body | contains("actions/runs/" + $run_id))] | last | .body')"
  echo "OK: run_id(${RUN_ID})一致でコメントを特定しました(1次経路)。" >&2
  printf '%s' "$BODY"
  exit 0
fi

# 【実測記録・Issue #93】この2次経路は実運用では発火しない
# （2026-08-25実測。ロジックは変更していない。設計判断は保留のまま）。
#
# 呼び出し元（.github/workflows/claude-review.yml、このスクリプトへの
# 入力生成箇所）は `gh pr view --json comments` を使っており、その出力の
# author.login は "github-actions"（"[bot]" サフィックス無し）である。
# 一方 `gh api repos/.../issues/.../comments` 経由で同じコメントを取得
# すると "github-actions[bot]" になる。サフィックスの有無は同一コメントの
# 属性ではなく、取得コマンド（GraphQL経由のgh pr view / REST経由のgh api）
# 依存で変わる。このスクリプトの下記の条件式は "[bot]" 付きの形式を
# 前提にしているため、呼び出し元が実際に使っている gh pr view の出力とは
# 一致しない。
#
# 実測範囲: ~/comic_checker-agent-notes/pr*_comments.json 19件（過去の
# claude-review実行時にgh pr viewで取得した実データ）および現行の
# gh pr view の出力。いずれも author.login は "[bot]" 無しで例外は無かった。
#
# 結果として、1次経路（run_id一致）が失敗した時点で、この2次経路の条件
# （下記 "github-actions[bot]"）に一致するコメントは実運用では常に0件になり、
# 必ず fail-closed（exit 2）になる。
#
# 条件を "github-actions" も許容する形に緩めるか、この2次経路自体を
# 削除するかの設計判断はここでは行わない（保留、別Issue）。
MATCH_COUNT="$(printf '%s' "$COMMENTS_JSON" | jq \
  '[.[] | select(.author.login == "github-actions[bot]")] | length')"

if [ "$MATCH_COUNT" -gt 0 ]; then
  BODY="$(printf '%s' "$COMMENTS_JSON" | jq -r \
    '[.[] | select(.author.login == "github-actions[bot]")] | last | .body')"
  echo "OK: github-actions[bot]名でコメントを特定しました(2次経路・フォールバック)。" >&2
  printf '%s' "$BODY"
  exit 0
fi

echo "NG: run_id一致・bot名一致のいずれでもコメントを特定できませんでした。" >&2
exit 2
