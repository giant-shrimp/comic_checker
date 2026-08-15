# -*- coding: utf-8 -*-
"""実judge()を、保存済みの生wikitext/extractを注入して呼び出すための共通ハーネス。

モンキーパッチするのは _pick_article と _fetch_wikitext のみ。それ以外は
すべて本物の comic_checker.wikipedia_client の関数をそのまま使う。
comic_checker/本体は変更しない。

再現手順（リポジトリルートから実行。ディレクトリ名がハイフンを含みPythonパッケージ
として import できないため、sys.path経由で読み込む）:
    python3 -c "
    import sys, json
    sys.path.insert(0, 'docs/regression_corpus_2026-08')
    from step98_judge_harness import run_judge_with_snapshot
    rows = json.load(open('docs/regression_corpus_2026-08/regression_corpus_wikitext.json',
                           encoding='utf-8'))['rows']
    r = rows[0]
    result = run_judge_with_snapshot(r['input_title'], r['matched_title'], r['extract'],
                                      r['url'], r['wikitext'])
    print(r['input_title'], '->', result.status, '/', result.evidence)
    "
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
import comic_checker.wikipedia_client as wc  # noqa: E402

_ORIG_PICK_ARTICLE = wc._pick_article
_ORIG_FETCH_WIKITEXT = wc._fetch_wikitext


def run_judge_with_snapshot(title, matched_title, extract, url, wikitext,
                             use_infobox=True, today=None):
    """保存済みデータを注入して実judge()を呼ぶ。

    差し替えるのは _pick_article と _fetch_wikitext の2関数のみ
    （呼び出し元で assert 済みの前提を守る）。
    """
    def fake_pick_article(_title):
        if matched_title is None:
            return None, None
        return (matched_title, extract, url), None

    def fake_fetch_wikitext(_page_title):
        return wikitext

    wc._pick_article = fake_pick_article
    wc._fetch_wikitext = fake_fetch_wikitext
    try:
        result = wc.judge(title, use_infobox=use_infobox, today=today)
    finally:
        wc._pick_article = _ORIG_PICK_ARTICLE
        wc._fetch_wikitext = _ORIG_FETCH_WIKITEXT
    return result


def list_monkeypatched_functions():
    return ["_pick_article", "_fetch_wikitext"]
