#!/usr/bin/env bash
#
# AI Loop実装計画書 Phase 7 が挙げる効果測定の3指標（採用率／受け入れ1件
# あたりのコスト／verify.shをすり抜けた不具合の件数）と、静かな失敗の兆候
# （実行時間の異常）を集計する。
#
# このスクリプトが行うのは「数えること」だけである。赤信号かどうかの判定・
# 提言は一切出力しない（読み方は計画書 Phase 7 を参照すること）。
#
# 取得可能性は指標ごとに異なる（docs/runbook.md「月次の効果測定」参照）:
#   - 採用率: 取得可能。ただしAI製PRと人間製PRを機械的に区別する手段が
#     本リポジトリには無い（全PRのauthorが同一アカウントに帰属し、
#     ラベル運用も無い）ため、全PRを対象にした値のみを出す。
#     参考情報として loop/<issue> ブランチ由来PR数も併記する。
#   - コスト: 条件付き。scripts/work_loop.sh の実行ログ（logs/run_*.json）
#     に total_cost_usd が記録されるが、logs/ は .gitignore 対象で
#     永続化されない設計（Phase4完了条件）。ログが無ければ「取得不能」。
#   - 不具合件数: 条件付き。bugラベルが実際に付与された実績が無ければ
#     「取得不能」（0件と表示すると「不具合が無かった」と誤読されうるため、
#     ラベル運用の不在と区別する）。
#
# 依存: gh, jq
set -euo pipefail

PERIOD_DAYS="${1:-30}"

# AI製PRを区別するラベル名。手順2の推奨案（ai-authored 1種類のみ）を
# 仮採用している。ラベル運用が実際に始まったら、この1行だけを変更すれば
# 差し替えられる。ラベル自体はこのスクリプトでは作成しない
# （`gh label create` は実行しない。docs/runbook.md 参照）。
AI_LABEL="ai-authored"

# ラベル運用を開始した日（YYYY-MM-DD）。未運用のうちは空のままにする。
# 運用を開始したら、この行に開始日を設定する。
AI_LABEL_START_DATE=""

if ! [[ "$PERIOD_DAYS" =~ ^[0-9]+$ ]]; then
  echo "エラー: 集計期間は正の整数（日数）で指定してください。例: $0 30" >&2
  exit 1
fi

command -v gh >/dev/null 2>&1 || { echo "エラー: gh コマンドが必要です" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "エラー: jq コマンドが必要です" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

SINCE="$(date -u -d "-${PERIOD_DAYS} days" +%Y-%m-%d)"

# gh/jq の失敗を握りつぶさない。ネットワーク不通・認証切れ等はここで
# エラー終了させ、静かに0を返す経路を作らない。
run() {
  local desc="$1"; shift
  if ! "$@"; then
    echo "エラー: ${desc} の取得に失敗しました（コマンド: $*）" >&2
    exit 1
  fi
}

col() {
  # 指標名 / 値 / 算出コマンド の3列を印字する（評価文言は含めない）
  printf '%-40s | %-30s | %s\n' "$1" "$2" "$3"
}

echo "=== AI Loop 効果測定（集計期間: 直近${PERIOD_DAYS}日、${SINCE}以降） ==="
echo

# ---------------------------------------------------------------------------
# 指標1: 採用率
# ---------------------------------------------------------------------------
PR_CMD="gh pr list --state all --search \"created:>=${SINCE}\" --limit 500 --json number,state,headRefName"
PR_JSON="$(gh pr list --state all --search "created:>=${SINCE}" --limit 500 --json number,state,headRefName)" \
  || { echo "エラー: PR一覧の取得に失敗しました" >&2; exit 1; }

PR_TOTAL="$(echo "$PR_JSON" | jq 'length')"
PR_MERGED="$(echo "$PR_JSON" | jq '[.[] | select(.state=="MERGED")] | length')"
PR_LOOP="$(echo "$PR_JSON" | jq '[.[] | select(.headRefName | startswith("loop/"))] | length')"

echo "--- 指標1: 採用率 ---"
echo "注記: AI製PRと人間製PRを機械的に区別する手段が本リポジトリには無い"
echo "（全PRのauthorが同一アカウントに帰属し、ラベル運用も無い、実測済み）。"
echo "そのため全PRを対象にした値のみを出す。"
col "作成されたPR数（全体）" "$PR_TOTAL" "$PR_CMD"
col "MERGEDされたPR数（全体）" "$PR_MERGED" "$PR_CMD | jq 'select(.state==\"MERGED\")'"
if [ "$PR_TOTAL" -gt 0 ]; then
  RATE="$(python3 -c "print(f'{${PR_MERGED} / ${PR_TOTAL} * 100:.1f}%')")"
else
  RATE="対象PR無し"
fi
col "採用率（MERGED/作成、全PR対象）" "$RATE" "MERGED数 / 作成数"
col "参考: loop/<issue> ブランチ由来PR数" "$PR_LOOP" "$PR_CMD | jq 'select(.headRefName|startswith(\"loop/\"))'"
echo

# --- 指標1（続き）: ラベルによるAI製PR限定の採用率 ---
# 「ラベルが1件も付いていない」を「該当期間に0件」と区別するため、
# 期間を絞らず全期間でこのラベルの使用実績があるかを先に確認する
# （bugラベルの判定〔指標3〕と同じパターン）。存在しないラベル名を
# 指定しても gh は空配列を返すだけでエラーにならないため
# （実測済み）、この事前チェックが無いと「未運用」と「該当0件」を
# 区別できず、静かに 0% を出す経路になる。
AI_LABEL_EVER="$(gh pr list --state all --label "$AI_LABEL" --limit 1 --json number | jq 'length')" \
  || { echo "エラー: ${AI_LABEL}ラベルの確認に失敗しました" >&2; exit 1; }

echo "--- 指標1（続き）: ${AI_LABEL}ラベルによるAI製PR限定の採用率 ---"
if [ "$AI_LABEL_EVER" -eq 0 ]; then
  col "AI製PR限定の採用率" "取得不能" \
    "理由: ${AI_LABEL}ラベルの付与実績が無い（実測: gh pr list --label ${AI_LABEL} が全期間で0件）。ラベル運用が未開始のため、上の「全PR対象」の値のみが利用できる"
else
  AI_PR_CMD="gh pr list --state all --label \"${AI_LABEL}\" --search \"created:>=${SINCE}\" --limit 500 --json number,state"
  AI_PR_JSON="$(gh pr list --state all --label "$AI_LABEL" --search "created:>=${SINCE}" --limit 500 --json number,state)" \
    || { echo "エラー: ${AI_LABEL}ラベル付きPRの期間集計に失敗しました" >&2; exit 1; }
  AI_PR_TOTAL="$(echo "$AI_PR_JSON" | jq 'length')"
  AI_PR_MERGED="$(echo "$AI_PR_JSON" | jq '[.[] | select(.state=="MERGED")] | length')"
  col "${AI_LABEL}ラベル付きPR数（作成、期間内）" "$AI_PR_TOTAL" "$AI_PR_CMD"
  if [ "$AI_PR_TOTAL" -gt 0 ]; then
    AI_RATE="$(python3 -c "print(f'{${AI_PR_MERGED} / ${AI_PR_TOTAL} * 100:.1f}%')")"
    col "AI製PR限定の採用率" "$AI_RATE" "MERGED数 / ${AI_LABEL}ラベル付きPR数（期間内）"
  else
    col "AI製PR限定の採用率" "取得不能" \
      "理由: ${AI_LABEL}ラベルは全期間で使われているが、指定した期間（${SINCE}以降）には該当PRが無い"
  fi
  if [ -n "$AI_LABEL_START_DATE" ] && [[ "$SINCE" < "$AI_LABEL_START_DATE" ]]; then
    echo "注記: 集計期間の開始（${SINCE}）がラベル運用開始日（${AI_LABEL_START_DATE}）より前のため、運用開始前の期間はラベルによる絞り込みの対象外になっている。"
  fi
fi
echo

# ---------------------------------------------------------------------------
# 指標2: 受け入れ1件あたりのコスト
# ---------------------------------------------------------------------------
echo "--- 指標2: 受け入れ1件あたりのコスト ---"
LOG_FILES=()
if [ -d "$REPO_ROOT/logs" ]; then
  while IFS= read -r -d '' f; do
    LOG_FILES+=("$f")
  done < <(find "$REPO_ROOT/logs" -maxdepth 1 -name 'run_*.json' -newermt "${SINCE}" -print0 2>/dev/null)
fi

if [ "${#LOG_FILES[@]}" -eq 0 ]; then
  col "受け入れ1件あたりのコスト" "取得不能" \
    "理由: logs/はgitignore対象で永続化されない設計（Phase4完了条件）。対話セッションのコストは本リポジトリ内から機械的に集計する手段が無い。期間内の run_*.json 無し"
else
  TOTAL_COST="$(jq -s '[.[].total_cost_usd] | add' "${LOG_FILES[@]}")"
  col "対象work_loop.sh実行ログ件数" "${#LOG_FILES[@]}" "find logs -name 'run_*.json' -newermt ${SINCE}"
  col "合計コスト（USD、work_loop.sh経由のみ）" "$TOTAL_COST" "jq -s '[.[].total_cost_usd] | add' logs/run_*.json"
  col "受け入れ1件あたりのコスト" "取得不能" \
    "理由: 対話セッション（本プロジェクト作業の大半）のコストが含まれておらず、上記合計はwork_loop.sh経由分のみの部分集計のため、PR採用数で割っても意味のある単価にならない"
fi
echo

# ---------------------------------------------------------------------------
# 指標3: verify.sh をすり抜けた不具合の件数
# ---------------------------------------------------------------------------
echo "--- 指標3: verify.sh をすり抜けた不具合の件数 ---"
BUG_LABEL_EVER="$(gh issue list --state all --label bug --limit 1 --json number | jq 'length')" \
  || { echo "エラー: bugラベルの確認に失敗しました" >&2; exit 1; }

if [ "$BUG_LABEL_EVER" -eq 0 ]; then
  col "verify.shをすり抜けた不具合の件数" "取得不能" \
    "理由: 不具合を表すラベル運用の実績が無い（実測: gh issue list --label bug が0件。bugラベル自体はリポジトリに定義済みだが一度も付与されていない）。提案: 該当する不具合issueにbugラベルを付与する運用を始めれば、以後このスクリプトで機械集計できるようになる（導入は本指示の範囲外）"
else
  BUG_CMD="gh issue list --state all --label bug --search \"created:>=${SINCE}\" --json number"
  BUG_COUNT="$(gh issue list --state all --label bug --search "created:>=${SINCE}" --json number | jq 'length')" \
    || { echo "エラー: bugラベルissueの期間集計に失敗しました" >&2; exit 1; }
  col "verify.shをすり抜けた不具合の件数（bugラベル）" "$BUG_COUNT" "$BUG_CMD"
fi
echo

# ---------------------------------------------------------------------------
# 追加調査: 静かな失敗の検出（実行時間の分布）
# ---------------------------------------------------------------------------
echo "--- 追加調査: Actions実行時間の分布（判定はしない。数値のみ） ---"
RUN_CMD="gh run list --created \">=${SINCE}\" --limit 1000 --json name,createdAt,updatedAt,conclusion"
RUN_JSON="$(gh run list --created ">=${SINCE}" --limit 1000 --json name,createdAt,updatedAt,conclusion)" \
  || { echo "エラー: Actions実行履歴の取得に失敗しました" >&2; exit 1; }

RUN_TOTAL="$(echo "$RUN_JSON" | jq 'length')"
col "期間内のActions実行件数（全ワークフロー合計）" "$RUN_TOTAL" "$RUN_CMD"

if [ "$RUN_TOTAL" -gt 0 ]; then
  echo
  echo "ワークフロー名ごとの実行時間（秒）: 件数 / 最小 / 最大 / 平均"
  echo "$RUN_JSON" | jq -r '
    map({name, dur: ((.updatedAt | fromdateiso8601) - (.createdAt | fromdateiso8601))})
    | group_by(.name)
    | .[]
    | "\(.[0].name)\t\(length)件\t最小\(min_by(.dur).dur)秒\t最大\(max_by(.dur).dur)秒\t平均\((([.[].dur] | add) / length) | floor)秒"
  ' | column -t -s $'\t'
  echo
  echo "算出コマンド: $RUN_CMD の各要素について (updatedAt - createdAt) をワークフロー名でgroup_by"
fi
