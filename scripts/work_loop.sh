#!/usr/bin/env bash
#
# 終了コードと logs/outcome_N.txt の対応（CIから呼ぶ場合はここを見れば足りる）
#
#   終了コード | outcome_N.txt              | 意味
#   -----------+----------------------------+--------------------------------------------
#   0          | success                    | 検証通過。かつ実行前後で実際に変更が発生した
#   1          | （記録なし）                | 起動時の前提条件エラー。jq不在、または
#              |                            | logs/ が.gitignore対象になっていない
#   1          | failed                     | claude実行自体の失敗（session_id取得不可。
#              |                            | timeoutによる強制終了・認証切れ・予算超過を含む）
#   1          | max_iterations             | MAX_ITERに到達（最終イテレーションのoutcomeを上書き）
#   2          | no-op                      | 検証は通過したが、実行前後で作業ツリーの内容が
#              |                            | 変化していない（実装が進んでいない可能性が高い）
#   3          | no_progress                | 前回とまったく同じ失敗が2回続いた（停止条件5層目）
#   3          | no_progress_unmeasurable   | 失敗行を2回連続で抽出できなかった。「行き詰まった」
#              |                            | のではなく「検証自体が成立していない」状態
#   -          | verify_failed              | そのイテレーションは検証失敗。次の反復へ進んだ
#
# 詳細は logs/verify_N.log（検証出力）と logs/run_N.json（is_error / stop_reason /
# num_turns）を参照。ループ開始時にツリーが汚れていた場合は logs/baseline_dirty.txt。
#
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

# 【重要な依存関係】このno-op検出の正しさは .gitignore の内容に依存している。
# snapshot()は git status --porcelain と git ls-files --others --exclude-standard を
# 使うため、logs/ が.gitignore対象である限り、ループ自身が毎イテレーション書き込む
# ログファイルはスナップショットに現れない。逆に言えば、将来誰かが.gitignoreから
# logs/ を外すと、エージェントが何もしなくてもログの書き込みだけでスナップショットが
# 必ず変化し、no-op検出が「静かに」無効化される（検査が壊れているのに通る側へ倒れる、
# というv8 1-3が警告している状態そのもの）。
# そのため下のプリフライトで logs/ が実際にignoreされているかを検査し、されていなければ
# 警告ではなく中断する（検査が成立しないなら止める）。
#
# 作業ツリーの「内容」に感応するスナップショットを取る。
# no-op検出に git status --porcelain の有無だけを使うのは誤りだった。理由は2つある。
#   1. ループ開始時点でツリーが既に汚れていると（未追跡ファイルが1つあるだけでも）
#      出力が非空になるため、エージェントが何もしなくても「変更あり」と判定される。
#   2. git status --porcelain の出力は、同じファイルを何度書き換えても " M path" の
#      ままで変化しない。よって2回目以降のイテレーションでは、実際に追加の変更が
#      あってもBEFORE==AFTERとなり、逆に誤ってno-opと判定される。
# 以下の3つを連結してハッシュ化することで、ファイルの出現・消滅と内容変更の両方に
# 感応させる。
#   - git status --porcelain          … ファイルの出現・消滅
#   - git diff HEAD                   … 追跡ファイルの内容変更（staged含む）
#   - 未追跡ファイルのsha256sum        … git diff HEADには現れないため個別に取る
# 未追跡ファイルの列挙は --exclude-standard 付きなので、.gitignore済みの logs/ 配下は
# 対象外。ループ自身が書くログでスナップショットが変化することはない。
# なお xargs の -r はGNU拡張（Linux前提。macOSで回すなら要調整）。
snapshot() {
  {
    git status --porcelain
    git diff HEAD
    git ls-files --others --exclude-standard -z \
      | xargs -0 -r sha256sum 2>/dev/null || true
  } | sha256sum | cut -d' ' -f1
}

# プリフライト1: logs/ がignoreされていることを確認する（snapshot()上のコメント参照）。
# ここが崩れるとno-op検出が無言で無効化されるため、警告ではなく中断する。
if ! git check-ignore -q logs/ 2>/dev/null; then
  echo "エラー: logs/ が .gitignore の対象になっていません。" >&2
  echo "  no-op検出は logs/ がignoreされていることを前提に成立しています。この状態で" >&2
  echo "  実行すると、ループ自身が書くログでスナップショットが必ず変化し、no-op検出が" >&2
  echo "  無効化されます（何も実装できていなくてもsuccessで終了する）。" >&2
  echo "  .gitignore に logs/ を戻してから再実行してください。" >&2
  exit 1
fi

# プリフライト2: pre-pushフック（mainへの直pushをブロック）が配線されているか。
# これは中断ではなく警告にとどめる。work_loop.sh自身はpushを行わない
# （--allowedToolsにgit pushが無く、work_loop.settings.jsonでもdenyしている）ため、
# フックが未設定でもこのループの判定の正しさには影響しないからである。
# プリフライト1を中断にしているのは、あちらがno-op検出の成立条件そのものを壊す
# ためで、性質が異なる。
# CI環境ではフックを設定しない運用のため、検査自体をスキップする。
if [ -z "${CI:-}" ] && [ "$(git config --get core.hooksPath || true)" != ".githooks" ]; then
  echo "警告: core.hooksPath が .githooks に設定されていません。" >&2
  echo "      mainへの直pushを止める pre-push フックが無効な状態です。" >&2
  echo "      ./scripts/setup_hooks.sh を実行してください（クローンごとに1回必要）。" >&2
fi

# プリフライト3: ループ開始時点で既に汚れているなら、その一覧を記録して警告する。
# 「どこからがエージェントの変更か」の基準を明示的に残すのが目的。中断はしない
# （手元の作業途中でループを回すこと自体は禁止しない）。
BASELINE_DIRTY="$(git status --porcelain)"
if [ -n "$BASELINE_DIRTY" ]; then
  printf '%s\n' "$BASELINE_DIRTY" > logs/baseline_dirty.txt
  echo "警告: ループ開始時点で作業ツリーが汚れています（logs/baseline_dirty.txt に記録）。" >&2
  echo "      no-op判定はこの状態からの内容変化を基準に行います。" >&2
else
  : > logs/baseline_dirty.txt
fi

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

  BEFORE_SNAPSHOT="$(snapshot)"

  timeout "$CLAUDE_TIMEOUT" claude "${ARGS[@]}" > "logs/run_${i}.json" 2> "logs/run_${i}.err" || true

  AFTER_SNAPSHOT="$(snapshot)"

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
    # 素通りしていた）。claude実行の前後でスナップショット（snapshot()参照）を比較し、
    # 「検証通過」と「無変化のまま終了（no-op）」を明確に区別する。
    if [ "$BEFORE_SNAPSHOT" = "$AFTER_SNAPSHOT" ]; then
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

  # 停止条件の5層目: 進捗で止める。上限（回数・金額・時間）に達して止まるのは
  # 「資源が尽きたら止まる」でしかなく、改善が止まったら資源が残っていても止めるべき。
  # 前回とまったく同じ失敗集合なら、同じ理解のまま書き方を変えているだけなので、
  # 次の反復に予算を使う意味がない。
  # 拾う行は2種類。この2つはうちのverify.shの実際の出力形式に合わせたもので、
  # 汎用の '^FAIL:' だけを見る書き方では pytest の失敗を1件も拾えない（verify.shが
  # run()ヘルパ形式ではなく pytest の出力をそのまま流しているため）。
  #   - "FAILED tests/...::test_name"  … pytest -q の短縮サマリ
  #   - "FAIL: テストのスキップ/..."    … verify.sh自身のskip/xfail検出
  if [ "$i" -gt 1 ]; then
    PREV_FAILS="$(grep -E '^(FAILED |FAIL: )' "logs/verify_$((i - 1)).log" 2>/dev/null | sort || true)"
    CURR_FAILS="$(grep -E '^(FAILED |FAIL: )' "logs/verify_${i}.log"       2>/dev/null | sort || true)"

    if [ "$PREV_FAILS" = "$CURR_FAILS" ]; then
      if [ -z "$CURR_FAILS" ]; then
        # 両方0件。これは「同じ失敗が2回続いた」のではなく「失敗内容をそもそも
        # 比較できていない」状態（pytestのcollection error、.venv不在、verify.sh自体の
        # 異常終了など、検証が成立していないケース）。停止する方向は同じだが、後から
        # ログを見たときに「AIが行き詰まった」のか「検証が成立していなかった」のかを
        # 区別できるよう、outcomeのラベルを分けて記録する。
        echo "検証は失敗しているのに、失敗行を2回連続で抽出できませんでした。" >&2
        echo "検証自体が成立していない可能性があります（collection error / .venv不在 /" >&2
        echo "verify.shの異常終了など）。logs/verify_${i}.log を直接確認してください。" >&2
        echo "no_progress_unmeasurable" > "logs/outcome_${i}.txt"
      else
        echo "前回とまったく同じ失敗が2回続きました。アプローチが変わっていません。中断します。" >&2
        echo "（失敗内容は logs/verify_${i}.log を確認してください）" >&2
        echo "no_progress" > "logs/outcome_${i}.txt"
      fi
      exit 3
    fi
  fi
done

echo "最大反復に到達しました．人間の確認が必要です．"
echo "max_iterations" > "logs/outcome_${MAX_ITER}.txt"
exit 1
