---
name: post-merge-cleanup
description: Use this skill whenever the user reports that they merged a PR via the GitHub GUI (e.g. "mergeは終えた", "マージ完了", "PRをマージした", "merge done"). Directly performs the standard post-merge housekeeping for comic_checker: pulls main, confirms via gh that the PR landed as MERGED, checks whether the linked Issue was auto-closed and proposes a gh issue close command if not, runs verify.sh, safely deletes the now-merged feature/loop branch (local delete after ancestor check, remote via fetch --prune only), and checks logs/ gitignore hygiene for loop/<issue> branches. Never merges PRs, closes issues, or pushes to main itself — the human always merges via GUI first; this skill only runs the cleanup steps afterward, and still stops for explicit confirmation before anything outside its fixed read-only/cleanup scope.
---

# Post-Merge Cleanup

comic_checker の運用では，PRのマージは常に人間がGitHub GUIで行う（ADR-001）．
このスキルは，マージ**後**の定型後始末を実行する．

## いつ使うか

ユーザー（遥哉）が「mergeは終えた」「マージ完了」のように，GUIでのマージ完了を
報告してきたとき．対象PR番号・ブランチ名が会話中に判明していない場合は，
1点だけ確認してから進める．

## 実行内容（このスキルが直接行う）

1. **main を最新化**
   ```
   git switch main
   git pull
   ```

2. **マージ結果の確認**（推測せず`gh`出力で確認する原則）
   ```
   git log --oneline -3
   gh pr list --state all --limit 5
   ```
   対象PRが MERGED になっていることを出力で確認する．
   なっていなければここで停止し，状況を報告する．

3. **対応Issueの状態確認**（Fixes/Closesキーワードの入れ忘れ対策。Issue #33・#38・#75で
   PRマージ後もIssueがOPENのまま残る事例が続いたための追加。ERRORS.mdは対象外
   ―― コードの正誤ではなくGitHub側の状態管理のため）
   ```
   gh pr view <PR番号> --json title,body
   ```
   タイトル・本文から `#N` パターンを正規表現で抽出する．このリポジトリの
   PRタイトルは慣習的に `#N ...` で始まるため，多くのケースで抽出できる．
   - **番号が1件だけ見つかった場合**: `gh issue view <N> --json state` で
     `OPEN` のままなら，`gh issue close <N> --comment "..."` のコマンド案を
     提示する．**実行はしない**（`Bash(gh issue close*)` は
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
   ```
   git merge-base --is-ancestor <branch> main
   ```
   YESの場合のみ `git branch -d <branch>` でローカル削除．
   NOの場合は削除せず停止し，`git log --oneline main..<branch>` を報告する．
   リモートは `git fetch --prune` で状態確認のみ行う．
   既に `[deleted]` なら追加操作は不要．そうでない場合も
   `git push origin --delete` は実行せず，状況を報告して指示を待つ
   （リモートブランチの明示的削除はこのスキルの自動実行範囲に含めない）．

6. **logs/ のgitignore hygiene確認**（対象ブランチが `loop/<issue>` の場合のみ）
   `logs/` 配下の生成物（run_N.json, outcome_N.txt, verify_N.log 等）が
   `git check-ignore -v` で無視対象になっており，
   `git status --porcelain` を汚していないことを確認する．
   汚れている場合は削除・追跡変更をせず，状況を報告して指示を待つ．

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

- 対象ブランチが `loop/<issue>` かどうかでステップ6の要否が変わる．
  `docs/*`, `chore/*` 等の対話セッション由来ブランチではステップ6を省略してよい．
- 途中のいずれかのステップで想定外の状態（PRがMERGEDでない，verify失敗，
  ancestor確認NG，logs/の汚れ）に遭遇したら，そこで止めて報告し，
  以降のステップには進まない．