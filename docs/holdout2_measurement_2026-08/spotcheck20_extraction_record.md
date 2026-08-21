# スポットチェック20件 抽出記録（事前登録の追補）

## 1. 事前登録との対応

`prereg_spotcheck_20.md`（md5 `ff7218e8a06479090e5039c2f9576936`）に照合済み。抽出条件
（seed=1580 / 20件 / 119件から / 昇順ソート後 sample）は事前登録どおり。

## 2. 抽出結果

- 件数: 20件
- 重複なしの確認結果: `assert len(set(sample)) == N` を通過（`len(sample) == len(set(sample)) == 20`）
- 全20件が `holdout2_labels_auto.json` の `labels[].title` に存在することを確認
  （不一致0件）

使用コマンド全文（事前登録 §2 のコードをそのまま使用。書き換えなし）:

```python
import json
import random

with open("docs/holdout2_measurement_2026-08/holdout2_labels_auto.json", encoding="utf-8") as f:
    data = json.load(f)

titles = [x["title"] for x in data["labels"]]
assert len(titles) == 119

# 再現性のため、抽出前に必ず昇順ソートする（ソート順が異なると再現性が失われる）
# ソート対象は title の文字列（list[str]）そのものであり、他の項目を含む
# タプルや辞書ではない。
titles_sorted = sorted(titles)

SEED = 1580
N = 20
sample = random.Random(SEED).sample(titles_sorted, N)
assert len(sample) == N
assert len(set(sample)) == N, "抽出結果に重複がある"
```

※ 抽出された作品タイトルの一覧は本文書には記載しない。

## 3. k の確定

k = **5**

算出コマンド全文:

```python
import json

with open("docs/holdout2_measurement_2026-08/holdout2_labels_auto.json", encoding="utf-8") as f:
    data = json.load(f)

by_title = {x["title"]: x for x in data["labels"]}

k = sum(1 for t in sample if by_title[t]["confused"])
print(k)
# => 5
```

事前登録 §4(d) の超幾何分布（N=119, K=22, n=20）における対応確率:

P(k=5) ≈ **0.165977**

（検証: `math.comb(22, 5) * math.comb(97, 15) / math.comb(119, 20)` ≈ 0.16597729452478316
で §4(d) 記載値と一致することを確認した。）

## 4. 判定基準の確定

本測定において，不一致件数が k=5 を上回った場合にラベル品質に問題ありと判断する。
すなわち**不一致6件以上**で問題ありとする。

本値は人手判断の開始前に確定したものであり，以降変更しない。

## 5. 生成ファイル

- `spotcheck20_presentation.json`（提示用。一連番号・title・extract・wikitextのみを含み，
  expected_status / applied_rule / evidence_summary / confused のいずれも含まない）
- `spotcheck20_human_labels.json`（記入用。一連番号・title を記載し，human_status・
  human_evidence は空欄）
