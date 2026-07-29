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

# Issue #56 のゲート（インフォボックスの「終了系が空欄 ⇒ 連載中」に継続の証拠を要求する）
# の回帰。**94行の回帰コーパスはこのゲートの検出側を一度も踏まない** ―― #56 の測定でも
# 回帰群22行・拡張群72行とも変化0件だった。したがってこのゲートが将来壊れても、pytest でも
# measure_false_negative_rate.py でも気づけない。効果の根拠は Issue #53 の96行にしかない。
#
# --verify は API を叩かず、scripts/m6d4_labels.py の人手ラベル96行に出荷関数を直接当てる
# （実行時間 約0.08秒）。期待値 54/59・1/37 の出所は Issue #53 の測定で、ラベルは PR #58 で
# 追跡ファイルに切り出したもの。比較は整数の分子・分母で行う（丸めた百分率では比べない）。
echo "--- M6-B-4 継続の証拠ゲート（Issue #53 のラベル96行） ---"
# 明細（96行の内訳）は不一致のときだけ読めればよいので stdout は捨てる。不一致の理由
# （期待/実測）は stderr に出るのでそのまま表示される。
if python scripts/survey_m6d4_infobox.py --verify --expect 54/59,1/37 >/dev/null; then
  echo "検出 54/59・副作用 1/37 で一致"
else
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "VERIFY FAILED"
  exit 1
fi

echo "VERIFY PASSED"
exit 0
