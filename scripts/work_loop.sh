#!/usr/bin/env bash
set -euo pipefail

command -v jq >/dev/null || { echo "jq が必要です（brew install jq / apt install jq）" >&2; exit 1; }

ISSUE="${1:?usage: ./scripts/work_loop.sh <issue-number>}"
MAX_ITER="${MAX_ITER:-3}"
MAX_TURNS="${MAX_TURNS:-20}"
MAX_BUDGET="${MAX_BUDGET:-2.00}"
CLAUDE_TIMEOUT="${CLAUDE_TIMEOUT:-600}"  # claude呼び出し自体がハングした場合の保険（秒）
ALLOWED="Read,Edit,Write,Glob,Grep,Bash(gh issue view:*),Bash(git diff:*),Bash(./scripts/verify.sh)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# git commit/push/add・python3任意実行・gh issueの破壊的操作・checkout・
# 自分自身の再帰呼び出しは、ALLOWEDから外すだけでは塞げない。permissions.allowは
# 発生源（--allowedTools／プロジェクトの.claude/settings.json／ローカルの
# .claude/settings.local.json）に関わらず加算されるため、settings.local.jsonに
# 対話セッション用の広いallow（python3 * や gh issue * 等）が存在すると、
# それがこの非対話実行にも素通しで効いてしまう（Issue #14実行時に実際に無許可で
# commitされ、判明した）。
# denyは発生源を問わず常にallowより優先される（Claude Code公式ドキュメント
# permissions.mdで確認済み）ため、強制力を持たせるにはdenyを使う。
# work_loop.settings.jsonをこの呼び出しにだけ追加で読み込ませ、
# 「ファイル編集とverify.shの実行だけで完結するタスク」の範囲を超える操作を
# 常にdenyする。
#
# 重要: これは「重要な変更かどうか」では分岐しない。非対話実行では、
# 変更の大小に関わらず、ALLOWEDに無いコマンド種別を一律禁止する設計。
#
# プロンプト文面で「commitして」「pythonを実行して」等と指示しても、
# このdenyは緩まない（denyはプロンプト内容を見て判断するものではなく、
# モデルへの指示ではなく権限システム側の強制であることが、この設計の要）。
# 許可したい場合は、work_loop.sh の呼び出し元（人間）が
# work_loop.settings.json 自体を対話セッションで見直すこと
# （プロンプトではなく、スクリプト起動時の帯域外の手段で許可する）。
SETTINGS_ARGS=(--settings "$SCRIPT_DIR/work_loop.settings.json")

mkdir -p logs

SESSION=""

for ((i = 1; i <= MAX_ITER; i++)); do
  echo "=== iteration ${i}/${MAX_ITER} ==="

  if [ -z "$SESSION" ]; then
    # /workをリテラルに呼び出す。disable-model-invocation: trueのスキルは、
    # プロンプト文字列に明示的な/skill-name呼び出しが無い限り自動発火せず、
    # SKILL.mdの内容が一度もコンテキストに読み込まれない（work skillの
    # Explore/Plan/Verify手順や制約が完全に無視された状態で実行されていた）。
    PROMPT="/work ${ISSUE}"
  else
    PROMPT="検証が失敗しました．以下の出力を読み，原因を特定して修正してください．同じ修正を繰り返さないこと．前回と違うアプローチを取ること．$(tail -c 4000 "logs/verify_$((i - 1)).log")"
  fi

  ARGS=(-p "$PROMPT"
        --max-turns "$MAX_TURNS"
        --max-budget-usd "$MAX_BUDGET"
        --allowedTools "$ALLOWED"
        "${SETTINGS_ARGS[@]}"
        --output-format json)

  if [ -n "$SESSION" ]; then
    ARGS+=(--resume "$SESSION")
  fi

  timeout "$CLAUDE_TIMEOUT" claude "${ARGS[@]}" > "logs/run_${i}.json" 2> "logs/run_${i}.err" || true

  NEW_SESSION=$(jq -r '.session_id // empty' "logs/run_${i}.json" 2>/dev/null || true)
  if [ -z "$NEW_SESSION" ]; then
    echo "実行に失敗しました（logs/run_${i}.err を確認。timeoutによる強制終了の可能性も含む）。中断します。" >&2
    echo "failed" > "logs/outcome_${i}.txt"
    exit 1
  fi
  SESSION="$NEW_SESSION"

  if ./scripts/verify.sh > "logs/verify_${i}.log" 2>&1; then
    # verify.shが通ることは「タスクが完了した証拠」にはならない。エージェントが
    # ターン数上限等で何も変更できないまま終了しても、既存テストは当然そのまま通ってしまう
    # （Issue #16で実際に発生: is_error=true・ターン数上限で失敗していたのに、verify.shは
    # 素通りしていた）。git status --porcelainで実際に変更が発生したかどうかを別途確認し、
    # 「検証通過」と「無変化のまま終了（no-op）」を明確に区別する。
    if [ -z "$(git status --porcelain)" ]; then
      echo "verify.shは通過しましたが、変更が一切発生していません（no-op）。実装が完了して" >&2
      echo "いない可能性が高いです。logs/run_${i}.json（is_error / stop_reason / num_turns）" >&2
      echo "を確認してください。" >&2
      echo "no-op" > "logs/outcome_${i}.txt"
      exit 2
    fi
    echo "verified — 停止します"
    echo "success" > "logs/outcome_${i}.txt"
    exit 0
  fi

  echo "検証失敗（詳細は logs/verify_${i}.log）"
  echo "verify_failed" > "logs/outcome_${i}.txt"
done

echo "最大反復に到達しました．人間の確認が必要です．"
echo "max_iterations" > "logs/outcome_${MAX_ITER}.txt"
exit 1
