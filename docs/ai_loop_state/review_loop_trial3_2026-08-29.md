# review_loop.sh 3回目試走記録（2026-08-29、起案役込み初回試走）

ADR-011／ADR-012／ADR-013／ADR-014（`docs/decisions/`）に基づき、起案役
（`scripts/review_proposer.sh`）を組み込んだ`scripts/review_loop.sh`の
初めての実運用試走の実測記録。初回試走（`docs/ai_loop_state/
review_loop_trial_2026-08-26.md`）・2回目試走（`docs/ai_loop_state/
review_loop_trial2_2026-08-27.md`）に続く3回目であり、`docs/ai_loop_state/
review_loop_trial2_2026-08-27.md`の構成に揃える。すべて実際のファイル内容・
コマンド出力から転記した値であり、推測・記憶による記述は含まない。導出
コマンドはその都度併記する。**コードの修正は行っていない。記録のみである。**

## 1. 試走の概要

- セッションID: `20260829-004435`（`ls -la ~/comic_checker-agent-notes/
  review_loop/20260829-004435/`の実測値）
- 対象ブランチ: `chore/jq-empty-string-audit`（`git status --porcelain`が
  クリーンなまま、変更ゼロで残存していることを確認済み）
- instruction: `~/comic_checker-agent-notes/
  instruction_proposer_trial_2026-08-29.md`（`diff`コマンドで
  `round_1/instruction.md`と完全一致することを確認済み。題材は「scripts/
  配下のシェルスクリプトについて、jqの`//`演算子による空文字列の扱いを
  点検し、欠陥があれば修正する」）
- ラウンド数: **2回**（`round_1`・`round_2`が存在）
- 各ラウンドのVERDICT: round_1・round_2とも`APPROVE_CONTINUE`
  （`cat round_{1,2}/verdict.txt`の実測値）
- **実測の終了コード: `11`**（人間が`echo $?`で確認したと報告されている。
  同一VERDICT`APPROVE_CONTINUE`が2ラウンド連続したことによる`scripts/
  review_loop.sh`の停止条件（`if [ -n "$PREV_VERDICT" ] && [ "$VERDICT" =
  "$PREV_VERDICT" ]; then ... exit 11; fi`）に合致する。ただし、2回目試走
  （`review_loop_trial2_2026-08-27.md`「1.」）と同様、プロセスの終了コード
  そのものをファイルから独立に検証する手段はセッションディレクトリ内に
  無い（`find ~/comic_checker-agent-notes/review_loop/20260829-004435 -maxdepth
  1 -type f`は0件）。**これまでの2回の試走では終了コードは常に推定
  （コードを読んでの論理的帰結）にとどまっていたが、本試走で初めて人間の
  `echo $?`による実測値として記録される。**

## 2. 題材と、題材の設計上の誤り

題材（`~/comic_checker-agent-notes/instruction_proposer_trial_2026-08-29.md`）
は「実際にjqを動かして確認せよ」「判定は実際にjqを動かして確認すること
（コードの読みだけで結論を出さない）」と要求していた。

一方、`scripts/review_loop.sh`が実行役に許可するツールは以下のとおりである
（`grep -n "EXECUTOR_ALLOWED" scripts/review_loop.sh`の実測値）。

```
EXECUTOR_ALLOWED="Read,Edit,Write,Glob,Grep,Bash(./scripts/verify.sh)"
```

`Bash(./scripts/verify.sh)`以外の`Bash`呼び出しは許可されていない。
**instructionが要求する「jqを実際に動かして確認する」という作業は、
`./scripts/verify.sh`という固定コマンド以外のBash実行を必要とし、実行役の
権限プロファイルでは実行できない。instructionが実行役の権限プロファイルと
矛盾していた。**

## 3. 実測（表形式）

`round_{1,2}/executor_result.json`（`jq '{is_error, num_turns,
total_cost_usd, terminal_reason}'`）・`round_{1,2}/metrics.json`（監査役）・
`round_1/proposer/metrics.json`（起案役）の実測値。

| | round_1 実行役 | round_1 監査役 | round_1 起案役 | round_2 実行役 | round_2 監査役 |
|---|---:|---:|---:|---:|---:|
| `num_turns` | 21 | 1 | 1 | 21 | 1 |
| `total_cost_usd` | 0.5634870000000001 | 0.1298375 | 0.06855080000000001 | 0.4632374000000001 | 0.030171 |
| `is_error` | **true** | false | false | **true** | false |
| `terminal_reason` | **max_turns** | completed | completed | **max_turns** | completed |

（round_2には`proposer/`ディレクトリが存在しない。理由は「5. 設計どおり
動いた点」参照）

### 起案役の増分率（実測、round_1のみ）

```
実行役+監査役の合計: 0.5634870000000001 + 0.1298375 = 0.6933245000000001
起案役込みの合計:     0.6933245000000001 + 0.06855080000000001 = 0.7618753000000001
増分率: 0.06855080000000001 / 0.6933245000000001 ≈ 0.098873 → 約9.89%増
```

### 事前推定との比較

`docs/ai_loop_state/proposer_design_options_2026-08-28.md`「3.」の事前推定は
約42%〜約139%増だった（起案役=opus・5ターンという未検証の仮定に基づく）。
本試走の実測（起案役=sonnet・1ターン、約9.89%増）はこの推定レンジより
大幅に低い。ただし比較対象のモデル・ターン数の前提自体が異なる
（事前推定はopus・5ターンの仮定、実測はsonnet・1ターンの実績）ため、
「推定が外れた」という単純な結論は書けない。**本試走は1サンプルであり、
起案役のコスト増分の発生率・分散のいずれも推定できない。**

## 4. 観測された欠陥（4件）

### 欠陥1: `review_loop.sh`が実行役の`is_error=true`/`terminal_reason=max_turns`を検出しない

両ラウンドとも`executor_result.json`は`is_error: true`・`num_turns: 21`・
`terminal_reason: "max_turns"`だった（3節の表を参照）。`EXECUTOR_MAX_TURNS`
の既定値は20（`grep -n "EXECUTOR_MAX_TURNS" scripts/review_loop.sh`の実測:
`EXECUTOR_MAX_TURNS="${EXECUTOR_MAX_TURNS:-20}"`）で、`num_turns=21`は
ターン上限到達を示す。

`scripts/review_loop.sh`の実行役呼び出し直後のチェックは次のとおりである
（該当箇所を確認して転記）。

```bash
if [ ! -s "${ROUND_DIR}/executor_result.json" ] || ! jq -e . "${ROUND_DIR}/executor_result.json" >/dev/null 2>&1; then
  echo "review_loop.sh: 実行役の呼び出し自体が失敗しました。" >&2
  ...
  exit 2
fi
jq -r '.result // empty' "${ROUND_DIR}/executor_result.json" > "${ROUND_DIR}/report.md"
```

`exit 2`の条件は「`executor_result.json`が空、または不正なJSON」のみで
あり、`is_error`フィールドの値は一切参照していない。そのため、
`is_error=true`かつ`terminal_reason=max_turns`という明確な失敗シグナルが
ファイルに記録されているにもかかわらず、両ラウンドともループは`exit 2`に
入らず、監査役の呼び出しへ進んだ（`round_{1,2}/review.md`が実在し監査が
成立していることがその証拠）。

### 欠陥2: 監査役が空の`report.md`に対し`APPROVE_CONTINUE`を出した

両ラウンドとも`report.md`・`diff.txt`はサイズ0バイト（`wc -c
round_{1,2}/{report.md,diff.txt}`の実測値、いずれも`0`）。`jq -r '.result
// empty'`が実行役の`.result`をそのまま`report.md`へ書き出す設計であり、
`.result`が空文字列だったことを示す（欠陥1の`is_error=true`により、実行役が
ターン上限まで作業したが最終的な報告テキストを返せなかったと考えられる）。

この空の報告に対し、監査役は両ラウンドとも`APPROVE_CONTINUE`と判定した。
`review.md`のCONTRADICTIONS節を引用する。

- round_1: 「なし（報告書が空のため、成果物と突き合わせるべき事実主張が
  存在しない。diff も空、verify 出力は `308 passed` かつ `VERIFY PASSED`
  で、矛盾の根拠となる箇所は無い）」
- round_2: 「なし（diff・報告書とも内容が空であり、成果物と突き合わせる
  べき事実主張が報告書に存在しない。verify 実出力は `308 passed in 5.67s`
  および末尾 `VERIFY PASSED` で PASS しており、FAIL の根拠も無い）」

**「報告が空だと突き合わせる事実主張が存在せず矛盾なしと判定される」**
という構造上の盲点がここに現れている。`scripts/review_audit_prompt.md`の
VERDICT定義は「報告書の記述と成果物（diff・verify出力）の間に事実の矛盾が
無く、かつverifyがPASSしている場合」に`APPROVE_CONTINUE`とするが、
「報告書に記述そのものが無い」場合の扱いを規定していない。監査役は
FOLLOWUPS節でこの状態自体には言及している（後述「5.」参照）が、VERDICTの
判定には反映されなかった。

### 欠陥3: 起案役が実行役の権限プロファイルを知らないため、実行不可能なinstructionを生成しうる

`round_1/proposer/next_instruction.md`（起案役の出力、round_2/instruction.md
と完全一致）は、実行役への次ラウンド指示として次を含んでいた。

> 2. **各箇所を実 jq で検証する。** コードの読みだけで結論を出さない。
> `.foo` に空文字列 `""` を与えたときに意図した分岐へ入るか、実際に jq を
> 起動して確かめる。箇所ごとに、実行したコマンドとその出力（末尾改行の
> 有無・`[ ! -s ]` 判定の通過可否まで分かる形）を報告書に貼る。

起案役へ渡した入力は元instruction（2節参照）と直近の`review.md`のみ
（`scripts/review_proposer_prompt.md`のプレースホルダは`
{{ORIGINAL_INSTRUCTION}}`・`{{REVIEW}}`の2つ）であり、実行役の
`EXECUTOR_ALLOWED`は含まれない。起案役はこの制約を知りようがないため、
元instructionが要求していた「jqを実際に動かして確認する」という、実行役の
権限プロファイルでは実行できない指示を、次ラウンドのinstructionにも
そのまま引き継いだ。

### 欠陥4: round_2で実行役が一時ファイルをリポジトリ配下へ`cp`しようとし、denyで阻止された

`round_2/executor_result.json`の`permission_denials`最終要素（`jq
'.permission_denials'`の実測値）:

```json
{
  "tool_name": "Bash",
  "tool_input": {
    "command": "cp /tmp/jqp/empty.json /tmp/jqp/missing.json /tmp/jqp/ok.json ~/maehata_ws/comic_checker/ 2>/dev/null; ls ~/maehata_ws/comic_checker/*.json",
    "description": "Copy fixtures into working dir"
  }
}
```

（`tool_input.command`中の絶対パスは、個人名を含めないという本文書の方針
に合わせ`~/maehata_ws/comic_checker/`の形式に正規化して引用した。実際の
値はリポジトリの作業ディレクトリの絶対パスである。）

実行役は`/tmp`配下に作った検証用フィクスチャ（`empty.json`等、欠陥3が
示す「実際にjqを動かして確認する」という指示に従って生成したと考えられる）
を、リポジトリの作業ディレクトリへ`cp`しようとした。`EXECUTOR_ALLOWED`に
`Bash(./scripts/verify.sh)`以外の`Bash`は含まれないため、この`cp`は拒否
された。`round_1`の`permission_denials`にも同種の`Bash`呼び出し拒否が複数
記録されている（`jq --version`・`bash /tmp/jqtest.sh`等、実測値は3節の
コマンド出力参照）。

### 欠陥1・2の組み合わせによる複合的な失敗モード

欠陥1（実行役の失敗を検出しない）と欠陥2（空の報告をAPPROVE_CONTINUEと
判定する）が組み合わさると、**「実行役が一度も作業に成功していないのに
ループが正常に見える」**という失敗モードになる。両ラウンドとも実行役は
ターン上限に達し空の報告を返したが、ループはエラーとして停止せず、監査役
も矛盾なしと判定し、人間が確認するまでは正常進行に見える状態だった。これは
`docs/ai_loop_state/2026-08-26.md`「§3-A」が`work_loop.sh`について記録した
「静かに失敗するループ」と同型の失敗モードである。

## 5. 設計どおり動いた点

- **`exit 11`の初めての実測**（1節参照）。これまでの2回の試走では終了コード
  は常にコードを読んでの推定だった
- **round_2に`proposer/`ディレクトリが存在しない**（`ls -la
  round_2/`の実測値に`proposer`が無い）。round_1のVERDICTと同じ
  `APPROVE_CONTINUE`がround_2でも出た時点で、`scripts/review_loop.sh`の
  停止条件（`exit 11`）が起案役の呼び出しより先に評価され、ループが終了
  した。ADR-014決定6が意図した「起案役の呼び出し位置は監査役の直後」の
  実装（`propose_next_instruction()`は停止条件チェックの**後**に置かれて
  いる）どおり、停止条件に該当したラウンドでは起案役の無駄なコストが
  発生しなかった
- **`round_1/proposer/next_instruction.md`と`round_2/instruction.md`が
  完全一致**（`diff round_1/proposer/next_instruction.md
  round_2/instruction.md`の実測結果: 差分0、exit 0）。ADR-014決定3
  （`build_next_instruction()`の廃止と起案役の出力による置き換え）が実運用
  で意図どおり機能した
- **起案役の出力が監査役の指摘の転記ではなく行動指示になっていた。**
  `round_1/proposer/next_instruction.md`は「実行役への次ラウンド指示：」
  という書き出しに続き、8項目の具体的な作業手順（洗い出しのやり直し・
  実jqでの検証・修正方式の指定・テスト追加・変異テスト・verify.sh実行・
  報告書の必須構成）を番号付きで列挙していた。さらに、起案役は監査役が
  VERDICTの判定には反映しなかった「報告書が空である」という状態そのものを
  問題として認識し、「前ラウンドは diff も報告書も空で提出されており、
  点検が実際に行われたのか、行われた結果「欠陥なし」だったのかを第三者が
  判別できない状態になっている」と明記したうえで、「空の報告書や無言での
  『完了』表現は不可」という指示を追加していた。これは監査役が見逃した点
  （欠陥2）を起案役が補った形になっている

## 6. 判別できないこととして明記する事項

- **起案役のinstruction生成品質（sonnetで十分か）は、本試走からは評価
  できていない。** 実行役が権限不足（2節・欠陥3参照）で実際の作業を
  遂行できなかったため、「起案役が生成した指示に従って実行役が正しく
  作業を完了できたか」という、生成品質を評価するための前提条件そのものが
  成立しなかった。「起案役の出力が（監査役の指摘の転記ではなく）具体的な
  行動指示になっていた」（5節）ことと、「sonnetというモデル選択が
  ADR-014決定4の判断として妥当である」ことは別の問題であり、本試走の
  実測はいずれの評価も完了させていない
- **監査役が空のreportを通す挙動（欠陥2）が、今回の権限不整合に固有の
  ものか、一般的な盲点かは、1回の観測では判別できない。** 権限不整合が
  無い状態（実行役が実際に作業を完了できる状態）でも同様に空のreportが
  発生しうるか、発生した場合に監査役が同じ判定をするかは、別の試走で
  確認する必要がある
- **起案役のコスト増分（約9.89%）は1サンプルであり、発生率も分散も
  推定できない。** 3節で述べたとおり、事前推定（約42%〜約139%増）との
  単純な比較（「推定が外れた」）も、モデル・ターン数の前提が異なるため
  書けない
