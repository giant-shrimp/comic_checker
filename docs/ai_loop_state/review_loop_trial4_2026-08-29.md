# review_loop.sh 4回目試走記録（2026-08-29、Issue #223・#225修正後の再試走）

ADR-011／ADR-012／ADR-013／ADR-014（`docs/decisions/`）に基づく`scripts/
review_loop.sh`の4回目試走の実測記録。3回目試走（`docs/ai_loop_state/
review_loop_trial3_2026-08-29.md`）で見つかった欠陥1（Issue #223／PR #224）・
欠陥3（Issue #225／PR #226）の修正後、同じ題材の改訂版で再試走したもの。
すべて実際のファイル内容・コマンド出力から転記した値であり、推測・記憶に
よる記述は含まない。導出コマンドはその都度併記する。**コードの修正は行って
いない。記録のみである。**

## 1. 試走の概要

- セッションID: `20260829-034709`（`ls -la ~/comic_checker-agent-notes/
  review_loop/20260829-034709/`の実測値）
- ラウンド数: **1回のみ**（`round_1`のみ存在。`round_2`は存在しない）
- instruction: `~/comic_checker-agent-notes/
  instruction_proposer_trial4_2026-08-29.md`（`diff`コマンドで
  `round_1/instruction.md`と完全一致することを確認済み）
- 実行役は`is_error: true`・`terminal_reason: "max_turns"`で終了し、
  `scripts/review_loop.sh`の`check_executor_result()`（Issue #223／
  PR #224で追加）がこれを検出。`wait_for_quit_only()`により人間の判断待ち
  となった
- **実測の終了コード: `0`**（人間が`q`を押して合流したと報告されている）。
  2回目・3回目試走と同様、プロセスの終了コードそのものをファイルから
  独立に検証する手段はセッションディレクトリ内に無い
  （`find ~/comic_checker-agent-notes/review_loop/20260829-034709
  -maxdepth 1 -type f`で0件を確認）

**3回目試走との違い**: 3回目試走（セッション`20260829-004435`）では、
両ラウンドとも実行役が同じ`is_error: true`・`terminal_reason: "max_turns"`
で終了していたが、当時の`review_loop.sh`はこれを検出せず、空の`report.md`
のまま監査役へ進んでいた（3回目試走記録「4. 欠陥1」）。本試走では、その後
実装された検出ロジックが実運用で初めて機能し、ループが人間の判断待ちで
停止した。

## 2. 題材

3回目試走と同じ「jqの`//`演算子による空文字列の扱いの点検」だが、
instructionを実行役の権限（`EXECUTOR_ALLOWED`）で完遂できる形に書き直した
（jqの直接実行を求めず、Grepツールでの洗い出しとpytest＋`./scripts/
verify.sh`での確認に変更）。3回目試走記録「2. 題材と、題材の設計上の誤り」
が指摘した「instructionが実行役の権限プロファイルと矛盾していた」問題を
修正した版である。

## 3. 実測

`round_1/executor_result.json`（`jq '{is_error, num_turns, total_cost_usd,
terminal_reason, permission_denials}'`）の実測値。

| フィールド | 値 |
|---|---|
| `is_error` | `true` |
| `num_turns` | `21` |
| `total_cost_usd` | `0.8027021999999999` |
| `terminal_reason` | `"max_turns"` |
| `permission_denials`の件数 | `0`（`jq '.permission_denials \| length'`） |

`round_1/`に生成されたファイルは`executor_result.err`（0バイト）・
`executor_result.json`（1,967バイト）・`instruction.md`（3,802バイト）の
3つのみ（`ls -la round_1/`の実測値）。`report.md`・`verify.txt`・
`diff.txt`・`review.md`・`verdict.txt`・`metrics.json`・`prompt.txt`・
`result.json`・`result.err`はいずれも存在せず、**監査役
（`review_audit.sh`）は一度も呼ばれていない。** `round_1/proposer/`
ディレクトリも存在せず、**起案役（`review_proposer.sh`）も一度も呼ばれて
いない。** したがって監査役・起案役のコストは今回発生していない
（3節の`total_cost_usd`は実行役単独の値）。

## 4. 修正が実運用で機能したことの確認（2件）

### 欠陥1の修正（Issue #223／PR #224）が機能した

実行役の`is_error=true`を`review_loop.sh`が検出し、`wait_for_quit_only()`
で人間の判断待ちになった（1節参照）。3回目試走では同じ状態（`is_error:
true`・`terminal_reason: "max_turns"`）が検出されず、空の`report.md`の
まま監査役へ進んでいたことと対比すると、修正が実運用で機能したことが
確認できる。

### 欠陥3の修正（Issue #225／PR #226）が機能したと考えられる

`permission_denials`が`0`件だった（3節参照）。3回目試走では両ラウンド
とも複数件の`Bash`拒否が記録されていた（`jq '.permission_denials |
length'`の実測値: セッション`20260829-004435`のround_1・round_2とも
**8件**）。

**限界（推定であることを明示）**: 今回はinstruction自体も実行役の権限に
合わせて書き直している（2節参照）ため、`permission_denials`が0になった
要因が「起案役へ許可ツールを渡した修正（Issue #225）」なのか
「instructionの書き直し」なのかは、この1回の観測だけでは判別できない。
そもそも**本試走では起案役が呼ばれていない**（3節のとおり`round_1`で
停止したため）ので、Issue #225の修正（起案役が実行役の権限を踏まえた
instructionを生成するようにした改修）の効果そのものは、本試走では
検証されていない。0件という結果は、実行役自身に渡すinstructionが
最初から権限内に収まっていたことの帰結である可能性が高く、起案役の
改修の有無とは別の要因で説明がつく。

## 5. 実行役が単独で作り込んだ誤り（本試走で最も重要な観測）

`round_1/executor_result.json`は空だが、実行役は`is_error=true`に至る
までの過程で作業ツリーに2件の変更を残していた（前ターンの作業で確認・
記録済み）。

- **`tests/test_review_audit.py`への`test_empty_result_field_returns_exit_3`
  の追加** → 妥当な変更。PR #228（コミット`bff8ffb`）で取り込み済み
- **`scripts/review_audit.sh`の`VALID_VERDICTS_RE`の変更** → 誤り。破棄した

### 破棄した変更の内容と、それが誤りである理由

```
変更前: ^VERDICT: (APPROVE_CONTINUE|REVISE|HALT_NEEDS_HUMAN|DONE)[[:space:]]*$
変更後: ^(VERDICT: (APPROVE_CONTINUE|REVISE|HALT_NEEDS_HUMAN|DONE))?[[:space:]]*$
```

（この変更前後の文字列は、破棄前の作業ツリーの内容を記録したコミット
`bff8ffb`（PR #228）のコミットメッセージに残っている。破棄後は作業
ツリーにもgit履歴にも当該diffそのものは残っていない。）

`bash`の`[[ =~ ]]`による実測（PR #228作成時に実施）で、変更後の正規表現
は次の2つの欠陥を持つことを確認済みである。

1. **空行に一致してしまう。** `first_line=""`のとき、変更後の正規表現は
   マッチする（`BASH_REMATCH[1]=""`）。`scripts/review_audit.sh`の
   `review_audit_process_result()`は`[[ "$first_line" =~ $VALID_VERDICTS_RE
   ]]`が真なら「抽出成功」とみなし`exit 0`で`verdict.txt`を書く分岐に
   入る。空文字列の`.result`（`review.md`の1行目が空）に対してもこの
   「成功」分岐に誤って入ってしまう
2. **正常なVERDICT行でも`BASH_REMATCH[1]`の意味がずれる。** 新しい外側の
   括弧`(...)?`によりグループ番号がずれ、`first_line="VERDICT:
   APPROVE_CONTINUE"`に対して`BASH_REMATCH[1]`が`"APPROVE_CONTINUE"`
   ではなく`"VERDICT: APPROVE_CONTINUE"`になる。正常系でも`verdict.txt`
   に誤った値が書かれる

（変異テストの実測結果はPR #228のPR本文・コミットメッセージに記録済み:
この変更を適用した状態で`tests/test_review_audit.py`のテスト10件中5件が
失敗した。）

### 矛盾に気づけなかったこと

実行役は、**自分の変更（`VALID_VERDICTS_RE`の改変）と自分が書いたテスト
（空`result`は`exit 3`になるべきという期待、`test_empty_result_field_
returns_exit_3`）が矛盾していることに気づかないまま**セッションを終えた。
原因は`max_turns`（3節参照）により`./scripts/verify.sh`へ到達できな
かったことである。

**この誤りは、監査役まで到達していれば「報告と実態の矛盾」として検出
されえた性質のものである。** これまで3回の試走（初回・2回目・3回目）で
`REVISE`は一度も出ておらず、監査役が実際に矛盾を検出する場面は実測されて
いなかった（`docs/decisions/ADR-013-stage2-adoption.md`「決定1の根拠」
参照）。本試走は、「監査役に届く前に打ち切られたために誤りが素通り
しかけた」という逆側からの観測を与える。実行役自身が書いたテストと実行役
自身が書いたコード変更が矛盾するという構図は、監査役の「報告書と成果物の
突き合わせ」という設計がまさに検出対象とするパターンに該当する。

**限界（推定であることを明示）**: 実際に監査役がこの矛盾を検出したわけ
ではない。今回は監査役が一度も呼ばれていない（4節参照）ため、「検出され
えた」は正規表現の性質とVERDICT抽出ロジックのコードから導いた推定であり、
実証ではない。

## 6. 新たに判明した問題（Issue #227）

`max_turns`到達時に`.result`が空になり、作業ツリーには成果が残るのに報告
だけが失われる。本試走では`total_cost_usd=0.8027021999999999`（3節）を
投じて実際に有効なテスト1件（5節）を生み出していたが、ループとしては
何も得られない状態で停止した。人間が`git diff`を見て初めて成果の存在が
分かった。

`EXECUTOR_MAX_TURNS`の既定値は`scripts/review_loop.sh:70`
（`EXECUTOR_MAX_TURNS="${EXECUTOR_MAX_TURNS:-20}"`）で`20`。`num_turns=21`
（3節）はこの上限への到達を示す。この事象は本試走から**Issue #227**として
記録した。

## 7. 判別できないこととして明記する事項

- **起案役のinstruction生成品質（ADR-014決定4のsonnet採用の妥当性）は、
  3回目試走に続き本試走でも評価できていない。** 今回は起案役がそもそも
  呼ばれなかった（3節参照）
- **欠陥3の修正（Issue #225）の効果は本試走では検証されていない**
  （4節参照）
- `EXECUTOR_MAX_TURNS=20`がこの種の調査タスクに対して小さすぎるのか、
  題材が大きすぎるのかは、1回の観測（本試走）だけでは判別できない
- **監査役がこの誤り（5節）を検出できたかは推定であり実証ではない。**
  今回は監査役が一度も呼ばれていないため、「報告と実態の矛盾として検出
  されえた」という記述は正規表現・抽出ロジックの性質から導いた推定に
  とどまる
