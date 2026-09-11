# ADR-020: --disallowedTools は現構成では未接続のツールを名指ししており、実効性は観測できない

- 日付：2026-09-11
- 状態：採用

## 背景

`claude-review.yml`のclaude_argsは`--disallowedTools mcp__github_file_ops__commit_files,
mcp__github_file_ops__delete_files`を指定している。ADR-006はこれを「未解消のまま」の
事項として次のように記録していた（`docs/decisions/ADR-006-phase5-step1-redesign.md`
490-492行目）。

> - `--disallowedTools`が`mcp__github_file_ops__commit_files`/
>   `delete_files`を実際にブロックするか、`--allowedTools`との優先順位 →
>   今回も試行そのものが0件で、検証機会が発生しなかった。

この論点はIssue #91として切り出された。実測5件（PR #204・#205・#206・#208・#272）
を通じて、`mcp__github_file_ops__commit_files`/`delete_files`への呼び出し試行は
一貫して0件であり、`permission_denials`も（PR #208での無関係なBash拒否1件を除き）
空配列だった。従来はこれを「試行が発生していないため、拒否機構が機能しているのか
単に呼ばれていないだけなのかを区別できない（判別不能）」と扱ってきた（Issue #91、
2026-08-25コメント）。

## 測定

Issue #91へ2026-09-11に投稿済みの実測コメント
（https://github.com/giant-shrimp/comic_checker/issues/91#issuecomment-5635761275 ）
と同一の実測に基づく。対象run:

- run 34498830878（PR #272のレビュー実行、2026-09-10T15:55:43Z、conclusion: success）
- run 32858669412（PR #208のレビュー実行、2026-08-25T14:19頃、conclusion: success）

いずれも`gh run view <id> --log`でログをファイルへ保存し、保存済みファイルに対して
grepを実行した。

**1. initイベントの`tools`配列に`mcp__github_file_ops__*`が含まれないこと**

`grep -n '"subtype": *"init"'` で特定したinitイベント（run 34498830878は910行目、
run 32858669412は903行目）直後の`"tools"`配列（両run共通、29要素）:

```
Task, Bash, CronCreate, CronDelete, CronList, DesignSync, Edit, EnterWorktree,
ExitWorktree, Glob, Grep, ListAgents, Monitor, NotebookEdit, PushNotification,
Read, RemoteTrigger, ReportFindings, ScheduleWakeup, SendMessage, Skill,
TaskOutput, TaskStop, ToolSearch, WebFetch, WebSearch, Workflow, Write,
mcp__github_comment__update_claude_comment
```

`mcp__github_file_ops__commit_files` / `mcp__github_file_ops__delete_files`は
この配列に含まれない（両run共通）。

**2. `mcp_servers`が`github_comment`1件のみで、`github_file_ops`という名前の
MCPサーバーがログ中に一切現れないこと**

`grep -c '"mcp_servers"'` は両runとも1件（initイベント中に1回のみ出現）。その内容
（両run共通）:

```
"mcp_servers": [
  {
    "name": "github_comment",
    "status": "connected"
  }
],
```

`grep -n '"name": "github'`でも両runとも`github_comment`の1件のみがヒットし、
`github_file_ops`という名前のMCPサーバーへの言及自体が存在しない。

**3. ログ中の`mcp__github_file_ops__*`の全出現が、claude_argsのecho・
disallowedTools設定のecho・ワークフローYAMLコメントの引用のいずれかであり、
tool_useは0件であること**

`grep -o 'mcp__github_file_ops__[a-z_]*' <ログ> | sort | uniq -c`の結果、両runとも
`commit_files`4件・`delete_files`4件がヒットしたが、`grep -n`で該当行を特定し
`cut -c1-400`で文脈を確認したところ、全出現は次のいずれかに分類された。

- run 34498830878: 207・363・370行目はclaude_args/CLAUDE_ARGSのecho、894・895行目は
  「SDK options」ログ中のdisallowedTools配列要素（禁止指定のecho）、2246・2256行目
  はReadツールで`claude-review.yml`冒頭コメントを読んだ結果のダンプ内での文中言及
- run 32858669412: 206・362・369行目はclaude_args/CLAUDE_ARGSのecho、887・888行目は
  disallowedTools配列要素のecho

`grep -n '"name": "mcp__github_file_ops'`は両runとも無ヒットであり、
`(iii) 実際のtool_use`に該当する出現は0件だった。

## 決定

1. **現構成ではmcp__github_file_ops__*を提供するMCPサーバーが接続されておらず、
   当該ツールは実行時に存在しない。したがって`--disallowedTools`の実効性は
   通常のrunでは観測できない、と記録する。**
2. **claude_argsの`--disallowedTools`指定は現状のまま維持する。** 多重防御の
   外側の層として、将来`github_file_ops`が接続される構成変更が起きた場合に
   備える（`docs/decisions/ADR-004-phase5-preconditions.md`決定2の位置づけを
   踏襲）。ワークフローの編集を伴う変更は行わない（人間の領分、ADR-003）。

## 決定の理由

- 「呼び出し試行が0件であること」の説明として、モデルが呼ばなかったという
  解釈と、ツールがそもそも存在しないという構造的説明の2つがあり、今回の実測
  （initイベントの`tools`配列・`mcp_servers`の両方でfile_opsが一切現れない）
  は後者を支持する。
- `--disallowedTools`の指定を外しても現時点の挙動は変わらないが、将来
  `github_file_ops`が接続される構成へ変わった場合に保護が失われるリスクが
  ある。指定を維持するコストはゼロに近く、維持する方がコストに対して見合う。

## 限界

- initイベントの`"tools"`配列は登録済みツールの一覧であって許可集合ではない。
  同配列には`Edit`・`Write`・`Bash`が含まれる一方、実際に`--allowedTools`へ
  渡された値（`Glob,Grep,LS,Read,mcp__github_comment__update_claude_comment,
  mcp__github_ci__*`3種、`Bash(git add:*)`等）には無く、許可判定は
  `"tools"`配列とは別の層（`--allowedTools`/`--disallowedTools`、およびBash
  コマンド単位の権限ゲート）で行われている。この構造は`ERRORS.md`1426行以降の
  Bash権限ゲートの記録（`decision_reason="This command requires approval"`、
  非対話環境での自動拒否）と整合する。**したがって本ADRの根拠は「`tools`配列に
  無いこと」ではなく、「`mcp_servers`に`github_file_ops`という名前のMCP
  サーバーが一切接続されていないこと」に置く。**
- 観測は2run（PR #272・PR #208）に限られる。他のrunや、action・SDKの
  バージョン・設定が変われば、この構造が維持される保証はない。
- `--allowedTools`と`--disallowedTools`の優先順位は依然として未検証である。
  本ADRはこれを解決しない。

## 見直す条件

`github_file_ops`を提供するMCPサーバーが接続される構成へ変わった場合、または
actionのバージョン更新でinitイベントの構造が変わった場合。その時点で得られる
観測データを根拠に、`--disallowedTools`の実効性を再検証する。

## 関連

- Refs #91
- 関連: `docs/decisions/ADR-006-phase5-step1-redesign.md`
  （`--disallowedTools`の未解消事項の初出）
- 関連: `docs/decisions/ADR-004-phase5-preconditions.md`
  （`--disallowedTools`を多重防御の外側の層として採用した決定2）
- 関連: `docs/decisions/ADR-019-remove-select-review-fallback.md`
  （同種の「実測5回以上で試行0件」という状況に対する過去の判断枠組み。
  ただしADR-019は不発の経路自体を削除した事例であり、本ADRは
  `--disallowedTools`の指定自体を維持する点で異なる）
