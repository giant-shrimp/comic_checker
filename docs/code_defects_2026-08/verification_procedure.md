# 系統2〜5・案Bへの安全性検証手順書（系統1で確立した手順の一般化）

系統1（SPINOFF_MARKERSへの「続編」追加、Issue #151／PR #152）の安全性検証で、
検証手法の欠陥が3回連続で見つかった（`ERRORS.md`「PR #152の安全性検証で、検証
手法の欠陥が3回連続で見つかった」参照）。その反省を踏まえ確立した手順を、
系統2〜5・案B（Issue #154）にも適用可能な形で汎用化する。**この文書は手順の
記述であり、実装・実行そのものではない。**

## 手順

### 1. 実judge()ハーネスを使う（合成シミュレーションを禁止）

`docs/regression_corpus_2026-08/step98_judge_harness.py`の
`run_judge_with_snapshot()`を使う。モンキーパッチするのは`_pick_article`と
`_fetch_wikitext`の2関数のみ。`_judge_extract`・`_judge_via_infobox`・`judge()`
本体のveto層（`_has_ongoing_signal()`、`_is_novel_primary()`）を含め、それ以外は
すべて本物の`comic_checker.wikipedia_client`をそのまま呼ぶ。

**コード例**（リポジトリルートから実行）:

```python
import sys, json
sys.path.insert(0, "docs/regression_corpus_2026-08")
from step98_judge_harness import run_judge_with_snapshot
import comic_checker.wikipedia_client as wc

rows = json.load(open("docs/regression_corpus_2026-08/regression_corpus_wikitext.json",
                       encoding="utf-8"))["rows"]

# 修正前後の切り替え例（SPINOFF_MARKERSの場合。対象の定数・正規表現に読み替える）
CURRENT = wc.SPINOFF_MARKERS
BEFORE = tuple(m for m in CURRENT if m != "続編")

for r in rows:
    wc.SPINOFF_MARKERS = BEFORE
    before = run_judge_with_snapshot(r["input_title"], r["matched_title"],
                                      r["extract"], r["url"], r["wikitext"])
    wc.SPINOFF_MARKERS = CURRENT
    after = run_judge_with_snapshot(r["input_title"], r["matched_title"],
                                     r["extract"], r["url"], r["wikitext"])
    if before.status != after.status or before.evidence != after.evidence:
        print(r["input_title"], before.status, "->", after.status)
```

**厳禁**: サブ関数だけを個別に呼び出すシミュレーション（`judge()`本体のveto層を
見落とす。系統1の欠陥1・2）、保存済みの抽出済みフィールドから入力を合成する方式
（「フィールド不在」と「存在するが空欄」を区別できない等、想定していない情報
欠落を生む。系統1の欠陥3）。**必要な入力（wikitext等）は必ず原本を保存し、
保存済みの抽出済みデータから再構成しない。**

### 2. 保存済みの生wikitextを注入する

`docs/regression_corpus_2026-08/regression_corpus_wikitext.json`
（記事あり61件）・`docs/holdout_measurement_2026-08/holdout_wikitext.json`
（記事あり99件）を入力に使う。Wikipediaへの再取得は行わない。

### 3. 修正前後をプロセス内で切り替えて比較する

対象の定数・正規表現を、修正前の値・修正後の値でプロセス内（`import`後の
属性差し替え）で切り替え、同一の生wikitext入力に対して`run_judge_with_snapshot()`
を2回呼んで`status`・`evidence`を比較する。`comic_checker/`本体のファイルは
一切変更しない。

### 4. ポジティブコントロール

- 対象語彙・パターンの出現件数を、保存済み全件（holdout99・regression61）の
  extractまたはwikitextに対して実測し、母数とともに表にする。
- 出現件数が0または極少の場合、「この母集団には判別力が無い」ことを明記する
  （「変化なし」を「無害の証拠」として扱わない）。
- 対象語彙を含む行を全件追跡し、実際に判定へ影響したか・影響しなかったかを
  区別する。影響しなかった場合はどこで足切りされたか（別の決着文が先に
  見つかる、`_is_novel_primary`ゲート、marker側の別条件等）を実測で示す。

### 5. ミューテーションテスト

検証系自体に判別力があることを示すため、対象母集団に頻出する別の語を
一時的に対象の定数・正規表現へ追加し、判定が変化する行が1件以上出ることを
確認する。0件なら検証系の欠陥として扱い、報告して停止する（自力で再設計しない）。

### 6. 期待ラベルとの照合・分類

`docs/holdout_measurement_2026-08/step98_a3_labels.json`の`expected_status`と
突き合わせ、変化した行を次のいずれかに分類する。

- **D_error → E_missed／A_correct**: 危険な確信誤りが解消された（安全側改善）
- **A_correct → D_error**: 新規の危険な誤判定を生んだ（回帰、修正不採用の理由になる）
- **E_missed → A_correct**: 正解に到達した（理想的な改善）
- **E_missed → 別のE_missed／判定不能のまま**: 変化はあるが精度指標上は未改善

### 7. 判別力が不足している場合の扱い（進めない判断基準）

**手順4のポジティブコントロールで対象語彙・パターンの出現件数が実測で0件、
または極少（目安: 現行コーパス160件中1〜2件程度）と判明した場合、その系統の
安全性検証は完了したとみなさない。** 出現件数が少ない状態での「変化なし」は
「無害の証拠」ではなく「その母集団で判別できなかった」ことを意味する
（作業98-5でSPINOFF_MARKERSの「続編」がregression61件中2件しか実効的に
判定へ影響しなかった実例を参照）。

この場合に取りうる選択肢は次のいずれかであり、**修正を先行させる（判別力が
無いまま実装に進む）という案は採らない**。

1. 判別力を得るのに十分な追加事例を、ホールドアウト規律に沿った方法で確保する
   （`docs/code_defects_2026-08/corpus_expansion_design.md`参照）。
2. 追加事例の確保が現実的でない場合、その系統への着手を保留し、理由を明記する。

### 8. 撤退条件（系統1から継続）

検証手順自体に新たな欠陥が見つかった場合、自力で再設計せず、欠陥の内容と
影響範囲のみを報告して停止する。

## 系統1で確立した現コーパスの判別力評価（実測値）

以下は2026-08-15時点の保存済みコーパス（holdout99・regression61、
`docs/holdout_measurement_2026-08/holdout_wikitext.json`・
`docs/regression_corpus_2026-08/regression_corpus_wikitext.json`）を使い、
系統1（SPINOFF_MARKERS「続編」追加）で実測した判別力評価。

| 語 | 回帰コーパス（母数61） | ホールドアウト100（母数99） |
|---|---|---|
| 番外編 | 2 | 4 |
| スピンオフ | 6 | 4 |
| 外伝 | 2 | 3 |
| 次世代編 | 0 | 0 |
| 続編 | 2 | 10 |
| いずれか1語以上 | 11/61 | 18/99 |

「続編」出現行のうち、実際に判定へ影響したのは既知の2件（バーテンダー à
Tokyo・JESUS 砂塵航路）のみで、残りは`_is_novel_primary`ゲート・本編自身の
完結文が先に決着する等の理由で無害化されていた（詳細は
`docs/regression_corpus_2026-08/spinoff_markers_verification.md`参照）。

## 系統2〜5・案Bの現コーパスでの判別力（2026-08-16実測）

| 系統 | 対象語彙・パターン | holdout99 | regression61 | 合計 | 判定 |
|---|---|---|---|---|---|
| 系統2 | インフォボックス「終了号/終了日 = ？」等のプレースホルダ | 1 | 0 | 1 | **判別力なし** |
| 系統3 | 「配信終了」 | 1 | 0 | 1 | **判別力なし** |
| 系統3 | 「連載されており」 | 1 | 0 | 1 | **判別力なし** |
| 系統3 | 「連載され、」 | 7 | 2 | 9 | 出現はあるが誤爆リスクが既に示唆されており、個別の文脈追跡が別途必要 |
| 系統4 | 「発行されている」 | 1 | 2 | 3 | 極少 |
| 系統4 | 「短編漫画」 | 3 | 0 | 3 | 極少 |
| 系統4 | 「隔年連載」 | 1 | 0 | 1 | **判別力なし** |
| 系統4 | 「書籍化された」 | 2 | 1 | 3 | 極少 |
| 系統5 | 構造的パターン（本編終了文＋散発掲載列挙＋直近12か月以内の活動） | — | — | — | **判別力自体が未設計**（語彙一致では測定不能。実データ根拠は1件のみ） |
| 案B | `_has_ongoing_signal()`のSPINOFF_MARKERS除外（「続編」を対象） | 10 | 2 | 12 | 上表参照。既存コーパスで検証可能 |

系統2・系統3の一部（配信終了・連載されており）・系統4の一部（隔年連載）・系統5
は現コーパスで判別力が無い、または判別力自体を測定できない。案Bと系統3の
「連載され、」は既存コーパスである程度の検証が可能。

## 参照

- `docs/regression_corpus_2026-08/spinoff_markers_verification.md`（系統1での適用実例）
- `docs/regression_corpus_2026-08/step98_judge_harness.py`
- `docs/code_defects_2026-08/corpus_expansion_design.md`（コーパス拡充の設計）
- `ERRORS.md`「PR #152の安全性検証で、検証手法の欠陥が3回連続で見つかった」
