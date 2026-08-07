# ADR-006: Phase 5 Step 1（`claude-review.yml`）の設計をやり直す

- 日付：2026-08-07
- 状態：採用
- **[ADR-005](https://github.com/giant-shrimp/comic_checker/blob/main/docs/decisions/ADR-005-auth-oauth-token.md)
  の「代替の制御手段」1項目目（`workflow_dispatch`限定）をsupersedeする。
  ADR-005の認証方式の決定と、残り2項目（`--max-turns`・実行のたびの
  枠観測）は有効なまま**
- 関連: [ADR-004](https://github.com/giant-shrimp/comic_checker/blob/main/docs/decisions/ADR-004-phase5-preconditions.md)
  （決定2・決定3は本ADRの対象外で有効なまま）

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

- `src/modes/detector.ts`の`detectMode()`全文を確認した。`pull_request`イベントは
  `isEntityContext()`が認識するentity contextに含まれる。ソース該当行:

  ```typescript
  // PR events (opened, synchronize, etc.)
  if (isEntityContext(context) && isPullRequestEvent(context)) {
    const supportedActions = [
      "opened",
      "synchronize",
      "ready_for_review",
      "reopened",
    ];
    if (context.eventAction && supportedActions.includes(context.eventAction)) {
      // If prompt is provided, use agent mode (default for automation)
      if (context.inputs.prompt) {
        return "agent";
      }
    }
  }

  // Default to agent mode (which won't trigger without a prompt)
  return "agent";
  ```

  https://github.com/anthropics/claude-code-action/blob/main/src/modes/detector.ts
- ただし**`pull_request`イベントであれば自動的にtag modeになるわけではない**。
  上記の通り`track_progress`が無効なら、`opened` / `synchronize` /
  `ready_for_review` / `reopened`のいずれのアクションであっても、promptが
  与えられていれば結局`"agent"`モードにフォールバックする（`workflow_dispatch`
  と同じ結末）。`track_progress`が有効な場合のみ、関数冒頭の別分岐が
  無条件で`"tag"`を返す:

  ```typescript
  // If track_progress is set for PR/issue events, force tag mode
  if (context.inputs.trackProgress && isEntityContext(context)) {
    if (
      isPullRequestEvent(context) ||
      isIssuesEvent(context) ||
      isIssueCommentEvent(context) ||
      isPullRequestReviewCommentEvent(context) ||
      isPullRequestReviewEvent(context)
    ) {
      return "tag";
    }
  }
  ```

  **したがって、単に`workflow_dispatch`を`pull_request`に変えるだけでは
  今回と同じagentモードの問題が再発する。`track_progress: true`の併用が
  必須になる。**
- `track_progress: true`を併用しtag modeになった場合の挙動は
  `src/modes/tag/index.ts`で確認した。ソース該当行:

  ```typescript
  // Create initial tracking comment
  const commentData = await createInitialComment(octokit.rest, context);
  const commentId = commentData.id;
  ...
  const githubData = await fetchGitHubData({
    octokits: octokit,
    repository: `${context.repository.owner}/${context.repository.repo}`,
    prNumber: context.entityNumber.toString(),
    isPR: context.isPR,
    ...
  });
  ```

  **tag modeは`createInitialComment()`で実行開始前にトラッキング用コメントを
  作成して`commentId`（=`CLAUDE_COMMENT_ID`）を得たうえで、`fetchGitHubData()`
  によりPRのdiff/メタデータを自動取得してプロンプトに注入する。** これは
  agentモードが欠いていた(a)(b)の両方を満たす。
  https://github.com/anthropics/claude-code-action/blob/main/src/modes/tag/index.ts
- **投稿されるコメントはissue commentである（review commentではない）。
  確定した。** `src/mcp/github-comment-server.ts`は
  `const isPullRequestReviewComment = eventName === "pull_request_review_comment";`
  で判定しており、`pull_request`イベントの`GITHUB_EVENT_NAME`は
  `"pull_request"`（`"pull_request_review_comment"`とは別値）のため
  `isPullRequestReviewComment`は`false`になる。この値を使う
  `src/github/operations/comments/update-claude-comment.ts`は

  ```typescript
  if (isPullRequestReviewComment) {
    response = await octokit.rest.pulls.updateReviewComment({...});
  } else {
    response = await octokit.rest.issues.updateComment({...});
  }
  ```

  という分岐であり、`false`側の`octokit.rest.issues.updateComment`
  （issue comment API）が呼ばれる。初回作成（`create-initial.ts`）も同様に
  `pull_request_review_comment`専用の`octokit.rest.pulls.createReplyForReviewComment`
  分岐には該当せず、`octokit.rest.issues.createComment`側になる。
  https://github.com/anthropics/claude-code-action/blob/main/src/mcp/github-comment-server.ts ,
  https://github.com/anthropics/claude-code-action/blob/main/src/github/operations/comments/update-claude-comment.ts ,
  https://github.com/anthropics/claude-code-action/blob/main/src/github/operations/comments/create-initial.ts

  → 現行`claude-review.yml`の`Count comments before review`/
  `Verify a review comment was posted`stepが使っている
  `gh pr view --json comments`（issue commentのみ取得）は、案Aを実装した
  場合も引き続き正しい検出対象になる。
- tag modeがコメント投稿に`update_claude_comment`ツール（Bashを経由しない
  MCP専用ツール）を使う設計であること自体は`src/mcp/github-comment-server.ts`
  から読み取れるが、そのツール呼び出し自体が`ERRORS.md`記載のBash
  サンドボックス問題（`decision_reason_type: "other"`、根本原因未確定）と
  同じ種類の承認要求を経由するかどうかは、**実測していないため確認できず。**
  `update_claude_comment`はBashではないため、少なくとも今回観測した
  「`gh`バイナリの呼び出しが一律拒否される」パターンとは異なる経路である
  可能性はあるが、断定はしない。

**残存リスクの追加検証（一次情報）**:

1. **tagモードは`prompt:`入力を使うか**: 使う。ただし既定プロンプトへの
   追記という形。`src/create-prompt/index.ts`の`generatePrompt()`該当行:
   ```typescript
   const defaultPrompt = generateDefaultPrompt(
     context,
     githubData,
     useCommitSigning,
   );

   if (context.githubContext?.inputs?.prompt) {
     return (
       defaultPrompt +
       `

   <custom_instructions>
   ${context.githubContext.inputs.prompt}
   </custom_instructions>`
     );
   }
   ```
   `context.inputs.prompt`（現行yamlの`prompt:`）は失われず
   `<custom_instructions>`タグ内に追記されるが、既定プロンプト
   （`generateDefaultPrompt()`、約400行相当と報告された長大なテンプレート）が
   先に置かれ、両者が同時にClaudeへ渡る。既定プロンプト側にコード変更・
   コミット関連の一般的な指示が含まれるため、こちらのリポジトリ固有の
   「コードは一切変更しない」という制約とどちらが優先されるかは
   **実測していないため確認できず**。
   https://github.com/anthropics/claude-code-action/blob/main/src/create-prompt/index.ts

2. **`--allowedTools`明示指定でコメント投稿用MCPツールが弾かれないか**:
   `docs/configuration.md`に次の記述がある（逐語引用）:
   > "By default, Claude only has access to:
   > - File operations (reading, committing, editing files, read-only git commands)
   > - Comment management (creating/updating comments)
   > - Basic GitHub operations"

   > "The base GitHub tools are always included. Use `--allowedTools` to add
   > additional tools (including specific Bash commands), and
   > `--disallowedTools` to prevent specific tools from being used."

   「base GitHub toolsは常に含まれる」と明記されており、コメント管理用
   ツール（`mcp__github_comment__update_claude_comment`）はbase toolに
   該当すると考えられるため、`--allowedTools`を明示指定しても弾かれない
   可能性が高い（3回目に拒否されたWebFetchはbase toolに含まれない汎用
   ツールであり、構造が異なる）。ただし文書自体に「`--allowedTools`が
   既定を保持するのか除去するのか曖昧」という趣旨の注記もあり、**一次情報
   だけでは断定できず、実測での確認が必要**。
   https://github.com/anthropics/claude-code-action/blob/main/docs/configuration.md

3. **tagモードは`contents: write`を要求しないか**: `src/mcp/github-file-ops-server.ts`
   が`commit_files`・`delete_files`という2つのMCPツールを登録しており、
   上記のFile operations（committing含む）はこれに該当すると見られる。
   ただしこのサーバは独自の昇格された権限を持たず、ワークフロー自身の
   `GITHUB_TOKEN`を使うだけである。ソース該当行:
   ```javascript
   const githubToken = process.env.GITHUB_TOKEN;
   if (!githubToken) {
     throw new Error("GITHUB_TOKEN environment variable is required");
   }
   ```
   APIコールは`Authorization: Bearer ${githubToken}`で行われるため、
   **ワークフローYAMLの`permissions: contents: read`（ADR-004決定2）を
   維持する限り、Claudeが`commit_files`を呼んでもGitHub API側で拒否される
   はずである。** ADR-004決定2による保護は、ツールの有無ではなくこの
   トークン権限そのものにあり、案A採用後もこの保護は変わらない。
   `commit_files`呼び出しがトークン権限不足で失敗した場合にClaudeが
   どう振る舞うか（エラーを認識して停止するか、リトライでターン数を
   消費するか）は**実測していないため確認できず**。
   https://github.com/anthropics/claude-code-action/blob/main/src/mcp/github-file-ops-server.ts

4. **fork PRの扱い**: GitHub公式ドキュメントによれば、`on: pull_request`
   （`pull_request_target`ではない）のfork由来の実行は次の通り
   （逐語引用）:
   > "With the exception of `GITHUB_TOKEN`, secrets are not passed to the
   > runner when a workflow is triggered from a forked repository. The
   > `GITHUB_TOKEN` has read-only permissions in pull requests from forked
   > repositories."

   これは現行の自作`Reject cross-repository (fork) PR`stepより強い
   プラットフォーム側の保護である。fork由来の`pull_request`実行では
   `CLAUDE_CODE_OAUTH_TOKEN`のようなリポジトリシークレット自体がruner側に
   渡らないため、`Claude PR Review`stepはfork判定stepの有無に関わらず
   認証エラーで失敗するはずである。既存の`Reject cross-repository (fork)
   PR`stepは`workflow_dispatch`前提で書かれているが、`pull_request`
   トリガーへ変えても無害な二重の防御として残せると考えられる。
   https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows
   （`github.event.pull_request.head.repo.full_name`が常に参照可能かは
   **確認できず**。GitHub公式のWebhookペイロード仕様ページを確認したが、
   `pull_request`オブジェクトのネストしたフィールド仕様までは記載が
   見つからなかった）

**欠点（必ず記載）**:

- PRが開く・更新されるたびに起動する構成になり、ADR-005が問題視した
  「金銭的な上限が立てにくい」状態に戻る。`CLAUDE_CODE_OAUTH_TOKEN`経由は
  `--max-budget-usd`が機能しないため、月額の見積もり手段が無いままPRの
  更新頻度に比例して起動回数が増える。
- ADR-005の「代替の制御手段」（起動を人間の`workflow_dispatch`実行回数だけに
  絞る）を放棄することになり、ADR-005自体の再検討（決定のsupersede）が
  必要になる。
- **費用ガードレールの再整理が要る。** `--max-budget-usd`が使えない前提で
  残る歯止めは、`concurrency`（同一PRの多重実行防止のみ、PR本数自体は
  防げない）、`timeout-minutes`、`--max-turns`、`types`の限定
  （`opened`のみにして`synchronize`を外す等。ただし追加コミットを
  レビューしなくなる）、`paths`/`paths-ignore`（ドキュメントのみのPRを
  除外）。いずれも「起動回数そのものの上限」にはならない。
- **月額上限の概算（実測ベース）**: 3回の実測実費（`0.291408` /
  `0.2815584` / `0.472` USD、平均`0.3483` USD、最大`0.472` USD）から
  概算すると、20 PR/月で約6.97〜9.44 USD、50 PR/月で約17.42〜23.60 USD、
  100 PR/月で約34.83〜47.20 USD。plan v8のPhase 7見積もり表
  （「PRレビュー | 上限/回 $1.00 | 回数の目安 20 PR | 月額上限 $20」、
  `--max-budget-usd`の上限値×想定回数という最悪値モデル）と比べると、
  20 PR/月の想定では実測ベースの方が小さい。ただし**この3回はいずれも
  途中で拒否されて終了した実行の費用であり**、サンドボックス問題が
  解消してレビューが最後まで走るようになった場合は`--max-turns`の
  上限まで消費する可能性があり、費用が上がる方向に変わりうる。加えて、
  OAuth経由はドル建て従量課金ではなくサブスク枠の消費（ADR-005）のため、
  このUSD換算はターン数・トークン消費の規模感の参考値に過ぎず、
  ADR-005が明記した「月額の金銭的上限を見積もる手段が無い」という制約は
  案A採用後も変わらない。

**決定に伴う影響（ADR-005の扱い）**: 案Aを採用する場合、ADR-005が
「代替の制御手段」として決定した「トリガーは当面`workflow_dispatch`
のみとする。`pull_request`トリガーは使わない」という一文と正面から
矛盾する。この扱いには少なくとも次の選択肢がある（結論は書かない）。

- **選択肢1: ADR-005の当該決定をsupersedeする新ADRを別途起こす。**
  ADR-005が「PR #83 / ADR-005」の形でADR-004決定1をsupersedeしたのと
  同じ形式。ADR-005の他の決定（認証方式そのもの）は変更しないため、
  supersedeの対象を「代替の制御手段」の項目に限定する必要がある。
- **選択肢2: 本ADR-006自体でADR-005の当該項目をsupersedeする。**
  新しいADRを起こさず、本ADRの「決定」節に「ADR-005の『代替の制御手段』
  の1項目目をsupersedeし、`pull_request`トリガーを許可する」旨を書く形。
  ADR間の参照が1つ増えずに済むが、ADR-006が「設計のやり直し」と
  「認証方式の制御手段の再決定」という2つの話題を1つのADRに含むことになる。
- **選択肢3: `workflow_dispatch`と`pull_request`を併存させる。**
  `on:`に両方のトリガーを持たせ、`pull_request`側にのみ
  `track_progress: true`を設定する。ADR-005の決定文言（「`pull_request`
  トリガーは使わない」）とは字面上矛盾するため、これも実質的には
  ADR-005の再検討を要する。

**未確認**: 上記いずれの選択肢を取るにせよ、ADR-005が「代替の制御手段」で
挙げていた3項目（トリガー限定・`--max-turns`・実行のたびの枠観測）のうち、
後者2つは案Aでも維持できるのか（`--max-turns`は`claude_args`にそのまま
残せるはずだが、`track_progress: true`の付与がターン数の消費傾向に
影響するかは実測していない）は確認できていない。

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
  `docs/faq.md`を「sandbox」「Write」「file writes」で検索したが、
  ワークスペース内へのファイル書き込みがサンドボックス承認の対象になるか
  どうかを明示する記述は**見つからなかった（確認できず）**。

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

**案A（`on: pull_request` + `track_progress: true`）を採用する。**

**ADR-005の決定のうち「代替の制御手段」1項目目——「トリガーは当面
`workflow_dispatch`のみとする。`pull_request`トリガーは使わない」——を
本ADRでsupersedeする。** ADR-005のもう一つの決定（認証は
`CLAUDE_CODE_OAUTH_TOKEN`を使う）は有効なまま維持する。ADR-005の
「代替の制御手段」の残り2項目（`--max-turns`を上限として使う、実行の
たびに対話セッション側の枠への影響を人間が観測する）も有効なまま維持する。

**supersedeする理由**: `workflow_dispatch`限定という決定は、
`anthropics/claude-code-action`のモード判定（`src/modes/detector.ts`）
において`workflow_dispatch`イベントに対応する`case`が無く"agent"モードへ
フォールバックするという副作用を持っていた。これによりPRコンテキストの
自動供給（`fetchGitHubData()`）とコメント追跡（`CLAUDE_COMMENT_ID`）の
両方が失われ、3回の実測（run 31094393958 / 31111080310 / 31113307119）
すべてでコメント投稿に到達しなかった。この副作用はADR-005の検討時点では
認識されておらず、`workflow_dispatch`限定によって得られていたはずの
コスト制御（起動回数を人間の実行回数だけに絞る）は、**そもそも機能する
ワークフローを実現できていない以上、代償に見合っていなかった。**

**コスト制御の代替手段**: `--max-budget-usd`が引き続き使えない
（OAuth経由、ADR-005）前提のまま、次の組み合わせで歯止めをかける。

- `concurrency`（group: PR番号、cancel-in-progress: true）で同一PRの
  多重実行を防ぐ
- `timeout-minutes: 15`で1回の実行時間を制限する
- `--max-turns 15`でターン数を制限する
- `types: [opened]`に限定し、`synchronize`（追加コミットのたびの
  再起動）を含めない。これにより起動回数はPR作成回数と一致し、
  更新頻度には比例しない

**前提の訂正**: ADR-005は「ドル建ての月額上限」という枠組みで費用を
統制しようとしていたが、OAuth経由はサブスク枠の消費であり従量課金では
ないため、**そもそもドル建ての上限という枠組み自体がこの経路には
当てはまらない。** 本ADRの費用試算（3回の実測実費0.291408〜0.472 USDを
基にした月額概算）も、実際の課金ではなくターン数・トークン消費の
規模感を掴むための参考値に過ぎない。この制約は案A採用後も変わらない。

**採用にあたって残る未検証事項**（配置前に実測で確認すること）:

- `mcp__github_comment__update_claude_comment`ツールの呼び出しが、
  3回の実測で観測したBashサンドボックスの承認要求（`decision_reason_type:
  "other"`）と同じ経路を通るかどうか（作業7-2で確認できずのまま）
- `--allowedTools`を明示指定してもbase GitHub tools（コメント管理）が
  弾かれないという理解が正しいか（`docs/configuration.md`の記述は
  一次情報としてやや曖昧、作業7-2）
- `--disallowedTools`が`mcp__github_file_ops__commit_files`等のMCP
  ツールを実際にブロックするか、`--allowedTools`との優先順位（作業8-2、
  確認できず）
- `generateDefaultPrompt()`の「Smart branch handling」節が実際に
  Claudeの挙動へ影響するか、custom_instructions側の打ち消し文で
  十分抑えられるか（作業8-3）
- 「PRの最新コメント＝Claudeのトラッキングコメント」という前提が
  実際に成立するか、成果物ゼロ検出stepの新ロジック（プレースホルダ
  残骸の検出＋本文長）が実runで正しく機能するか（作業8-1・8-4の
  下書きコメントに明記済み）

これらはいずれも`claude-review.yml.draft`（`~/comic_checker-agent-notes/`）
に反映済みだが、**配置前に実測での検証が必要**。

**ADR-005へのsupersede表記について、前例から意図的に外れた判断**:
作業8-5では「ADR-004はADR-005にsupersedeされた際も無編集のままであり、
その前例に倣ってADR-005本体への追記は不要」と提案したが、この判断は
撤回した。ADR-005は「トリガー方針は何か」を調べる人が最初に開く文書で
あり、supersede済みの決定が無標のまま残っていると古い決定を現行の
決定として読んでしまう。これは本ADR自身が扱っている「推定を検証済みの
事実として次の判断の前提に使う」失敗（ERRORS.md参照）と同型であり、
**「前例に倣う」こと自体が、その前例の妥当性を検証しないまま踏襲する
という同種の失敗になりかねないと判断した。** ADR-005のヘッダーに
supersede表記を追記済み。同じ理由でADR-004（決定1がADR-005に
supersedeされている）にも同様の追記が必要と判断し、追記案を提示した
（2026-08-07、ADR-004・ADR-005いずれにも遡って追記した）。

### 4回目実測（PR #90 / run 31155912534）による解消状況

配置PR #90自身の`opened`イベントで新版ワークフローが起動し（詳細は
`ERRORS.md`「`claude-review.yml`（Phase 5 Step 1）: 4回目実測（案A版、
PR #90 / run 31155912534）でコメント投稿に到達した」を参照）、上記
「採用にあたって残る未検証事項」を次の通り切り分ける。

**解消**:

- `mcp__github_comment__update_claude_comment`ツールの呼び出しが、Bash
  サンドボックスの承認要求と同じ経路を通るかどうか → **通らなかった**。
  5件の`permission_denied`はすべて`tool_name: "Bash"`で、コメント関連
  ツールは1件も拒否されていない。
- `--allowedTools`を明示指定してもbase GitHub tools（コメント管理）が
  弾かれないという理解が正しいか → **正しかった**。`--allowedTools
  Read,Glob,Grep`の明示指定下でもコメント投稿・更新は問題なく機能した。
- 「PRの最新コメント＝Claudeのトラッキングコメント」という前提が実際に
  成立するか、成果物ゼロ検出stepの新ロジックが実runで正しく機能するか →
  **成立した**（1次経路・run_id一致で特定に成功）。ただし2次経路
  （bot名フォールバック）は未検証のまま。

**部分的に解消（留保付き）**:

- `generateDefaultPrompt()`の「Smart branch handling」節が実際にClaudeの
  挙動へ影響するか → 今回の1回の実測では、ブランチ作成・pushを試みる
  形跡は観測されなかった。ただしこれは積極的な検証ではなく1回の観測に
  留まるため、「十分抑えられている」と断定はしない。
- `track_progress: true`がtagモードを強制しているか（agentモードへ
  フォールバックしていないか） → トラッキングコメント（issue comment ID
  `5213632357`）が実在し、実行中にジョブリンク付きで更新された
  （agentモードなら`CLAUDE_COMMENT_ID`は`undefined`のままのはずで、この
  動作と整合しない）。**ただし`"mode"`フィールドそのものをログ中に直接
  確認できたわけではなく、間接証拠に基づく判断である点は留保する。**

**未解消のまま**:

- `--disallowedTools`が`mcp__github_file_ops__commit_files`/
  `delete_files`を実際にブロックするか、`--allowedTools`との優先順位 →
  今回も試行そのものが0件で、検証機会が発生しなかった。

### `--max-turns`という歯止めが何を数えているかは、一次情報でも実測でも確定していない

上記「決定」節（「コスト制御の代替手段」）は`--max-turns`を`concurrency`・
`timeout-minutes`・`types`限定と並ぶ歯止めの1つとして採用した。しかし
作業19〜21（4回目実測以降の追加実測）で、**この歯止めが正確に何を
数えているかは、一次情報の確認・実測データの再分析のいずれを尽くしても
確定しなかった。** 特にPR #90は`--max-turns 15`という上限の下で
`num_turns: 20`（上限を上回るツール呼び出し）を経ながら`success`として
終了しており、この矛盾は**未解決のまま残っている**。

詳細（引用した一次情報・実測の生ログ・数値の一覧）はすべて`ERRORS.md`
「`claude-review.yml`（Phase 5 Step 1）: `num_turns`探り実測（作業19〜21）
で分かったこと・分からなかったこと」に記録した。数値の重複記録はここでは
行わない。**「`--max-turns`を歯止めとして使う」という決定自体は覆さない
が、その歯止めの実際の効き方には未解明の部分があることを明記しておく。**
