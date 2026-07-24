#!/usr/bin/env bash
#
# .githooks/ をこのクローンの有効なフックディレクトリとして設定する。
#
# なぜこのスクリプトが必要か:
#   core.hooksPath は .git/config に書かれるローカル設定であり、リポジトリに
#   付いて回らない。したがってクローンし直した環境・別マシンでは、フックが
#   「静かに無効」な状態から始まる。これは安全装置が黙って外れる形なので、
#   設定を1コマンドに固めた上で、設定後に実際の値を読み直して検証する。
#
# 冪等: 何度実行してもよい。既に設定済みなら同じ値を書き直すだけ。
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

HOOKS_DIR=".githooks"

if [ ! -d "$HOOKS_DIR" ]; then
  echo "エラー: ${HOOKS_DIR}/ が見つかりません（リポジトリルート: ${REPO_ROOT}）" >&2
  exit 1
fi

git config core.hooksPath "$HOOKS_DIR"
chmod +x "$HOOKS_DIR"/* 2>/dev/null || true

# 設定したつもりで終わらせず、実際に読み直して確認する
ACTUAL="$(git config --get core.hooksPath || true)"
if [ "$ACTUAL" != "$HOOKS_DIR" ]; then
  echo "エラー: core.hooksPath の設定に失敗しました（現在値: '${ACTUAL:-未設定}'）" >&2
  exit 1
fi

echo "core.hooksPath = ${ACTUAL}"
echo "有効なフック:"
for h in "$HOOKS_DIR"/*; do
  [ -f "$h" ] || continue
  if [ -x "$h" ]; then
    echo "  $(basename "$h")  (実行可能)"
  else
    echo "  $(basename "$h")  ★実行権限なし — フックとして呼ばれません" >&2
  fi
done
