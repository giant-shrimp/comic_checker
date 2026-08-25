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

## 5. 月次の効果測定

`scripts/loop_metrics.sh` で、AI Loop実装計画書 Phase 7 が挙げる効果測定
指標を集計する。数値と算出コマンドのみを出力し、評価・提言は行わない
（読み方は `ai-loop-implementation-plan_v8.md` Phase 7「効果を測る」を
参照する）。

```bash
./scripts/loop_metrics.sh        # 既定: 直近30日
./scripts/loop_metrics.sh 7      # 集計期間を日数で指定（例: 直近7日）
```

依存: `gh`（認証済みであること）・`jq`。読み取りのみで、GitHubの設定・
issue・PRは一切変更しない。

出力される指標のうち、現時点で「取得不能」と出るものがある（受け入れ
1件あたりのコスト、verify.shをすり抜けた不具合の件数、AI製PR限定の
採用率）。これは実測に基づく判断であり、実装漏れではない。理由は各行に
出力される。取得可能にするための条件（bugラベルの運用開始等）も同じ行に
記載される。

### 採用率100%を品質指標として読まないこと

「採用率（MERGED/作成、全PR対象）」「AI製PR限定の採用率」は、実測すると
いずれも100%に張り付く（本節作成時点の実測: 直近30日で127/127）。**これは
本プロジェクトの運用が構造的にそうなるためであり、計画書 Phase 7 が想定する
「品質の高さの表れ」ではない。**

本プロジェクトは対話セッションで `./scripts/verify.sh` を通してから
PRを作る運用（ADR-001・CLAUDE.mdの作業ルール）を採っている。そのため
「作られたPR」を分母にする限り、検証を通らなかった変更はそもそもPRに
ならず、不採用（MERGEDされないPR）がほぼ発生しない。計画書 Phase 7 の
「採用率50%を下回ったら赤信号」という判定基準は、この分母のままでは
機能しない（100%を下回ることがほぼ無いため、赤信号は原理的に検知
できない）。`scripts/loop_metrics.sh` の出力にも同じ注記が付く。

**指標の再設計（分母の変更等）は本文書の範囲外。** 現状は「読んだ人が
100%を誤って『良好』と解釈しない」ための注記に留める。

### ラベル運用（AI製PR限定の採用率を機能させる場合）

計画書 Phase 7 が意図する採用率（AIの成果物のうち何割が受け入れられたか）
を測るには、AI製PRと人間製PRを区別する必要がある。本リポジトリでは
PRのauthorが常に同一アカウントに帰属し、ブランチ名・コミット内容からも
機械的に区別できないため（実測済み。詳細は該当PRの説明を参照）、
**PRラベルによる人手での区別**を採用する。

- **貼るラベル**: `ai-authored`（`scripts/loop_metrics.sh` 冒頭の`AI_LABEL`
  変数と一致させること。ラベル名を変える場合は両方を揃える）
- **誰が、いつ貼るか**: PRを作成した本人（対話セッションでClaude Codeが
  実装した場合は人間が、PR作成時またはマージ前までに）が判断して貼る。
  機械的な自動判定は無いため、貼るかどうかは人手の判断に委ねられる。
- **ラベル自体の作成**: 初回のみ `gh label create ai-authored --description
  "Claude Codeが実装したPR" --color <任意の16進色>` を実行する（未作成）。
- **貼り忘れた場合どうなるか**: `scripts/loop_metrics.sh` は、`ai-authored`
  ラベルの付与実績が全期間で0件の場合に「取得不能（ラベル未運用）」を
  出力する設計になっている。したがって、貼り忘れが**全件**に及ぶ限りは
  「0%」のような誤った数値が静かに出ることはない。ただし、**一部のPRだけ
  貼り忘れた場合はこの検出機構が働かない**（ラベル自体は使われているため
  「運用あり」と判定され、貼り忘れたPRはAI製PRの母数から単純に漏れる）。
  この種の部分的な貼り忘れは、目視での定期確認以外に検出する手段が
  現時点では無い。

### マージ済みPRの抜き取り確認（ADR-010）

ADR-010（`docs/decisions/ADR-010-loop-adoption-rate-not-adopted.md`）が
記録した通り、計画書 Phase 7 の定量3指標（採用率・コスト・不具合件数）は
本プロジェクトではいずれも判定基準として機能しない。**この抜き取り確認が、
現状で唯一の監視手段である。**

```bash
./scripts/pr_spot_check.sh        # 既定: 直近30日・seed=0・3件抽出
./scripts/pr_spot_check.sh 30 42  # 集計期間とseedを指定
./scripts/pr_spot_check.sh 30 42 5  # 抽出件数も指定（既定3件）
```

同じ期間・同じseedを指定すれば、同じPRが選ばれる（再現可能）。

**判定は必ず人間が行う。AIに説明させない。** スクリプトが出力するのは
PR番号・タイトル・変更ファイル数・差分行数・URLという事実のみで、
「なぜ必要だったか」の判断は含まない。実行後、出力されたPRを**人間が
1件ずつ開いて読み**、計画書の自問

> 「この変更がなぜ必要だったか、1行で説明できるか」

に自分で答える。AIに「説明してください」と頼んで、その説明を読んで
納得する形にしない（それでは「読んだつもり」で終わり、理解の負債は
減らない。計画書1622行）。

判定基準（計画書の記述をそのまま）：3件中1件でも説明できないなら、
マージが速すぎる。**その場合の対応はPRを小さくするか、本数を減らす**
（規則の改訂やスクリプトの修正ではない）。
