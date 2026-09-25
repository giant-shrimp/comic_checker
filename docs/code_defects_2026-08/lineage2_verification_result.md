# 検証結果: 系統2（Issue #156、インフォボックスプレースホルダ値誤認識）の実測照合

**実行日**: 2026-09-25
**位置づけ**: 事前登録`docs/code_defects_2026-08/prereg_lineage2_infobox_placeholder.md`
（コミット`6e427056f82683967e8598aac519e77ac2cd69f5`）に対応する結果コミット。
事前登録8節「事前登録コミットと結果コミットの厳格な分離」に従い、事前登録本体・
2節・4節の予測値は結果を見た後に書き換えていない。

**最重要原則の遵守**: 実測は事前登録4節の予測と完全に一致した。予測の書き換えは
一切発生していない。

## 1. 事前登録へのリンクとロック値

- 事前登録本体: `docs/code_defects_2026-08/prereg_lineage2_infobox_placeholder.md`
- 事前登録コミット（手順1で確認済み）: `6e427056f82683967e8598aac519e77ac2cd69f5`
- 実装コミット: `c9bd1b4f128934a40be5604cf2c3a0f9365b2346`
  （`comic_checker/wikipedia_client.py`・`tests/test_wikipedia_client.py`を1コミットに含む）

**照合値**:

```
md5sum docs/code_defects_2026-08/prereg_lineage2_infobox_placeholder.md
325631d6b6edcb9ac093fd0258f07a99
```

事前登録作成時（PR #312コメントで記録済み）のmd5と一致。事前登録文書は実装フェーズを
通じて未改変。

## 2. 予測と実測の対照表（事前登録4節）

事前登録4節の予測を、`docs/regression_corpus_2026-08/step98_judge_harness.py`の
`run_judge_with_snapshot()`による実judge()実測（保存コーパス160行＝
`regression_corpus_wikitext.json`61件＋`holdout_wikitext.json`99件、変更前後の
`_judge_via_infobox()`をそれぞれ適用）と対照した。

| 項目 | 予測値 | 実測値 | 一致/不一致 |
|---|---|---|---|
| `judge()`最終出力が変化する行数 | ちょうど1件 | 1件 | **一致** |
| 変化の方向 | 完結→判定不能 | 完結→判定不能 | **一致** |
| 他159件 | 変化なし | 変化なし | **一致** |
| 既存テストスイート | すべて通る | すべて通る（453 passed、後述） | **一致** |

**予測と実測の不一致は0件。**

### 変化した行の個別追跡（値・作品名は記載しない）

- 出典: `docs/holdout_measurement_2026-08/step98_b_compare_result.md`のNo.44
  （bucket=F_unverifiable）と同一行。
- 変化前: `judge()`最終出力＝完結、evidence種類＝インフォボックスの終了系フィールド
  （値はプレースホルダ）。
- 変化後: `judge()`最終出力＝判定不能、evidence＝`None`
  （`_judge_via_infobox()`が`(None, None)`を返し、判定は`_judge_extract()`が
  元々返していた判定不能のまま維持された）。
- この1件以外の159件について、`status`・`evidence`のいずれにも変化は無い
  （実測、`run_judge_with_snapshot()`の出力を全件突き合わせて確認）。

### 事前登録2節「範囲外2件」への影響

事前登録2節が「範囲外」とした2件（数字を含まない非空値で「連載中」「休載」も
含まない値）は、いずれも上記1件には含まれない。今回の変更条件（値が「？」「?」
のみ）に該当しないため、`_judge_via_infobox()`の経路が変わらないという事前登録の
記述どおりの結果になった。

## 3. ミューテーションテストの結果（事前登録5節・6節）

手順4で追加した`_is_placeholder_value()`呼び出し（新設の分岐）のみを一時的に
無効化し、5節の合成フィクスチャ3ケースを再実行した。

| テスト名 | 分岐あり（通常） | 分岐を外した状態 |
|---|---|---|
| `test_judge_via_infobox_placeholder_fullwidth_stays_unknown` | PASSED | **FAILED**（`完結`が返り`status is None`のassertが失敗） |
| `test_judge_via_infobox_placeholder_halfwidth_stays_unknown` | PASSED | **FAILED**（同上） |
| `test_judge_via_infobox_numeric_end_field_still_completed` | PASSED | PASSED（数字を含む通常値のケースは分岐の有無に関わらず`完結`のまま） |

**判定**: 分岐を外すと「？」「?」のケースのテストが失敗し、数字ケースのテストは
通ったままだった。事前登録6節が定義した確認内容（追加した分岐を外すと新規テストが
失敗すること、かつ対象条件に該当しない値の経路は変えていないこと）を両方満たす。
確認後、分岐は元の状態に復元した（`git diff`で復元後の差分が意図した実装のみで
あることを確認済み）。

## 4. 合否判定

事前登録6節の停止条件（出力が変わる件数が1件でない場合、または完結→判定不能以外の
変化がある行が見つかった場合）はいずれも成立しなかった。2節の予測・3節の
ミューテーションテストともに事前登録どおりの結果が得られたため、**この実装案を
採用する**。

## 5. 限界の開示

> 該当1件（No.44相当）は本Issueの発見材料である（事前登録7節）。保存コーパス160件
> 全体を対象にした本検証は、新規回帰が起きないことの副作用チェックとしては有効だが、
> この変更が「有効に機能する」ことの有効性の証拠にはならない（Issue #53の原則）。
> 範囲外2件（事前登録2節）は本変更の対象外のまま残っており、この2件が誤判定を含む
> かどうかは本検証では評価していない。新規抽出（未消費142件プール）・holdout2は
> 事前登録7節の方針どおり使用していない。

## 6. 導出方法

- **入力データ**: `docs/regression_corpus_2026-08/regression_corpus_wikitext.json`
  （61件）・`docs/holdout_measurement_2026-08/holdout_wikitext.json`（99件）、
  計160件の保存済み生wikitext・extract。Wikipediaへの再取得は行っていない。
- **修正前後の切替**: 変更前は`git stash`等でファイルを退避するのではなく、実装
  コミット前後でそれぞれ`run_judge_with_snapshot()`を全件実行し、結果をリポジトリ
  管理外のディレクトリ（`logs/`、`.gitignore`で無視対象であることを`git check-ignore`
  で確認済み）へJSONとして保存し、Pythonで突き合わせた。`comic_checker/`本体への
  一時的なプロセス内差し替えではなく、実際にコード（`comic_checker/wikipedia_client.py`）
  を変更した状態でそれぞれ実行している。
- **`judge()`最終出力レベルの測定**: `run_judge_with_snapshot()`経由で`judge()`本体
  （インフォボックスフォールバックを含む）を呼び出した。
- **ミューテーションテスト**: `comic_checker/wikipedia_client.py`内の該当分岐を
  一時的にコメントアウトし、`pytest`を該当テストのみ実行して結果を確認した後、
  分岐を元の内容に復元した。
- **参考記録**: `./scripts/verify.sh`（453 passed、M6-B-4ゲート値の確認を含む）・
  `bash scripts/check_scanner_registry.sh`（OK）。

作品名と値は本文書に記載していない。行の特定は測定結果ファイルの行番号（No.44）
だけで行った（ERRORS.mdの記載規則に関する記録に従う）。
