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
#   7. 起案役（scripts/review_proposer.sh）を呼び、次ラウンドのinstructionを
#      生成する（ADR-014決定6。監査役の直後、人間の1キー入力より前）。
#      VERDICTがDONE／HALT_NEEDS_HUMANのラウンドでは次ラウンドが存在しない
#      ため起案役を呼ばない
#   8. 人間にVERDICT・CONTRADICTIONS・次ラウンドのinstruction本文・各ファイルの
#      絶対パスを見せ、1キー入力を待つ
#      （c=次ラウンドへ / q=終了。次のいずれかのときはqのみ:
#       VERDICTがHALT_NEEDS_HUMAN／DONE、起案役の呼び出しが失敗、
#       起案役がNO_FURTHER_ACTIONと判断）
#   9. cなら起案役が生成したinstructionを次ラウンドのinstructionにする
#      （ADR-014決定3。build_next_instruction()による review.md の機械抽出は
#      廃止した）
#
# 停止条件（決定9。人間の入力を待たず強制終了する）:
#   - ラウンド数がMAX_ROUNDS（既定10、環境変数で変更可）に達した
#   - 同じVERDICTが2ラウンド連続した
#   - no-opハッシュ（snapshot()）が前ラウンドと不変
#
# 終了コード:
#   0   人間が q を選んで正常終了（起案役の呼び出しが失敗した場合・起案役が
#       NO_FURTHER_ACTIONと判断した場合・実行役がis_error=trueで終了した場合
#       （Issue #223）も、人間が q を押してここへ合流する。
#       ADR-014が「未決定」として残していた「起案役の失敗に新しい終了コードを
#       新設するか否か」は、**新設しない**と判断した。決定8が定める扱いは
#       「HALT_NEEDS_HUMAN相当／DONE相当として人間の判断待ちにする」ことであり、
#       これは既存のq限定入力待ちの分岐でそのまま表現できる。ループは
#       強制終了せず人間の入力を待つため、停止条件（exit 10-12）のような
#       新しい終了コードを必要としない。実行役のis_error=true検出（Issue #223）
#       も同じ思想で同じ扱いとし、新しい終了コードは割り当てていない）
#   2   実行役の呼び出し自体が失敗（timeoutでexecutor_result.jsonが空/不正なJSON。
#       executor_result.jsonが有効なJSONだがis_error=trueの場合はexit 2ではなく
#       上記exit 0の経路に入る。「呼び出し自体の失敗」と「呼び出しは成立したが
#       完了しなかった」を区別している。Issue #223）
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

# ADR-014決定8: 起案役が「本来の目的は達成済みで次にやることが無い」と判断した
# ことを表すマーカー。scripts/review_proposer.sh・scripts/review_proposer_prompt.md
# と同じ文言でなければならない（snapshot()をwork_loop.shから複製しているのと
# 同じく、意図的な複製である。文言を変えるときは3ファイルすべてを手で追随させること）。
NO_FURTHER_ACTION_MARKER="NO_FURTHER_ACTION"

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

# ADR-014決定6: 起案役を呼び、次ラウンドのinstructionを生成する。
#
# ADR-014決定3により、旧 build_next_instruction()（review.mdからFOLLOWUPS節を
# awkで除去して次のinstructionにしていた、ADR-012決定3の実装）は廃止した。
# 機械抽出という方式そのものを廃止したため、ADR-013決定4（CONTRADICTIONS節
# 内側の仕様外コンテンツを除去できない欠陥への対処）も不要になっている
# （ADR-014決定3でsupersede済み）。
#
# 起案役の出力先を round_dir 直下ではなく round_dir/proposer/ にしているのは、
# review_audit.sh と review_proposer.sh が同名のファイル（prompt.txt /
# result.json / result.err / metrics.json）を出力先ディレクトリに書くため。
# 同じ round_N/ を渡すと監査役の記録が起案役に上書きされる。ADR-011決定4は
# 1ラウンドにつきinstruction/report/review/verdictの4ファイルを round_N/ に
# 残すことを定めるのみで、サブディレクトリを禁じていない。
#
# 変異テストで単体検証できるよう、review_audit.shのreview_audit_process_result
# と同様に独立した関数にしてある（テストからは SCRIPT_DIR を差し替えて
# 偽の review_proposer.sh を呼ばせる）。
#
# 戻り値（$?）:
#   0  次ラウンドのinstructionを生成できた（out_file が使える）
#   1  起案役の呼び出しが失敗した（review_proposer.shがexit 0以外）。
#      ADR-014決定8によりHALT_NEEDS_HUMAN相当として扱う
#   2  起案役が「次にやることが無い」と判断した（NO_FURTHER_ACTION）。
#      ADR-014決定8によりDONE相当として扱う（失敗ではない）
propose_next_instruction() {
  local original_instruction="$1" review_md="$2" round_dir="$3"
  local proposer_dir="${round_dir}/proposer"

  local proposer_exit=0
  "${SCRIPT_DIR}/review_proposer.sh" "$original_instruction" "$review_md" "$proposer_dir" \
    || proposer_exit=$?

  if [ "$proposer_exit" -ne 0 ]; then
    return 1
  fi

  local first_line
  first_line="$(head -n1 "${proposer_dir}/next_instruction.md" 2>/dev/null || true)"
  if [ "$first_line" = "$NO_FURTHER_ACTION_MARKER" ]; then
    return 2
  fi

  return 0
}

# Issue #223: 実行役呼び出し直後のexecutor_result.jsonを検査する。
# 「呼び出し自体の失敗（executor_result.jsonが空/不正なJSON）」と
# 「呼び出しは成立したが実行役が完了しなかった（is_error=true。典型例:
# max_turns到達）」を区別する。前者を検出しないままだと、後者のケースで
# 空のreport.mdのまま監査役へ進んでしまう欠陥があった
# （docs/ai_loop_state/review_loop_trial3_2026-08-29.md「4. 欠陥1」）。
#
# claudeを呼ばずにこの関数だけを試せるよう、executor_result.jsonが既に
# round_dirに存在する前提で動く独立した関数にしてある（変異テスト用。
# review_audit.shのreview_audit_process_result()と同じ流儀）。is_error=true
# の場合、terminal_reason・num_turnsを画面へ出力する（呼び出し元でwait_for_
# quit_onlyへ渡す前の、人間向けの診断表示）。
#
# 戻り値（$?）:
#   0  is_error=false（従来どおり後続処理へ進んでよい）
#   1  is_error=true（実行役が完了しなかった。診断情報を画面へ出力済み）
#   2  executor_result.jsonが空/不正なJSON（呼び出し自体の失敗）
check_executor_result() {
  local round_dir="$1"
  local executor_result="${round_dir}/executor_result.json"

  if [ ! -s "$executor_result" ] || ! jq -e . "$executor_result" >/dev/null 2>&1; then
    return 2
  fi

  local is_error
  is_error="$(jq -r '.is_error // false' "$executor_result")"
  if [ "$is_error" = "true" ]; then
    local terminal_reason num_turns
    terminal_reason="$(jq -r '.terminal_reason // "unknown"' "$executor_result")"
    num_turns="$(jq -r '.num_turns // "unknown"' "$executor_result")"
    echo "--- 実行役が正常終了しませんでした ---"
    echo "terminal_reason : ${terminal_reason}"
    echo "num_turns       : ${num_turns}"
    echo "executor_result : ${executor_result}"
    echo "executor_err    : ${round_dir}/executor_result.err"
    return 1
  fi

  return 0
}

# 人間の1キー入力（q のみ）を待つ。ADR-011決定8の「1キーで承認」という形式を
# 保ったまま、続行できない理由が複数（VERDICTがHALT_NEEDS_HUMAN／DONE、
# 起案役の呼び出し失敗、NO_FURTHER_ACTION）に増えたため関数へ切り出した。
wait_for_quit_only() {
  local reason="$1"
  local key
  while true; do
    read -n 1 -r -p "${reason}のため続行できません。終了します [q]: " key
    echo
    if [ "$key" = "q" ]; then
      return 0
    fi
    echo "review_loop.sh: q のみ入力できます。"
  done
}

main() {

[ "$#" -eq 1 ] || usage

command -v jq >/dev/null || die "jq が必要です（brew install jq / apt install jq）"

# ブランチ検査（work_loop.shのプリフライト4と同じ流儀。エラーメッセージの
# 書き方・git rev-parse --abbrev-ref HEADによる取得・exit 1の前提条件エラー
# 扱いを揃えた）。ただし判定の向きはwork_loop.shとは逆になる。work_loop.sh
# はmainから新しいループブランチを分岐させるためmain "である"ことを要求するが、
# review_loop.shは実行役に既存の作業ブランチ上でファイルを編集させる設計
# （新しいブランチをこのスクリプト自身が作ることはしない）なので、main "で
# ない"ことを要求する。main上で実行すると、実行役の変更がそのままmainの
# 作業ツリーに入ってしまう。
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" = "main" ]; then
  echo "review_loop.sh: エラー: main 上で実行しています。" >&2
  echo "      作業用ブランチを作成してから再実行してください（例:" >&2
  echo "      git checkout -b fix/some-topic）。" >&2
  exit 1
fi

INSTRUCTION_FILE="$1"
[ -f "$INSTRUCTION_FILE" ] || die "instruction-file が存在しません: ${INSTRUCTION_FILE}"
INSTRUCTION_FILE="$(cd "$(dirname "$INSTRUCTION_FILE")" && pwd)/$(basename "$INSTRUCTION_FILE")"

SESSION="$(date +%Y%m%d-%H%M%S)"
SESSION_DIR="${LOOP_HOME}/${SESSION}"
mkdir -p "$SESSION_DIR"
echo "review_loop.sh: セッション ${SESSION} を開始します（${SESSION_DIR}）。"

CURRENT_INSTRUCTION_FILE="$INSTRUCTION_FILE"
# ADR-014決定1: 起案役には「1ラウンド目のinstruction（本来の目的）」と
# 「直近ラウンドのreview.md」の2つを渡す。CURRENT_INSTRUCTION_FILEは毎ラウンド
# 起案役の出力で上書きされるため、1ラウンド目のパスを別変数で保持する。
# この変数はループ内で再代入してはならない（再代入すると、trial2で観測された
# 「元のタスクの目的が失われる」という no-op の原因が再発する）。
ORIGINAL_INSTRUCTION_FILE="$INSTRUCTION_FILE"
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

  executor_check=0
  check_executor_result "$ROUND_DIR" || executor_check=$?

  if [ "$executor_check" -eq 2 ]; then
    echo "review_loop.sh: 実行役の呼び出し自体が失敗しました。" >&2
    echo "  ${ROUND_DIR}/executor_result.err を確認してください（timeoutの可能性も含む）。" >&2
    exit 2
  fi

  # Issue #223: 呼び出し自体（executor_result.jsonが有効なJSONであること）は
  # 成立していても、is_error=trueは「実行役が最後まで完了しなかった」ことを
  # 示す（典型例: max_turns到達）。exit 2（呼び出し自体の失敗）とは性質が
  # 異なるため区別する。強制終了（新しいexit code）ではなく、ADR-014決定8が
  # 起案役の失敗について採った「HALT_NEEDS_HUMAN相当として人間の判断待ちに
  # する」という思想に揃え、wait_for_quit_only()でq限定の入力待ちにする。
  # ADR-011決定8の1キー承認をここでも維持する。
  if [ "$executor_check" -eq 1 ]; then
    EXECUTOR_TERMINAL_REASON="$(jq -r '.terminal_reason // "unknown"' "${ROUND_DIR}/executor_result.json")"
    wait_for_quit_only "実行役が正常終了しなかった（is_error=true, terminal_reason=${EXECUTOR_TERMINAL_REASON}）"
    echo "review_loop.sh: round ${round} で終了します（実行役 is_error=true）。"
    exit 0
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
  # このとき次ラウンドは存在しないため、起案役も呼ばない（ADR-014決定6）。
  if [ "$VERDICT" = "HALT_NEEDS_HUMAN" ] || [ "$VERDICT" = "DONE" ]; then
    wait_for_quit_only "VERDICT=${VERDICT}"
    echo "review_loop.sh: round ${round} で終了します（VERDICT=${VERDICT}）。"
    exit 0
  fi

  # 起案役を呼ぶ（ADR-014決定6。監査役の直後、人間の1キー入力より前）。
  echo "review_loop.sh: 起案役を呼び出しています（次ラウンドのinstructionを生成）..."
  propose_exit=0
  propose_next_instruction "$ORIGINAL_INSTRUCTION_FILE" "${ROUND_DIR}/review.md" "$ROUND_DIR" \
    || propose_exit=$?

  NEXT_INSTRUCTION_FILE="${ROUND_DIR}/proposer/next_instruction.md"

  # ADR-014決定8: 起案役の呼び出しが失敗した場合はHALT_NEEDS_HUMAN相当、
  # NO_FURTHER_ACTIONの場合はDONE相当として扱い、いずれも c を選べなくする。
  # build_next_instruction()へのフォールバックは行わない（決定3で廃止済みで
  # あり、そもそもフォールバック先が存在しない）。
  if [ "$propose_exit" -eq 1 ]; then
    echo "review_loop.sh: 起案役の呼び出しが失敗しました。" >&2
    echo "  ${ROUND_DIR}/proposer/result.err ${ROUND_DIR}/proposer/result.json を確認してください。" >&2
    wait_for_quit_only "起案役の呼び出し失敗（HALT_NEEDS_HUMAN相当）"
    echo "review_loop.sh: round ${round} で終了します（起案役の呼び出し失敗）。"
    exit 0
  fi

  if [ "$propose_exit" -eq 2 ]; then
    echo "--- 起案役の判断: 次に実行すべき作業は無い（${NO_FURTHER_ACTION_MARKER}） ---"
    echo "判断根拠:"
    tail -n +2 "$NEXT_INSTRUCTION_FILE"
    echo
    wait_for_quit_only "${NO_FURTHER_ACTION_MARKER}（DONE相当）"
    echo "review_loop.sh: round ${round} で終了します（${NO_FURTHER_ACTION_MARKER}）。"
    exit 0
  fi

  # 生成された次ラウンドのinstruction本文を、承認の判断材料として提示する
  # （ADR-014決定6。従来の「次ラウンドへ進むこと」への承認から、「この指示で
  # 進むこと」への承認に変わる）。
  echo "--- 起案役が生成した次ラウンドのinstruction ---"
  cat "$NEXT_INSTRUCTION_FILE"
  echo
  echo "  next instruction : ${NEXT_INSTRUCTION_FILE}"
  echo "  proposer metrics : ${ROUND_DIR}/proposer/metrics.json"
  echo

  while true; do
    read -n 1 -r -p "この指示で次ラウンドへ進みますか？ [c=続行 / q=終了]: " KEY
    echo
    case "$KEY" in
      c)
        PREV_VERDICT="$VERDICT"
        PREV_SNAPSHOT="$ROUND_SNAPSHOT"
        CURRENT_INSTRUCTION_FILE="$NEXT_INSTRUCTION_FILE"
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

}

# 変異テストからこのファイルを`source`してpropose_next_instruction・
# wait_for_quit_only等だけを直接呼び出せるよう、実行ファイルとして呼ばれた
# ときだけmainを走らせる（review_audit.shと同じ流儀）。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
