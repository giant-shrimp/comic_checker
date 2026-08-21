# スポットチェック20件 測定結果

## 1. 事前登録との対応

`prereg_spotcheck_20.md`（md5 `ff7218e8a06479090e5039c2f9576936`）に照合済み。
抽出記録 `spotcheck20_extraction_record.md` の k=5 に照合済み（本測定でも
confused=true の件数を再確認したところ5件であり，一致した）。

## 2. 手続きと事前登録からの逸脱

**盲検の担保状況**: `spotcheck20_presentation.json` には title / extract / wikitext /
一連番号のみを含み，expected_status / applied_rule / evidence_summary / confused は
含まれていなかった（生成時に grep で0件を確認済み）。判断者はこの提示ファイルと
ラベル規則v3のみを参照し，`holdout2_labels_auto.json` を参照していない。

**逸脱**: 事前登録 §3 は，記入ファイル（`spotcheck20_human_labels.json`）に
`human_evidence`（判断根拠）を記録することを規定していたが，本測定では判断根拠を
記録しなかった。この決定は照合の実施前（`human_status` の記入は完了していたが
`holdout2_labels_auto.json` を参照する前）に行われた。照合後に不一致項目についてのみ
根拠を追記することは，第2回ラベルを見た後に書かれた根拠であり盲検下の記録にならない
ため，禁止とした。全20件の `human_evidence` には固定文字列
`（本測定では判断根拠を記録しない。照合前の決定による。spotcheck20_result.md §2 参照）`
を記入した。

**影響**: 一致件数の算出には影響しない（`human_status` と `expected_status` の比較のみ
で完結するため）。ただし §5 の所見において，不一致がラベル規則v3の解釈の相違による
ものか，本文の読解の相違によるものかを項目単位で切り分けることはできない。

## 3. 結果

算出コマンド全文:

```python
import json
import math
from collections import Counter

with open("docs/holdout2_measurement_2026-08/spotcheck20_human_labels.json", encoding="utf-8") as f:
    human_data = json.load(f)

with open("docs/holdout2_measurement_2026-08/holdout2_labels_auto.json", encoding="utf-8") as f:
    auto_data = json.load(f)

by_title = {x["title"]: x for x in auto_data["labels"]}

match = 0
mismatch = 0
mismatch_nos = []
mismatch_confused = {"true": 0, "false": 0}
direction_counter = Counter()

for rec in human_data["records"]:
    no = rec["no"]
    title = rec["title"]
    human_status = rec["human_status"]
    auto_rec = by_title[title]
    auto_status = auto_rec["expected_status"]
    confused = auto_rec["confused"]

    if human_status == auto_status:
        match += 1
    else:
        mismatch += 1
        mismatch_nos.append(no)
        if confused:
            mismatch_confused["true"] += 1
        else:
            mismatch_confused["false"] += 1
        direction_counter[(human_status, auto_status)] += 1

def wilson_ci(x, n, z=1.959963984540054):
    p_hat = x / n
    denom = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denom
    half_width = (z * math.sqrt((p_hat * (1 - p_hat) / n) + (z**2 / (4 * n**2)))) / denom
    lo = center - half_width
    hi = center + half_width
    return lo, hi

lo, hi = wilson_ci(match, 20)
```

結果:

- 一致件数: **13**
- 不一致件数: **7**
- 一致率: 13/20 = **65.0%**
- Wilson 95%信頼区間: **(43.3%, 81.9%)**

不一致項目の通番: **No.3, No.4, No.5, No.6, No.11, No.12, No.20**（作品名は記載しない）

confused 内訳:
- confused=true（5件）のうち不一致: **2件**
- confused=false（15件）のうち不一致: **5件**

不一致の方向内訳（human_status → 第2回ラベルのexpected_status）:

| human_status | expected_status（第2回） | 件数 |
|---|---|---|
| 連載中 | 判定不能 | 3 |
| 判定不能 | 完結 | 1 |
| 連載中 | 完結 | 1 |
| 完結 | 連載中 | 1 |
| 完結 | 判定不能 | 1 |

## 4. 判定

不一致件数7件は k=5 を上回る（7 > 5）。事前登録 §4(c) の判定基準
「不一致件数が k を上回った場合にラベル品質に問題あり」に従い，**本測定は「ラベル品質に
問題あり」と判定する**。

事前登録 §4(a) の点予測（18/20 一致）との対比: 実測は13/20一致であり，**点予測は外れた**
（点予測より5件多く不一致だった）。

## 5. 所見

- confused=false（15件）の不一致率は 5/15 ≈ 33.3%，confused=true（5件）の不一致率は
  2/5 = 40.0% だった。confused=true の方が幾分高いが，件数が少なく差は大きくない。
  事前登録 §4(b) が述べた「ラベル規則v3は本文中の記述の有無を確認する形で構成されており，
  該当する記述が明確な項目（confused=false）については判断が割れにくい」という作業上の
  所見は，**本測定の結果からは支持されなかった**。confused=false の項目でも33.3%という
  高い不一致率が観測されており，「規則が明確な項目は判断が割れにくい」という前提が
  成立していなかったことを示している。
- §2 で記録した逸脱（human_evidence 未記録）により，この不一致が具体的にどのラベル規則
  （R1'〜R5）の解釈の相違に起因するのか，あるいは本文の読解自体の相違（規則以前の
  事実認定のずれ）に起因するのかを，項目単位で切り分けることはできない。所見の解像度は
  「confused/not-confused という二値の切り口」に限られる。
- n=20 の統計上の限界（事前登録 §6）により，本結果は参考値として扱い，pass/failの
  機械的なゲートとしては使用しない。ただし事前登録 §4(c) で確定した判定基準
  （不一致 > k）自体は，本文書 §4 の通り適用済みである。

## 6. 量Xとの関係

本結果は「人手判断 vs 第2回ラベル」（量Y）の測定である。`relabel_consistency_finding.md`
が記録した「第1回ラベル vs 第2回ラベル」（量X，下限3.3%）とは別種の量であり，両者を
直接比較していない。量Xの項目単位での定量は，引き続き別途の測定課題のままである。
