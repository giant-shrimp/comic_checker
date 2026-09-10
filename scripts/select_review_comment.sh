#!/usr/bin/env bash
#
# claude-review.yml のトラッキングコメントを、PRのコメント一覧JSON配列
# から特定する。ネットワーク・gh CLIには一切触れず、渡されたJSONだけで
# 完結する（scripts/check_review_comment.sh と同じ設計方針。ADR-006
# 作業12-2）。
#
# 特定方法は単一経路: 本文に "actions/runs/<run_id>" を含む最新コメント。
#   anthropics/claude-code-action の src/entrypoints/
#   update-comment-link.ts / src/github/operations/comment-logic.ts を
#   確認したところ、この文字列は actionFailed・claudeSuccess の
#   状態や、Claudeが実際に何か書いたかに関わらず、コメント本文へ
#   無条件に組み込まれる（jobUrl経由）。さらに初期プレースホルダ
#   （src/github/operations/comments/common.ts の createCommentBody()）
#   自体も同じrun IDを埋め込む（createJobRunLink経由）ため、
#   「更新後」でも「未更新のまま」でも一致する。
#
# 【設計変更・ADR-019】以前はauthor.loginが"github-actions[bot]"である
# 最新コメントへのフォールバック（2次経路）を持っていたが、実測でこの経路が
# 実運用では発火しないことが判明したため削除した（Issue #207、ADR-019）。
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
# 標準エラー: 見つけたか、または見つからなかったかのログ
# 終了コード:
#   0 = 発見（run_id一致）
#   1 = 引数(run_id)が無い（使い方の誤り）
#   2 = run_id一致が見つからなかった（fail-closed）

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
  echo "OK: run_id(${RUN_ID})一致でコメントを特定しました。" >&2
  printf '%s' "$BODY"
  exit 0
fi

echo "NG: run_id一致でコメントを特定できませんでした。" >&2
exit 2
