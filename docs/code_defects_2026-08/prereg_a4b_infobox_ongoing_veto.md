# 事前登録：本文が完結でもインフォボックスが連載中なら判定不能にする（Issue #367，候補A4 案b）

## 1. 変更案
judge()（comic_checker/wikipedia_client.py）で，use_infobox=True のとき，本文（_judge_extract）が完結を返した場合も _judge_via_infobox を呼び，連載中を返したら最終 status を判定不能にする．use_infobox=False のときは変えない．
出力は完結→判定不能の向きにしか動かない（単調）．

## 2. 測定方法
- スクリプト：docs/code_defects_2026-08/a4b_measure.py（本文書と同じコミットに含める）．
- 現行コードのまま，before（ハーネス run_judge_with_snapshot の最終 status），ext（_judge_extract），ibx（_judge_via_infobox）を求め，before＝完結 かつ ext＝完結 かつ ibx＝連載中 の行を after＝判定不能とする．
- today は 2026-08-15 に固定する．ネットワークは遮断する．
- 対象：保存データ160行（--dataset saved）と holdout2（--dataset holdout2．docs/holdout2_measurement_2026-08/ の holdout2_wikitext.json と holdout2_labels_v4.json）．
- holdout2 での実行は，本文書のコミット後に1回だけ行う．結果を見てスクリプト・基準・対象を変えない．

## 3. 予測
- 保存データ：変わる行は0行（本文書の作成前に測定済み．ext＝完結 かつ ibx＝連載中 の行が0行のため）．スナップショット照合テストの基準は変わらない．
- holdout2：変わる行数は予測しない．変わる行はすべて完結→判定不能の向き．

## 4. 採否の基準（holdout2 の結果に適用する）
- L：変わった行のうち期待ラベルが完結の行数（正しい完結を失う）．
- G：変わった行のうち期待ラベルが完結以外の行数（誤った完結を判定不能に直す）．
- 期待ラベルが見つからない行は L・G に数えず，件数を別に記録する．
1. 完結→判定不能 以外の向きが1件でもあれば，採用せず原因を調べる．
2. 変わった行が0行なら，コードは変更しない（既知の限界として記録するかを別に決める）．
3. G≧1 かつ L≦G なら採用する．それ以外は採用しない．

## 5. 採用した場合の検証
テストを先に追加し，変更前に失敗することを確かめてから実装する．実装後，実際の judge() で holdout2 を測り，変わる行が本測定の after と一致することを確かめる．
