#!/usr/bin/env bash
#
# マージ済みPRから無作為に抜き取り、判定の材料になる事実（PR番号・タイトル・
# 変更ファイル数・差分行数・URL）だけを出力する。
#
# AI Loop実装計画書 Phase 7「理解の負債」節が挙げる確認手順の、**抽出だけ**を
# 自動化したものである。「この変更がなぜ必要だったか、1行で説明できるか」の
# 自問と判定は、必ず人間が行う。このスクリプト自身も、呼び出した側のAIも、
# 抽出したPRの内容を評価・要約しない（評価させると、自分の書いた変更を
# 自分で採点することになり、計画書Phase 4-1が指摘する「評価役が会話しか
# 読めない」問題と同じ構造になる。計画書1622行「AIに要約させると、読んだ
# つもりになるだけで負債は減らない」も参照）。
#
# 依存: gh, jq, python3
set -euo pipefail

PERIOD_DAYS="${1:-30}"
SEED="${2:-0}"
SAMPLE_SIZE="${3:-3}"
# 母集団の絞り込み範囲。"code"（既定）はコード変更PRのみ、"all"は絞り込み
# 無し（従来どおり全PR対象）。既定を"code"にした根拠は実測に基づく
# （直近30日130件中、comic_checker/・tests/・scripts/配下の変更を1つも
# 含まないPRが87件＝66.9%を占めた。無作為抽出のままではドキュメント/記録
# のみのPRが選ばれやすく、実際に初回運用〔seed=20260825〕で3件とも
# ドキュメント系になり、「コードの理解が失われているか」を検知できなかった）。
SCOPE="${4:-code}"

# コード変更PRと判定するパスのパターン。1箇所変更すれば差し替えられる。
CODE_PATH_PATTERN='^(comic_checker|tests|scripts)/'

if [ "$SCOPE" != "code" ] && [ "$SCOPE" != "all" ]; then
  echo "エラー: 第4引数（絞り込み範囲）は code または all を指定してください（渡された値: ${SCOPE}）" >&2
  exit 1
fi

for name_val in "PERIOD_DAYS:$PERIOD_DAYS" "SEED:$SEED" "SAMPLE_SIZE:$SAMPLE_SIZE"; do
  name="${name_val%%:*}"
  val="${name_val#*:}"
  if ! [[ "$val" =~ ^[0-9]+$ ]]; then
    echo "エラー: ${name} は0以上の整数で指定してください（渡された値: ${val}）" >&2
    echo "使い方: $0 [集計期間の日数=30] [seed=0] [抽出件数=3] [絞り込み範囲=code|all（既定code）]" >&2
    exit 1
  fi
done

command -v gh >/dev/null 2>&1 || { echo "エラー: gh コマンドが必要です" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "エラー: jq コマンドが必要です" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "エラー: python3 が必要です" >&2; exit 1; }

SINCE="$(date -u -d "-${PERIOD_DAYS} days" +%Y-%m-%d)"

PR_CMD="gh pr list --state merged --search \"merged:>=${SINCE}\" --limit 500 --json number,title,additions,deletions,changedFiles,url,files"
PR_JSON_RAW="$(gh pr list --state merged --search "merged:>=${SINCE}" --limit 500 --json number,title,additions,deletions,changedFiles,url,files)" \
  || { echo "エラー: マージ済みPR一覧の取得に失敗しました" >&2; exit 1; }

RAW_TOTAL="$(echo "$PR_JSON_RAW" | jq 'length')"

if [ "$SCOPE" = "code" ]; then
  PR_JSON="$(echo "$PR_JSON_RAW" | jq --arg pat "$CODE_PATH_PATTERN" \
    '[.[] | select(any(.files[]; .path | test($pat)))]')"
else
  PR_JSON="$PR_JSON_RAW"
fi

TOTAL="$(echo "$PR_JSON" | jq 'length')"

echo "=== マージ済みPRの抜き取り確認（集計期間: 直近${PERIOD_DAYS}日、${SINCE}以降、seed=${SEED}、絞り込み範囲=${SCOPE}） ==="
echo "算出コマンド（母集団の取得）: $PR_CMD"
if [ "$SCOPE" = "code" ]; then
  echo "算出コマンド（絞り込み）: jq 'select(any(.files[]; .path | test(\"${CODE_PATH_PATTERN}\")))'"
  echo "母集団のPR数（期間内・絞り込み前）: ${RAW_TOTAL}"
  echo "母集団のPR数（期間内・コード変更PRのみ）: ${TOTAL}"
else
  echo "母集団のPR数（期間内・全体、絞り込み無し）: ${TOTAL}"
fi
echo

if [ "$TOTAL" -eq 0 ]; then
  echo "対象PR無し（期間内にマージ済みPRが0件のため抽出できない）。"
  echo
  echo "この期間については、下記の自問・判定を実施できる対象が無い。"
else
  if [ "$TOTAL" -lt "$SAMPLE_SIZE" ]; then
    echo "注記: 母数（${TOTAL}件）が抽出件数（${SAMPLE_SIZE}件）に満たないため、全件を出力する。"
    echo
  fi

  # 母集団をPR番号昇順に固定してからsampleする。gh APIの返却順は保証されない
  # ため、順序を固定しないと同じseedでも異なる部分集合が選ばれうる。
  echo "$PR_JSON" | python3 -c '
import json, random, sys

period_days, seed, sample_size = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
prs = json.load(sys.stdin)
prs.sort(key=lambda p: p["number"])

total = len(prs)
k = min(sample_size, total)
selected = random.Random(seed).sample(prs, k) if total > 0 else []
selected.sort(key=lambda p: p["number"])

header_col1, header_col2, header_col3 = "PR番号", "変更ファイル数", "差分行数"
blank = ""
print(f"{header_col1:<8} {header_col2:<10} {header_col3:<10} タイトル / URL")
for p in selected:
    num = p["number"]
    changed = p["changedFiles"]
    diff = p["additions"] + p["deletions"]
    title = p["title"]
    url = p["url"]
    pr_label = f"#{num}"
    print(f"{pr_label:<8} {changed:<10} {diff:<10} {title}")
    print(f"{blank:<8} {blank:<10} {blank:<10} {url}")
' "$PERIOD_DAYS" "$SEED" "$SAMPLE_SIZE"
fi

echo
echo "--- ここから先は人間が行うこと（AIに判定させない） ---"
echo
echo "各PRについて自問する:"
echo "  「この変更がなぜ必要だったか、1行で説明できるか」"
echo "（AI Loop実装計画書 Phase 7「理解の負債」節、1733行の記述を引用）"
echo
echo "判定基準（計画書の記述をそのまま引用）:"
echo "  3件中1件でも説明できないなら、マージが速すぎる。"
echo "  PRを小さくするか、本数を減らす。"
echo
echo "このスクリプトはPRを選ぶところまでしか行わない。PRを開いて読み、"
echo "説明できるかどうかを判定するのは人間である（計画書1622行）。"
