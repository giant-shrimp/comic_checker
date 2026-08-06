# ADR-006: Phase 5 Step 1（`claude-review.yml`）の設計をやり直す

- 日付：2026-08-07
- 状態：草案（`決定`節はTBD、人間の判断待ち）
- 関連: [ADR-004](https://github.com/giant-shrimp/comic_checker/blob/main/docs/decisions/ADR-004-phase5-preconditions.md)
  （決定2・決定3は本ADRの対象外で有効なまま）、
  [ADR-005](https://github.com/giant-shrimp/comic_checker/blob/main/docs/decisions/ADR-005-auth-oauth-token.md)
  （本ADRが再検討する決定を含む）

## 背景

ADR-005は、`--max-budget-usd`（ドル建ての予算上限）が`CLAUDE_CODE_OAUTH_TOKEN`
経由では機能しないことを理由に、「代替の制御手段」として
**「トリガーは当面`workflow_dispatch`のみとする。`pull_request`トリガーは
使わない」**と決定した（起動回数を人間が明示的に実行した回数だけに絞ることで、
金銭的な歯止めの代わりとする狙い）。

この決定にもとづき`claude-review.yml`を`workflow_dispatch`限定で実装し
（PR #84・#85・#86）、`gh workflow run claude-review.yml -f pr_number=82`で
3回実測した（run 31094393958 / 31111080310 / 31113307119。詳細は
`ERRORS.md`「`claude-review.yml`（Phase 5 Step 1）: `workflow_dispatch`実行が
コメント投稿まで到達しない」を参照）。3回とも、Actionの終了コード上は
「成功」でありながら、PRへのコメント投稿には一度も到達しなかった。

**3回の実測で初めて判明した因果関係**: `anthropics/claude-code-action`の
`src/modes/detector.ts`を確認したところ、`workflow_dispatch`イベントに対応する
`case`が無く、コメント`// Default to agent mode (which won't trigger without a
prompt)`の通り"agent"モードにフォールバックしていた。`src/modes/agent/index.ts`
によれば、agentモードは (a) PRのdiff/メタデータを自動取得・注入しない、
(b) コメント追跡用の`CLAUDE_COMMENT_ID`を`undefined`のまま渡す
（コード内コメント`"// No tracking comment in agent mode"`）。**ADR-005が
コスト制御のために選んだ`workflow_dispatch`限定という決定が、副作用として
「PRコンテキストの自動供給」と「コメント追跡（tracking comment）」の
両方を失わせていた。** これはADR-005の検討時点では認識されておらず、
`claude-code-action`のソースコードを実際に読むまで気づけなかった。

現行`claude-review.yml`が`gh pr diff` / `gh pr view`をプロンプトで明示的に
指示しているのは、agentモードが自動供給しない分の代替措置だが、その代替経路
自体がBashサンドボックス側の拒否（`decision_reason_type: "other"` /
`"This command requires approval"`、根本原因は`ERRORS.md`に記載の通り判定不能）
に阻まれ、3回とも機能しなかった。

## 比較する案

### 案A: `on: pull_request`に戻す（plan v8原案）

**検証結果（一次情報、本日時点の`anthropics/claude-code-action` `main`ブランチ）**:

- `src/modes/detector.ts`を確認した。`pull_request`イベントは
  `isEntityContext()`が認識するentity contextに含まれる
  （`if (isEntityContext(context) && isPullRequestEvent(context))`という
  分岐が存在する）。
  https://github.com/anthropics/claude-code-action/blob/main/src/modes/detector.ts
- ただし**`pull_request`イベントであれば自動的にtag modeになるわけではない**。
  `track_progress`が有効な場合のみ即座に`"tag"`モードを返す
  （`if (context.inputs.trackProgress && isEntityContext(context)) { if
  (isPullRequestEvent(context)...`）。`track_progress`が無効なら、
  `opened` / `synchronize` / `ready_for_review` / `reopened`のいずれの
  アクションであっても、promptが与えられていれば結局`"agent"`モードに
  フォールバックする（コメント`"If prompt is provided, use agent mode
  (default for automation)"`、最終フォールバックも`return "agent"`）。
  **したがって、単に`workflow_dispatch`を`pull_request`に変えるだけでは
  今回と同じagentモードの問題が再発する。`track_progress: true`の併用が
  必須になる。**
- `track_progress: true`を併用しtag modeになった場合の挙動は
  `src/modes/tag/index.ts`で確認した。**tag modeは`fetchGitHubData()`で
  PRのdiff/メタデータを自動取得してプロンプトに注入し、
  `createInitialComment()`で実行開始前にトラッキング用コメントを作成して
  `CLAUDE_COMMENT_ID`を設定する。** これはagentモードが欠いていた
  (a)(b)の両方を満たす。
  https://github.com/anthropics/claude-code-action/blob/main/src/modes/tag/index.ts
- ただし、tag modeで生成される自動コメントの形式（issue commentかreview
  commentか）や、そのコメントが`Bashサンドボックス問題`（`ERRORS.md`記載、
  未確定）を経由するかどうかまでは、今回のソース確認だけでは確定できて
  いない。tag modeは`update_claude_comment`ツール（Bashを経由しないMCP専用
  ツール）を使う設計に見えるため、Bashサンドボックス問題を回避できる
  可能性があるが、**実測していない。**

**欠点（必ず記載）**:

- PRが開く・更新されるたびに起動する構成になり、ADR-005が問題視した
  「金銭的な上限が立てにくい」状態に戻る。`CLAUDE_CODE_OAUTH_TOKEN`経由は
  `--max-budget-usd`が機能しないため、月額の見積もり手段が無いままPRの
  更新頻度に比例して起動回数が増える。
- ADR-005の「代替の制御手段」（起動を人間の`workflow_dispatch`実行回数だけに
  絞る）を放棄することになり、ADR-005自体の再検討（決定のsupersede）が
  必要になる。

### 案B: `workflow_dispatch`を維持し、I/OをClaudeから剥がす

runner側の通常step（Claudeのサンドボックスを経由しない、Actionの`run:`ステップ
そのもの）で`gh pr diff` / `gh pr view`を取得し、Claudeには`Read`のみ許可して
レビュー結果をローカルファイルへ書かせ、runner側の通常stepで
`gh pr comment --body-file`により投稿する。この構成なら、Claude自身は
ネットワークも`gh` CLIも一切呼ばない。

**検証結果（一次情報）**:

- `action.yml`の`outputs:`を確認した。`execution_file`
  （`"Path to the Claude Code execution output file"`）という出力があり、
  Claudeの実行結果（`result`フィールドを含むJSON）のパスをruner側の後続
  stepが読める。`--json-schema`を`claude_args`に指定した場合は
  `structured_output`（`"JSON string containing all structured output fields
  ... Use fromJSON() to parse"`）も使える。
  https://github.com/anthropics/claude-code-action/blob/main/action.yml
- 現行の`Count comments before review`・`Verify a review comment was posted`
  stepは、いずれもruner側の`run:`ステップとして`gh pr view`を実行しており、
  3回の実測すべてで**問題なく成功している**（Claudeのサンドボックス問題は
  一度も発生していない）。**したがって、Bashサンドボックスの拒否は
  Claudeのツール呼び出し経由に限られ、Actionの通常`run:`ステップには
  及ばないことは実測済みの事実である。**
  （run 31113307119ログの`Count comments before review`・
  `Verify a review comment was posted`両stepの成功を参照）
- 3回目実測で、Claudeが`Write`ではなく`Bash`経由の`gh`/`git fetch`/
  `WebFetch`をすべて試みて拒否されたことは確認済みだが、**`Write`ツール
  そのものがローカルファイルへの書き込みとして拒否されずに通るかどうかは
  今回まだ実測していない。** 同じ実測ログで、ネットワークを伴わない
  `git remote -v`（Bash）は拒否されずに成功しているため、ローカル完結の
  `Write`も同様に通る可能性は高いが、**未検証の推測であり、断定はしない。**

**利点**:

- サンドボックス問題（根本原因は`ERRORS.md`記載の通り判定不能）を
  Claudeに一切触らせないことで**回避できる可能性がある**。
- `on: pull_request`への変更を伴わないため、ADR-005の「起動回数を
  `workflow_dispatch`の実行回数だけに絞る」というコスト制御の前提を
  維持できる。

**欠点**:

- Claudeへの`Read`のみの許可では、`gh pr diff`の内容をどう渡すか
  （ファイルに書き出してから`Read`させる、runner側stepでファイル化して
  `--allowedTools Read`の対象パスに含める、等）の具体的な受け渡し方式を
  別途設計する必要があり、現時点では未設計。
- レビュー結果をClaudeにファイルへ書かせる場合、`Write`ツールの許可範囲
  （書き込み先パスの限定）を`--allowedTools`でどこまで絞れるかは
  未検証。

### 案C: Phase 5 Step 1を保留し、先へ進まない

`ai-loop-implementation-plan_v8.md`のPhase 5は「Step 1に1〜2週間留まる」ことを
前提にしていた。しかし実際には、**3回の実測（2026-08-06〜08-07）を経ても
「コメントが1件でも投稿される」という最小の成功状態にすら到達していない。**
この前提（1〜2週間で足りる）がそもそも成立するかどうかを、この案では
問い直す。

- 案Aも案Bも「検証が必要」な未実測事項を含んでおり、それぞれの検証・実装・
  再実測にさらに時間がかかる。特に案Aはコスト制御の再設計（ADR-005の
  再検討）を伴う。
- 保留する場合、Phase 5全体を止めるか、Step 1の目的（PRの自動レビュー）を
  諦めて次のステップに進むかは別途判断が要る。
- 保留しない場合との対比として、「あと1回の実測で解決する」という楽観的な
  見積もりを避け、**必要な検証項目（案A・案Bそれぞれの未検証事項）を
  先に洗い出してから再開するかどうかを判断する**、という位置づけの案。

## 決定

TBD（人間の判断待ち）
