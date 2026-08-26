#!/usr/bin/env bash
#
# ADR-011（docs/decisions/ADR-011-review-loop-design.md）段階0のオーケストレータ。
# 「毎ラウンド人間が1キーで承認する」段階0**のみ**を実装する。段階1（条件付き
# 自動継続）以降は実装しない（決定8）。
#
# 使い方:
#   ./scripts/review_loop.sh <instruction-file>
#
# 1ラウンドの流れ（決定4）:
#   1. ~/comic_checker-agent-notes/review_loop/<session>/round_N/ を作る
#   2. instructionを実行役（sonnet, work_loop.settings.jsonを流用）に投入する
#   3. 実行役の出力（resultフィールド）を report.md に保存する
#   4. ./scripts/verify.sh を実行し、出力を verify.txt に保存する
#   5. git diff を diff.txt に保存する
#   6. scripts/review_audit.sh diff.txt verify.txt report.md <round-dir> を呼ぶ
#   7. 人間にVERDICT・CONTRADICTIONS・各ファイルの絶対パスを見せ、1キー入力を待つ
#      （c=次ラウンドへ / q=終了。VERDICTがHALT_NEEDS_HUMANまたはDONEのときはqのみ）
#   8. cならreview.mdの内容を次ラウンドのinstructionにする
#
# 停止条件（決定9。人間の入力を待たず強制終了する）:
#   - ラウンド数がMAX_ROUNDS（既定10、環境変数で変更可）に達した
#   - 同じVERDICTが2ラウンド連続した
#   - no-opハッシュ（snapshot()）が前ラウンドと不変
#
# 終了コード:
#   0   人間が q を選んで正常終了
#   2   実行役の呼び出し自体が失敗（timeoutでexecutor_result.jsonが空/不正なJSON）
#   10  停止条件: ラウンド数上限に到達
#   11  停止条件: 同一VERDICTが2ラウンド連続
#   12  停止条件: no-opハッシュが前ラウンドと不変
#   13  監査役の呼び出しが成立しなかった（review_audit.shがexit 0以外）
#   1   前提条件エラー（jq不在・instruction-file不在等）
#   64  引数の個数が誤り
#
# 【禁止事項として意図的に外していること】
#   git commit / push / PR作成 / Issue作成は一切行わない（段階0では成果物は
#   ローカルに留める）。--resume は使わない（決定3。毎ラウンド新規セッション。
#   前ラウンドの文脈は次instructionのテキストとしてのみ引き継がれる）。
#   --max-budget-usd は渡さない（ERRORS.md「--max-budget-usdは支出の上限では
#   なく、ターン境界での打ち切りである」の実測に基づく。支出の制御は
#   MAX_ROUNDS と --max-turns で行う。決定10。review_audit.sh側も同じ設計）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

MAX_ROUNDS="${MAX_ROUNDS:-10}"
EXECUTOR_MAX_TURNS="${EXECUTOR_MAX_TURNS:-20}"
CLAUDE_TIMEOUT="${CLAUDE_TIMEOUT:-300}"
# 実行役に許可するツール。work_loop.shのALLOWEDを参考にしたが、GitHub Issueは
# 扱わない（instructionはファイルで直接渡す）ため gh issue view を、
# diffはこのスクリプト自身がstep5で取るため git diff をそれぞれ外している。
EXECUTOR_ALLOWED="Read,Edit,Write,Glob,Grep,Bash(./scripts/verify.sh)"
LOOP_HOME="${HOME}/comic_checker-agent-notes/review_loop"

usage() {
  cat >&2 <<'USAGE'
usage: ./scripts/review_loop.sh <instruction-file>
USAGE
  exit 64
}

die() {
  echo "review_loop.sh: $*" >&2
  exit 1
}

# work_loop.sh の snapshot() と完全に同一の計算方法（意図的な複製）。
# 共通化するには work_loop.sh 側を「共有ファイルをsourceする」形へ変更する
# 必要があるが、本タスクの範囲は review_loop.sh の新規作成に限られ、
# 既に運用中の work_loop.sh には触れない（手順0・手順5の前提）。そのため
# ここでは複製に留める。計算式を変えるときはwork_loop.sh側も手で追随させること。
snapshot() {
  {
    git status --porcelain
    git diff HEAD
    git ls-files --others --exclude-standard -z \
      | xargs -0 -r sha256sum 2>/dev/null || true
  } | sha256sum | cut -d' ' -f1
}

[ "$#" -eq 1 ] || usage

command -v jq >/dev/null || die "jq が必要です（brew install jq / apt install jq）"

INSTRUCTION_FILE="$1"
[ -f "$INSTRUCTION_FILE" ] || die "instruction-file が存在しません: ${INSTRUCTION_FILE}"
INSTRUCTION_FILE="$(cd "$(dirname "$INSTRUCTION_FILE")" && pwd)/$(basename "$INSTRUCTION_FILE")"

SESSION="$(date +%Y%m%d-%H%M%S)"
SESSION_DIR="${LOOP_HOME}/${SESSION}"
mkdir -p "$SESSION_DIR"
echo "review_loop.sh: セッション ${SESSION} を開始します（${SESSION_DIR}）。"

CURRENT_INSTRUCTION_FILE="$INSTRUCTION_FILE"
PREV_VERDICT=""
PREV_SNAPSHOT=""

for ((round = 1; round <= MAX_ROUNDS; round++)); do
  ROUND_DIR="${SESSION_DIR}/round_${round}"
  mkdir -p "$ROUND_DIR"
  echo
  echo "=== round ${round}/${MAX_ROUNDS} (${ROUND_DIR}) ==="

  cp "$CURRENT_INSTRUCTION_FILE" "${ROUND_DIR}/instruction.md"

  cd "$REPO_ROOT"

  # プロンプトはargvではなくstdin経由で渡す（review_audit.shと同じ理由。
  # ラウンドが進むほどinstruction＝前ラウンドのreview.mdが長くなりうるため）。
  timeout "$CLAUDE_TIMEOUT" claude -p \
    --model sonnet \
    --max-turns "$EXECUTOR_MAX_TURNS" \
    --allowedTools "$EXECUTOR_ALLOWED" \
    --settings "${SCRIPT_DIR}/work_loop.settings.json" \
    --output-format json \
    < "${ROUND_DIR}/instruction.md" \
    > "${ROUND_DIR}/executor_result.json" \
    2> "${ROUND_DIR}/executor_result.err" || true

  if [ ! -s "${ROUND_DIR}/executor_result.json" ] || ! jq -e . "${ROUND_DIR}/executor_result.json" >/dev/null 2>&1; then
    echo "review_loop.sh: 実行役の呼び出し自体が失敗しました。" >&2
    echo "  ${ROUND_DIR}/executor_result.err を確認してください（timeoutの可能性も含む）。" >&2
    exit 2
  fi
  jq -r '.result // empty' "${ROUND_DIR}/executor_result.json" > "${ROUND_DIR}/report.md"

  ./scripts/verify.sh > "${ROUND_DIR}/verify.txt" 2>&1 || true
  git diff > "${ROUND_DIR}/diff.txt" || true

  audit_exit=0
  "${SCRIPT_DIR}/review_audit.sh" "${ROUND_DIR}/diff.txt" "${ROUND_DIR}/verify.txt" "${ROUND_DIR}/report.md" "$ROUND_DIR" \
    || audit_exit=$?

  if [ "$audit_exit" -ne 0 ]; then
    echo "review_loop.sh: 監査役の呼び出しが成立しませんでした（review_audit.sh exit=${audit_exit}）。" >&2
    echo "  ${ROUND_DIR}/result.err ${ROUND_DIR}/result.json を確認してください。" >&2
    exit 13
  fi

  VERDICT="$(cat "${ROUND_DIR}/verdict.txt")"
  ROUND_SNAPSHOT="$(snapshot)"

  echo
  echo "--- round ${round} 監査結果 ---"
  echo "VERDICT: ${VERDICT}"
  echo
  echo "CONTRADICTIONS:"
  awk '/^CONTRADICTIONS:/{flag=1; next} /^FOLLOWUPS:/{flag=0} flag' "${ROUND_DIR}/review.md"
  echo
  echo "ファイル:"
  echo "  instruction : ${ROUND_DIR}/instruction.md"
  echo "  report      : ${ROUND_DIR}/report.md"
  echo "  diff        : ${ROUND_DIR}/diff.txt"
  echo "  verify      : ${ROUND_DIR}/verify.txt"
  echo "  review      : ${ROUND_DIR}/review.md"
  echo "  metrics     : ${ROUND_DIR}/metrics.json"
  echo

  # 停止条件（決定9）。ここに該当したら人間の入力を待たず強制終了する。
  if [ "$round" -ge "$MAX_ROUNDS" ]; then
    echo "review_loop.sh: 強制終了 — ラウンド数上限（${MAX_ROUNDS}）に到達しました。" >&2
    exit 10
  fi
  if [ -n "$PREV_VERDICT" ] && [ "$VERDICT" = "$PREV_VERDICT" ]; then
    echo "review_loop.sh: 強制終了 — 同一VERDICT（${VERDICT}）が2ラウンド連続しました。" >&2
    exit 11
  fi
  if [ -n "$PREV_SNAPSHOT" ] && [ "$ROUND_SNAPSHOT" = "$PREV_SNAPSHOT" ]; then
    echo "review_loop.sh: 強制終了 — no-opハッシュが前ラウンドと不変です（変更が生じていません）。" >&2
    exit 12
  fi

  # VERDICTがHALT_NEEDS_HUMANまたはDONEの場合は c を選べない（終了のみ）。
  if [ "$VERDICT" = "HALT_NEEDS_HUMAN" ] || [ "$VERDICT" = "DONE" ]; then
    while true; do
      read -n 1 -r -p "VERDICT=${VERDICT} のため続行できません。終了します [q]: " KEY
      echo
      if [ "$KEY" = "q" ]; then
        echo "review_loop.sh: round ${round} で終了します（VERDICT=${VERDICT}）。"
        exit 0
      fi
      echo "review_loop.sh: q のみ入力できます。"
    done
  fi

  while true; do
    read -n 1 -r -p "次ラウンドへ進みますか？ [c=続行 / q=終了]: " KEY
    echo
    case "$KEY" in
      c)
        PREV_VERDICT="$VERDICT"
        PREV_SNAPSHOT="$ROUND_SNAPSHOT"
        CURRENT_INSTRUCTION_FILE="${ROUND_DIR}/review.md"
        break
        ;;
      q)
        echo "review_loop.sh: 人間の指示により round ${round} で終了します。"
        exit 0
        ;;
      *)
        echo "review_loop.sh: c または q を入力してください。"
        ;;
    esac
  done
done
