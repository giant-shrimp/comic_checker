# スポットチェック20件 事前登録

## 1. 目的

本測定が測る量を明確にする。以下は別種の量であり，本文書全体でこれを混同しない。

- 量X: 第1回ラベル vs 第2回ラベル（同一機構による読解者内不一致）。
  `relabel_consistency_finding.md` の下限3.3%はこの量である。
- 量Y: 人手判断 vs 第2回ラベル（人と機構の読解者間不一致）。
  **本スポットチェックが測るのはこの量である。**

量Xと量Yは異なる比較対象の間の不一致であり，一方の値から他方を推定することはできない。
本測定の位置づけは「量Xとは別の角度から，第2回ラベルの誤差を評価すること」であり，
`relabel_consistency_finding.md` §7 が述べる「ラベル誤差の項目単位での定量」（量Xを
項目単位に置き換えること）を本測定で達成するものではない。量Xの項目単位での定量は，
引き続き別途の測定課題のままである。

## 2. 標本

`holdout2_labels_auto.json` の119件から seed=1580 で20件を抽出する。抽出は昇順ソート後に
`random.sample` を用いる（holdout2 抽出時と同一手順）。プールの消費は発生しない（既に
消費済みの119件の部分集合であるため）。

抽出コマンド（事前登録時点では未実行。事前登録コミット後に実行する）:

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

抽出手順は `extract_holdout2_sample.py`（holdout2 の120件抽出）と同一パターン
（昇順ソート → `random.Random(seed).sample`）を踏襲する。母集団はプール全体ではなく
`holdout2_labels_auto.json` の119件そのものであるため，新たなプール消費は発生しない。

**ソート対象の一致確認**: `extract_holdout2_sample.py` は
`pool_titles = pool["holdout_pool_titles"]`（`list[str]`）から作った
`remaining`（`list[str]`）を `sorted(remaining)` でソートしている（同ファイル24〜35行目）。
実際に `docs/holdout_pool_2026-08/step93_2_holdout_pool.json` を読み込んで確認したところ，
`holdout_pool_titles` の要素は文字列型（作品タイトル文字列そのもの）だった。本文書のソート対象
（`titles = [x["title"] for x in data["labels"]]`）も `list[str]` であり，型・ソート対象
（title文字列そのもの）ともに `extract_holdout2_sample.py` と同一である。

## 3. 盲検の担保

人手判断者には以下のみを提示する。

- title
- extract
- wikitext
- ラベル規則v3（R1'〜R5）

以下は提示しない。

- expected_status
- applied_rule
- evidence_summary
- confused

提示物と照合用データを別ファイルに分離し，人手判断が完了して記録されるまで照合用ファイルを
開かないこととする。分離は以下2ファイルによる（生成自体は事前登録コミット後に行う。
本節はファイル仕様の規定のみ）。

`docs/holdout2_measurement_2026-08/spotcheck20_presentation.json`
- 含めるもの: title / extract / wikitext / 一連番号（1〜20）
- 含めないもの: expected_status / applied_rule / evidence_summary / confused

`docs/holdout2_measurement_2026-08/spotcheck20_human_labels.json`
- 人手判断の記入先。一連番号・human_status・判断根拠の欄を空で用意する。
- 第2回ラベルとの照合は，このファイルへの記入が完了した後に行う。

## 4. 予測（コミット後は変更禁止）

- (a) 20件中の一致件数の点予測: **18/20**
- (b) 予測の根拠（量X・3.3%からの導出ではない。使用してよいのは以下のみ）:
  - ラベル規則v3（R1'〜R5）の作業上の所見: 各規則は「本文中の完結・連載中の明記」
    「終了日の有無」など，本文中の記述の有無を確認する形で構成されており，該当する
    記述が明確な項目については判断が割れにくいという所感を得た。
  - 第2回ラベルにおいて confused=true は119件中22件（18.5%）だった（算出コマンドは
    下記）。confused は，該当する記述が曖昧・不足・矛盾するなどの理由で判断に迷った
    項目に立てたフラグであり，これらは人手判断でも第2回ラベルと異なる結論に至る
    可能性が，confused=false の項目より相対的に高いと考えられる。
  - 上記2点から，20件の標本中に含まれる confused 項目の期待件数を
    20 × 22/119 ≈ 3.7件 と見積もる（正確な分布は下記(d)の超幾何分布を参照）。
    confused=false の項目（約16.3件）は判断が割れにくいためほぼ一致すると仮定し，
    confused=true の項目（約3.7件）は判断が割れやすいため一致率をおおまかに5割と
    仮定すると，期待一致件数は 16.3 × 1.0 + 3.7 × 0.5 ≈ 18.15 → 18件 となる。これを
    点予測とする。
    **この「5割」は実測や過去データに基づく推定値ではなく，作業上の仮置きの数値で
    ある。** confused項目における人手と第2回ラベルの実際の一致率を示す既存データは
    ない。5割という仮定が外れれば点予測18/20も外れうる。

    confused=true 件数の算出コマンド:
    ```python
    import json
    with open("docs/holdout2_measurement_2026-08/holdout2_labels_auto.json", encoding="utf-8") as f:
        data = json.load(f)
    labels = data["labels"]
    n_total = len(labels)
    n_confused = sum(1 for x in labels if x["confused"])
    print(n_total, n_confused, n_confused / n_total)
    # => 119 22 0.18487394957983194
    ```

- (c) 品質に問題ありと判断する閾値: **標本中の confused 件数 k を上回る不一致が
  あった場合**（固定の整数閾値は用いない）。
  - k は，母集団119件・confused 22件から20件を非復元抽出した際に標本に含まれる
    confused 件数である。k は抽出結果によって定まる確率変数であり，20件中の
    confused 件数を一定の整数（例: 4件）で決め打ちすることはできない。
  - この方式を採る理由は，k が標本ごとに変動するため，固定の整数閾値では標本の
    ばらつきを吸収できないからである。
  - k は抽出直後（人手判断の開始前）に確定させ，本文書の追補として記録する。
    k の確定は人手判断の結果を見る前に行うため，事後的な閾値操作にはあたらない。
  - 「不一致件数が k を上回る」を閾値とする根拠: confused=false の項目
    （規則の適用が明確なはずの項目）で人手判断と食い違いが生じることは(b)の
    作業上の所見と矛盾する。不一致件数が標本中の confused 件数 k を上回るという
    ことは，confused=false の項目でも食い違いが生じたことを意味するため，これを
    もってラベル品質に問題ありと判断する。

- (d) k（標本中の confused 件数）の分布: 超幾何分布
  （母集団N=119，confused K=22，抽出n=20，非復元）に従う。標準ライブラリ（math）
  のみで算出した。コード全文と結果は以下の通り。

  ```python
  import math

  N = 119
  K = 22
  n = 20

  def hypergeom_pmf(k, N, K, n):
      if k < 0 or k > n or k > K or (n - k) > (N - K):
          return 0.0
      return math.comb(K, k) * math.comb(N - K, n - k) / math.comb(N, n)

  expected = n * K / N
  pmf = {k: hypergeom_pmf(k, N, K, n) for k in range(0, 11)}
  p_ge5 = sum(hypergeom_pmf(k, N, K, n) for k in range(5, n + 1))
  p_ge7 = sum(hypergeom_pmf(k, N, K, n) for k in range(7, n + 1))
  ```

  結果:
  - 期待値 E[k] = 20 × 22/119 ≈ **3.697**
  - P(k=0)=0.011092, P(k=1)=0.062571, P(k=2)=0.158012, P(k=3)=0.237019,
    P(k=4)=0.236287, P(k=5)=0.165977, P(k=6)=0.084988, P(k=7)=0.032377,
    P(k=8)=0.009284, P(k=9)=0.002015, P(k=10)=0.000331
  - P(k≥5) ≈ **0.2950**（約29.5%）
  - P(k≥7) ≈ **0.0441**（約4.4%）

  最頻値は k=3（P≈0.237）とk=4（P≈0.236）がほぼ同率で並ぶ。k は3〜4件付近に
  分布が集中するが，k=5以上になる確率も約29.5%あり，無視できない。閾値を
  固定整数にできない理由はこの分布の広がりにも表れている。

**本測定の結果を量X（3.3%）と直接比較してはならない。両者は異なる機構間の一致を測る
ものであり，比較可能な量ではない。**

## 5. 不一致項目の取り扱い（結果を見る前に確定させる）

人手判断と第2回ラベルが不一致だった項目について，ラベルの修正は行わない。誤差として
計上するのみとする。

理由: 人手判断も誤りうるため，事後にどちらを正とするかを決めると恣意的な選択が入り，
ラベルの独立性が損なわれるため。

## 6. 統計上の限界（結果を見る前に記載する）

n=20 は信頼区間が広い。Wilson score interval を標準ライブラリのみ（`math`）で算出した。
使用したコード全文は以下の通り。

```python
import math

def wilson_ci(x, n, z=1.959963984540054):
    p_hat = x / n
    denom = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denom
    half_width = (z * math.sqrt((p_hat * (1 - p_hat) / n) + (z**2 / (4 * n**2)))) / denom
    lo = center - half_width
    hi = center + half_width
    return lo, hi

for x, n, label in [(20, 20, "20/20"), (18, 20, "18/20 (点予測)")]:
    lo, hi = wilson_ci(x, n)
    print(f"{label}: p_hat={x/n:.3f}, 95%CI=({lo*100:.1f}%, {hi*100:.1f}%)")
```

算出結果:

| ケース | 一致率 | Wilson 95%信頼区間 |
|---|---|---|
| 20/20（全一致） | 100.0% | 83.9% 〜 100.0% |
| 18/20（§4(a) 点予測） | 90.0% | 69.9% 〜 97.2% |

§4(c) の閾値は固定の一致件数（例: 15/20）ではなく標本依存の値
（不一致件数 > 標本中の confused 件数 k）に変更したため，固定値に対する
信頼区間は算出しない。

いずれのケースも信頼区間の幅は概ね15〜20ポイントに及ぶ。したがって本測定の結果は
参考値として扱い，pass/fail のゲートとしては使用しない。

**本測定の一致件数は，ラベル品質を確定させるゲートとしては使用しない。** §4(c) の閾値は
「さらなる調査が必要かどうか」の目安であり，通過・不通過を機械的に判定する基準ではない。

## 7. 本測定に含まれないもの

- judge() の実行および出力との照合
- ラベルの修正
- 標本の追加抽出

## 8. 三値ロック

本文書の md5 を本文書内に記載すると自己参照により値が変動するため，ロック値は本文書には
記載しない。事前登録コミットの実行時に，以下をコミットメッセージ本文に記載する。

- コミット直前の HEAD hash
- 本文書の md5sum
- 事前登録コミット後の git log hash

§4 および §5 は本コミット以降，変更禁止とする。
