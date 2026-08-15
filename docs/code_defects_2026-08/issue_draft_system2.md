## 背景

`_judge_via_infobox()`は、終了系フィールド（`END_FIELD_NAMES`）の値が
`ONGOING_FIELD_MARKER`・`HIATUS_MARKER`のいずれとも一致しない場合、その値を
そのまま終了値として採用する。「？」のような未確定を示すプレースホルダ値も
区別されない。

## 実測されている影響

- **F_unverifiable 1件**（天使の裁量、`docs/holdout_measurement_2026-08/step98_b_compare_result.md` No.44。
  実測: `judge()` evidence=`'インフォボックス: 終了号 = ？'`、判定=完結。ラベルは
  判定不能）。D_errorではない（ラベル側も確信が無かった行のため）。

## 現コーパスでの判別力

母数160件（holdout99+regression61）で、wikitext中の「終了号/終了日 = ？」
パターンの出現は**1件のみ**（実測、`docs/code_defects_2026-08/verification_procedure.md`）。
**判別力なし。**

## 検証標本の3分類

| 分類 | 対象 |
|---|---|
| 回帰フィクスチャ | 天使の裁量（1件） |
| 副作用チェック用 | holdout98件＋regression61件（手元にあり） |
| 有効性の証拠 | 未消費262件からの独立標本（**未取得**。`docs/code_defects_2026-08/corpus_expansion_design.md`で設計のみ完了） |

## 事前登録した必要事例数

10件（定性的根拠。`corpus_expansion_design.md`参照）。現時点で0件（新規抽出後の
取得が必要）。

## 検証手順書

`docs/code_defects_2026-08/verification_procedure.md`を適用する。実judge()ハーネス
（`_pick_article`/`_fetch_wikitext`のみ差し替え）を使い、合成wikitextでの
シミュレーションは行わない。

## 想定される修正方針（未検証）

`END_FIELD_NAMES`の値が既知のプレースホルダパターン（「？」単体等）に一致する
場合、非null値として扱わず空欄と同様の経路（巻数フィールドの継続証拠チェック）に
回す。**この修正方針の安全性は未検証。** 他のプレースホルダ表記の実例も未確認。

## 完了条件

- 未消費262件からの新規抽出（N=50、seed=517、`corpus_expansion_design.md`参照）
  を取得し、対象パターンの出現件数を実測する
- 最低必要事例数（10件）に届かない場合は`corpus_expansion_design.md`の追加抽出
  基準に従う
- 実judge()ハーネスでの安全性検証（ポジティブコントロール・ミューテーション
  テスト・期待ラベルとの照合）を行う
- 修正実装後、既存の回帰テストが通ることを確認する

## 優先度

中。D_errorではなくF_unverifiable（ラベル側も判定不能で確信が無かった行）であり、
危険度は系統1・5より軽い。現コーパスでの判別力が無く、着手は新規抽出後になる。
