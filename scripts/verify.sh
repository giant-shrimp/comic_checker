#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

source "$REPO_ROOT/.venv/bin/activate"
cd "$REPO_ROOT"

fail=0

echo "--- pytest ---"
python -m pytest -q
if [ $? -ne 0 ]; then
  fail=1
fi

# テストのskip/xfail追加を検出する。
# verify.sh通過が「タスク完了の証拠」にならなかった問題（Issue #16）と同種の
# 抜け道 ―― 既存テストを緩めて通す ―― を塞ぐための追加チェック。
# origin/main が無い環境（浅いクローン等）では静かにスキップする。
echo "--- skip/xfail check ---"
if git rev-parse --verify origin/main >/dev/null 2>&1; then
  if git diff origin/main -- tests \
     | grep -qE '^\+.*(@pytest\.mark\.(skip|xfail)|\.skip\(|\.todo\()'; then
    echo "FAIL: テストのスキップ/xfailが追加されています"
    fail=1
  fi
else
  echo "origin/main が見つからないためスキップ検出は実施していません"
fi

if [ "$fail" -ne 0 ]; then
  echo "VERIFY FAILED"
  exit 1
fi

echo "VERIFY PASSED"
exit 0
