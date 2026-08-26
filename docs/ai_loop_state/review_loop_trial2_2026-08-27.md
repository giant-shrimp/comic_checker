# review_loop.sh 2回目試走記録（2026-08-27、REVISE試走）

ADR-011／ADR-012（`docs/decisions/`）の段階0オーケストレータの2回目試走の実測記録。
初回試走（`docs/ai_loop_state/review_loop_trial_2026-08-26.md`）に続き、今回はブランチ
検査（ADR-012以前は無かった）とFOLLOWUPS除去（`build_next_instruction()`、ADR-012決定3）
を初めて実運用で確認する目的で行った。**題材はREVISEを誘発する構造として選定したが、
結果は2ラウンドともAPPROVE_CONTINUEだった。** すべて実際のファイル内容・コマンド出力
から転記した値であり、推測・記憶による記述は含まない。導出コマンドはその都度併記する。

## 1. セッション概要

- セッションID: `20260827-012024`（`ls -1 ~/comic_checker-agent-notes/review_loop/`
  の実測値）
- 対象ブランチ: `fix/stale-c-section`（`main`ではない。ADR-012で追加したブランチ
  検査を実際にすり抜けて起動できたことが、セッションディレクトリ・round_1が生成
  されている事実から間接的に確認できる。**ブランチ検査が初めて実運用された**）
- instruction: `~/comic_checker-agent-notes/review_loop_trial2/instruction_round1.md`
  （`docs/ai_loop_state/2026-08-26.md`§3-Cの陳腐化した記述の修正を指示）
- ラウンド数: **2回**（`round_1`・`round_2`が存在）
- `review_loop.sh`の終了コード: **コード上は`exit 11`（同一VERDICTが2ラウンド連続）
  のはず。** ただし、この値はプロセスの実際の戻り値としてファイルに記録されて
  おらず、セッションディレクトリ直下（`round_1`・`round_2`以外）に該当ファイルは
  無い（`find "$SESSION" -maxdepth 1 -type f`で0件を確認）。以下で示すとおり、
  round_1・round_2ともVERDICT=`APPROVE_CONTINUE`（同一）であり、`scripts/
  review_loop.sh`の該当コード（`if [ -n "$PREV_VERDICT" ] && [ "$VERDICT" =
  "$PREV_VERDICT" ]; then ... exit 11; fi`）に照らせばこの条件に合致するため、
  **コードロジック上は`exit 11`になるはずだが、プロセスの実際の終了コードそのもの
  はファイルから独立に検証できていない**

## 2. round_1・round_2に生成されたファイル一覧とサイズ

`ls -la ~/comic_checker-agent-notes/review_loop/20260827-012024/round_{1,2}/`の実測値。

| ファイル | round_1 | round_2 |
|---|---:|---:|
| `instruction.md` | 1,798 | 1,748 |
| `executor_result.json` | 2,907 | 2,747 |
| `executor_result.err` | 0 | 0 |
| `report.md` | 921 | 486 |
| `verify.txt` | 507 | 507 |
| `diff.txt` | 4,478 | 4,478 |
| `next_instruction.md` | 1,748 | （round_2は`c`が選ばれなかったため生成されない） |
| `prompt.txt` | 7,421 | 6,986 |
| `result.json` | 4,398 | 4,966 |
| `result.err` | 0 | 0 |
| `review.md` | 2,425 | 2,990 |
| `verdict.txt` | 17 | 17 |
| `metrics.json` | 134 | 134 |

## 3. 実行役・監査役の実測値

`executor_result.json`・`metrics.json`（監査役）・`result.json`（監査役の`modelUsage`
確認用）から実測。

| | round_1 実行役 | round_1 監査役 | round_2 実行役 | round_2 監査役 |
|---|---:|---:|---:|---:|
| モデル | sonnet（`modelUsage`に`claude-sonnet-5`） | opus（`modelUsage`に`claude-opus-5`） | sonnet | opus |
| `num_turns` | 9 | 2 | 4 | 3 |
| `total_cost_usd` | 0.2098964 | 0.262723 | 0.0951604 | 0.275611 |
| `is_error` | false | false | false | false |
| `terminal_reason` | completed | completed | completed | completed |

## 4. コスト比較

- round_1合計（実行役+監査役）: `0.2098964 + 0.262723 = 0.4726194` USD
- round_2合計: `0.0951604 + 0.275611 = 0.3707714` USD
- **2ラウンド合計: `0.8433908` USD**
- 初回試走（1ラウンドのみ）: `0.5353943` USD/ラウンド
- round_1単体との比較: `0.4726194 - 0.5353943 = -0.0627749`（初回より安い）
- round_2単体との比較: `0.3707714 - 0.5353943 = -0.1646229`（初回より安い）
- 2ラウンド平均（`0.8433908 / 2 = 0.4216954`）との比較: `-0.1136989`（初回より安い）

いずれも初回試走より1ラウンドあたりのコストが低かった。原因は未調査（実行役・
監査役とも`num_turns`が初回（実行役12・監査役7）より少ない。ラウンドを追う
ごとにタスクが軽くなった可能性、プロンプトキャッシュの効き方の違いなど複数の
仮説が考えられるが、今回はこの差の原因を特定する材料を集めていない）。

## 5. round_2/instruction.mdの検証（`build_next_instruction()`の初めての実運用）

`diff round_1/review.md round_2/instruction.md`の実測結果:

```
14,16d13
< FOLLOWUPS:
< - 2026-08-26.md:244 の再取得コマンドが...
< - 本節の「その後の対応」が指す修正の出所...
```

**差分はFOLLOWUPS節の2項目のみ。** VERDICT行・CONTRADICTIONS節は完全に一致して
おり、`build_next_instruction()`（ADR-012決定3）が実運用で意図どおりFOLLOWUPS節
だけを除去したことを確認した。テストでは通っていたが実データでの使用はこれが
初めてであり、テストのfixtureと同じ挙動が実データでも再現されたことになる。

## 6. 監査役が出力形式を守っていたか（round_1とround_2の比較）

初回試走（2026-08-26）では、監査役が`scripts/review_audit_prompt.md`の出力形式
指定に無い「検証した根拠（矛盾なしの裏付け）」という見出しをCONTRADICTIONS節に
自発的に追加していたことが判明していた（`docs/ai_loop_state/
stage1_options_2026-08-27.md`「2.」参照）。

今回の2ラウンドを比較すると、**この挙動はセッション間で不安定だった**。

- **round_1**: `review.md`のCONTRADICTIONS節は「CONTRADICTIONS: なし」の直後に
  直接箇条書きが続く形式で、**「検証した根拠」という仕様外の見出しは含まれて
  いなかった**
- **round_2**: `review.md`のCONTRADICTIONS節には「検証した根拠（矛盾なしの
  裏付け）」という**仕様外の見出しが含まれていた**（初回試走と同じパターン）

同じプロンプトテンプレート（`scripts/review_audit_prompt.md`）を使っていても、
監査役が出力形式を厳密に守るかどうかは実行のたびに変わりうることが、同一
セッション内の2ラウンドの比較で確認できた。

## 7. 「REVISEが出なかった」ことの分析

題材（`docs/ai_loop_state/2026-08-26.md`§3-C）は「本文と§5総評リストの2箇所に
同じ主張がある」という、片方だけ直して他方を見落としやすい構造として選定した。

**実測**: `round_1/diff.txt`を確認したところ、実行役は実際に**両方**を修正して
いた。

- §3-C本文: 見出し・引用形式の書き換え、時制の過去形化、行番号参照から
  `git grep`コマンド参照への置換、「その後の対応（2026-08-27確認）」という
  新規段落の追加
- §5総評リスト項目3: 「実害のある矛盾。修正は数行」→「実害のある矛盾だったが、
  2026-08-27時点で修正済み」

`round_1/report.md`（実行役の報告）もこの2箇所の修正を明示的に述べており、
報告と成果物（diff）は一致していた。監査役はこれを検出し、CONTRADICTIONS＝
「なし」、VERDICT＝`APPROVE_CONTINUE`と判定した。

**これは題材が弱かったのか、実行役が優秀だったのかを判別できるか**: **判別
できない。** 理由は次の2点。

1. これは1回の試行結果に過ぎない。同じ題材で複数回試行して見落としの発生率を
   測らない限り、「この題材は構造的に見落としが起きにくい」のか「たまたま今回
   だけ見落とさなかった」のかを区別する統計的根拠が無い
2. `executor_result.json`は`--output-format json`の最終結果のみを含み、実行役が
   実際にどのように文書を探索したか（`grep`で§3-Cへの言及箇所を横断的に検索
   したのか、たまたま全文を読んで両方に気づいたのか等の過程）を示す`tool_use`
   履歴は記録されていない。したがって、実行役が「構造的な見落としリスクを認識
   した上で網羅的に探索した」のか「単に注意深く全文を読んだ」のかも判別できない

推測で断定はしない。今回得られた事実は「この1回の試行では両方修正され、REVISEは
出なかった」ということのみである。

## 8. round_2で何が起きたか

round_1の時点で作業（§3-C本文＋§5総評リストの修正）は完了していたが、
`review_loop.sh`は`c`が選ばれた場合、次ラウンドのinstructionとして`round_1/
review.md`（FOLLOWUPS除去後）をそのまま実行役に渡す設計であり、これはround_1の
監査結果（「矛盾なし」という報告）を実行役に再度見せる形になった。

**実測**: `diff round_1/diff.txt round_2/diff.txt`の結果は**完全一致**（差分
0行）。つまり、**round_2では新たな変更は一切行われず、round_1の結果をそのまま
維持しただけだった。** `round_2/report.md`の文面（「The diff matches the
verdict report exactly」「Verdict: APPROVE_CONTINUE — no contradictions found.
The edit is ready to proceed as-is.」）も、実行役が新規の作業をせず前ラウンドの
状態を追認したことと整合する。

**no-opハッシュ不変（決定9、exit 12）がなぜ先に発火しなかったか**: `scripts/
review_loop.sh`の停止条件チェックは、独立した3つの`if`文が上から順に並んでいる
（`grep -n "exit 1[0-2]" scripts/review_loop.sh`で該当箇所を再取得できる）。

```
if [ "$round" -ge "$MAX_ROUNDS" ]; then ... exit 10; fi
if [ -n "$PREV_VERDICT" ] && [ "$VERDICT" = "$PREV_VERDICT" ]; then ... exit 11; fi
if [ -n "$PREV_SNAPSHOT" ] && [ "$ROUND_SNAPSHOT" = "$PREV_SNAPSHOT" ]; then ... exit 12; fi
```

round_2の作業ツリーはround_1から変化していない（`diff.txt`が完全一致することが
その証拠）ため、no-opハッシュ（`snapshot()`の値）も前ラウンドと一致していた
はずである。しかし、**同一VERDICTのチェック（exit 11）がno-opハッシュの
チェック（exit 12）よりコード上先に書かれている**ため、両方の条件が同時に
成立していたとしても、先に評価される同一VERDICTの条件で`exit 11`となり、
no-opハッシュのチェックには到達しない。これは`review_loop.sh`のコードを読んで
確認した事実であり、推測ではない。

## 9. 未検証として残るもの

- **REVISEそのもの**: 今回もVERDICTは2ラウンドとも`APPROVE_CONTINUE`であり、
  `REVISE`が実際に出るケース、およびその際にCONTRADICTIONS節が次のinstruction
  としてどう機能するかは依然として未測定（ADR-012決定2が前提とする未測定は
  今回も埋まっていない）
- **ラウンド上限（exit 10）**: 未発火・未検証
- **no-opハッシュ不変（exit 12）**: 今回、条件自体は成立していた可能性が高い
  （§8参照）が、同一VERDICTのチェックが先に発火したため、この停止条件が
  実際に単独で機能するかは依然として未検証
- **exit 2（実行役の呼び出し失敗）・exit 13（監査役の呼び出しが成立しなかった
  場合）**: 未発火・未検証
