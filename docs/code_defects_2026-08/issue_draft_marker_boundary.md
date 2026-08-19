> **本文書はIssue #171として起票済み**。分析内容・実測データ自体は本文書と
> Issue #171で同一だが、**最新の行番号情報はIssue #171本文が保持している**
> （起票時点＝2026-08-19の実測値）。
>
> **行番号依存を解消した経緯**: 本文書「影響範囲」表は当初、行番号
> （例: `L693`）を直接記載していたが、これは案B（Issue #154）適用前の
> 状態で記録されたものだった。案Bが`_has_ongoing_signal()`のSPINOFF_MARKERS
> 除外ロジック等を追加した結果、記載していた行番号の多くが実装からズレる
> 事態が生じた（Issue #171起票時に判明、詳細は
> `~/comic_checker-agent-notes/marker_boundary_filing_decision_material.md`
> 8節参照）。再発を防ぐため、下記「影響範囲」表は行番号を直接記載する形式
> から、定数名・関数名と`grep`コマンドによる参照形式に変更した
> （2026-08-19、参照形式の変更のみ。分析内容・結論は無変更）。

## 背景

案B（Issue #154）の合成フィクスチャによるミューテーションテスト
（`docs/code_defects_2026-08/planb_mutation_result.md`）の過程で、
`_has_ongoing_signal()`のSPINOFF_MARKERS除外判定が`marker in sentence`という
単純な部分文字列一致であり、単語境界を考慮しないことが判明した。マーカー語を
部分文字列として偶然含む、意味的には無関係な語（「継続編成」が「続編」を含む等）
が、除外対象として巻き込まれることを合成フィクスチャで実測した。

## 実測されている影響（合成フィクスチャによる。実データでの発見ではない）

`~/comic_checker-agent-notes/step106_negative_control_addendum.md`で設計し、
`docs/code_defects_2026-08/planb_mutation_result.md`で実行した3件。

| 巻き込みリスク語 | 含んでしまうマーカー | 実測結果 |
|---|---|---|
| 継続編成 | 続編 | `_has_ongoing_signal()`の除外対象に巻き込まれた（True→False） |
| 海外伝道師 | 外伝 | 同上 |
| 次世代編成局 | 次世代編 | 同上 |

**いずれも合成文（単一文からなる、検証目的で作成したテキスト）による確認であり、
実際のWikipedia記事での発見ではない。**

## 現コーパスでの実害（実測）

holdout99+regression61（計160行）の全`extract`に対し、`SPINOFF_MARKERS`の5要素
（続編・番外編・スピンオフ・外伝・次世代編）が部分文字列として出現する箇所を
全件（30件）洗い出し、各出現の前後6文字の文脈を目視で確認した。

**実測0件。** 全30件の出現はいずれも、マーカー語が独立した語として使われている
（例:「番外編として」「スピンオフ作品」「本編以外に外伝があり」「続編に『陰陽師
玉手匣』がある」等）正当な用法であり、他の語に埋め込まれた偶然の部分文字列一致は
1件も無かった。

**したがって、現時点でこの欠陥による実害（誤った除外による誤判定）は確認されて
いない。** 今回の発見は、現行コーパスでの実害の指摘ではなく、除外機構の設計に
内在する潜在的なリスクの指摘である。

## 影響範囲: 同じ部分文字列一致を使っている他の箇所

`comic_checker/wikipedia_client.py`を`grep`で調査したところ、`marker in X`
形式の部分文字列一致は`SPINOFF_MARKERS`に限らず、マーカー語彙を扱う複数の
箇所で使われている（いずれも単語境界を考慮しない同じ性質を持つ）。

**参照方法**: 下表は行番号を記載しない。各定数について、以下の形式の
`grep`コマンド（リポジトリルートから実行）で現在の該当箇所を再測定できる。

| 対象定数 | 用途 | 参照コマンド |
|---|---|---|
| `ARTICLE_RELEVANCE_MARKERS` | 記事の関連性判定 | `grep -n "ARTICLE_RELEVANCE_MARKERS" comic_checker/wikipedia_client.py` |
| `MERGED_COVERAGE_MARKERS` | 複数作品併記の宣言判定（`_declares_merged_coverage`） | `grep -n "MERGED_COVERAGE_MARKERS" comic_checker/wikipedia_client.py` |
| `DERIVATIVE_WORK_MARKERS`（デフォルト引数） | 派生作品としての言及判定（`_mentions_as_derivative_work`／`_marker_modifies_mention`、Issue #51）。実際の部分文字列比較は`_marker_modifies_mention()`内で引数名`markers`として行われるため、`grep`結果は定義・デフォルト引数指定箇所を指す | `grep -n "DERIVATIVE_WORK_MARKERS" comic_checker/wikipedia_client.py` |
| `NOVEL_MARKERS` | メディアミックス（原作小説）判定 | `grep -n "NOVEL_MARKERS" comic_checker/wikipedia_client.py` |
| `MANGA_MARKERS` | 漫画マーカー判定 | `grep -n "MANGA_MARKERS" comic_checker/wikipedia_client.py` |
| `SPINOFF_MARKERS` | 決着文からの派生作品文除外（案Bの`_has_ongoing_signal()`除外もこの定数を使う） | `grep -n "SPINOFF_MARKERS" comic_checker/wikipedia_client.py` |
| `CONTINUATION_MARKER`（`not in`） | M6-B-4継続の証拠判定 | `grep -n "CONTINUATION_MARKER" comic_checker/wikipedia_client.py` |
| `ONGOING_FIELD_MARKER` | インフォボックス「連載中」判定 | `grep -n "ONGOING_FIELD_MARKER" comic_checker/wikipedia_client.py` |
| `HIATUS_MARKER` | インフォボックス「休載」判定 | `grep -n "HIATUS_MARKER" comic_checker/wikipedia_client.py` |

**この欠陥はSPINOFF_MARKERS・案B固有のものではなく、プロジェクト全体でマーカー語彙を
扱う際の共通パターンに内在する性質である。**

## 想定される対処の方向性（未検証。決定しない）

- 部分文字列一致を、単語境界を考慮した一致（例: 前後が特定の文字種でないことを
  確認する、正規表現の単語境界相当を導入する等）に置き換える。ただし日本語には
  英語のような明確な単語区切りが無く、形態素解析等の追加処理が必要になる可能性が
  ある。
- 現状維持とし、既知の限界として`docs/known_limitations.md`に記載する
  （現コーパスでの実害が0件であることを踏まえた判断）。
- 巻き込みが起こりうる具体的な語のペア（今回発見した3件等）だけを個別に除外する
  対症療法。

いずれを採るかはこのIssueでは決定しない。

## 完了条件

- 対処方針の決定（上記のいずれか、または他の方針）
- 方針決定後、実データでの追加調査（現コーパス以外の記事でも実害が無いか）
- 対処を実施する場合、影響範囲の表に挙げた全箇所について、同じ対処が必要かを
  個別に判断する

## 優先度

低〜中。現コーパスでの実害は実測0件であり、緊急の修正を要する状態ではない。
一方、影響範囲がSPINOFF_MARKERS単独ではなくプロジェクト全体のマーカー語彙処理に
及ぶ構造的な性質であるため、記録として残す価値がある。

Refs: Issue #154, `docs/code_defects_2026-08/planb_mutation_result.md`,
`docs/code_defects_2026-08/mutation_candidate_search_result.md`
