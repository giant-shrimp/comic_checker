#!/usr/bin/env bash
#
# Claude PR Review（Phase 5 Step 1）のトラッキングコメント本文を検査し、
# 実質的なレビューが書かれているかを判定する。ネットワーク・gh CLIには
# 一切触れず、渡された本文だけで完結する。
#
# 切り出した理由: 判定ロジックを .github/workflows/ の中に直書きすると、
# その領域は Claude Code へ deny（ADR-004決定3）でテストが書けず、
# 「わざと壊して確認する」（CLAUDE.md）を本番runでしか実施できない。
# これは verify.sh を deny している理由と同じ構造の問題だったため、
# ロジックをこのスクリプトへ切り出した（ADR-006 作業9-1）。
#
# 使い方:
#   scripts/check_review_comment.sh < comment_body.txt
#   scripts/check_review_comment.sh comment_body.txt
#
# 終了コード:
#   0 = 実質的なレビューあり
#   1 = 初期プレースホルダの残骸が残っている
#       （Claudeが update_claude_comment を一度も呼んでいない可能性が高い）
#   2 = 本文が短すぎる（閾値未満）
#
# 判定根拠: ERRORS.md「claude-review.yml（Phase 5 Step 1）」、
# ADR-006（docs/decisions/ADR-006-phase5-step1-redesign.md）を参照。
# 対象コメントの特定方法（author.login等）はワークフロー側の責務であり、
# このスクリプトは渡された本文だけを見る。

set -euo pipefail

# 文字数カウントの単位をUTF-8文字数に固定する（バイト数にしない）。
# GitHub Actions ランナーの既定ロケールに依存させない（作業9-3）。
export LC_ALL=C.UTF-8

# anthropics/claude-code-action の一次情報（src/github/operations/comments/
# common.ts の createCommentBody()、comment-logic.ts の updateCommentBody()）
# から機械的にトレースして確認した、初期プレースホルダの残骸となる固定文字列。
# Claudeが update_claude_comment を一度も呼ばずに終了すると、最終コメントの
# 区切り線（---）直後にこの文がそのまま残る（ADR-006参照）。
PLACEHOLDER_RESIDUE="I'll analyze this and get back to you."

# 実質的なレビューとみなす本文の最小文字数（UTF-8文字数）。
#
# 根拠:
#   - プレースホルダ残骸（英文38文字）は exit 1 で別途検出されるため、
#     この閾値の役割はそれではなく「Claudeが update_claude_comment は
#     呼んだが、内容が空虚だった」ケースを捉えることにある。
#   - 「問題ありません。」のような1桁〜十数文字の空虚な一言は弾きたい。
#   - 一方、「差分を確認しましたが、`verify.sh` のゲート空洞化や
#     fail-closed原則の崩れは見当たりませんでした。指摘事項はありません。」
#     （69文字）のような、指摘事項が無いという正当な短い実質的レビューは
#     弾きたくない。
#   - したがって、この2つの間（十数文字より大きく69文字より小さい）に
#     閾値を置く。50文字を暫定値とする。
#   - あくまで恣意的な下限値であり、実運用のログを見て再調整する前提。
MIN_LENGTH=50

if [ "${1:-}" != "" ]; then
  BODY="$(cat "$1")"
else
  BODY="$(cat -)"
fi

if printf '%s' "$BODY" | grep -qF "$PLACEHOLDER_RESIDUE"; then
  echo "NG: プレースホルダ残骸(\"${PLACEHOLDER_RESIDUE}\")が検出されました。Claudeがupdate_claude_commentを一度も呼んでいない可能性があります。" >&2
  exit 1
fi

# ヘッダー・リンク行を除いた、区切り線（---）より後ろの本文を取り出す。
# 区切り線ちょうど1文字の行（updateCommentBody()が必ず挿入する）が
# 見つからない場合はCONTENTを空とみなす（fail-closed。想定外の形式の
# コメントを誤って「実質的」と判定しないため）。
CONTENT="$(printf '%s\n' "$BODY" | awk 'f{print} /^---$/{f=1}')"
LEN="$(printf '%s' "$CONTENT" | wc -m)"

if [ "$LEN" -lt "$MIN_LENGTH" ]; then
  echo "NG: 本文が短すぎます(${LEN}文字、閾値${MIN_LENGTH}文字)。実質的なレビューが投稿されていない可能性があります。" >&2
  exit 2
fi

echo "OK: レビューコメントの内容を確認しました(${LEN}文字)。"
exit 0
