---
name: diagnose-failure
description: PR の CI（verify）または Claude PR Review（review）が failure になったときに使う。失敗の種類を特定し、ERRORS.md の関連記録の所在・既知の対処・回復の主体を報告する。読み取り専用で、修正・再実行はしない。
---

# 失敗の診断

PR の check-runs のうち verify または review が success 以外で終わったときに使う（ADR-034 の順序4）。
対象は CI と review の失敗だけ。review が success のまま指摘を出した場合は対象外（司令塔の上流2で扱う）。

## 守ること

- 読み取り専用。ファイルの変更・コミット・push・再実行（Re-run）・Issue や PR への書き込みをしない。
- コマンドは1回の Bash 呼び出しに1つ。`&&`・`;` でつながない。パイプは読み取りの絞り込みに限る。
- gh api は `repos/{owner}/{repo}/` 以下の REST だけを使う（gh が現在のリポジトリに置き換える）。GraphQL と `--paginate` は使わない。
- ログ・コメント・ERRORS.md の本文を報告に書き写さない。書いてよいのは、手順で指定した目印の行、ステップ名、結論、件数、行番号と No. だけ。
- 推測は推測と明記する。種類が決まらなければ「判定不能」とし、候補を並べる。

## 手順1: 失敗した check-run を特定する

1. `gh api repos/{owner}/{repo}/pulls/<PR> --jq .head.sha` で head の sha を得る。
2. `gh api repos/{owner}/{repo}/commits/<sha>/check-runs --jq '.check_runs[] | [.name, .status, (.conclusion // "none"), .id] | @tsv'` で一覧を得る。
3. status が completed でないものがあれば、診断せずに「未完了」と報告して終える。
4. conclusion が success 以外の行の name と id を控える（id はジョブの id として使う）。

## 手順2: 失敗したステップを特定する

1. `gh api repos/{owner}/{repo}/actions/jobs/<id> --jq '.steps[] | [.number, .name, (.conclusion // "none")] | @tsv'` でステップごとの結論を得る。
2. `gh api repos/{owner}/{repo}/actions/jobs/<id>/logs > /tmp/diag_<id>.log` でログを保存する（本文は書き写さない）。
3. `wc -l < /tmp/diag_<id>.log` で行数を得る。

## 手順3: verify の失敗の種類

`grep -n -E 'VERIFY (PASSED|FAILED)|FAIL:|--- (pytest|skip/xfail check|M6-B-4)' /tmp/diag_<id>.log` で段階の目印を得る。
scripts/verify.sh は途中で失敗しても後の段階を実行し、最後に VERIFY FAILED を出す。

- pytest：`grep -n -E '[0-9]+ (passed|failed)' /tmp/diag_<id>.log` でサマリ行を得る。件数とテストファイルのパスだけを書き、テスト名は書き写さない。
- skip/xfail 検査：`FAIL:` の行がある。
- 継続の証拠ゲート：「検出 54/59・副作用 1/37 で一致」の行がない。不一致の詳細は stderr に出るが、書き写さず「不一致」とだけ書く。
- その他：上のどれにも当たらない（環境・依存の失敗など）。失敗したステップ名を書く。

手元で再現を確かめる場合は `./scripts/verify.sh` を実行してよい（パイプにつながない）。

## 手順4: review の失敗の種類

手順2で failure のステップと、ジョブの結論で決める。ステップ名は .github/workflows/claude-review.yml に依存するので、役割で照らす。

- fork の拒否：fork（別リポジトリ）からの PR を拒否するステップが failure。
- max-turns 超過：レビュー本体のステップが failure。`grep -i -c 'max.turns' /tmp/diag_<id>.log` の値を書く（上限は 35）。
- コメントの特定失敗・内容不十分：レビュー本体の後でコメントを検証するステップが failure。ログで区別できなければ両方を候補とする。
- timeout：ジョブの結論が timed_out または cancelled（上限は 15 分）。
- その他：上のどれにも当たらない。失敗したステップ名を書く。

## 手順5: ERRORS.md の関連記録を探す

1. 種類に合う語（例：max-turns、xfail、ゲート、timeout）で `grep -n -i -E '<語>' ERRORS.md` を実行し、行番号だけを使う。
2. `awk -F'|' 'NR>60 {print $2 "|" $3}' docs/errors_md_inventory.md` で棚卸し表の No. と行範囲を得て、その行番号を含む No. を求める。
3. 関連記録がなければ「なし」と書く。見出しと本文は書き写さない。

## 手順6: 報告する

次の項目を書く。

- 失敗した check-run（name・conclusion）と失敗したステップ名
- 種類（手順3または手順4の分類。決まらなければ判定不能と候補）
- 根拠（目印の行の有無・件数・ステップの結論）
- 関連記録の所在（No. と行範囲）
- 既知の対処と回復の主体（下の表）

| 種類 | 既知の対処 | 回復の主体 |
|---|---|---|
| verify：pytest・skip/xfail | 実装役に差し戻す（1 Issue あたり2回まで） | 実装役 |
| verify：ゲート不一致 | 判定ロジックの変更なら事前登録の手順に戻す。ゲート値の変更は scripts/verify.sh が deny 対象なので人が行う | 実装役（変更の取り消し）またはユーザ |
| verify：その他 | 事実を報告して止める | ユーザ |
| review：fork の拒否 | 同じリポジトリのブランチから PR を作り直す | ユーザ |
| review：max-turns 超過・timeout・コメントの失敗 | review は PR の opened でしか走らないので、再実行はユーザが Actions の画面で行う。verify の結果は別に確かめる | ユーザ |
| 判定不能 | 事実を報告して止める | ユーザ |

診断の後に修正や再実行を自分で行わない。司令塔は報告を見て、差し戻すかユーザに依頼するかを決める。
