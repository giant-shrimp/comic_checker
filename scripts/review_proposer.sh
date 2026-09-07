#!/usr/bin/env bash
#
# ADR-014（docs/decisions/ADR-014-proposer-design.md）の起案役1回分の呼び出し。
# 監査役の指摘（直近ラウンドのreview.md）を、実行役への次ラウンドの行動指示に
# 翻訳する。review_loop.shへの組み込み（ADR-014決定6）はまだ無い。この段階
# では「1回分の起案を実行し、次ラウンドのinstructionテキストと実測メトリクス
# をファイルに残す」ことだけを行う。
#
# 使い方:
#   ./scripts/review_proposer.sh <original-instruction-file> <review-md-file> <output-dir> [executor-allowed-tools]
#
# 第4引数 executor-allowed-tools は省略可（Issue #225）。実行役の
# --allowedTools にそのまま渡すのと同じカンマ区切り文字列（例:
# "Read,Edit,Write,Glob,Grep,Bash(./scripts/verify.sh)"）を渡すと、
# プロンプトの{{EXECUTOR_ALLOWED}}へ埋め込まれ、起案役が実行役の権限を
# 踏まえたinstructionを書けるようになる。review_loop.sh経由の呼び出しでは
# 常にEXECUTOR_ALLOWEDが渡される。省略時（review_proposer.shを単体で試す
# 場合など）はEXECUTOR_ALLOWED_UNKNOWN_TEXTを使う。
#
# 出力（すべて <output-dir> 配下）:
#   prompt.txt           実際に投入したプロンプト全文
#   result.json          claude -p --output-format json の生出力
#   result.err           claude 実行時の標準エラー
#   next_instruction.md  result.json の result フィールド（次ラウンドのinstruction
#                         本文。ADR-014決定5により、起案役自身はファイルを書かず、
#                         このスクリプトが書き出す）
#   metrics.json          total_cost_usd / num_turns / is_error / terminal_reason /
#                         permission_denials
#
# 終了コード:
#   0  next_instruction.md へ書き出せた（NO_FURTHER_ACTIONマーカーの場合も含む。
#      「起案が成立した」ことのみを意味する。呼び出し側がnext_instruction.mdの
#      1行目を読んで判断すること）
#   2  claude の実行自体が失敗（timeoutでresult.jsonが空/不正なJSON、または
#      is_error=trueで終了）
#   3  実行は成功したが、resultフィールドが空だった（出力形式不正）
#   1  引数エラー以外の前提条件エラー（jq不在・入力ファイル不在等）
#   64 引数の個数が誤り
#
# 【禁止事項として意図的に外していること】
#   --resume は使わない（ADR-011決定3と同じ流儀。起案役も毎回新規セッション）。
#   --max-budget-usd は渡さない（review_audit.shと同じ理由。ERRORS.md
#   「--max-budget-usdは支出の上限ではなく、ターン境界での打ち切りである」の
#   実測に基づく）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

CLAUDE_TIMEOUT="${CLAUDE_TIMEOUT:-300}"

# ADR-014決定8: 「本来の目的が既に達成され、次にやることが無い」という判断を
# 空文字列で表現させない。scripts/review_proposer_prompt.mdで同じ文言を指示
# しており、プロンプトとスクリプトの両方でこの文言を一貫させる。
NO_FURTHER_ACTION_MARKER="NO_FURTHER_ACTION"

# Issue #225: executor-allowed-toolsが省略された場合（review_proposer.shを
# review_loop.shを介さず単体で試す場合など）に{{EXECUTOR_ALLOWED}}へ埋め込む
# 文言。空文字列のまま埋め込むとプロンプト上で「一覧が空＝何も使えない」と
# 「一覧が渡されていない」を区別できなくなるため、明示的な文言にする。
EXECUTOR_ALLOWED_UNKNOWN_TEXT="（不明。呼び出し元から実行役の許可ツール一覧が渡されていません）"

usage() {
  cat >&2 <<'USAGE'
usage: ./scripts/review_proposer.sh <original-instruction-file> <review-md-file> <output-dir> [executor-allowed-tools]

  original-instruction-file  1ラウンド目のinstructionファイル（テキストファイル、事前に存在すること）
  review-md-file              直近ラウンドのreview.md（テキストファイル、事前に存在すること）
  output-dir                  出力先ディレクトリ（無ければ作成する）
  executor-allowed-tools      省略可。実行役の--allowedToolsと同じカンマ区切り
                              文字列（例: "Read,Edit,Write,Glob,Grep,Bash(./scripts/verify.sh)"）。
                              省略時はEXECUTOR_ALLOWED_UNKNOWN_TEXTを使う

引数は3個または4個。
USAGE
  exit 64
}

die() {
  echo "review_proposer.sh: $*" >&2
  exit 1
}

# プレースホルダ {{ORIGINAL_INSTRUCTION}} / {{REVIEW}} / {{EXECUTOR_ALLOWED}}
# を置換し、prompt_file へ書き出す。review_audit.shのrender_prompt()と同じ理由
# （sedの区切り文字と衝突しないよう、Pythonで単純文字列置換する。元のinstruction・
# review.mdの中身に任意の文字が含まれうるため）。executor_allowedはファイル
# パスではなく文字列そのもの（ORIGINAL_INSTRUCTION/REVIEWと違いファイルの中身を
# 読まない。Issue #225）。
render_prompt() {
  local template="$1" original_instruction_file="$2" review_file="$3" executor_allowed="$4" prompt_file="$5"
  python3 - "$template" "$original_instruction_file" "$review_file" "$executor_allowed" "$prompt_file" <<'PY'
import sys

template_path, original_path, review_path, executor_allowed, out_path = sys.argv[1:6]

with open(template_path, encoding="utf-8") as f:
    text = f.read()
with open(original_path, encoding="utf-8") as f:
    original_text = f.read()
with open(review_path, encoding="utf-8") as f:
    review_text = f.read()

text = text.replace("{{ORIGINAL_INSTRUCTION}}", original_text)
text = text.replace("{{REVIEW}}", review_text)
text = text.replace("{{EXECUTOR_ALLOWED}}", executor_allowed)

with open(out_path, "w", encoding="utf-8") as f:
    f.write(text)
PY
}

# result.json から next_instruction.md・metrics.json を作る。
# claude を呼ばずにこの関数だけを試せるよう、result.json が既に output_dir に
# 存在する前提で動く独立した関数にしてある（変異テスト用。review_audit.shの
# review_audit_process_result()と同じ流儀。このファイルをsourceすれば、
# この関数だけを直接呼び出せる）。
#
# 戻り値（$?）:
#   0  next_instruction.md へ書き出せた
#   2  result.json が空/不正なJSON、または is_error=true
#   3  result フィールドが空だった
review_proposer_process_result() {
  local output_dir="$1"
  local result_json="${output_dir}/result.json"

  if [ ! -s "$result_json" ] || ! jq -e . "$result_json" >/dev/null 2>&1; then
    echo "review_proposer.sh: claude の実行自体が失敗しました（result.jsonが空/不正なJSON）。" >&2
    echo "  ${output_dir}/result.err を確認してください（timeoutによる強制終了の可能性も含む）。" >&2
    return 2
  fi

  local is_error
  is_error="$(jq -r '.is_error // false' "$result_json")"

  # is_error/terminal_reason/permission_denials等は、失敗時の診断にも使うため
  # is_errorの真偽に関わらずここで書き出す（review_audit.shと同じ流儀）。duration_ms
  # はIssue #267（適用されたCLAUDE_TIMEOUTに対して実際にどれだけ時間を要したかを
  # 事後に確認するため）。
  jq '{total_cost_usd, num_turns, duration_ms, is_error, terminal_reason, permission_denials}' \
    "$result_json" > "${output_dir}/metrics.json"

  if [ "$is_error" = "true" ]; then
    local terminal_reason
    terminal_reason="$(jq -r '.terminal_reason // "unknown"' "$result_json")"
    echo "review_proposer.sh: claude の実行が is_error=true（terminal_reason=${terminal_reason}）で終了しました。" >&2
    return 2
  fi

  # jqの `//` は空文字列("")をnull/falseと区別せず真値として扱うため、
  # `.result // empty` だけでは.result=""を検出できない（jq -rは空文字列でも
  # 改行1文字を出力し、ファイルサイズでの空判定[ ! -s ... ]をすり抜けてしまう）。
  # コマンド置換で末尾改行を落としたうえで文字列として空かどうかを判定する。
  local result_text
  result_text="$(jq -r '.result // empty' "$result_json")"

  if [ -z "$result_text" ]; then
    echo "review_proposer.sh: resultフィールドが空でした（出力形式不正）。" >&2
    return 3
  fi

  printf '%s\n' "$result_text" > "${output_dir}/next_instruction.md"

  local first_line
  first_line="$(head -n1 "${output_dir}/next_instruction.md" 2>/dev/null || true)"
  if [ "$first_line" = "$NO_FURTHER_ACTION_MARKER" ]; then
    echo "review_proposer.sh: 起案役は追加の作業が無い（${NO_FURTHER_ACTION_MARKER}）と判断しました。" >&2
  fi

  return 0
}

# Issue #267: 適用されたCLAUDE_TIMEOUTの値を成果物へ書き出す。claude呼び出しの
# 前に呼ぶことで、タイムアウトで強制終了された場合でもこのファイルだけは残る。
# claudeを呼ばずにこの関数だけを試せるよう、独立した関数にしてある
# （review_proposer_process_result()と同じ流儀）。
write_claude_timeout_marker() {
  local output_dir="$1"
  echo "$CLAUDE_TIMEOUT" > "${output_dir}/claude_timeout.txt"
}

main() {
  { [ "$#" -eq 3 ] || [ "$#" -eq 4 ]; } || usage

  local original_instruction_file="$1" review_file="$2" output_dir="$3"
  local executor_allowed="${4:-$EXECUTOR_ALLOWED_UNKNOWN_TEXT}"

  command -v jq >/dev/null || die "jq が必要です（brew install jq / apt install jq）"
  command -v python3 >/dev/null || die "python3 が必要です"

  [ -f "$original_instruction_file" ] || die "original-instruction-file が存在しません: ${original_instruction_file}"
  [ -f "$review_file" ] || die "review-md-file が存在しません: ${review_file}"

  # 相対パスの入力ファイルを、以降 REPO_ROOT へ cd する前に絶対パス化しておく。
  original_instruction_file="$(cd "$(dirname "$original_instruction_file")" && pwd)/$(basename "$original_instruction_file")"
  review_file="$(cd "$(dirname "$review_file")" && pwd)/$(basename "$review_file")"

  mkdir -p "$output_dir"
  output_dir="$(cd "$output_dir" && pwd)"

  # --settings scripts/review_proposer.settings.json をリポジトリルート基準の
  # 相対パスとして解決できるよう、ここでcdする（review_audit.shと同じ流儀）。
  cd "$REPO_ROOT"

  render_prompt "$SCRIPT_DIR/review_proposer_prompt.md" "$original_instruction_file" "$review_file" \
    "$executor_allowed" "${output_dir}/prompt.txt"

  write_claude_timeout_marker "$output_dir"

  timeout "$CLAUDE_TIMEOUT" claude -p \
    --model sonnet \
    --settings scripts/review_proposer.settings.json \
    --output-format json \
    < "${output_dir}/prompt.txt" \
    > "${output_dir}/result.json" \
    2> "${output_dir}/result.err" || true

  review_proposer_process_result "$output_dir"
}

# 変異テストからこのファイルを `source` して review_proposer_process_result・
# render_prompt だけを直接呼び出せるよう、実行ファイルとして呼ばれたときだけ
# main を走らせる（review_audit.sh・review_loop.shと同じ流儀）。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
