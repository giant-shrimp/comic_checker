#!/usr/bin/env bash
#
# 走査器（scripts/check_no_personal_info.py）を全git追跡ファイルへかけ、
# docs/scanner_scan_history.md（走査器の定期走査 実行結果記録、ADR-024決定3・
# ADR-027）へ追記する1行分の値を計算して標準出力へ出す。
#
# 本スクリプトはファイルへの書き込みを一切行わない。表への追記自体は、
# 出力された行を人間またはAIが docs/scanner_scan_history.md の表の末尾へ
# 手で追加する（登録簿・棚卸し表と同じ運用）。
#
# 出力する値:
#   検出のあったファイル数・検出総件数・型ごとの件数（home-path/email/
#   honorific）・docs/scanner_false_positive_registry.md の登録件数。
#
# 出力に検出行の本文は含めない（ADR-022の運用規約）。
#
# 使い方:
#   scripts/scanner_scan_summary.sh
#     引数なし。リポジトリの git 追跡ファイル全件と
#     docs/scanner_false_positive_registry.md を見る。
#     Markdown表の1行分（`| 日付 | ... |`の形。日付は当日、前回比の列は
#     空欄のまま出力するので、記録簿へ追記する側が直前行と比較して埋める）
#     を標準出力へ出し、終了コード0で終了する。
#   本ファイルに実行権限は付与していない。`bash scripts/scanner_scan_summary.sh`
#   のように bash 経由で呼び出す運用とする。
#
# 環境変数（テスト用。未設定ならリポジトリの実ファイル・git追跡ファイル全件を見る）:
#   REGISTRY_MD   ... 登録簿のファイルパス
#   SCANNER_PY    ... 走査器モジュールのファイルパス
#   TARGET_FILES  ... 走査対象ファイルの改行区切りリスト（相対パス）。
#                     未設定なら `git ls-files` の結果を使う。
#   BASE_DIR      ... TARGET_FILES の相対パスを解決する基点ディレクトリ。
#                     未設定ならリポジトリルート。
#   SCAN_DATE     ... 出力する日付（YYYY-MM-DD）。未設定なら実行日。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REGISTRY_MD="${REGISTRY_MD:-${REPO_ROOT}/docs/scanner_false_positive_registry.md}"
SCANNER_PY="${SCANNER_PY:-${REPO_ROOT}/scripts/check_no_personal_info.py}"
BASE_DIR="${BASE_DIR:-${REPO_ROOT}}"
SCAN_DATE="${SCAN_DATE:-$(date +%Y-%m-%d)}"

if [ ! -f "$REGISTRY_MD" ]; then
  echo "登録簿が見つかりません: $REGISTRY_MD" >&2
  exit 2
fi
if [ ! -f "$SCANNER_PY" ]; then
  echo "走査器が見つかりません: $SCANNER_PY" >&2
  exit 2
fi

if [ -n "${TARGET_FILES+x}" ]; then
  target_files="$TARGET_FILES"
else
  target_files="$(cd "$REPO_ROOT" && git ls-files)"
fi

REGISTRY_MD="$REGISTRY_MD" SCANNER_PY="$SCANNER_PY" BASE_DIR="$BASE_DIR" \
  SCAN_DATE="$SCAN_DATE" TARGET_FILES_RESOLVED="$target_files" python3 - <<'PY'
import importlib
import os
import sys

REGISTRY_MD = os.environ["REGISTRY_MD"]
SCANNER_PY = os.environ["SCANNER_PY"]
BASE_DIR = os.environ["BASE_DIR"]
SCAN_DATE = os.environ["SCAN_DATE"]
target_files = [
    line for line in os.environ["TARGET_FILES_RESOLVED"].splitlines() if line.strip()
]

sys.path.insert(0, os.path.dirname(SCANNER_PY))
mod_name = os.path.splitext(os.path.basename(SCANNER_PY))[0]
scanner = importlib.import_module(mod_name)

files_with_hits = 0
total_hits = 0
counts = {"home-path": 0, "email": 0, "honorific": 0}

for relpath in target_files:
    full_path = os.path.join(BASE_DIR, relpath)
    try:
        hits = scanner.scan_path(full_path)
    except OSError:
        continue
    if not hits:
        continue
    files_with_hits += 1
    for _path, _lineno, line in hits:
        total_hits += 1
        if scanner.HOME_PREFIX_PATTERN.search(line):
            counts["home-path"] += 1
        if scanner.EMAIL_PATTERN.search(line):
            counts["email"] += 1
        if scanner._honorific_hit(line):
            counts["honorific"] += 1

registered = 0
in_table = False
with open(REGISTRY_MD, encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\n")
        if line.startswith("| ファイル "):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        registered += 1

print(
    "| %s | %d | %d | %d | %d | %d | %d | (直前行と比較して埋める) |"
    % (
        SCAN_DATE,
        files_with_hits,
        total_hits,
        counts["home-path"],
        counts["email"],
        counts["honorific"],
        registered,
    )
)
PY
