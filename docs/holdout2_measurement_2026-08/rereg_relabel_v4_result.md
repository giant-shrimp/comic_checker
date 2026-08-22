# v4再ラベル付け・再スポットチェック 結果記録

本文書は `prereg_relabel_v4.md` §8 が「この追補文書に記録する」と定める内容を満たす
ための追補文書である。事前登録・規則ファイルの事後変更は行わない。診断的な解釈・
規則改訂の検討は本文書のスコープ外であり，行っていない。

## 1. 確定値サマリ

| 項目 | 値 |
|---|---|
| confused件数（119件中） | 21件（`total_confused_119 <= 30` の歯止め未抵触） |
| kの値 | 4 |
| kの確定タイミング | 新標本20件抽出直後・人手判断開始前（`spotcheck20_v4_sample.json` 作成時点） |
| 新標本20件の一致件数 | 18/20（不一致2件） |
| 判定式の適用結果 | 「不一致件数 > k」→ 2 > 4 は偽 → **問題なし** |
| 点予測との対比 | 予測 17/20（`prereg_rules_v4.md` §7(a)）／実測 18/20（事実として記載，評価語は用いない） |
| 前回20件の一致件数 | 15/20（**成否判定には用いない参考記録**。事前登録上，成否は新標本20件のみで判定する） |

## 2. confused件数の確定（119件中21件）

導出コマンド:

```python
import json
with open("docs/holdout2_measurement_2026-08/holdout2_labels_v4.json", encoding="utf-8") as f:
    v4 = json.load(f)["labels"]
confused_count = sum(1 for r in v4 if r.get("confused"))
print(confused_count, "/", len(v4))
```

出力: `21 / 119`。`spotcheck20_v4_sample.json` の `k.total_confused_119` (=21) および
`k.total_confused_exceeds_30` (=false) と一致する。事前登録§7(c)の30件歯止めに抵触しない。

## 3. kの値と確定タイミング

- `spotcheck20_v4_sample.json` の記録値: `k.value = 4`。
- 確定手続き: 新標本20件の抽出直後，人手判断（`spotcheck20_v4_human_labels.json` への記入）を
  開始する前に，抽出済み20件について `holdout2_labels_v4.json` の `confused` フラグを参照し，
  `confused=true` の件数を数えて確定した（`confused_procedure_note_v4.md` §5・
  `spotcheck20_v4_sample.json` の `k.method` に基づく）。

再算出（再現）コマンドと出力:

```python
import json
with open("docs/holdout2_measurement_2026-08/holdout2_labels_v4.json", encoding="utf-8") as f:
    v4 = json.load(f)["labels"]
title_to_confused = {r["title"]: r["confused"] for r in v4}

with open("docs/holdout2_measurement_2026-08/spotcheck20_v4_sample.json", encoding="utf-8") as f:
    sample = json.load(f)
sample_titles = sample["sample_titles"]

k = sum(1 for t in sample_titles if title_to_confused[t])
confused_titles = [t for t in sample_titles if title_to_confused[t]]
print("k(再算出):", k)
print("confused_true_titles(再算出):", confused_titles)
print("記録値と一致:", confused_titles == sample["k"]["confused_true_titles"])
```

出力:
```
k(再算出): 4
confused_true_titles(再算出): ['四十七大戦', '土下座で頼んでみた', '東山道転墜異聞', '戦う!セバスチャン']
記録値と一致: True
```

## 4. 新標本20件の抽出方法（再現性のための記録）

- 母集団: holdout2 119件から，前回スポットチェック済み20件（`spotcheck20_human_labels.json`
  の `title` で特定）を除いた**99件**。
- seed: `2026`（`prereg_rules_v4.md` §6に明記された値をそのまま使用。新規選定なし）。
- 手順: 母集団99件をタイトル昇順（Python標準の文字列比較）でソートした上で
  `random.Random(2026).sample(population_sorted, 20)` を適用。

抽出コマンド全文（`spotcheck20_v4_sample.json` の `extraction.command` から転記）:

```python
import random
population_sorted = sorted(population_99)
sample = random.Random(2026).sample(population_sorted, 20)
```

抽出方式の根拠: `docs/holdout2_measurement_2026-08/README.md` に記載された原初抽出
（未消費262件を昇順ソートし `random.Random(158).sample(pool, 120)`）と同一方式であり，
本プロジェクトの既存前例に整合する非恣意的な手順（`spotcheck20_v4_sample.json` の
`extraction.algorithm_rationale`）。

抽出日時: `2026-08-21T18:16:14Z`。

## 5. 盲検化の手続き

- 人手判断は**別セッション**で，既存ラベル（v4ラベル由来の `expected_status` /
  `applied_rule` / `evidence_summary` / `confused` / `rule_trace`）を一切参照せずに実施した。
- 提示ファイル `spotcheck20_v4_presentation.json` はv4ラベル由来フィールドを一切含まない
  （`extract` と `infobox_manga_blocks` のみ）。
- `item_id`（S01〜S20）の並び順は，抽出順・タイトル昇順ではなく shuffle 済み
  （`shuffle_seed: 20260822`）。並び順そのものが照合情報を与えないための措置。
- `item_id` と `title` の対応づけ（`spotcheck20_v4_keymap.json`）は，人手判断コミット後
  （§7参照）にのみ使用した。

## 6. 三値ロック（時系列の固定記録）

以下3コミットにより，準備物・人手判断・（本文書作成時点で参照可能になった）照合対象データが
それぞれ独立したタイミングで固定されていることを記録する。

| 段階 | コミット | 内容 |
|---|---|---|
| ラベル確定 | `f4f25713d3f205a3c341c800b9dddb4d96648cf3` | holdout2 v4再ラベル付け結果（119件）の追加 |
| 準備物 | `a84d85c9676cc60a1df4e96509ce3b7b63bb9a09` | 新標本20件の抽出記録・盲検提示ファイル・空の回答ファイルの追加 |
| 人手判断 | `6ba827ef0648e2ab285a35a21ca876a3631f9b3b` | 盲検人手判断（20件）の記入・コミット |

**人手判断（`spotcheck20_v4_human_labels.json`）は，既存ラベルとの照合を行う前に単独コミットで
固定されている。** 照合結果を見た後に人手判断ファイルを書き換えることはできない
（照合作業のブロックで遵守事項として明示され，本文書作成時点まで同ファイルへの変更は行っていない）。

## 7. 新標本20件の照合結果

導出コマンド:

```python
import json

with open("docs/holdout2_measurement_2026-08/spotcheck20_v4_keymap.json", encoding="utf-8") as f:
    keymap = json.load(f)["map"]
item_to_title = {r["item_id"]: r["title"] for r in keymap}

with open("docs/holdout2_measurement_2026-08/spotcheck20_v4_human_labels.json", encoding="utf-8") as f:
    human = json.load(f)["records"]
item_to_human = {r["item_id"]: r["human_status"] for r in human}

with open("docs/holdout2_measurement_2026-08/holdout2_labels_v4.json", encoding="utf-8") as f:
    v4 = json.load(f)["labels"]
title_to_expected = {r["title"]: r["expected_status"] for r in v4}

match, mismatch, mismatch_rows = 0, 0, []
for item_id, title in item_to_title.items():
    h = item_to_human[item_id]
    e = title_to_expected[title]
    if h == e:
        match += 1
    else:
        mismatch += 1
        mismatch_rows.append((item_id, title, h, e))
print("一致:", match, "不一致:", mismatch)
print(mismatch_rows)
```

出力: `一致: 18 不一致: 2`

不一致2件（事実列挙。探索的診断は事前登録が要求していないため実施していない）:

| item_id | title | human_status | expected_status(v4) |
|---|---|---|---|
| S05 | 東山道転墜異聞 | 判定不能 | 完結 |
| S19 | 土下座で頼んでみた | 連載中 | 完結 |

## 8. 判定式の適用

- k = 4（§3）
- 不一致件数 = 2（§7）
- 判定式「不一致件数 > k ならば問題あり」（`prereg_rules_v4.md` §7(c)）を適用: `2 > 4` は偽。
- **結果: 問題なし。**

点予測との対比（事実として記載。予測の当否についての評価的表現は用いない）:

| | 一致件数 |
|---|---|
| 事前登録§7(a)の点予測 | 17/20 |
| 実測（本測定） | 18/20 |

## 9. 前回20件の一致件数（参考記録）

**この数値は事前登録上，v4改訂の成否判定には用いない参考記録である。** 成否の判定は
事前登録§6が定める通り，新標本20件（§7）のみによって行う。

導出コマンド:

```python
import json

with open("docs/holdout2_measurement_2026-08/spotcheck20_human_labels.json", encoding="utf-8") as f:
    prev = json.load(f)["records"]

with open("docs/holdout2_measurement_2026-08/holdout2_labels_v4.json", encoding="utf-8") as f:
    v4 = json.load(f)["labels"]
title_to_expected = {r["title"]: r["expected_status"] for r in v4}

prev_match = sum(1 for r in prev if title_to_expected.get(r["title"]) == r["human_status"])
print(prev_match, "/", len(prev))
```

出力: `15 / 20`

## 10. 分類A・C相当4件の変化（観察された事実。判断は保留）

探索的診断 `spotcheck20_diagnosis.md` が分類A（規則の適用対象の解釈差，2件）・分類C（規則が
沈黙している事例，2件）とした計4件について，v4ラベルが前回（v3期）の人手判断と一致するように
なったかを個別に確認した結果を以下に収録する。

| 分類 | title | 第2回(auto)ラベル | 人手（v3期） | v4 | v4 vs 人手一致 |
|---|---|---|---|---|---|
| A (No.5) | 魔女と野獣 | 判定不能（R4） | 連載中 | 判定不能（R4, confused=False） | 不一致 |
| A (No.6) | グリードパケット∞ | 判定不能（R4） | 連載中 | 判定不能（R4, confused=False） | 不一致 |
| C (No.3) | 15歳、今日から同棲はじめます。 | 判定不能（なし, confused=True） | 連載中 | 連載中（なし, confused=True） | 一致 |
| C (No.20) | 大人にゃ恋の仕方がわからねぇ! | 判定不能（なし, confused=True） | 完結 | 連載中（なし, confused=True） | 不一致 |

観察された事実（規則改訂の是非についての判断は保留する）:

- 分類A2件（魔女と野獣・グリードパケット∞）は，v4でも `applied_rule=R4` のまま判定不能を
  維持しており，v3期人手判断（連載中）とは一致しなかった。
- 分類C2件（15歳、今日から同棲はじめます。・大人にゃ恋の仕方がわからねぇ!）は，
  `applied_rule` が「なし」のままであり，**R6は適用されていない**。
- 加えて，119件全体でR6が適用されたのは以下の**2件のみ**であった（下記コマンドで再算出）。

```python
import json
with open("docs/holdout2_measurement_2026-08/holdout2_labels_v4.json", encoding="utf-8") as f:
    v4 = json.load(f)["labels"]
r6_titles = [r["title"] for r in v4 if r.get("applied_rule") == "R6"]
print(len(r6_titles), r6_titles)

# rule_trace側での matched=True も併せて確認
r6_trace_titles = [
    r["title"] for r in v4
    for rt in r.get("rule_trace", [])
    if rt.get("rule_id") == "R6" and rt.get("matched")
]
print(len(r6_trace_titles), r6_trace_titles)
```

出力: `2 ['世界の終わりに柴犬と', '世紀末★ダーリン']`（`applied_rule` 基準・`rule_trace` 基準の
いずれでも同じ2件で一致）。

## 11. 適用解釈ログへの参照

`labeling_interpretation_log_v4.md` には，119件のラベル付け中に発見された規則未定義論点への
適用解釈が I-001〜I-003 として記録されている（複数Infoboxブロックにおける評価単位，
終了号/終了日フィールドの値が非完結キーワードのみの場合の扱い，終了号/終了日フィールドの値が
終了時期を示さない断片のみの場合の扱い）。いずれも区間1〜4（119件）への遡及確認が完了しており，
確認の結果としての追加ラベル修正は無い旨が同ログに記録済みである。詳細は同ログを直接参照する
（本文書では内容を転記しない）。

`holdout2_labels_v4.json` および4分割ファイルの `segment` / `count` フィールドは，各ファイルが
119件中のどの範囲（例: `1-30` / 30件）を保持しているかを示す付加的なメタデータであり，本文書
作成時点で `labeling_interpretation_log_v4.md` への追記提案は見送った（提案内容を裏付ける記録が
本セッションのコンテキスト内に無く，内容を検証できないため）。

## 12. 参照ファイルのmd5sum一覧

```
078d3d32ee7299a1826031553394c7a1  docs/holdout2_measurement_2026-08/holdout2_labels_v4.json
68ecee2d7af917cb646cfe003d871fa7  docs/holdout2_measurement_2026-08/holdout2_labels_v4_partial_1-30.json
1f1d4e849c9a1f89f0c6a3c14a9060b3  docs/holdout2_measurement_2026-08/holdout2_labels_v4_partial_31-60.json
c8c2b9009b7d4731aa7b451f51962fd1  docs/holdout2_measurement_2026-08/holdout2_labels_v4_partial_61-90.json
174b78c26b0a37ef8c63fc71035c7239  docs/holdout2_measurement_2026-08/holdout2_labels_v4_partial_91-119.json
32a8fa80f7e62dd7d551ce6bbd44f5c3  docs/holdout2_measurement_2026-08/spotcheck20_v4_human_labels.json
4368e7f581a4764def8e3056a25ea935  docs/holdout2_measurement_2026-08/spotcheck20_v4_presentation.json
312e0a26c0a39f411d87cee76e695d23  docs/holdout2_measurement_2026-08/spotcheck20_v4_keymap.json
d03c057b814e8514d403e65eb90e9ac4  docs/holdout2_measurement_2026-08/spotcheck20_v4_sample.json
effaa1c1d6870520c28333c86c7e6799  docs/holdout2_measurement_2026-08/spotcheck20_human_labels.json
cd473fdd9b4423f567f94b98e4b5a500  docs/holdout2_measurement_2026-08/spotcheck20_diagnosis.md
63b9e500dbd17629d38359888e9ac16e  docs/holdout2_measurement_2026-08/confused_procedure_note_v4.md
4eeb9d61f628c06472e9e7fa46fd6306  docs/holdout2_measurement_2026-08/labeling_interpretation_log_v4.md
c29bfa264dfa204078cc100133400ca6  docs/holdout2_measurement_2026-08/prereg_relabel_v4.md
5dc3d0d8a138e6aeefe713c94e09b64d  docs/holdout2_measurement_2026-08/prereg_rules_v4.md
a90df4b5b5fd135dedd6323fc02f61e8  docs/holdout_measurement_2026-08/step98_a_labeling_rules_v4.json
```

## 13. 本文書のスコープ外事項

以下は本文書の作成にあたり一切実施していない。

- 不一致2件（S05・S19）の探索的診断。事前登録が診断を要求していないため。
- 規則v4の改訂案・v5の設計・`judge()` の修正の検討。
- R6の適用範囲・妥当性についての評価的判断。§10は観察された事実のみを記載し，判断は保留する。
