---
name: post-merge-cleanup
description: Use this skill whenever the user reports that they merged a PR via the GitHub GUI (e.g. "mergeは終えた", "マージ完了", "PRをマージした", "merge done"). Directly performs the standard post-merge housekeeping for comic_checker: pulls main, confirms via the GitHub REST API (gh api) that the PR landed as merged, checks whether the linked Issue was auto-closed and proposes a gh issue close command if not, runs verify.sh, and safely deletes the now-merged feature branch (local delete after ancestor check, remote via fetch --prune only). Never merges PRs, closes issues, or pushes to main itself — the human always merges via GUI first; this skill only runs the cleanup steps afterward, and still stops for explicit confirmation before anything outside its fixed read-only/cleanup scope.
---

# Post-Merge Cleanup

comic_checker の運用では，PRのマージは常に人間がGitHub GUIで行う（ADR-001）．
このスキルは，マージ**後**の定型後始末を実行する．

## いつ使うか

ユーザーが「mergeは終えた」「マージ完了」のように，GUIでのマージ完了を
報告してきたとき．対象PR番号・ブランチ名が会話中に判明していない場合は，
1点だけ確認してから進める．

## GitHub への問い合わせ方法（Issue #328）

クラウドセッション（claude.ai/code）では，GraphQL を使う `gh pr list`・`gh pr view`・
`gh issue view` が HTTP 403 になる．このスキルでは，ローカル・クラウドの両方で動く
REST API（`gh api`）だけを使う．`gh pr ...`・`gh issue view` に置き換えない．

## 実行内容（このスキルが直接行う）

1. **main を最新化**
```
   git switch main
   git pull
```

2. **マージ結果の確認**（推測せず`gh api`出力で確認する原則）
```
   git log --oneline -3
   gh api repos/giant-shrimp/comic_checker/pulls/<PR番号> --jq '{number, state, merged_at, merge_commit_sha, head_ref: .head.ref}'
```
   `merged_at` が null でないことを出力で確認する（null なら未マージ）．
   未マージならここで停止し，状況を報告する．
   `head_ref` を手順5の対象ブランチ名として使う．

3. **対応Issueの状態確認**（Fixes/Closesキーワードの入れ忘れ対策。Issue #33・#38・#75で
   PRマージ後もIssueがOPENのまま残る事例が続いたための追加。ERRORS.mdは対象外
   ―― コードの正誤ではなくGitHub側の状態管理のため）
```
   gh api repos/giant-shrimp/comic_checker/pulls/<PR番号> --jq '{title, body}'
```
   タイトル・本文から `#N` パターンを正規表現で抽出する．このリポジトリの
   PRタイトルは慣習的に `#N ...` で始まるため，多くのケースで抽出できる．
   - **番号が1件だけ見つかった場合**:
     `gh api repos/giant-shrimp/comic_checker/issues/<N> --jq '{state, state_reason}'`
     で `state` が `open` のままなら，`gh issue close <N> --comment "..."` の
     コマンド案を提示する．**実行はしない**（`Bash(gh issue close*)` は
     `.claude/settings.local.json` でdeny対象のため，Claude Codeからは
     そもそも実行できない．人間がターミナルまたはGitHub GUIでクローズする）．
   - **番号が0件，または異なる複数の番号が見つかった場合**: 自動判定は行わず，
     「対応Issueを特定できなかった」旨を報告するに留める（無関係なIssueを
     誤ってクローズ候補として提示しないため）．

4. **検証**
```
   ./scripts/verify.sh
```
   pytestのサマリ行をそのまま報告する．既知のゲート値
   （例: M6-B-4 検出54/59・副作用1/37）が変化していないか明記する．
   verify が落ちたらここで停止し，diffを提示して指示を仰ぐ
   （このスキルの範囲外の対応が必要なため）．

5. **ブランチの後始末**
   対象ブランチがローカルに存在しない場合（GitHub の Web 画面で作成したブランチ等）は，
   ローカル削除は不要とし，リモートの確認（下記の `git fetch --prune`）だけを行う．

   ローカルに存在する場合:
```
   git merge-base --is-ancestor <branch> main
```

   YESの場合は `git branch -d <branch>` でローカル削除．
   NOの場合（squash マージ等）は，次を実行する．

```
   gh api "repos/giant-shrimp/comic_checker/pulls?state=all&head=giant-shrimp:<branch>" --jq '[.[] | {number, merged_at, merge_commit_sha, head_sha: .head.sha}]'
```

   次の3条件をすべて確認する．
   (a) 該当 PR がちょうど1件で，`merged_at` が null でない．
   (b) `git merge-base --is-ancestor <merge_commit_sha> main` が YES．
   (c) `git rev-parse <branch>` が `head_sha` と一致．
   3条件をすべて満たす場合だけ `git branch -D <branch>` でローカル削除．
   1つでも満たさない場合は削除せず停止し，満たさなかった条件と `git log --oneline main..<branch>` を報告する．
   リモートは `git fetch --prune` で状態確認のみ行う．
   既に `[deleted]` なら追加操作は不要．そうでない場合も
   `git push origin --delete` は実行せず，状況を報告して指示を待つ
   （リモートブランチの明示的削除はこのスキルの自動実行範囲に含めない）．

## このスキルが行わないこと（常に停止して人間の指示を待つ）

- PRのマージ・クローズ・コメント追加
- Issueのクローズ実行（コマンド案の提示までで，実行は人間が行う。deny対象でもある）
- リモートブランチの明示的削除（`push origin --delete`）
- 新しいブランチの作成
- 次のIssue／タスクへの着手
- commit / push を伴う一切の変更（後始末はread-only操作とローカルブランチ削除のみ）

## 出力フォーマット

- 箇条書きで（罫線表は使わない）
- 各コマンドの出力を報告する
- ブランチ削除の可否と実行結果を明記する
- 完了したら停止し，次の指示を待つ

## 注意

- 途中のいずれかのステップで想定外の状態（PRが未マージ，verify失敗，
  ancestor確認NG，`gh api` の失敗）に遭遇したら，そこで止めて報告し，
  以降のステップには進まない．
