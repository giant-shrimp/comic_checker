#!/bin/bash
# クラウドセッション（claude.ai/code）専用の準備。ローカルでは何もしない。
# SessionStart フックから呼ばれる。verify.sh は変更せず、その前提（.venv と画面）を整える。
# 前提：環境のセットアップスクリプトが /opt/comic_venv（/usr/bin/python3.12 由来）を作成済みで、
#       環境変数 DISPLAY=:99 が設定済みであること。
set -u
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi
cd "${CLAUDE_PROJECT_DIR:?}" || exit 1

if [ ! -e .venv ]; then
  if [ -x /opt/comic_venv/bin/python ]; then
    ln -s /opt/comic_venv .venv
  else
    echo "cloud_setup: /opt/comic_venv が無い。環境のセットアップスクリプトを確認すること。" >&2
    exit 1
  fi
fi
.venv/bin/pip install -q -r requirements-dev.txt || { echo "cloud_setup: pip install に失敗" >&2; exit 1; }

if ! pgrep -x Xvfb >/dev/null 2>&1; then
  setsid nohup Xvfb :99 -screen 0 1280x1024x24 >/dev/null 2>&1 < /dev/null &
fi
exit 0
