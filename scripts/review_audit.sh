#!/usr/bin/env bash
#
# ADR-011（docs/decisions/ADR-011-review-loop-design.md）の監査役1回分の呼び出し。
# ループ本体（オーケストレータ）はまだ無い。この段階では「1回分の監査を実行し、
# VERDICT・矛盾点・改善提案・実測メトリクスをファイルに残す」ことだけを行う。
#
# 使い方:
#   ./scripts/review_audit.sh <diff-file> <verify-output-file> <report-file> <output-dir>
#
# 出力（すべて <output-dir> 配下）:
#   prompt.txt    実際に投入したプロンプト全文
#   result.json   claude -p --output-format json の生出力
#   result.err    claude 実行時の標準エラー
#   review.md     result.json の result フィールド（監査役の出力本文）
#   verdict.txt   review.md の1行目から抽出したVERDICT値（1語のみ）
#   metrics.json  total_cost_usd / num_turns / is_error / terminal_reason /
#                 permission_denials（ADR-011決定10。logs/ と違いgitignoreされない
#                 場所に残すため）
#
# 終了コード:
#   0  VERDICTが4値（APPROVE_CONTINUE/REVISE/HALT_NEEDS_HUMAN/DONE）のいずれかとして
#      抽出できた。**「監査が成立した」ことのみを意味し、VERDICTの内容そのものは
#      問わない。** 呼び出し側がverdict.txtを読んで判断すること。
#   2  claude の実行自体が失敗（timeoutでresult.jsonが空/不正なJSON、または
#      is_error=trueで終了）
#   3  実行は成功したが、VERDICTが1行目から抽出できない、または4値以外だった
#   1  引数エラー以外の前提条件エラー（jq不在・入力ファイル不在等）
#   64 引数の個数が誤り（usage参照。loop_git.shと同じ流儀）
#
# 【禁止事項として意図的に外していること】
#   --resume は使わない（ADR-011決定3。監査役は毎回新規セッション）。
#   --max-budget-usd は渡さない（ERRORS.md「--max-budget-usdは支出の上限ではなく、
#   ターン境界での打ち切りであり、上限を大きく超えて課金されうる」の実測により、
#   1ターンあたりの支出を抑える効果を持たないと分かっているため。支出の制御は
#   呼び出し元の timeout とラウンド上限で行う、というADR-011決定10の設計）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

CLAUDE_TIMEOUT="${CLAUDE_TIMEOUT:-300}"
VALID_VERDICTS_RE='^VERDICT: (APPROVE_CONTINUE|REVISE|HALT_NEEDS_HUMAN|DONE)[[:space:]]*$'

usage() {
  cat >&2 <<'USAGE'
usage: ./scripts/review_audit.sh <diff-file> <verify-output-file> <report-file> <output-dir>

  diff-file           監査対象のdiff（テキストファイル、事前に存在すること）
  verify-output-file  ./scripts/verify.sh の実出力（テキストファイル、事前に存在すること）
  report-file         作業者の報告書（テキストファイル、事前に存在すること）
  output-dir          出力先ディレクトリ（無ければ作成する）

引数はちょうど4個。
USAGE
  exit 64
}

die() {
  echo "review_audit.sh: $*" >&2
  exit 1
}

# プレースホルダ {{DIFF}} / {{VERIFY}} / {{REPORT}} を対応ファイルの中身で
# 置換し、prompt_file へ書き出す。sed の区切り文字と衝突しないよう、
# Pythonで単純文字列置換する（diff・報告書の中身に任意の文字が含まれうるため）。
render_prompt() {
  local template="$1" diff_file="$2" verify_file="$3" report_file="$4" prompt_file="$5"
  python3 - "$template" "$diff_file" "$verify_file" "$report_file" "$prompt_file" <<'PY'
import sys

template_path, diff_path, verify_path, report_path, out_path = sys.argv[1:6]

with open(template_path, encoding="utf-8") as f:
    text = f.read()
with open(diff_path, encoding="utf-8") as f:
    diff_text = f.read()
with open(verify_path, encoding="utf-8") as f:
    verify_text = f.read()
with open(report_path, encoding="utf-8") as f:
    report_text = f.read()

text = text.replace("{{DIFF}}", diff_text)
text = text.replace("{{VERIFY}}", verify_text)
text = text.replace("{{REPORT}}", report_text)

with open(out_path, "w", encoding="utf-8") as f:
    f.write(text)
PY
}

# result.json から review.md・verdict.txt・metrics.json を作る。
# claude を呼ばずにこの関数だけを試せるよう、result.json が既に output_dir に
# 存在する前提で動く独立した関数にしてある（変異テスト用。このファイルを
# `source` すれば、この関数だけを直接呼び出せる）。
#
# 戻り値（$?）:
#   0  VERDICTを抽出できた
#   2  result.json が空/不正なJSON、または is_error=true
#   3  VERDICTを1行目から抽出できない、または4値以外
review_audit_process_result() {
  local output_dir="$1"
  local result_json="${output_dir}/result.json"

  if [ ! -s "$result_json" ] || ! jq -e . "$result_json" >/dev/null 2>&1; then
    echo "review_audit.sh: claude の実行自体が失敗しました（result.jsonが空/不正なJSON）。" >&2
    echo "  ${output_dir}/result.err を確認してください（timeoutによる強制終了の可能性も含む）。" >&2
    return 2
  fi

  local is_error
  is_error="$(jq -r '.is_error // false' "$result_json")"

  # is_error/terminal_reason/permission_denials等は、失敗時の診断にも使うため
  # is_errorの真偽に関わらずここで書き出す。
  jq '{total_cost_usd, num_turns, is_error, terminal_reason, permission_denials}' \
    "$result_json" > "${output_dir}/metrics.json"

  if [ "$is_error" = "true" ]; then
    local terminal_reason
    terminal_reason="$(jq -r '.terminal_reason // "unknown"' "$result_json")"
    echo "review_audit.sh: claude の実行が is_error=true（terminal_reason=${terminal_reason}）で終了しました。" >&2
    return 2
  fi

  jq -r '.result // empty' "$result_json" > "${output_dir}/review.md"

  local first_line
  first_line="$(head -n1 "${output_dir}/review.md" 2>/dev/null || true)"

  if [[ "$first_line" =~ $VALID_VERDICTS_RE ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}" > "${output_dir}/verdict.txt"
    return 0
  fi

  echo "review_audit.sh: review.mdの1行目からVERDICTを抽出できませんでした。" >&2
  echo "  1行目: ${first_line}" >&2
  return 3
}

main() {
  [ "$#" -eq 4 ] || usage

  local diff_file="$1" verify_file="$2" report_file="$3" output_dir="$4"

  command -v jq >/dev/null || die "jq が必要です（brew install jq / apt install jq）"
  command -v python3 >/dev/null || die "python3 が必要です"

  [ -f "$diff_file" ] || die "diff-file が存在しません: ${diff_file}"
  [ -f "$verify_file" ] || die "verify-output-file が存在しません: ${verify_file}"
  [ -f "$report_file" ] || die "report-file が存在しません: ${report_file}"

  # 相対パスの入力ファイルを、以降 REPO_ROOT へ cd する前に絶対パス化しておく。
  diff_file="$(cd "$(dirname "$diff_file")" && pwd)/$(basename "$diff_file")"
  verify_file="$(cd "$(dirname "$verify_file")" && pwd)/$(basename "$verify_file")"
  report_file="$(cd "$(dirname "$report_file")" && pwd)/$(basename "$report_file")"

  mkdir -p "$output_dir"
  output_dir="$(cd "$output_dir" && pwd)"

  # --settings scripts/review_audit.settings.json をリポジトリルート基準の
  # 相対パスとして解決できるよう、ここでcdする（loop_git.shと同じ流儀）。
  cd "$REPO_ROOT"

  render_prompt "$SCRIPT_DIR/review_audit_prompt.md" "$diff_file" "$verify_file" "$report_file" \
    "${output_dir}/prompt.txt"

  timeout "$CLAUDE_TIMEOUT" claude -p \
    --model opus \
    --settings scripts/review_audit.settings.json \
    --output-format json \
    < "${output_dir}/prompt.txt" \
    > "${output_dir}/result.json" \
    2> "${output_dir}/result.err" || true

  review_audit_process_result "$output_dir"
}

# 変異テストからこのファイルを `source` して review_audit_process_result だけを
# 直接呼び出せるよう、実行ファイルとして呼ばれたときだけ main を走らせる。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
