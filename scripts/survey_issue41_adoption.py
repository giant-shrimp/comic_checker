"""Issue #41 の調査。「(漫画)」曖昧さ回避記事での mediamix チェック緩和の実データ収集。

**これは pytest の対象ではない**（実ネットワークI/Oを伴う）。他の `survey_*.py` と
同じ扱いで、必要なときに手で走らせる。

    python scripts/survey_issue41_adoption.py

`scripts/m6d3_labels.py` の `REGRESSION_LABELS`（22行）に対して出荷中の `judge()` を
そのまま呼び、`adoption_path` が `ADOPTION_PATH_DIRECT_DISAMBIGUATION`（＝「〜 (漫画)」
表記の直参照）だった行に限って、緩和の設計材料として `_is_novel_primary()` /
`_lands_on_a_different_work()` を**診断目的で**適用する。判定（status/evidence）には
一切影響しない。

拡張群（`LABELS`・72行）とM6-D-4（`m6d4_labels.LABELS`・96行）は対象にしない。
両者とも `expected_page` に `(漫画)` を含む行が0件であることは事前に確認済みで
（`REGRESSION_LABELS` はラベル自体が「Wikipediaの記事を人手で読んで」決めた期待着地先
なので、曖昧さ回避表記へ着地する行があればそこに現れているはずである）、実際に
`judge()` を168件分呼んで「やはり0件だった」を確認する情報価値は、Issue #41が
問題にしている「`(漫画)`表記に着地した行がどう判定されるか」という問いに対しては
薄い。API呼び出し（168件 x 1〜2リクエスト x 1.0秒間隔で数分規模）に見合わないと
判断し、対象を回帰群22行に絞る。

出力は `~/comic_checker-agent-notes/issue41_adoption_survey.json` へ書く（リポジトリには
入れない）。Issue #41の緩和条件を設計するための一時的な実データであり、
`scripts/m6d3_labels.py` のような恒久的なラベル定義とは性質が違う。

**`adoption_probe`と`matched_title`は別物である。** probeは「〜 (漫画)」曖昧さ回避表記
そのものだが、Wikipedia側のリダイレクトでmatched_titleが素タイトルへ解決されることが
ある（実例: `幼女戦記`はprobe=`幼女戦記 (漫画)`でtrusted採用されたが、matched_titleは
`幼女戦記`）。`expected_page`（≒matched_title相当）に`(漫画)`が含まれるかで曖昧さ回避
経由の件数を数えると、この形の行を見落とす。

判定は `wikipedia_client` の関数をそのまま import して呼ぶ。調査したコードと出荷する
コードが同一でなければ意味が無い（#51 で採った方針と同じ）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from m6d3_labels import REGRESSION_LABELS

from comic_checker import wikipedia_client
from comic_checker.wikipedia_client import (
    ADOPTION_PATH_DIRECT_DISAMBIGUATION,
    _is_novel_primary,
    _lands_on_a_different_work,
    judge,
)

OUTPUT_PATH = os.path.expanduser(
    "~/comic_checker-agent-notes/issue41_adoption_survey.json"
)

# `_fetch_extract()` を薄くラップして、matched_titleごとのextractを控える。
# `judge()`自体はextractを外へ出さないため、診断（_is_novel_primary等）に使う実文を
# 得るには何らかの形で控える必要がある。matched_titleをキーにするのは、
# `_fetch_extract()`が返す`resolved_title`（=リダイレクト解決後のタイトル）が、
# `judge()`が返す`matched_title`とそのままthreadされて一致するため
# （`_accept_article` -> `_pick_via_*` -> `_pick_article` -> `judge`の間で
# 加工されない）。この控えを使う分、追加のAPI呼び出しは発生しない。
_extract_by_matched_title = {}
_original_fetch_extract = wikipedia_client._fetch_extract


def _fetch_extract_recording(page_title):
    result = _original_fetch_extract(page_title)
    if result is not None:
        resolved_title, extract, _url = result
        _extract_by_matched_title[resolved_title] = extract
    return result


wikipedia_client._fetch_extract = _fetch_extract_recording


def main():
    rows = []
    for label in REGRESSION_LABELS:
        result = judge(label.title)
        extract = _extract_by_matched_title.get(result.matched_title)
        is_disambiguation_route = (
            result.adoption_path == ADOPTION_PATH_DIRECT_DISAMBIGUATION
        )

        novel_primary_flag = None
        different_work_flag = None
        if extract is not None:
            novel_primary_flag = _is_novel_primary(extract)
            different_work_flag = _lands_on_a_different_work(
                result.matched_title, extract, label.title
            )

        row = {
            "no": label.no,
            "title": label.title,
            "expected_page": label.expected_page,
            "expected": label.expected,
            "status": result.status,
            "correct": result.status == label.expected,
            "matched_title": result.matched_title,
            "adoption_path": result.adoption_path,
            "adoption_trusted": result.adoption_trusted,
            "adoption_probe": result.adoption_probe,
            "is_disambiguation_route": is_disambiguation_route,
            "is_novel_primary": novel_primary_flag,
            "lands_on_different_work": different_work_flag,
        }
        rows.append(row)
        print(
            f"  [{label.no}] {label.title!r:20} status={result.status!r:6} "
            f"(期待 {label.expected!r:6}) matched={result.matched_title!r} "
            f"path={result.adoption_path!r}",
            flush=True,
        )

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)

    disambiguation_rows = [r for r in rows if r["is_disambiguation_route"]]
    print(f"\n{len(rows)}件を判定。うち曖昧さ回避経路（'(漫画)'直参照）: "
          f"{len(disambiguation_rows)}件")
    print(f"書き出し先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
