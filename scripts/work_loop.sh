#!/usr/bin/env bash
set -euo pipefail

command -v jq >/dev/null || { echo "jq が必要です（brew install jq / apt install jq）" >&2; exit 1; }

ISSUE="${1:?usage: ./scripts/work_loop.sh <issue-number>}"
MAX_ITER="${MAX_ITER:-3}"
MAX_TURNS="${MAX_TURNS:-20}"
MAX_BUDGET="${MAX_BUDGET:-2.00}"
ALLOWED="Read,Edit,Write,Glob,Grep,Bash(gh issue view:*),Bash(git diff:*),Bash(./scripts/verify.sh)"

mkdir -p logs

SESSION=""

for ((i = 1; i <= MAX_ITER; i++)); do
  echo "=== iteration ${i}/${MAX_ITER} ==="

  if [ -z "$SESSION" ]; then
    PROMPT="GitHub Issue #${ISSUE} を読み，実装してください．完了前に必ず ./scripts/verify.sh を実行し，失敗したら修正してください．push はしないでください．"
  else
    PROMPT="検証が失敗しました．以下の出力を読み，原因を特定して修正してください．同じ修正を繰り返さないこと．前回と違うアプローチを取ること．$(tail -c 4000 "logs/verify_$((i - 1)).log")"
  fi

  ARGS=(-p "$PROMPT"
        --max-turns "$MAX_TURNS"
        --max-budget-usd "$MAX_BUDGET"
        --allowedTools "$ALLOWED"
        --output-format json)

  if [ -n "$SESSION" ]; then
    ARGS+=(--resume "$SESSION")
  fi

  claude "${ARGS[@]}" > "logs/run_${i}.json" 2> "logs/run_${i}.err" || true

  NEW_SESSION=$(jq -r '.session_id // empty' "logs/run_${i}.json" 2>/dev/null || true)
  if [ -z "$NEW_SESSION" ]; then
    echo "実行に失敗しました（logs/run_${i}.err を確認）．中断します．" >&2
    exit 1
  fi
  SESSION="$NEW_SESSION"

  if ./scripts/verify.sh > "logs/verify_${i}.log" 2>&1; then
    echo "verified — 停止します"
    exit 0
  fi

  echo "検証失敗（詳細は logs/verify_${i}.log）"
done

echo "最大反復に到達しました．人間の確認が必要です．"
exit 1
