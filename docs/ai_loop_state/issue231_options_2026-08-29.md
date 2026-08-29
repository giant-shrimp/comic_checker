# 欠陥A（diff.txt が未追跡ファイルの変更を含まない）への対処選択肢（2026-08-29）

Issue #232（欠陥B）が完了したため、5 回目試走で対に検出された Issue #231
（欠陥A）の調査と対処選択肢を整理する。**本文書は選択肢の列挙までであり、
実装・採否は含まない（採否はユーザが決める）。**

数値・引用はすべて実出力・実ファイルからの転記で、導出コマンドを併記する。

## 読んだ資料

- Issue #231 本文（`gh issue view 231 --json body`）
- `scripts/review_loop.sh`（`diff.txt` 生成箇所・監査役呼び出し）
- `scripts/review_audit.sh`（`render_prompt()`・引数処理）
- `scripts/review_audit_prompt.md`（`{{DIFF}}` プレースホルダ）
- `scripts/review_audit.settings.json`（監査役の権限プロファイル）
- `~/comic_checker-agent-notes/review_loop/` 配下の全セッションの `round_*/diff.txt`
  ・`prompt.txt`・`report.md`・`review.md`
- `docs/decisions/ADR-013-stage2-adoption.md`・`docs/decisions/ADR-014-proposer-design.md`

---

## 1. 該当箇所の再確認（事実）

### 1.1 Issue #231 本文（全文転記）

導出: `gh issue view 231 --json number,title,state,body`

> ## 事象
>
> scripts/review_loop.shが監査役へ渡すdiff.txtは`git diff`のみで生成され
> （git status --porcelainを併用していない）、新規作成された未追跡ファイル
> の内容は一切含まれない。
>
> ## 根拠
>
> docs/ai_loop_state/review_loop_trial5_2026-08-29.md「8. 検出した欠陥」
> 欠陥A。セッション20260829-154741のround_1・round_2とも、対象ファイル
> （新規作成のため未追跡）に対する変更がありながらdiff.txtは0バイトだった
> （wc -cで実測）。
>
> scripts/review_loop.shの該当箇所:
>   git diff > \"${ROUND_DIR}/diff.txt\" || true
>
> 一方、no-op検出用のsnapshot()はgit status --porcelainを含んでおり、この
> 欠陥の影響を受けない。影響を受けるのはdiff.txtのみである。
>
> ## 実害
>
> 本試走では監査役が実ファイルを直接読んで補い、実質的な判定への悪影響は
> 無かった。ただし、監査役に渡される「証拠」としてのdiff.txtが本来の役割
> （報告書と成果物の突き合わせの根拠）を果たしていない状態であり、監査役が
> 実ファイルを読まなかった場合に見逃しにつながる可能性がある。
>
> ## 範囲
>
> 本Issueは事象の記録のみとし、対処の方向（git status --porcelainの併用、
> 未追跡ファイルの内容そのものの添付、等）は決めない。

state: `OPEN`。

### 1.2 `diff.txt` を生成している箇所

導出: `grep -n 'diff' scripts/review_loop.sh`

- `scripts/review_loop.sh:414`
  ```
  git diff > "${ROUND_DIR}/diff.txt" || true
  ```
  この 1 行のみが監査役へ渡る `diff.txt` を生成する。`git status --porcelain`
  も `git ls-files --others` も併用していない。`git diff`（引数なし）は
  追跡済みファイルのワークツリー変更のみを出力し、未追跡ファイルは対象外。

- 参考: 同ファイルには既に未追跡ファイルを捕捉する前例が 2 箇所ある。
  - `snapshot()`（`scripts/review_loop.sh:105-112`）: `git status --porcelain`
    と `git ls-files --others --exclude-standard` を含む。no-op ハッシュ用で、
    Issue #231 本文が言うとおり本欠陥の影響を受けない。
  - `preserve_work_tree_state()`（`scripts/review_loop.sh:221-240`、Issue #227
    ／PR #230）: `git diff > preserved_diff.txt` と
    `git status --porcelain > preserved_status.txt` を **両方** 書く。
    コメント `scripts/review_loop.sh:214` に
    「新規（未追跡）ファイルを捉えるために別途保存する（git diffには
    現れないため）」と明記。ただしこれは is_error=true 経路専用で、
    正常系（監査役へ渡す `diff.txt`）には使われない。

### 1.3 監査役プロンプトに `diff.txt` が渡る経路（行番号付き）

導出: `grep -n 'diff\|render_prompt\|DIFF' scripts/review_audit.sh` /
`cat -n scripts/review_audit_prompt.md`

1. `scripts/review_loop.sh:417`
   ```
   "${SCRIPT_DIR}/review_audit.sh" "${ROUND_DIR}/diff.txt" "${ROUND_DIR}/verify.txt" "${ROUND_DIR}/report.md" "$ROUND_DIR" \
   ```
   `diff.txt` を第 1 引数（`<diff-file>`）として渡す。

2. `scripts/review_audit.sh:143`
   ```
   local diff_file="$1" verify_file="$2" report_file="$3" output_dir="$4"
   ```
   `scripts/review_audit.sh:148` で `[ -f "$diff_file" ]` を確認、
   `:153` で絶対パス化。

3. `scripts/review_audit.sh:164-165`
   ```
   render_prompt "$SCRIPT_DIR/review_audit_prompt.md" "$diff_file" "$verify_file" "$report_file" \
     "${output_dir}/prompt.txt"
   ```

4. `scripts/review_audit.sh:66-89` `render_prompt()` ―― Python で
   `{{DIFF}}` をファイル中身に単純置換（`:75-76` で `diff_path` を読み、
   `:82` で `text = text.replace("{{DIFF}}", diff_text)`）。

5. `scripts/review_audit_prompt.md:4-7`
   ```
   ## diff
   ```diff
   {{DIFF}}
   ```
   ```
   `diff.txt` が 0 バイトなら、この fenced block は空行 1 つになる。

6. `scripts/review_audit.sh:167-173` ―― `prompt.txt` を標準入力から
   `claude -p --model opus --settings scripts/review_audit.settings.json`
   に投入。

### 1.4 監査役の権限プロファイル（本欠陥の実害範囲に関係）

導出: `cat scripts/review_audit.settings.json`

```
{
  "permissions": {
    "deny": [ "Write", "Write(*)", "Edit", "Edit(*)", "NotebookEdit",
              "NotebookEdit(*)", "Bash", "Bash(*)" ]
  }
}
```

`--allowedTools` は渡していない（`scripts/review_audit.sh:167-173`）。したがって
監査役は **Read / Grep / Glob を使える**が、**Bash は deny** ―― 監査役自身が
`git status` や `git diff` を実行して未追跡ファイルを発見することはできない。
未追跡ファイルの存在を知る手段は「報告書（`{{REPORT}}`）の記述から推測して
`Read` する」経路のみ。

---

## 2. 実データによる裏付け

### 2.1 全セッションの `diff.txt` サイズ

導出:
```
find ~/comic_checker-agent-notes/review_loop -name diff.txt -path '*/round_*' \
  | sort | while read f; do printf '%8d  %s\n' "$(wc -c < "$f")" "${f#$HOME/comic_checker-agent-notes/review_loop/}"; done
```

| バイト数 | セッション/ラウンド | 実行役タスクの対象 |
|---|---|---|
| 2014 | 20260826-235806/round_1 | 追跡済み `ERRORS.md` の修正 |
| 4478 | 20260827-012024/round_1 | 追跡済み `docs/ai_loop_state/2026-08-26.md` の修正 |
| 4478 | 20260827-012024/round_2 | 同上（round_1 と同一内容。ADR-013 で既知） |
| 0 | 20260829-004435/round_1 | jq `//` 点検（**報告書も 0 バイト。別事象**） |
| 0 | 20260829-004435/round_2 | 同上 |
| 0 | 20260829-154741/round_1 | **新規** `docs/ai_loop_state/review_loop_exit_codes.md` 作成 |
| 0 | 20260829-154741/round_2 | 同ファイル（未追跡のまま）を更新 |
| 0 | 20260829-163046/round_1 | **新規** `docs/ai_loop_state/review_audit_summary.md` 作成 |
| 0 | 20260829-223912/round_1 | **新規** `docs/ai_loop_state/review_audit_summary.md` 作成 |
| 0 | 20260829-223912/round_2 | 同ファイル（未追跡のまま）を更新 |
| 0 | 20260829-225022/round_1 | **新規** `docs/ai_loop_state/review_audit_summary.md` 作成 |

非空の 2 セッション（235806・012024）は、いずれも **追跡済みファイル** を
修正したもの（`head -1 <diff.txt>` が `diff --git a/ERRORS.md ...` /
`diff --git a/docs/ai_loop_state/2026-08-26.md ...`）。`git diff` が正しく
機能している。

### 2.2 未追跡ファイルが「落ちていた」再現事例

Issue #231 が挙げるセッション **20260829-154741** を中心に、実データ上の
再現事例は **計 4 セッション・6 ラウンド**:

| セッション/ラウンド | 作成/更新された未追跡ファイル | `diff.txt` | 監査 VERDICT |
|---|---|---|---|
| 20260829-154741/round_1 | `docs/ai_loop_state/review_loop_exit_codes.md`（新規） | 0 バイト | REVISE |
| 20260829-154741/round_2 | 同（未追跡のまま更新） | 0 バイト | DONE |
| 20260829-163046/round_1 | `docs/ai_loop_state/review_audit_summary.md`（新規） | 0 バイト | （診断セッション） |
| 20260829-223912/round_1 | `docs/ai_loop_state/review_audit_summary.md`（新規） | 0 バイト | APPROVE_CONTINUE |
| 20260829-223912/round_2 | 同（未追跡のまま更新） | 0 バイト | APPROVE_CONTINUE |
| 20260829-225022/round_1 | `docs/ai_loop_state/review_audit_summary.md`（新規） | 0 バイト | APPROVE_CONTINUE |

導出（例、154741/round_1 の監査プロンプトの `## diff` ブロック）:
`sed -n '4,7p' ~/comic_checker-agent-notes/review_loop/20260829-154741/round_1/prompt.txt`
```
## diff
```diff

```
```
→ `{{DIFF}}` が空行 1 つに展開されている。

### 2.3 report.md / review.md との突き合わせ

**20260829-154741/round_1**（Issue #231 が引くラウンド）:

- `report.md` 冒頭:
  「### 作成したファイル / `docs/ai_loop_state/review_loop_exit_codes.md`
  （新規作成。同名文書は存在しなかった）」
- `review.md`（VERDICT: REVISE）補足:
  「（補足：diff が空である点は矛盾ではない。`git status` 上
  `docs/ai_loop_state/review_loop_exit_codes.md` は未追跡ファイルであり、
  `git diff` には現れない。他の全 exit 行番号 … は実ファイルと一致を
  確認した。）」
  → 監査役は `diff.txt` が空なので **実ファイルを直接 Read して照合** した。
  その照合の結果、報告書の行番号誤り（`exit 1` の位置を 94 行目としたが
  実際は 93 行目）を検出し REVISE を出している。

**20260829-154741/round_2**（VERDICT: DONE）:

- `review.md`:「報告書の主要な事実主張は、いずれも現物と一致することを
  確認した（diff が空なのは対象ファイル … が未追跡（`git status` の `??`）で
  `git diff` に現れないためで、実ファイルを直接読んで照合した）。」

**20260829-223912 / 20260829-225022**（本会話での段2 検証セッション）:

- いずれも `review.md` に「提示された diff が空だった。成果物が未追跡ファイル
  （`?? docs/ai_loop_state/review_audit_summary.md`）のため `git diff` に
  現れない … 実ファイルを直接読んで確認した」旨の記述があり、監査役が毎回
  補っている。

### 2.4 実データ上の結論

- **未追跡ファイルが `diff.txt` から落ちる事象は再現性がある**（新規ファイル
  作成タスクでは毎回発生。上表 6 ラウンド）。
- **この欠陥が監査 VERDICT を誤らせた実データ上の事例は無い。** 観測された
  全ラウンドで、監査役は `diff.txt` が空であることに自ら気づき、報告書が
  挙げたパスを `Read` して照合し、防御的な VERDICT（1 件は行番号誤りを
  捉えて REVISE）を出している。
- ただしこの補償は「監査役が報告書からファイルパスを読み取り、自発的に
  `Read` する」という LLM の裁量に依存しており、保証されていない
  （Issue #231「実害」欄と同じ認識）。

---

## 3. 対処の選択肢（実装はしない）

### 選択肢A: `git status --porcelain` を新プレースホルダ `{{STATUS}}` として監査役へ渡す

- **変更対象ファイルと要点**:
  - `scripts/review_loop.sh:414` 付近 ―― `git status --porcelain >
    "${ROUND_DIR}/status.txt"` を追加。
  - `scripts/review_loop.sh:417` ―― `review_audit.sh` 呼び出しに
    `status.txt` を第 5 引数として追加。
  - `scripts/review_audit.sh` ―― 位置引数 4→5、`render_prompt()` に
    `status_file` を追加し `{{STATUS}}` を置換。`usage`／`[ -f ]` チェック更新。
  - `scripts/review_audit_prompt.md` ―― `## 作業ツリーの状態（git status --porcelain）`
    セクションと `{{STATUS}}` を追加。
- **想定される副作用**:
  - 監査役プロンプトの増分は porcelain 出力のみ（変更ファイル 1 個につき
    1 行、`?? path` 形式）。実データでは 1〜2 行程度。入力トークン増は軽微。
  - `diff.txt` 肥大化は無い（`diff.txt` 自体は不変）。
  - 監査役は「未追跡ファイルが**存在すること**」は知れるが、**中身は
    見えない**。従来どおり `Read` は必要。
  - `review_audit.sh` の引数個数が変わる。`tests/test_review_audit.py` は
    `review_audit_process_result()` のみを対象にしており（同ファイル
    docstring・`grep -n 'def test' tests/test_review_audit.py`）、`main()`／
    `render_prompt()`／引数個数を検査するテストは無いため、既存テストは
    落ちない。ただし `<diff-file> <verify-output-file> <report-file> <output-dir>`
    を前提に呼ぶ箇所（`review_loop.sh:417`）と `usage` 文言の同時更新が必要。
- **検証方法（識別力）**:
  - pytest で検証できる: `review_loop.sh` が `status.txt` を生成する行の
    構造テスト、`render_prompt()` を `source` して `{{STATUS}}` が
    porcelain 文字列で置換されることの単体テスト、`review_audit.sh` の
    引数不足時 `exit 64` の回帰。
  - **識別力未検証**: 「porcelain を渡したことで監査役がより正確な VERDICT を
    出す」ことは pytest では確認できない（監査役は opus の LLM）。§2.4 の
    とおり、証拠欠落が VERDICT を誤らせた実データ事例が無いため、この案が
    実際の誤判定を防ぐ効果は実データで示せない。
- **既存 ADR との整合**:
  - ADR-014 決定1（`docs/decisions/ADR-014-proposer-design.md:58-62`）は
    **起案役**への入力を `original instruction + review.md` に絞り、
    `diff`/`report` を重ねて渡さない方針。本案は**監査役**への追加であり
    起案役の入力は変えないため矛盾しない。
  - ADR-013 は `diff.txt` を監査・no-op 判定の中核証拠として扱っており
    （`ADR-013:88,104-105`）、その証拠を補強する方向で整合。

### 選択肢B: 未追跡ファイルの内容も `diff.txt` に含める（`git add -N` 後に `git diff`）

- **変更対象ファイルと要点**:
  - `scripts/review_loop.sh:414` を、たとえば
    ```
    git ls-files --others --exclude-standard -z | xargs -0 -r git add -N --
    git diff > "${ROUND_DIR}/diff.txt" || true
    git reset -q -- . 2>/dev/null || true
    ```
    のように、未追跡ファイルを intent-to-add で一時的に索引へ登録してから
    `git diff` を取り、直後に取り消す。`review_audit.sh` 側は無変更
    （引数個数不変）。
- **想定される副作用**:
  - **`diff.txt` 肥大化**: 新規ファイルが全行 `+` 付きで出る。20260829-154741
    が作成した `docs/ai_loop_state/review_loop_exit_codes.md` は現在 359 行
    （`wc -l docs/ai_loop_state/review_loop_exit_codes.md`。PR #233 で追跡化
    済み）。この規模の新規ファイルを作るタスクでは `diff.txt` が数百行規模に
    なり、監査役の入力トークンが新規ファイル行数にほぼ比例して増える
    （`review_audit_summary.md` 系タスクは instruction が「200字程度」を
    指定しており増分は小さいが、上限はタスク次第）。ADR-014 決定3 が起案役で
    警戒した「入力の肥大化」と同じ懸念が監査役側で生じる。
  - **索引の変更という副作用**: `git add -N` はワークツリーの index を
    変える。直後に `git reset` で戻すが、途中で失敗すると index が汚れ、
    後続の `snapshot()`（`git diff HEAD` を含む）や
    `preserve_work_tree_state()` の出力意味が変わる。`set -euo pipefail`
    下での失敗時挙動の検討が要る。
  - `git add -N` 済みファイルは `git diff` に出るが、`git diff --stat` の
    行数カウント等、周辺挙動も変わりうる。
- **検証方法（識別力）**:
  - pytest で検証できる: 一時 git リポジトリ（`tests/test_review_loop.py`
    の `_init_repo()` の前例）で新規ファイルを作り、当該処理を通した後の
    `diff.txt` に新規ファイルの中身が現れること・処理後に index が元に
    戻っていること（`git status` が処理前と一致）を検証できる。この案は
    「中身が入る」ことを**構造・実挙動レベルで検証できる**点が A・C より強い。
  - **識別力未検証**: VERDICT の正確さへの寄与は §2.4 のとおり実データで
    示せない。
- **既存 ADR との整合**:
  - ADR-014 決定1・3（起案役の入力を絞る／肥大化を避ける）とは**思想的に
    逆行**する（監査役側とはいえ入力を増やす）。ADR-014 は起案役限定の
    決定なので直接の違反ではないが、レビューで論点になりうる。
  - ADR-013 の「`diff.txt` を証拠の中核とする」方針には最も忠実。

### 選択肢C: 監査役プロンプトに「未追跡ファイルは diff に出ない。報告書が挙げたパスを Read せよ」と明記（プロンプトのみ変更）

- **変更対象ファイルと要点**:
  - `scripts/review_audit_prompt.md` のみ。`## diff` セクションの直後か
    出力形式の前に、
    「新規作成ファイルは未追跡のため `## diff` に現れないことがある。
    報告書が新規作成・追加と述べるパスは `Read` で直接確認し、報告書の
    記述と照合せよ」といった 2〜3 行の指示を追加。
  - `scripts/review_loop.sh`・`scripts/review_audit.sh` は無変更。
- **想定される副作用**:
  - 入力トークン増はテンプレート数行分のみで最小。
  - `diff.txt` は不変（肥大化なし）。索引にも触れない。
  - 効果は監査役の指示遵守と、報告書がファイルパスを正しく書いていることに
    全面的に依存する。報告書がパスを書かない／曖昧な場合は救えない
    （監査役は Bash deny のため自力で `git status` できない ―― §1.4）。
    §2.3 のとおり監査役は既にこの補償を自発的に行っているので、
    「現状の追認」に近い。
- **検証方法（識別力）**:
  - pytest で検証できる範囲は**ほぼ無い**。テンプレート文字列に当該指示が
    含まれることの文言テストは書けるが、監査役の挙動は検証できない。
  - **識別力未検証**（本案は特に、pytest では実効性を一切示せないことを
    明示的に宣言する）。
- **既存 ADR との整合**:
  - ADR-013 決定3・ADR-013「限界」（`ADR-013:124`「この対処が監査役の
    出力を完全に無害化する保証は無い」）と同じく「プロンプトで監査役の
    振る舞いを誘導するが保証はしない」という既存の割り切りの範囲内。
  - 入力を増やさない点は ADR-014 の思想と整合。

### 選択肢D: `git status --porcelain` を `diff.txt` の冒頭へ連結する（`review_loop.sh` のみ変更・署名不変）

- **変更対象ファイルと要点**:
  - `scripts/review_loop.sh:414` を
    ```
    { git status --porcelain; echo; git diff; } > "${ROUND_DIR}/diff.txt" || true
    ```
    に変更。`review_audit.sh`・`review_audit_prompt.md`・引数個数は無変更。
  - 監査役から見ると `## diff` ブロックの先頭に `?? docs/ai_loop_state/foo.md`
    のような porcelain 行が入り、その下に通常の `git diff` が続く。
- **想定される副作用**:
  - `diff.txt` の意味が「純粋な diff」から「status + diff」に変わり、
    ファイル名（`diff.txt`）と中身がややずれる。`## diff` の fenced block
    に非 diff 行が混じる。
  - 入力トークン増は porcelain 行数分のみ（軽微）。肥大化なし。索引にも
    触れない。
  - 選択肢A と同じく「存在は分かるが中身は見えない」。監査役の `Read` は
    引き続き必要。
  - 署名・テンプレート・テスト対象関数のいずれも変えないため、既存テストへの
    影響が最小。ただし `diff.txt` 生成行は `main()` 内にあり関数化されて
    いないため（`preserve_work_tree_state()` と違い `source` して呼べない）、
    pytest では構造テスト止まりになる。
- **検証方法（識別力）**:
  - pytest で検証できる: `review_loop.sh` の当該行が `git status --porcelain`
    と `git diff` の両方を `diff.txt` へ書く形になっていることの構造テスト。
    実挙動テストは、生成行を `preserve_work_tree_state()` のように関数へ
    切り出せば一時リポジトリで検証可能になる（切り出しは追加変更）。
  - **識別力未検証**（VERDICT 正確さへの寄与は実データで示せない、§2.4）。
- **既存 ADR との整合**:
  - 選択肢A と同じ（起案役入力は不変、`diff.txt` を証拠として補強）。
  - `preserve_work_tree_state()`（Issue #227／PR #230）が既に
    「`git diff` と `git status --porcelain` の両方を書く」前例を作って
    おり、同ファイル内の実装様式と整合。

---

## 4. 選択肢の比較（採否はユーザが決める）

| 観点 | A（{{STATUS}}追加） | B（中身をdiffへ） | C（プロンプトのみ） | D（statusをdiff.txt冒頭へ） |
|---|---|---|---|---|
| 変更ファイル数 | 4 | 1 | 1 | 1 |
| `review_audit.sh` 署名変更 | あり（4→5） | なし | なし | なし |
| 未追跡ファイルの**中身**が監査役に渡るか | 渡らない（存在のみ） | 渡る | 渡らない（Read頼み） | 渡らない（存在のみ） |
| `diff.txt`／入力トークン肥大化 | 軽微 | **新規ファイル行数に比例** | なし | 軽微 |
| 索引（git index）を触るか | 触らない | **触る（要 reset）** | 触らない | 触らない |
| pytest で実挙動を検証できるか | 一部（render_prompt 単体） | **可（一時リポジトリ）** | ほぼ不可 | 構造のみ（関数化すれば可） |
| 識別力（VERDICT 改善効果）の検証 | 未検証 | 未検証 | 未検証 | 未検証 |
| ADR-014（入力を絞る思想）との関係 | 整合 | 逆行気味 | 整合 | 整合 |
| 既存の実装様式との整合 | 中 | 中 | 高（ADR-013の割り切り内） | 高（preserve_work_tree_state の前例） |
| 現状（監査役が自発 Read）からの実質的前進 | 中（自発判断の起点を機械的に提供） | 大（Read 不要化） | 小（追認） | 中（Aと同等） |

補足:
- **識別力はどの案も未検証**。§2.4 のとおり、この欠陥が VERDICT を誤らせた
  実データ事例が存在しないため、「この案なら誤判定を防げる」ことを既存
  データで実証する手段が無い。pytest で確認できるのは「証拠が監査役に
  届く形になっているか」という**形式面**に限られる。
- B だけが「未追跡ファイルの中身そのもの」を監査役へ渡す。他の 3 案は
  「未追跡ファイルが存在する」ことを伝えるに留まり、中身の照合は監査役の
  `Read` に依存し続ける（監査役は Bash deny のため `git` を自力実行不可）。
- A と D は伝える情報が同じ（porcelain）。違いは「新引数＋新プレースホルダ
  として明示的に分離するか（A）」「既存 `diff.txt` に混ぜて署名を変えないか
  （D）」。

---

## 本文書で決めていないこと

- 4 案のどれを採るか（複数案の組み合わせも含め、採否はユーザ）。
- 未追跡ファイルの内容を渡す場合の上限（大きな新規ファイルをどう扱うか。
  行数上限・要約・添付見送りなど）。
- `diff.txt` 生成行を関数へ切り出すか（切り出せば pytest の実挙動テストが
  可能になるが、本 Issue の範囲外の追加変更）。
- 監査役に Bash（`git status` 限定）を許可する案 ―― 権限プロファイルの
  変更は ADR-014 決定5（監査役・起案役とも全 deny）に触れるため、
  本文書では選択肢として展開していない。必要ならユーザ判断で別途検討。
- `tests/` の具体的なテスト追加内容（本タスクは `scripts/`・`tests/` の
  変更を禁止しているため、実装 PR で設計する）。

### 識別力（VERDICT 改善効果）は既存データで決められない

§2 の実測から確定している事実と、それが選択肢の評価に与える帰結:

- 未追跡ファイルが `diff.txt` から落ちる事象は **4 セッション・6 ラウンド**で
  再現した（§2.2 の表）。
- そのうち、この欠陥が監査 VERDICT を誤らせた事例は **0 件**。観測された
  全ラウンドで監査役は `diff.txt` が空であることに自ら気づき、報告書が
  挙げたパスを `Read` して照合している（§2.3。1 件は行番号誤りを捉えて
  REVISE、他は APPROVE_CONTINUE/DONE で、いずれも実ファイル照合を経ている）。
- この補償は「監査役が報告書からファイルパスを読み取り、自発的に `Read` する」
  という LLM（opus）の裁量に依存しており、コード上の保証は無い（監査役は
  Bash deny のため自力で `git status` を実行できない ―― §1.4）。
- 上記より、**選択肢 A〜D のいずれも「識別力」を既存データで実証できない。**
  誤判定事例が 0 件である以上「この案なら誤判定を防げる」ことを示す比較対象
  が無く、どの案も「識別力未検証」という宣言を付けたうえでの採用にしか
  ならない（pytest で確認できるのは「証拠が監査役に届く形になっているか」
  という形式面に限られる ―― §3 各案の「検証方法」）。
