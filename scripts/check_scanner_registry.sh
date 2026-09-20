#!/usr/bin/env bash
#
# 走査器（scripts/check_no_personal_info.py）の検出結果を、
# docs/scanner_false_positive_registry.md（既知の偽陽性の事前登録簿、
# ADR-024決定1・Issue #271）と突き合わせる。
#
# 背景: 走査器はファイル内容しか見ておらず、本プロジェクトが扱う実在の
# 作品名の敬称字形（honorific型）を中心に、既知の構造的偽陽性が多数残る
# （ADR-017・ADR-024）。走査器のパターン自体を絞ると検出漏れが増えるため
# （ADR-017「誤検出と検出漏れがパターン側では分離できない」）、走査器
# そのものは変更せず、既知の偽陽性だけを別文書（登録簿）で抑制する。
#
# 走査器のPython API（scan_path・HOME_PREFIX_PATTERN・EMAIL_PATTERN・
# _honorific_hit）を呼び出すだけで、走査器のファイル自体は一切変更しない。
#
# 投稿前走査の標準手段: 生の走査器（scripts/check_no_personal_info.py）は
# 登録簿を一切参照しないため、投稿前走査には走査器を直接呼ぶのではなく
# 本層（scripts/check_scanner_registry.sh）を使うこと。本層は内部で走査器を
# 呼び、検出が1件でも未登録なら非ゼロ終了する。対象ファイルに登録が無ければ
# 生の走査器と同じ結果（検出があれば非ゼロ）になるため、本層は生の走査器の
# 上位互換であり、確認手段を1本化できる。
#
# 検査項目:
#   1. 未登録検出: 走査器が検出したが登録簿に無い（ファイル, ハッシュ）の組
#   2. 陳腐化登録: 登録簿にあるが、現在は検出されない（ファイル, ハッシュ）の組
#
# いずれか1件でもあれば非ゼロ終了する。登録簿は既知の偽陽性を抑制するだけで、
# 新規の検出・陳腐化した登録のいずれも見逃さない（ADR-024決定1の設計要件）。
#
# 出力に検出行の本文は含めない（ADR-022の運用規約）。ファイルパス・ハッシュ・
# 型のみを標準エラーへ出す。
#
# 使い方:
#   scripts/check_scanner_registry.sh
#     引数なし。リポジトリの git 追跡ファイル全件（`git ls-files`）に加え、
#     git 未追跡ファイル（`git ls-files --others --exclude-standard`。
#     .gitignore で除外されたファイルは含まない）も対象に含め、
#     docs/scanner_false_positive_registry.md を見る。新規に作成した
#     ファイルほど、まだ人の目やレビューを経ていないため投稿前走査が
#     最も必要であり、追跡・未追跡を問わず対象にする。
#     すべて一致 -> 標準出力に OK / 終了コード 0
#     未登録検出・陳腐化登録が1件でもある -> 標準エラーへ出力 / 非ゼロ終了
#   本ファイルに実行権限は付与していない。`bash scripts/check_scanner_registry.sh`
#   のように bash 経由で呼び出す運用とする。
#
# 環境変数（テスト用。未設定ならリポジトリの実ファイル・git追跡ファイル全件を見る）:
#   REGISTRY_MD           ... 登録簿のファイルパス
#   SCANNER_PY            ... 走査器モジュールのファイルパス
#   TARGET_FILES          ... 走査対象ファイルの改行区切りリスト（相対パス）。
#                             未設定なら `git ls-files` と
#                             `git ls-files --others --exclude-standard`
#                             を合わせた結果を使う。
#   BASE_DIR              ... TARGET_FILES の相対パスを解決する基点ディレクトリ。
#                             未設定ならリポジトリルート。
#   GIT_SCAN_ROOT          ... TARGET_FILES 未設定時に `git ls-files` /
#                             `git ls-files --others --exclude-standard` を
#                             実行するディレクトリ。未設定ならリポジトリ
#                             ルート。テストで隔離されたgitリポジトリに対し、
#                             本番と同じ「追跡＋未追跡」判定ロジックを
#                             実リポジトリに触れずに検証するためのもの。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REGISTRY_MD="${REGISTRY_MD:-${REPO_ROOT}/docs/scanner_false_positive_registry.md}"
SCANNER_PY="${SCANNER_PY:-${REPO_ROOT}/scripts/check_no_personal_info.py}"
BASE_DIR="${BASE_DIR:-${REPO_ROOT}}"
GIT_SCAN_ROOT="${GIT_SCAN_ROOT:-${REPO_ROOT}}"

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
  target_files="$(cd "$GIT_SCAN_ROOT" && git ls-files && git ls-files --others --exclude-standard)"
fi

set +e
REGISTRY_MD="$REGISTRY_MD" SCANNER_PY="$SCANNER_PY" BASE_DIR="$BASE_DIR" \
  TARGET_FILES_RESOLVED="$target_files" python3 - <<'PY'
import hashlib
import importlib
import os
import sys

REGISTRY_MD = os.environ["REGISTRY_MD"]
SCANNER_PY = os.environ["SCANNER_PY"]
BASE_DIR = os.environ["BASE_DIR"]
target_files = [
    line for line in os.environ["TARGET_FILES_RESOLVED"].splitlines() if line.strip()
]

# 走査器をモジュールとしてimportする（呼び出すだけで、走査器のファイル自体は
# 一切変更しない）。
sys.path.insert(0, os.path.dirname(SCANNER_PY))
mod_name = os.path.splitext(os.path.basename(SCANNER_PY))[0]
scanner = importlib.import_module(mod_name)


def classify(line):
    if scanner.HOME_PREFIX_PATTERN.search(line):
        return "home-path"
    if scanner.EMAIL_PATTERN.search(line):
        return "email"
    if scanner._honorific_hit(line):
        return "honorific"
    return None


# --- 現在の検出を集める: {(file, hash): type} ---
actual = {}
for relpath in target_files:
    full_path = os.path.join(BASE_DIR, relpath)
    try:
        hits = scanner.scan_path(full_path)
    except OSError:
        continue
    for _path, _lineno, line in hits:
        kind = classify(line)
        if kind is None:
            continue
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]
        actual[(relpath, digest)] = kind

# --- 登録簿の読み込み: {(file, hash): type} ---
with open(REGISTRY_MD, encoding="utf-8") as f:
    registry_lines = f.read().splitlines()

registered = {}
in_table = False
for line in registry_lines:
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
    file_ = parts[1].strip()
    digest = parts[2].strip()
    kind = parts[3].strip()
    registered[(file_, digest)] = kind

# --- 突き合わせ ---
unregistered = sorted(key for key in actual if key not in registered)
stale = sorted(key for key in registered if key not in actual)

mismatches = []
for file_, digest in unregistered:
    mismatches.append(("未登録検出", file_, digest, actual[(file_, digest)]))
for file_, digest in stale:
    mismatches.append(("陳腐化登録", file_, digest, registered[(file_, digest)]))

for label, file_, digest, kind in mismatches:
    print("%s / %s / %s / %s" % (label, file_, digest, kind), file=sys.stderr)

sys.exit(1 if mismatches else 0)
PY
status=$?
set -e

if [ "$status" -eq 0 ]; then
  echo "OK"
  exit 0
fi
exit 1
