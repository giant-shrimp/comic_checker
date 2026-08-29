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
#   5. git status --porcelain と git diff を diff.txt に保存する（ADR-015 案D）
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
# Issue #232: drain_stray_input()が1バイトを読むごとに待つ上限秒数。
# 診断調査（docs/ai_loop_state/review_loop_trial5_2026-08-29.md「8. 検出
# した欠陥」）で使った値を踏襲している。
STDIN_DRAIN_TIMEOUT="${STDIN_DRAIN_TIMEOUT:-0.05}"
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

# Issue #231 / ADR-015（案D）: write_diff_evidence()がdiff.txtの冒頭に置く
# 固定見出し。監査役がstatus節とdiff節を機械的に見分けられるようにする。
# tests/test_review_loop.py もこの2つをソース本文からgrepで取り出して参照する
# ため、値を変えるときはテスト側の追随は不要（テストが本文から読む）だが、
# 見出しの存在自体はテストの前提になっている。
DIFF_EVIDENCE_STATUS_HEADING="=== git status --porcelain ==="
DIFF_EVIDENCE_DIFF_HEADING="=== git diff ==="

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
  local original_instruction="$1" review_md="$2" round_dir="$3" executor_allowed="$4"
  local proposer_dir="${round_dir}/proposer"

  # Issue #225: 起案役へ実行役の許可ツール一覧（EXECUTOR_ALLOWED）を渡し、
  # 実行不可能なinstructionを生成しないよう制約する。
  local proposer_exit=0
  "${SCRIPT_DIR}/review_proposer.sh" "$original_instruction" "$review_md" "$proposer_dir" "$executor_allowed" \
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

# Issue #227: 実行役がmax_turnsに到達すると.resultが空になり、報告
# （report.md）が失われる。それでも作業ツリーに残った変更（成果）だけは
# 保全する。check_executor_result()はexecutor_result.jsonを読んで判定する
# だけの純粋な関数（gitを呼ぶ副作用を持たない）であり、その性質を壊さない
# よう、git diff・git status --porcelainを呼ぶ処理は別関数として切り出す
# （判断の詳細はPR本文参照）。
#
# round_dir/preserved_diff.txt・round_dir/preserved_status.txtへ、呼び出し
# 時点の作業ツリーの状態を書き出す。既存のdiff.txt（正常系で監査役へ渡す
# もの）とは意味が異なるため、別名にしてある。git status --porcelainは
# 新規（未追跡）ファイルを捉えるために別途保存する（git diffには現れない
# ため）。呼び出し元（main()）が既に REPO_ROOT へ cd 済みであることを前提に
# する（既存の`git diff > "${ROUND_DIR}/diff.txt"`と同じ前提）。
#
# 戻り値（$?）:
#   0  作業ツリーに変更があった（保全すべき成果が存在した）
#   1  作業ツリーに変更が無かった（クリーン）
preserve_work_tree_state() {
  local round_dir="$1"
  local diff_file="${round_dir}/preserved_diff.txt"
  local status_file="${round_dir}/preserved_status.txt"

  git diff > "$diff_file" || true
  git status --porcelain > "$status_file" || true

  echo "--- 実行役の作業ツリーの状態を保全しました ---"
  echo "  preserved_diff   : ${diff_file}"
  echo "  preserved_status : ${status_file}"

  if [ -s "$status_file" ]; then
    echo "  作業ツリーに変更があります（上記ファイルを確認してください）。"
    return 0
  fi

  echo "  作業ツリーに変更はありません（実行役は何も変更していません）。"
  return 1
}

# Issue #231 / ADR-015（案D）: 監査役へ渡す diff.txt を生成する。
#
# 欠陥A ―― `git diff`（引数なし）は追跡済みファイルのワークツリー変更しか
# 出力しないため、実行役が新規作成した未追跡ファイルは証拠から抜け落ちる
# （docs/ai_loop_state/review_loop_trial5_2026-08-29.md「8. 欠陥A」、
# docs/ai_loop_state/issue231_options_2026-08-29.md、
# docs/decisions/ADR-015-diff-evidence-untracked-files.md）。
#
# 対処: `git status --porcelain` の出力を冒頭節として連結する。監査役は
# `?? <path>` 行から未追跡ファイルの存在を知り、必要なら実ファイルを Read
# して報告書と照合できる（監査役へその読み方を明記する review_audit_prompt.md
# の改訂は ADR-015 案C＝段2。本関数は段1で、渡す情報を増やすだけ）。
#
# preserve_work_tree_state() と同型: git を呼ぶ副作用を持つ独立関数にして
# ある（source して単体テストできるようにするため）。失敗してもループを
# 止めない（内部の git 呼び出しは `|| true`、関数自体は常に return 0）。
# 呼び出し元（main()）が既に REPO_ROOT へ cd 済みであることを前提にする
# （既存の `git diff > "${ROUND_DIR}/diff.txt"` と同じ前提）。
#
# 出力（out_file）の構成 ―― 見出しは上の DIFF_EVIDENCE_*_HEADING 定数:
#   === git status --porcelain ===
#   <git status --porcelain の出力（空のこともある）>
#   === git diff ===
#   <git diff の出力（空のこともある）>
#
# 戻り値（$?）: 常に 0。作業ツリーがクリーンでも非ゼロにしない
#              （既存の `git diff > ... || true` と同じく、ここで
#               ループを止めるべきではないため）。
write_diff_evidence() {
  local out_file="$1"

  {
    echo "$DIFF_EVIDENCE_STATUS_HEADING"
    git status --porcelain || true
    echo "$DIFF_EVIDENCE_DIFF_HEADING"
    git diff || true
  } > "$out_file" || true

  return 0
}

# Issue #232（欠陥B: 承認プロンプトが先行入力を人間の承認として受理して
# しまう）への対処。docs/ai_loop_state/typeahead_mitigation_options_
# 2026-08-29.md選択肢Bを実装する。承認プロンプトの直前に呼び出し、標準
# 入力バッファに残留しているバイト（先行入力／type-ahead）を検出して
# 警告し、破棄する。段1でこの関数を新設し、段2で下記2箇所の承認プロンプト
# （wait_for_quit_only内・main内の[c=続行 / q=終了]）へ組み込んだ。
#
# 先頭の端末判定ガード（[ ! -t 0 ]）は段2で追加した。type-aheadは人間が
# 端末へキーを先読み入力したときにのみ生じる現象なので、標準入力が端末で
# ない場合（パイプ・リダイレクト経由。承認入力をパイプで渡すテストや
# 非対話実行）は、そこにあるのは捨ててはならない正当な入力として扱い、
# 何もせず return 1 する。
#
# read -t 0 は入力ストリームがEOF（パイプが閉じている等）の場合にも
# 「読める」と判定してしまう既知の挙動があるため（本関数の変異テストで
# 実測確認済み）、実際に読み出せた内容が空でない場合にのみ警告する
# （空ガード）。EOFのみの場合は1バイトも読み出せず buf が空のまま残る。
# 端末判定ガードが先に効くため、この空ガードが主に効くのは端末で改行のみ
# など実質空の先読み入力があった場合。
#
# ループ内で IFS= を指定するのは、既定のIFSのままだと read -n 1 で読んだ
# 1文字が空白のとき変数へ空文字列が代入されてしまい（bashの実測確認済みの
# 挙動）、先行入力中の空白がbufから失われるため。
#
# ファイルへの書き出し・git操作等の副作用は持たない。
#
# 戻り値（$?）:
#   0  先行入力を検出し、破棄した（警告を表示済み）
#   1  先行入力は無かった（標準入力が端末でない場合・EOFのみだった場合を含む）
drain_stray_input() {
  local buf="" ch

  # 端末判定ガード（段2で追加）。先行入力（type-ahead）は人間が端末へキーを
  # 打ち込んだときにのみ発生する現象なので、標準入力が端末でない場合
  # （パイプ・リダイレクト・ヒアドキュメント経由）は何もせず「破棄して
  # いない」を返す。このガードが無いと、承認プロンプトへパイプで渡された
  # 正当な入力（tests/test_review_loop.py が input= で渡す "q"／"c" 等、
  # および非対話実行での入力）を先行入力と誤認して破棄してしまう
  # （段2の組み込み時、ガード無しで test_wait_for_quit_only_accepts_q 等が
  # 実際に落ちることを実測で確認済み）。
  if [ ! -t 0 ]; then
    return 1
  fi

  if read -t 0; then
    while IFS= read -t "$STDIN_DRAIN_TIMEOUT" -n 1 -r ch; do
      buf+="$ch"
    done
  fi

  if [ -z "$buf" ]; then
    return 1
  fi

  # od -An -c は制御文字を \n や 033（8進）のような表記に変換するため、
  # 破棄した内容をそのまま端末へ出力しても制御文字が実行されない
  # （エスケープシーケンス等がそのまま流れ込まない）。
  local escaped
  escaped="$(printf '%s' "$buf" | od -An -c)"
  echo "review_loop.sh: 先行入力（${#buf}バイト）を検出したため破棄しました。内容:${escaped}"

  return 0
}

# 人間の1キー入力（q のみ）を待つ。ADR-011決定8の「1キーで承認」という形式を
# 保ったまま、続行できない理由が複数（VERDICTがHALT_NEEDS_HUMAN／DONE、
# 起案役の呼び出し失敗、NO_FURTHER_ACTION）に増えたため関数へ切り出した。
wait_for_quit_only() {
  local reason="$1"
  local key
  while true; do
    drain_stray_input || true
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
    # Issue #227: 人間が判断する前に、作業ツリーに残った成果を保全する。
    preserve_work_tree_state "$ROUND_DIR" || true
    wait_for_quit_only "実行役が正常終了しなかった（is_error=true, terminal_reason=${EXECUTOR_TERMINAL_REASON}）"
    echo "review_loop.sh: round ${round} で終了します（実行役 is_error=true）。"
    exit 0
  fi

  jq -r '.result // empty' "${ROUND_DIR}/executor_result.json" > "${ROUND_DIR}/report.md"

  ./scripts/verify.sh > "${ROUND_DIR}/verify.txt" 2>&1 || true
  # Issue #231 / ADR-015（案D）: git diff 単独ではなく git status --porcelain も
  # 連結し、未追跡ファイル（新規作成物）を監査役の証拠に含める。
  write_diff_evidence "${ROUND_DIR}/diff.txt" || true

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
  propose_next_instruction "$ORIGINAL_INSTRUCTION_FILE" "${ROUND_DIR}/review.md" "$ROUND_DIR" "$EXECUTOR_ALLOWED" \
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
    drain_stray_input || true
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
