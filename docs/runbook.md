# 緊急停止手順（runbook）

事故の最中に読む文書。設計の説明ではなく、手順を上から順に実行できる形にしてある。
背景・理由を知りたい場合は `docs/decisions/ADR-001-main-protection.md` を参照。

---

## 1. ローカルループ（work_loop.sh）を止める

### 1-1. 実行中のプロセスを止める

- フォアグラウンドで動かしている場合: そのターミナルで `Ctrl+C`
- バックグラウンド／別ターミナルで動かしている場合:
  ```bash
  pgrep -f work_loop.sh
  kill <上で出たPID>
  ```
- `work_loop.sh` 自体には `trap` 等のシグナルハンドラは無い（`scripts/work_loop.sh` の
  内容で確認済み）。素の bash スクリプトなので、`Ctrl+C`／`kill` は通常のシグナル伝播に
  従う。`claude` 呼び出しは `timeout "$CLAUDE_TIMEOUT" claude ...`（既定600秒）で
  ラップされているだけで、それ以外の独自の停止用フックは無い
- `claude` 呼び出しが応答しなくなっている場合でも、`CLAUDE_TIMEOUT`（既定600秒）に
  達すれば `timeout` が自動的にその呼び出しを終了させる。ただし `MAX_ITER`
  （既定3）に達するまでは次のイテレーションへ進もうとするので、完全に止めたいなら
  上記の `kill` が確実

### 1-2. 途中commit・`loop/<issue>/iter-N` タグが残った状態からの後始末

`work_loop.sh` はイテレーションごとに `loop_git.sh commit` → `loop_git.sh tag` で
ローカルにコミットとタグを残す（verify失敗版も含む。push するのは成功時のみ）。

状態を確認する:
```bash
git log --oneline loop/<issue番号>
git tag -l 'loop/<issue番号>/*'
git show loop/<issue番号>/iter-N --stat   # 特定のイテレーションの内容を見る
```

不要なら片付ける（`work_loop.sh` プリフライト4のエラーメッセージが提示する
コマンドと同じもの。`main` に戻ってから実行する）:
```bash
git switch main
git branch -D loop/<issue番号>
git tag -d $(git tag -l 'loop/<issue番号>/*')
```

**この時点でリモート（origin）には何も出ていないのが通常**（`loop_git.sh push` は
verify通過・no-op でない場合にしか呼ばれない）。念のため次で確認する:
```bash
git ls-remote --heads origin 'loop/<issue番号>'
```
何も出力されなければ origin には無い。出力があれば「2. push済みの変更を戻す」へ。

### 1-3. `loop/<issue>` ブランチを捨てる場合と残す場合の判断基準

- **捨ててよい**: outcome が `failed` / `no-op` / `no_progress` /
  `no_progress_unmeasurable` / `max_iterations`（= success以外）で、かつ
  `git show loop/<issue>/iter-N --stat` を見て残す価値のある内容が無い場合
- **残す（少なくとも判断するまで消さない）**: outcome が `success` で
  `push_failed` / `pr_failed` の場合。これは verify を通過し、意図した変更が
  既にコミットされている状態なので、捨てずに「2. push済みの変更を戻す」ではなく
  手動での push / PR作成を検討する対象になる
- **`no_progress` 等でも即座に捨てない方がよい場合**: 複数の `iter-N` タグが
  あり、最後のイテレーションより前の版の方が「落ち方がまし」なことがある
  （`work_loop.sh` 冒頭コメントに明記されている設計）。`git show loop/<issue>/iter-N`
  を1つずつ見てから判断する

---

## 2. push済みの変更を戻す

### 2-1. feature branch（`loop/<issue>` 等）の場合

- **PRがまだ無い、または draft のまま**: リモートブランチを削除する
  ```bash
  git push origin --delete loop/<issue番号>
  ```
  `.githooks/pre-push` は `main` への直push だけを対象にしているため、
  feature branch の push・削除はこのフックの対象外（ブロックされない）
- **PRが既に存在する場合**: `gh pr close <PR番号>` でクローズする。
  Claude Codeからこのコマンドが実行可能かどうかは今回未確認
  （`gh issue close*` は `.claude/settings.local.json` の `deny` 対象と
  確認済みだが、`gh pr close` については確認していない）。**確実なのは
  人間がターミナルまたはGitHub GUIで行うこと**

### 2-2. 万一 `main` に入ってしまった場合（`--no-verify` 迂回を含む）

通常の push 経路では `.githooks/pre-push` が `main` への直push をブロックするため、
原則として起こらない。起こりうる条件は ADR-001 の「受け入れたリスク」に明記されている
次の3つ：

1. 人間が `git push --no-verify` で意図的／誤ってフックを迂回した場合
2. 別クローン・別マシンで `core.hooksPath` が未設定のまま push した場合
   （`core.hooksPath` はローカル設定でリポジトリに付いて回らない）
3. GitHub Actions 等CIからの push（クライアントサイドフックは原理的にCIには効かない。
   ただし現時点でこのリポジトリに push を行うワークフローは存在しない）

対処:
```bash
git log --oneline -5              # 何が入ったか確認する
git revert <入ってしまったコミットのSHA>
git push origin main
```
**`git reset --hard` や force-push で戻さないこと。** 既に他者が fetch している
可能性のある共有ブランチ（`main`）なので、履歴を書き換えず `revert` で
打ち消しコミットを積む。

**このリポジトリ（GitHub Free + private）はブランチ保護を設定できない**
（`branches/main/protection` は403 `Upgrade to GitHub Pro or make this repository
public` で確認済み）。したがって `main` への防御は現状 `.githooks/pre-push` と
目視だけであり、上記の事後 `revert` が実質的な最終手段になる。

---

## 3. GitHub Actions を止める（将来用）

**現時点ではこのリポジトリに対象となる常時稼働ワークフローは存在しない。**
`.github/workflows/` には `verify.yml`（PR/push時のVERIFY Gate）と
`build-windows.yml`（手動・タグ契機のEXEビルド）のみがあり、どちらも
Claude を使った自律実行ではない。以下はPhase 5（GitHub Actions常時稼働）に
着手し、該当ワークフローを追加した場合に備えた手順。

### 3-1. ワークフローの無効化
GitHubの当該リポジトリ → Actions タブ → 対象ワークフローを選択 →
`⋯` → **Disable workflow**

### 3-2. シークレット削除
Settings → Secrets and variables → Actions → 該当シークレット
（`ANTHROPIC_API_KEY` 等）を削除。
**削除だけでなく、Anthropic Console側でもAPIキーを失効させること。**
削除しただけでは、既に流出したキーは有効なままである。

### 3-3. 実行中ジョブのキャンセル
Actions タブ → 実行中のワークフロー実行を選択 → **Cancel workflow**

---

## 4. 判断基準：どこまで戻すか

**既定は「`./scripts/verify.sh` が通る直近の地点まで戻す」。**

- ローカルループの後始末（1章）でも、`main` への誤った変更を戻す場合（2章）でも、
  戻した後に必ず `./scripts/verify.sh` を実行し、通ることを確認する
- `loop/<issue>/iter-N` タグを遡って良い版を探す場合、タグだけでは
  verify の合否が分からない（verify失敗版もタグは打たれる）。`logs/verify_N.log`
  または `logs/outcome_N.txt` と突き合わせて判断する。ただし `logs/` は
  `.gitignore` 対象のため、事故発生からしばらく経っている、または別マシンで
  対応している場合はローカルに残っていない可能性がある。その場合は
  `iter-N` を1つずつ取り出して手動で `./scripts/verify.sh` を回して確認する
- `main` まで戻す必要が生じた場合も同様に、`revert` 後に `verify.sh` を
  実行してから push する
