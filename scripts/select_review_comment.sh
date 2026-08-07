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
