# 司令塔方式の試走記録（2026-10-02、ADR-034 順序5）

## 1. 試走の概要

- 目的：ADR-034「実装の順序」の5（小さな Issue 1件で試走し、結果を記録する）。
- 対象：Issue #389／PR #390 の一連（上流1 → 下流 → review → 上流2 → マージ → 後始末）。
- 実行環境：クラウド版。司令塔は Opus、実装役は `.claude/agents/implementer.md` の指定どおり Sonnet。
- 結果：差し戻し0回でマージまで到達した。途中で帰属フッタの削除のために実装役が停止し、司令塔が引き継いだ（4.1）。

## 2. 題材

`docs/runbook.md` 3-2 節が削除対象のシークレットとして `ANTHROPIC_API_KEY` を挙げており、ADR-005・ADR-006 と `.github/workflows/claude-review.yml` の設定（`CLAUDE_CODE_OAUTH_TOKEN`）と食い違っていた。文書1ファイル・1節の修正で、判定ロジックと workflow は変更していない。

## 3. 経過

### 3.1 上流1

- 司令塔が関係する文書を読み、Issue 案を示してユーザの承認の手前で停止した。
- 承認後に Issue #389 を作成した。

### 3.2 下流（実装役）

- 実装役はツール呼び出し14回、約49秒、トークン約3万で完了した。ターン数は不明。
- verify.sh・pre-push-check の各検査は終了コード 0。PR #390 を作成した。
- PR 本文の帰属フッタを削除できず、停止して司令塔に返した（4.1）。

### 3.3 上流2

- check-runs は review・verify ともに success。review にブロッカーはなかった。
- 差し戻しは0回。

### 3.4 マージと後始末

- ユーザがマージした。Issue #389 は自動クローズされた。
- post-merge-cleanup で verify.sh は終了コード 0。ローカルのブランチを削除し、リモートのブランチは削除済みだった。

## 4. 新たに得られた知見

### 4.1 gh api（REST）で作成しても帰属フッタが付いた

Issue・PR を `gh api`（REST）で作成しても、本文の末尾に帰属フッタが付いた。実装役は GitHub MCP の更新用ツールを持たず、`gh api` の PATCH で削除してもフッタが付き直った。司令塔が GitHub MCP の更新用ツールで削除した。

### 4.2 Issue 本文の更新後の取得が分類器に拒否された

司令塔が GitHub MCP で Issue 本文を更新した後、本文を取得して照合するコマンドが分類器に拒否された。その後、単独のコマンド（パイプや `;` でつながない）での取得は通った。

### 4.3 環境はブランチ名を指定しなかった

指示は「環境が指定する `claude/` で始まるブランチ」を使うとしていたが、環境はブランチ名を指定しなかった。司令塔が命名した。

### 4.4 実装役の最終応答に Xvfb の確認欄がない

`.claude/agents/implementer.md` の最終応答の形式に Xvfb の確認欄がなく、確認の結果が報告されなかった（CI の verify は success）。

### 4.5 指示の「1つずつ実行」に反した

後始末の確認で、司令塔が読み取りコマンドを1回の応答でまとめて出した。結果には影響しなかった。

### 4.6 報告の規則と「全文書き写す」指示が食い違った

司令塔の報告の規則（Issue・PR のタイトルとコミットの件名を書かない）と、依頼文を「全文書き写す」という指示が食い違った。

## 5. 改善の候補

本記録では列挙だけを行う。対応はそれぞれ別の Issue とする。

- `.claude/skills/publish-github/SKILL.md`：REST で作成しても帰属フッタが付くこと、Issue にもフッタの削除が要ることを書く（4.1）。
- `.claude/agents/implementer.md`：GitHub MCP の更新用ツールがない場合は、フッタの削除を司令塔に返す手順を書く（4.1）。
- `.claude/skills/commander/SKILL.md`：本文の照合の取得を単独のコマンドで行う手順を書く（4.2）。
- `.claude/skills/commander/SKILL.md`：環境がブランチ名を指定しない場合の命名の規則を書く（4.3）。
- `.claude/agents/implementer.md`：最終応答の形式に Xvfb の確認欄を足す（4.4）。
- `.claude/skills/commander/SKILL.md`：報告の規則と「全文書き写す」指示のどちらを優先するかを書く（4.6）。
- `.claude/skills/post-merge-cleanup/SKILL.md`：手順3で PR のタイトルを表示せずに Issue 番号を抽出する（4.6）。

いずれも deny 対象のファイルであり、変更はユーザが行う（commander の手順4）。

## 6. 未決定

- `scripts/loop_metrics.sh` と `docs/runbook.md` 5章の扱い：未決定（試走後に別途判断）。
