# Issue #232 修正の実端末検証（2026-08-29）

## 目的

Issue #232（欠陥B: `review_loop.sh` の承認プロンプトが先行入力／type-ahead を
人間の承認として受理してしまう。`docs/decisions/ADR-011-review-loop-design.md`
決定8 の「毎ラウンド人間が1キーで承認する」人間ゲートが成立しなかった）に対し、
PR #234（段1: `drain_stray_input()` 新設）と PR #235（段2: 承認プロンプト2箇所への
組み込み＋端末判定ガード）で対処し、Issue #232 はクローズ済み。

pytest（`tests/test_review_loop.py` の pty テスト）は sourced 関数単体
（`drain_stray_input()` / `wait_for_quit_only()`）の検証に留まり、`main()` を
通した実ループ・実 `claude` 呼び出し・実端末での本物の type-ahead は踏まない。
そこを埋めるため、実端末で `./scripts/review_loop.sh` を 2 回起動して確認した
記録である。

いずれのセッションも段2（PR #235）の変更を含むコード上で実行された
（各 `verify.txt` が `340 passed`＝段2でテストが 333→340 に増えた後の件数で
あることと符合する。セッション時刻 22:39 / 22:50 JST は PR #235 マージ
13:37 UTC = 22:37 JST の後）。

数値はすべて各セッションディレクトリ
（`~/comic_checker-agent-notes/review_loop/<session>/`）の実ファイルから取った。

両セッションで実行役に与えた instruction は同一で、
「`scripts/review_audit.sh` の役割を 200 字程度で要約し
`docs/ai_loop_state/review_audit_summary.md` に書く」という無害なもの。
検証対象はループの承認手続きであって instruction の中身ではない。

---

## 検証1: 先行入力なし（正常系）— セッション `20260829-223912`

### 条件

先行入力を作らず、通常どおりループを起動。round_1 の監査後、承認プロンプト
`この指示で次ラウンドへ進みますか？ [c=続行 / q=終了]:` で人間が `c` を押した。

### 結果

- 承認プロンプトは停止して入力を待ち、人間の `c` を受理して round_2 を実行した。
- round_2 も監査結果 `APPROVE_CONTINUE` となり、同一 VERDICT 2 ラウンド連続の
  停止条件により `exit 11` で終了した（人間の入力を待たない強制終了）。
- **人間の承認が正しく機能した状態で round_2 まで到達した初めての実行。**
  5 回目試走（`docs/ai_loop_state/review_loop_trial5_2026-08-29.md` 8節）の
  round_2 到達は先行入力による誤承認であり、正常な人間ゲートを経ていなかった。

### 実測値（各 `metrics.json` / `executor_result.json`）

| ラウンド | 区分 | num_turns | duration_ms | total_cost_usd | terminal_reason |
|---|---|---|---|---|---|
| round_1 | 実行役 | 5 | 29368 | 0.0954306 | completed |
| round_1 | 監査役 | 3 | — | 0.230569 | completed |
| round_1 | 起案役 | 1 | — | 0.0613664 | completed |
| round_2 | 実行役 | 7 | 48892 | 0.1287128 | completed |
| round_2 | 監査役 | 3 | — | 0.243255 | completed |
| round_2 | 起案役 | （呼ばれず） | — | — | — |

- round_2 の起案役が呼ばれないのは、監査直後の停止条件（同一 VERDICT 2 連続）で
  `exit 11` に入り、起案役呼び出しより前で終了したため
  （`~/comic_checker-agent-notes/review_loop/20260829-223912/round_2/` に
  `proposer/` サブディレクトリが存在しないことと符合）。
- 実行役セッション ID: round_1 `ca56e07b-a076-48f2-a1ce-f377a8427eb2`、
  round_2 `618ec365-c96d-4472-be3e-1df3b8f1814e`。
- 記録された分の合計コスト: 実行役 0.2241434 ＋ 監査役 0.473824 ＋
  起案役 0.0613664 ＝ **約 0.759 USD**。
- 両ラウンドの `verify.txt` は `340 passed` / `VERIFY PASSED` / 継続の証拠ゲート
  `検出 54/59・副作用 1/37 で一致`。
- 両ラウンドの `verdict.txt` は `APPROVE_CONTINUE`。

---

## 検証2: 先行入力あり（異常系）— セッション `20260829-225022`

### 条件

ループ起動直後に `echo $?` ＋ Enter を端末へ打ち込み、先行入力を作った状態で
実行。これは 5 回目試走で誤承認を引き起こしたのと同じ操作
（`docs/ai_loop_state/review_loop_trial5_2026-08-29.md` 8節「確定した原因」）。

### 結果（実端末での実出力、記録）

round_1 の実行役・監査役・起案役（`claude` サブプロセス。合計で実測 約 90 秒超の
実作業）を経たのち、承認プロンプトの直前に次が表示された:

```
review_loop.sh: 先行入力（7バイト）を検出したため破棄しました。内容:   e   c   h   o       $   ?
```

その後プロンプトは停止して入力を待ち、人間が押した `q` を受理して
`exit 0`（`review_loop.sh: 人間の指示により round 1 で終了します。`）で終了した。
**先行入力は承認として受理されなかった。** round_2 は実行されていない
（セッションディレクトリに `round_2/` が無い）。

### 実測値（各 `metrics.json` / `executor_result.json`）

| ラウンド | 区分 | num_turns | duration_ms | total_cost_usd | terminal_reason |
|---|---|---|---|---|---|
| round_1 | 実行役 | 6 | 29988 | 0.097743 | completed |
| round_1 | 監査役 | 4 | — | 0.25266 | completed |
| round_1 | 起案役 | 1 | — | 0.0597304 | completed |

- 実行役セッション ID: `8bd18adb-888d-48ab-b506-20150f09e882`。
- 起案役は呼ばれており（`round_1/proposer/next_instruction.md` が生成されている）、
  ループは正常に `[c=続行 / q=終了]` プロンプトまで到達したうえで、その直前の
  `drain_stray_input()` が先行入力を破棄した。
- 記録された分の合計コスト: 実行役 0.097743 ＋ 監査役 0.25266 ＋
  起案役 0.0597304 ＝ **約 0.410 USD**。
- `verify.txt` は `340 passed` / `VERIFY PASSED` / `検出 54/59・副作用 1/37 で一致`。
- `verdict.txt` は `APPROVE_CONTINUE`。

### 検出バイト数が 8 ではなく 7 である理由

端末へ打ち込んだのは `echo $?` ＋ Enter の 8 バイト
（`e` `c` `h` `o` ` ` `$` `?` `\n`）。`drain_stray_input()` の読み取りループは
`while IFS= read -t "$STDIN_DRAIN_TIMEOUT" -n 1 -r ch; do buf+="$ch"; done` で、
`read -n 1` が改行バイトを読むと `read` は行区切りとして扱い、成功を返しつつ
`ch` に空文字列を代入する。したがって `buf+=""` となり改行はバイト数に
加算されない（改行バイト自体は標準入力から取り除かれるため、後続の `read` へ
漏れない）。結果 `${#buf}` ＝ 7。これは `scripts/review_loop.sh` の
`drain_stray_input()` 冒頭コメントの設計意図どおりであり、5 回目試走 8節の
バイト単位再構成（`\n` を「消費されるが不一致（空読み）」として数えている）とも
整合する。

---

## pytest（pty テスト）では確認できず、実端末でのみ確認できたこと

`tests/test_review_loop.py` の pty テストは `bash -c 'source ...; <関数>'` で
`drain_stray_input()` / `wait_for_quit_only()` を単体呼び出しし、
`pty.openpty()` ＋ raw mode で擬似端末を stdin にあてがい、
`os.write(master, b"echo $?\n")` で type-ahead を模す。以下は、その方式では
届かず本検証で初めて実端末上で確認できた事項:

1. **`main()` を通した実ループ全体**。pty テストは `main()`（ラウンド for ループ、
   実 `claude` 呼び出し、`[c=続行 / q=終了]` プロンプト本体）を実行しない。
   検証1・検証2 は実行役・監査役・起案役の実 `claude` 呼び出しを挟んだうえで
   承認手続きが機能することを示した。

2. **`[c=続行 / q=終了]` プロンプトの実挙動**。pty テストはこの分岐が `main()`
   内にあり実 `claude` 呼び出しを含むため動的に走らせられず、`case` 分岐の
   静的確認と drain 呼び出し位置の構造テストに留まる（PR #235 本文「テストで
   確認できること・できないこと」）。検証1 は実際の `c` 押下で round_2 へ進み、
   検証2 は実際の `q` 押下で `exit 0` した ―― どちらも実端末での本物のキー
   入力を `main()` 内の当該プロンプトが受理したことを示す。

3. **実端末からの本物の type-ahead が、複数の長時間サブプロセスをまたいで
   残留すること**。pty テストの type-ahead はプロセス起動直前に 1 回書き込むだけ。
   検証2 では、人間がループ起動前に打った `echo $?`＋Enter が、実行役・監査役・
   起案役の 3 つの `claude` サブプロセス実行（実測 約 90 秒超）をまたいで
   標準入力バッファに残り続け、その後の承認プロンプト直前で `drain_stray_input()`
   に検出・破棄された。「長時間の実作業をまたいで残る先行入力」という
   5 回目試走の実条件は pty テストでは再現できない。

4. **誤承認が起きないことの `main()` レベルでの実証**。5 回目試走の誤承認は
   実 `main()` 実行で発生した。pty テストは `drain_stray_input()` 単体が
   先行入力を破棄することしか示せない。検証2 は、その破棄が実ループの
   `[c=続行 / q=終了]` プロンプトの手前で実際に効き、先行入力が承認として
   消費されず `q` 待ちで停止することを、実 `main()` 実行で示した。

5. **端末判定ガードが本物の端末デバイス上で真になり、かつ raw byte を端末へ
   流し込まないこと**。検証2 の出力 `内容:   e   c   h   o       $   ?` は
   `od -An -c` 整形済みで、制御文字がそのまま端末へ出ていない。pty slave
   ではなく実ログインシェル配下の端末で `[ ! -t 0 ]` の分岐と `set -euo pipefail`
   下の `drain_stray_input || true` が想定どおり動くことを確認した。

逆に、pty テストで十分に固定できている事項（非端末 stdin での no-op、IFS= に
よる空白保持、制御文字エスケープ、空ガード、drain の 2 プロンプトへの結線）は
本検証で改めて確認する必要がなく、実施していない。

---

## ADR-011 決定8 の復旧が実証されたこと

`docs/decisions/ADR-011-review-loop-design.md` 決定8 は段階0 として
「毎ラウンド人間が 1 キーで承認する」ことを定める。5 回目試走
（`docs/ai_loop_state/review_loop_trial5_2026-08-29.md` 7節・8節）では
round_1→round_2 の遷移が人間の入力を経ずに起き、**段階0 の唯一の人間ゲートが
成立していなかった**。

本検証で:

- **検証1** ―― 人間の `c` が round_1→round_2 の遷移を実際にゲートした
  （正当な承認で round_2 に到達した初めての実行）。
- **検証2** ―― 先行入力はゲートを通らず、人間の `q` が終了をゲートした。

正常系・type-ahead 混入系の両方で、決定8 の人間ゲートが `main()` 実行上で
機能することを確認した。Issue #232 の対処（PR #234 段1・PR #235 段2）は
実端末で有効である。
