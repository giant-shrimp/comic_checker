#!/usr/bin/env bash
#
# docs/errors_md_inventory.md（ERRORS.md の棚卸し分析文書、作成 2026-08-23）に
# 書かれた値が、現行の ERRORS.md の実測値と乖離していないか検査する。
#
# 背景: 棚卸し文書の作成後に ERRORS.md が剪定・追記され、文書内の統計値
# （総行数・見出し数）が現行と食い違っている（Issue #193）。本スクリプトは
# その乖離を機械的に検出するだけで、どちらのファイルも書き換えない。
#
# 検査項目:
#   1. 総行数（統計表の記載値 vs ERRORS.md の実測）
#   2. 見出し数（同上）
#   3. 分類表の各行の行範囲（Issue #286 決定1）
#   4. 分類の内訳件数 A/B/C と合計（Issue #286 決定2）
#   5. 分類表に対応する行を持たない見出し（Issue #292）
#   6. 分類表の見出し列とERRORS.mdの見出し実体との完全一致（Issue #281、ADR-025）
#
# 検査1・2は統計値のみを見るため、既存見出しへの追記で行範囲がずれても、
# また見出しが分類表から抜け落ちても検出できなかった（Issue #286・#292）。
# 検査3〜5はその取りこぼしを埋める。検査3〜5は行範囲という同定手段のみに
# 依存しており、無関係な変更（挿入位置より後ろの記録）まで道連れで検出して
# しまう。検査6は、行範囲に依存しない同定手段として見出し列自体の一致を見る
# （ADR-025決定1・決定2）。
#
# 使い方:
#   scripts/check_errors_inventory.sh
#     引数なし。リポジトリの ERRORS.md と docs/errors_md_inventory.md を見る。
#     すべて一致 -> 標準出力に OK / 終了コード 0
#     1つでも食い違う -> 標準エラーに「項目 / 記載値 / 実測値」/ 非ゼロ終了
#   本ファイルに実行権限は付与していない。`bash scripts/check_errors_inventory.sh`
#   のように bash 経由で呼び出す運用とする（モードは変更しない）。
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

# --- 4. 追加検査（検査3: 行範囲 / 検査4: 内訳件数 / 検査5: 未対応見出し /
#        検査6: 見出し列の完全一致）---
#
# この4検査は、分類表のパイプ区切り列の取り出し・見出しごとの行範囲の算出・
# 集合比較を伴う。bash で書くと連想配列と awk の組み合わせになり読みにくく、
# 検査自体の正しさを確かめにくいため python に委ねる（python はリポジトリの
# 既存の依存であり、新たな依存を増やさない）。呼び出し口である本スクリプトの
# インタフェース（引数なし実行）と環境変数の扱いは変えない。出力の書式
# 「項目 / 記載値 / 実測値」と終了コードの規約も検査1・2と同じにする。
#
# 検査6は見出し文字列そのものを標準エラーに出さない（ADR-022の運用規約）。
# 記載値・実測値には文字数のみを出す。
#
# 対象外の見出し（失敗記録ではない節）は行番号でハードコードせず、棚卸し文書の
# 「### 本表の対象外とする見出し」節に列挙された見出し文字列から読み取る。
set +e
ERRORS_MD="$ERRORS_MD" INVENTORY_MD="$INVENTORY_MD" python3 - <<'PY'
import os
import re
import sys

EXCLUDE_SECTION = "### 本表の対象外とする見出し"

with open(os.environ["ERRORS_MD"], encoding="utf-8") as f:
    errors_lines = f.read().splitlines()
with open(os.environ["INVENTORY_MD"], encoding="utf-8") as f:
    inventory_lines = f.read().splitlines()

# ERRORS.md の実測: 見出し行から次の見出しの直前行まで（最後の見出しは総行数まで）。
heading_starts = [i + 1 for i, line in enumerate(errors_lines) if line.startswith("## ")]
ends = heading_starts[1:] + [len(errors_lines) + 1]
spans = {start: end - 1 for start, end in zip(heading_starts, ends)}

# 分類表の行だけを拾う。No 列が数字で始まる行のみを対象にすることで、
# 統計表・内訳表の行（No 列が数字で始まらない）は混ざらない。
RANGE_RE = re.compile(r"^(\d+)-(\d+)$")
rows = []
for line in inventory_lines:
    if not line.startswith("|"):
        continue
    parts = line.split("|")
    if len(parts) < 6:
        continue
    no = parts[1].strip()
    if not no[:1].isdigit():
        continue
    rows.append((no, parts[2].strip(), parts[3].strip(), parts[4].strip()))

mismatches = []


def report(item, doc_value, actual_value):
    mismatches.append((item, doc_value, actual_value))


def first_int(text):
    found = re.search(r"\d+", text)
    return int(found.group(0)) if found else None


# 検査3: 見出しごとの行範囲
covered_starts = set()
for no, cell, _heading_col, _cls in rows:
    matched = RANGE_RE.match(cell)
    if matched is None:
        # 退避先を書いた行（対応する見出しが ERRORS.md に無い）は行範囲を持たない。
        continue
    start, end = int(matched.group(1)), int(matched.group(2))
    covered_starts.add(start)
    if start not in spans:
        report("行範囲(No.%s)" % no, "%d-%d" % (start, end), "%d行目に見出しなし" % start)
    elif spans[start] != end:
        report("行範囲(No.%s)" % no, "%d-%d" % (start, end), "%d-%d" % (start, spans[start]))

# 検査4: 分類の内訳件数（A/B/C と合計）
actual_counts = {"A": 0, "B": 0, "C": 0}
for _no, _cell, _heading_col, cls in rows:
    key = cls.replace("*", "").strip()
    if key in actual_counts:
        actual_counts[key] += 1

for key in ("A", "B", "C"):
    doc_count = None
    label = re.compile(r"^\|\s*%s（" % key)
    for line in inventory_lines:
        if label.match(line):
            parts = line.split("|")
            if len(parts) >= 3:
                doc_count = first_int(parts[2])
            break
    if doc_count is None:
        report("分類内訳(%s)" % key, "記載なし", str(actual_counts[key]))
    elif doc_count != actual_counts[key]:
        report("分類内訳(%s)" % key, str(doc_count), str(actual_counts[key]))

doc_total = None
for line in inventory_lines:
    if re.match(r"^\|\s*\*\*合計\*\*", line):
        parts = line.split("|")
        if len(parts) >= 3:
            doc_total = first_int(parts[2])
        break
if doc_total is None:
    report("分類内訳(合計)", "記載なし", str(len(rows)))
elif doc_total != len(rows):
    report("分類内訳(合計)", str(doc_total), str(len(rows)))

# 検査5: 分類表に対応する行を持たない見出し
excluded = set()
in_section = False
for line in inventory_lines:
    if line.startswith("#"):
        in_section = line.strip() == EXCLUDE_SECTION
        continue
    if in_section:
        entry = re.match(r"^- `(.+)`$", line.strip())
        if entry:
            excluded.add(entry.group(1))

for start in heading_starts:
    if start in covered_starts:
        continue
    if errors_lines[start - 1] in excluded:
        continue
    # 見出し文字列そのものは出さない（ADR-022 の運用規約）。行番号で位置を示す。
    report(
        "未対応見出し(ERRORS.md %d行目)" % start,
        "除外一覧に記載なし",
        "分類表に対応する行なし",
    )

# 検査6: 見出し列とERRORS.mdの見出し実体との完全一致（ADR-025）
# 行範囲を持たない行（退避先の記載等）は突き合わせ先が無いため対象外。
# 見出し文字列そのものは出さない（ADR-022 の運用規約）。文字数のみを示す。
for no, cell, heading_col, _cls in rows:
    matched = RANGE_RE.match(cell)
    if matched is None:
        continue
    start = int(matched.group(1))
    if start not in spans:
        # 検査3で既に報告済み（見出し自体が実在しない）のでここでは報告しない。
        continue
    actual_heading = errors_lines[start - 1][3:]
    if heading_col != actual_heading:
        report(
            "見出し一致(No.%s)" % no,
            "%d文字" % len(heading_col),
            "%d文字" % len(actual_heading),
        )

for item, doc_value, actual_value in mismatches:
    print("%s / %s / %s" % (item, doc_value, actual_value), file=sys.stderr)

sys.exit(1 if mismatches else 0)
PY
extra_status=$?
set -e
if [ "$extra_status" -ne 0 ]; then
  status=1
fi

if [ "$status" -eq 0 ]; then
  echo "OK"
  exit 0
fi
exit 1
