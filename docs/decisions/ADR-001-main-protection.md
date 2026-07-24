# ADR-001: main への直push防止に pre-push フック（core.hooksPath方式）を採用する

- 日付：2026-07-24
- 状態：採用

## 背景

AI Loop（`scripts/work_loop.sh`／将来的にはGitHub Actions）を運用するにあたり、
`main` への直接pushを構造的に防ぐ必要が出た。

前提として、このプロジェクトでは「モデルへの指示（プロンプト・`CLAUDE.md`・SKILL.md）は
確率的であり、強制力を持たない」という結論をIssue #14〜#16で実測により得ている。
したがって取り返しのつかない操作は、指示ではなく仕組みで止める必要がある。

当初は `.claude/settings.json` の `permissions.deny` に `Bash(git push:*)` を加える案を
検討したが、「決定論的な防御はリポジトリ設定側（ブランチ保護）に置き、ローカルの
`ask` 運用は速度のために残す」という方針を採ることにした。しかしその前提が成立するかを
実測したところ、成立しないことが判明した（下記「却下した案」1つ目）。

## 決定

**`.githooks/pre-push` によるクライアントサイドフックを採用し、`core.hooksPath` で
配線する。**

- フック本体：`.githooks/pre-push`（リポジトリにコミットする）
- 配線：`./scripts/setup_hooks.sh` を**クローンごとに1回**実行する
- 判定：push対象の `remote ref` が `refs/heads/main` なら exit 1
- `Bash(git push:*)` は `deny` に入れず、現行どおり `ask` のままとする

フックはgit本体が呼ぶため、Claude Code経由・手動ターミナルを問わず**全push経路で
発火する**。これが採用の決め手である。

## 却下した案

### 1. GitHubのブランチ保護 / rulesets

**理由：現在のプラン（GitHub Free）のprivateリポジトリでは利用できない。**

伝聞ではなく、このリポジトリに対して実際にAPIを叩いて確認した（2026-07-24）。

| 叩いたエンドポイント | 結果 |
|---|---|
| `GET /repos/giant-shrimp/comic_checker/rulesets` | HTTP 403 |
| `GET /repos/giant-shrimp/comic_checker/branches/main/protection` | HTTP 403 |

両方とも同一のメッセージを返した：

```
Upgrade to GitHub Pro or make this repository public to enable this feature.
```

公式ドキュメント側の記載とも一致する（rulesetsはGitHub Freeではpublicリポジトリのみ、
privateで使うにはPro / Team / Enterpriseが必要）。

**この記録を残す理由**：将来プランを変更した場合、または本リポジトリをpublicにした
場合には、この決定を再検討する起点になるため。その際は本ADRを `docs/archive/` へ移し、
新しいADRの「背景」から参照すること。

なお、もしPro以降へ移行してブランチ保護を導入する場合、**bypass指定を空にしないと
リポジトリ管理者（＝本プロジェクトの唯一の作業者）は素通りする**点に注意。
rulesetsならBypass listを空のままにする。classic branch protectionなら
「Do not allow bypassing the above settings」（旧UIでは「Include administrators」）を
有効にする必要がある。

### 2. GitHub Pro への課金

費用対効果の判断により却下。本リポジトリは個人開発のprivateリポジトリであり、
`main` 保護のためだけに課金する段階ではない。

### 3. `.claude/settings.json` の `deny` に `Bash(git push:*)` を追加する

**理由：フックと比べて精度が低く、重ねる利得がコストに見合わない。**

フックは push の**行き先**（`remote ref`）を見て判定するため、「`main` への直push」という
危険な行き先だけを塞ぎ、安全なフィーチャーブランチへのpushは通す。
一方 `deny` は行き先を問わずClaude Code経由のpushを一律に止めるため、
フィーチャーブランチへのpushまで失われる。

すなわち、フックだけで危険な経路は塞がっており、`deny` を重ねても
「安全な操作まで止まる」という副作用が増えるだけである。

## 受け入れたリスク

いずれも承知の上で受け入れる。フックの目的は「不可能にすること」ではなく
「事故を意図的な行為に変えること」である。

1. **`--no-verify` による迂回ができる。**
   これは欠陥ではなく設計上の受け入れ。`--no-verify` を打つ人間は、自分が何を
   迂回しているかを理解している。事故（うっかり `git push` を `main` で打つ）は
   これで防げる。

2. **別クローン・別マシンでは `core.hooksPath` が未設定のため、フックが黙って無効になる。**
   `core.hooksPath` は `.git/config` に書かれるローカル設定で、リポジトリに付いて
   回らない。緩和として `./scripts/setup_hooks.sh` を用意し、`work_loop.sh` の
   プリフライトで未設定を警告する（ただし `work_loop.sh` 自身はpushしないため、
   中断ではなく警告にとどめる）。

3. **CI（GitHub Actions）や他マシンからのpushには効かない。**
   クライアントサイドフックである以上、原理的にカバーできない。Phase 5で
   Actionsからのpushを導入する場合は、この決定を再検討する必要がある。

4. **セットアップ手順の周知先が `docs/` しかない。**
   本来なら `CLAUDE.md` に「クローン後に `setup_hooks.sh` を実行する」と書きたいが、
   `CLAUDE.md` は現在 `.gitignore` の対象であり、リポジトリに付いて回らない。
   このため新しいクローンでは、手順書の存在自体に気づけない可能性がある。
   これは `CLAUDE.md` 非追跡問題が実害を出した2件目である（1件目は、CI上で
   プロジェクト記憶がゼロになるというPhase 5のブロッカー）。別途扱う。

   **追記（Issue #18 / 2026-07-25）**: `CLAUDE.md` を `.gitignore` から外し、
   git 追跡対象に戻した（同時にv8計画6-3の目安150行まで剪定し、設計詳細は
   `docs/architecture.md`、既知の制限は `docs/known_limitations.md`、過去に詰まった
   失敗は `ERRORS.md` へ移動した）。これにより「周知先が `docs/` しかない」という
   前提そのものが解消され、`CLAUDE.md` に手順を書けば新しいクローンにも付いて回る。
   ただしIssue #18は移動と参照更新のみを範囲としたため、`CLAUDE.md` への
   「クローン後に `setup_hooks.sh` を実行する」の追記自体はまだ行っていない。
   このリスクは「周知先が無い」から「周知先はあるが未記載」に格下げされた状態である。

## この決定が縛るもの

- **今後 `main` へは直接pushしない。** ブランチを切り、PRを作成してGitHub上で
  マージする。
- 新しいクローンを作ったら、最初に `./scripts/setup_hooks.sh` を実行する。
- フックを変更した場合は `docs/work_loop_testing.md` の 5-a / 5-b を再実行し、
  結果を更新する。

## 補足：`deny` は人間を縛らない

本ADRおよび関連ドキュメントで `permissions.deny` に言及する箇所があるが、
`deny` が縛るのは **Claude Code のツール実行**であって、ターミナルを打つ人間ではない。
`deny` に `git reset --hard` が入っていても、人間が自分のターミナルでそれを実行する
ことには何の制約もない。

この区別はIssue #14以降このプロジェクトで一貫して扱ってきた論点であり、
混同すると「denyに入れたから安全」という誤った安心につながる。
`deny` はエージェントに対する速度制限であり、人間に対する防御ではない。
