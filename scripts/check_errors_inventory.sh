#!/usr/bin/env bash
#
# docs/errors_md_inventory.md（ERRORS.md の棚卸し分析文書、作成 2026-08-23）の
# 統計表に書かれた値が、現行の ERRORS.md の実測値と乖離していないか検査する。
#
# 背景: 棚卸し文書の作成後に ERRORS.md が剪定・追記され、文書内の統計値
# （総行数・見出し数）が現行と食い違っている（Issue #193）。本スクリプトは
# その乖離を機械的に検出するだけで、どちらのファイルも書き換えない。
#
# 使い方:
#   scripts/check_errors_inventory.sh
#     引数なし。リポジトリの ERRORS.md と docs/errors_md_inventory.md を見る。
#     すべて一致 -> 標準出力に OK / 終了コード 0
#     1つでも食い違う -> 標準エラーに「項目 / 記載値 / 実測値」/ 非ゼロ終了
#
# 環境変数（テスト用。未設定ならリポジトリの実ファイルを見る）:
#   ERRORS_MD     ... 実測対象のファイルパス
#   INVENTORY_MD  ... 統計表の記載値を読むファイルパス

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ERRORS_MD="${ERRORS_MD:-${REPO_ROOT}/ERRORS.md}"
INVENTORY_MD="${INVENTORY_MD:-${REPO_ROOT}/docs/errors_md_inventory.md}"

if [ ! -f "$ERRORS_MD" ]; then
  echo "ERRORS.md が見つかりません: $ERRORS_MD" >&2
  exit 2
fi
if [ ! -f "$INVENTORY_MD" ]; then
  echo "inventory が見つかりません: $INVENTORY_MD" >&2
  exit 2
fi

# --- 1. ERRORS.md の実測値 ---
actual_lines="$(wc -l < "$ERRORS_MD" | tr -cd '0-9')"
# grep -c は 0 件のとき終了コード 1 を返すため set -e 対策で || true
actual_headings="$(grep -c '^## ' "$ERRORS_MD" || true)"
actual_headings="$(printf '%s' "$actual_headings" | tr -cd '0-9')"

# --- 2. inventory の統計表からの記載値 ---
# 「2,014行」のようにカンマ・単位付きで書かれているので数字以外を除去する。
extract_digits() {
  # $1: 行を絞り込む grep パターン
  grep -m1 "$1" "$INVENTORY_MD" | tr -cd '0-9'
}

doc_lines="$(extract_digits '^| *総行数')"
doc_headings="$(extract_digits '^| *見出し数')"

# --- 3. 比較 ---
status=0
report_mismatch() {
  # $1: 項目名  $2: 記載値  $3: 実測値
  printf '%s / %s / %s\n' "$1" "$2" "$3" >&2
  status=1
}

if [ "$doc_lines" != "$actual_lines" ]; then
  report_mismatch "総行数" "$doc_lines" "$actual_lines"
fi
if [ "$doc_headings" != "$actual_headings" ]; then
  report_mismatch "見出し数(## )" "$doc_headings" "$actual_headings"
fi

if [ "$status" -eq 0 ]; then
  echo "OK"
  exit 0
fi
exit 1
