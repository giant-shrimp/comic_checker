# 案B（Issue #154）安全性検証: 実行結果の記録

**実行日**: 2026-08-16
**この文書は事実の記録のみ。新しい設計・提案・代替案は含まない。**

## md5ロック（検証実行前の事前登録の状態）

```
git rev-parse HEAD
1f3a7842fc0622aa346f056d5f469406fc07229e

md5sum docs/code_defects_2026-08/prereg_planb_safety_verification.md
f110963c82104ec82eaf542f10fac173  docs/code_defects_2026-08/prereg_planb_safety_verification.md

git log -1 --format=%H -- docs/code_defects_2026-08/prereg_planb_safety_verification.md
96a0db018c19d941f6d661d61a4f3a8a4e359337
```

上記3値が、検証実行前に確定していた事前登録（`prereg_planb_safety_verification.md`）
の状態を特定する。検証実行中、このファイルは一切編集していない。

## 使用したスクリプト

`~/comic_checker-agent-notes/`に置いた（リポジトリには含めていない）。

- `step104_planb_verification.py`: 主検証（`_has_ongoing_signal()`の修正前後比較、
  holdout99+regression61全件）
- `step104_planb_mutation_test.py`: ミューテーションテスト（代替語「コミカライズ」）

いずれも`docs/regression_corpus_2026-08/step98_judge_harness.py`の
`run_judge_with_snapshot()`を使い、`comic_checker.wikipedia_client._has_ongoing_signal`
をプロセス内で差し替える方式。`comic_checker/wikipedia_client.py`自体は変更していない。
保存済みスナップショット（`holdout_wikitext.json`・`regression_corpus_wikitext.json`）
のみを使用し、Wikipedia APIへの呼び出しは行っていない。

## 主検証: 変化した記事の全件記録

holdout99・regression61、計160行に対して修正前後の`judge()`を実行した。

| 記事 | corpus | 修正前 | 修正後 | 経路 | 修正後evidence |
|---|---|---|---|---|---|
| バーテンダー à Tokyo | holdout | 判定不能 | 完結 | `_judge_extract()`単体 | 『グランドジャンプ』（集英社）にて、2013年23号から2015年23号まで連載した後、『グランドジャンプPREMIUM』（同社刊）に掲載誌を移した後に2016年1号から同年7号まで連載。 |
| 陰陽師 | regression | 判定不能 | 完結 | インフォボックスveto | インフォボックス: 終了号 = [[2005年]]7月号<br />（月刊メロディ） |

変化した行数: **2 / 160**。「経路」の判別は、evidenceの形式（生の文＝`_judge_extract`単体、
「インフォボックス: 」接頭辞＝インフォボックスveto経由）から実測で確認した。

## 事前登録3節の予測との突き合わせ

事前登録の変化予測（3節）は書き換えていない。突き合わせ結果は次のとおり。

- **変化件数**: 予測2件、実測2件。一致。
- **対象記事**: 予測（陰陽師・バーテンダー à Tokyo）、実測（同一）。一致。
- **バーテンダー à Tokyoの経路**: 予測は「`_judge_extract()`単体で完結に到達し、
  インフォボックスフォールバックに到達すらしない」。実測のevidenceは生の文
  （インフォボックス接頭辞なし）であり、`_judge_extract()`単体経路と整合。**予測どおり**。
- **陰陽師の経路**: 予測は「`_judge_extract()`単体は判定不能のまま、`judge()`全体では
  インフォボックスveto経由で完結」。実測のevidenceは「インフォボックス: 終了号 = …」
  であり、インフォボックス経路と整合。**予測どおり**。
- **陰陽師のevidence文言**: 予測時に実wikitextから確認した`終了号 = [[2005年]]7月号<br
  />（月刊メロディ）`と、実測のevidence文言は完全一致。
- **この2件以外の変化**: 予測「無い」。実測も0件（残り158行は変化なし）。**予測どおり**。
- **期待ラベルとの一致**: 陰陽師（`scripts/m6d3_labels.py`、`COMPLETED`）・
  バーテンダー à Tokyo（`spinoff_markers_verification.md`、「完結」）いずれも期待ラベル
  「完結」と一致。E_missed→A_correctに分類される。

**外れた予測は主検証には無い。**

## 副作用チェック

影響候補2件（陰陽師・バーテンダー à Tokyo）以外の158行（160−2）について、修正前後で
status・evidenceが完全一致することを実測で確認した（`step104_planb_verification.py`の
`changed`リストが上記2件のみであることが、その裏返しの確認になっている）。
**新規回帰0件。**

## ミューテーションテスト（代替語「コミカライズ」）の結果

```
変化 regression=0 holdout=0 計=0
```

事前登録6節の見積もり（正規表現のみの静的走査による「フリップ候補7件」）に対し、
実`judge()`では**0件**だった。**予測は外れており、そのまま記録する（書き換えない）。**

### 診断（読み取りのみ、7候補すべてを個別実行して確認）

7候補（異世界迷宮でハーレムを、わたしの幸せな結婚〈特装版がない場合通常版〉、
僕のカノジョ先生、時々ボソッとロシア語でデレる隣のアーリャさん、経験済みなキミと、
経験ゼロなオレが、お付き合いする話。、幼女戦記、冒険者になりたいと都に出て行った娘が
Sランクになってた）はいずれも、`_judge_extract()`の修正前後で**同一のstatus・
同一のevidence文**を返した。実測したevidence文はすべて「メディアミックスとして…
コミカライズが…連載されている/連載中」という形の文で、`MANGA_MARKERS`
（"コミカライズ"を含む）に一致するため、`_judge_extract()`の決着ループが
`has_ongoing_elsewhere`を経由せず、この文自身を直接の決着文として採用していた
（699-702行目、`is_multimedia=True`かつ`has_manga=True`の直接return経路）。

## 既存テストへの影響（実測）

`comic_checker/`は変更していないため、通常の`pytest`実行は現状（案B未適用）の
ベースライン確認になる。

```
python -m pytest tests/test_wikipedia_client.py -k "test_judge_extract_excludes_zokuhen_sentence_bartender_a_tokyo or test_strong_completion_is_not_vetoed_by_ongoing_elsewhere" -v
2 passed

python -m pytest -q
269 passed
```

加えて、`_has_ongoing_signal`のみをプロセス内で差し替え、両テストが使う入力文
（テストファイルは編集せず、文字列を直接読んで使用）を`_judge_extract`に通した結果:

- `test_judge_extract_excludes_zokuhen_sentence_bartender_a_tokyo`のextract:
  `('判定不能', None)` → `('完結', '『グランドジャンプ』…2016年1号から同年7号まで連載。')`。
  **現在のアサーション`assert status == STATUS_UNKNOWN`は案B適用後に失敗する。**
- `test_strong_completion_is_not_vetoed_by_ongoing_elsewhere`のextract:
  `('完結', '本編は2020年に完結した。')` → `('完結', '本編は2020年に完結した。')`。
  **アサーションは通り続けるが、veto発火の前提が消滅していることを実測で確認した**
  （事前登録4-3節が予測したとおり）。

## 現時点の判定: 保留

事前登録5節の合否条件のうち、条件1（2件の変化方向が期待ラベルと一致）・条件2
（158行で新規回帰0件）はいずれも満たしている。しかし条件3「3-2節の予測が実測と
一致すること。一致しない場合は手順8に従い報告して停止する」は、**ミューテーション
テスト側で予測（フリップ候補7件）と実測（0件）が乖離したため未充足**。
`verification_procedure.md`手順5の規定（「0件なら検証系の欠陥として扱い、報告して
停止する（自力で再設計しない）」）に従い、**「合格」の結論は出さず保留する**。

代替語候補の再選定・合成フィクスチャによる再設計は、本文書とは別の記録
（`docs/code_defects_2026-08/mutation_candidate_search_result.md`・
`docs/code_defects_2026-08/prereg_planb_mutation_addendum.md`）で扱う。
