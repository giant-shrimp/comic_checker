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
#   1 = 初期プレースホルダ・進捗テンプレートのまま終了した可能性が高い
#       （Claudeが update_claude_comment を最後まで呼び終えていない）
#   2 = 本文が短すぎる（閾値未満）
#
# 判定根拠: ERRORS.md「claude-review.yml（Phase 5 Step 1）」、
# ADR-006（docs/decisions/ADR-006-phase5-step1-redesign.md）を参照。
# 対象コメントの特定方法（author.login等）はワークフロー側の責務であり、
# このスクリプトは渡された本文だけを見る。
#
# fail-openの穴（Issue #94）への対応: tagモードの初期進捗テンプレート
# （「### レビュー進行中」、チェック項目がすべて未完了の`- [ ] `のまま）は、
# 旧来のプレースホルダ残骸検出（PLACEHOLDER_RESIDUE）にも文字数閾値にも
# 引っかからず、誤ってexit 0（実質的なレビューあり）を返していた
# （PR #92, run 31160930257で実測、`error_max_turns`によりstep自体は
# 失敗したため実害は無かったが、fail-closed原則の穴として記録
# されていた）。この穴を塞ぐため、本文の**全文**（`---`区切り線より前の
# ヘッダー行を含む）を対象にした判定を追加した（_check_header・
# _check_incomplete_checkbox）。既存の`---`以降だけを対象にした判定
# （_check_placeholder_residue・_check_min_length）とは対象範囲が異なる
# ため、判定ごとに関数を分けて対象範囲を明示した。

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

# tagモードの初期進捗テンプレート（「### レビュー進行中」）が持つ、
# 未完了チェックボックスの行頭マーカー。実データ（PR #92・PR #98・PR #99の
# 実行中プレースホルダ）で確認済み。完了レビューの本文にこのマーカーが
# 出現した例は、実測7点（PR #90・#92・#95・#96・#97・#98・#99）の中には
# 無い（Issue #94参照）。
INCOMPLETE_CHECKBOX_MARKER="- [ ] "

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

# --- 全文（ヘッダー行を含む）を対象にした判定 ---
#
# anthropics/claude-code-action は実行結果に応じて本文の先頭行を
# "**Claude finished ..."（成功）または"**Claude encountered an error ..."
# （失敗）のいずれかに固定して生成する。このヘッダーはClaude自身の
# 応答内容に左右されない機械生成の固定テンプレートであるため、
# 実データ7点（PR #90・#92・#95・#96・#97・#98・#99）すべてで
# この2パターンのいずれかに一致することを確認済み。

_check_header() {
  local body="$1"
  local first_line
  first_line="$(printf '%s\n' "$body" | head -1)"
  case "$first_line" in
    '**Claude finished'*)
      return 0
      ;;
    '**Claude encountered an error'*)
      echo "NG: ヘッダーが\"**Claude encountered an error\"です。Claudeの実行がエラーで終了した可能性があります。" >&2
      return 1
      ;;
    *)
      echo "NG: 本文の先頭が\"**Claude finished\"で始まっていません（想定外の形式）。" >&2
      return 1
      ;;
  esac
}

_check_incomplete_checkbox() {
  local body="$1"
  if printf '%s\n' "$body" | grep -qF -- "$INCOMPLETE_CHECKBOX_MARKER"; then
    echo "NG: 未完了のチェックボックス(\"${INCOMPLETE_CHECKBOX_MARKER}\")が検出されました。進捗テンプレートのまま終了した可能性があります。" >&2
    return 1
  fi
  return 0
}

# --- ヘッダー・リンク行を除いた、区切り線（---）より後ろだけを対象にした判定 ---
#
# 区切り線ちょうど1文字の行（updateCommentBody()が必ず挿入する）が
# 見つからない場合はCONTENTを空とみなす（fail-closed。想定外の形式の
# コメントを誤って「実質的」と判定しないため）。

_extract_content() {
  printf '%s\n' "$1" | awk 'f{print} /^---$/{f=1}'
}

_check_placeholder_residue() {
  local content="$1"
  if printf '%s' "$content" | grep -qF -- "$PLACEHOLDER_RESIDUE"; then
    echo "NG: プレースホルダ残骸(\"${PLACEHOLDER_RESIDUE}\")が検出されました。Claudeがupdate_claude_commentを一度も呼んでいない可能性があります。" >&2
    return 1
  fi
  return 0
}

if ! _check_header "$BODY"; then
  exit 1
fi

if ! _check_incomplete_checkbox "$BODY"; then
  exit 1
fi

CONTENT="$(_extract_content "$BODY")"

if ! _check_placeholder_residue "$CONTENT"; then
  exit 1
fi

LEN="$(printf '%s' "$CONTENT" | wc -m)"

if [ "$LEN" -lt "$MIN_LENGTH" ]; then
  echo "NG: 本文が短すぎます(${LEN}文字、閾値${MIN_LENGTH}文字)。実質的なレビューが投稿されていない可能性があります。" >&2
  exit 2
fi

echo "OK: レビューコメントの内容を確認しました(${LEN}文字)。"
exit 0
