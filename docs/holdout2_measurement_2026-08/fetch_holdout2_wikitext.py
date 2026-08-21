# -*- coding: utf-8 -*-
"""holdout2（120件）の生wikitextを取得する。

docs/regression_corpus_2026-08/step98_fetch_raw_wikitext.py と同じ方式（生wikitextを
そのまま保存、合成wikitext方式は使わない）を踏襲する。ただしholdout2はmatched_titleが
未確定の新規標本のため、_pick_article(title) による記事解決を先に行う点が異なる。

comic_checker/本体は変更しない。取得と保存のみを行い、内容の読解・分類・要約は行わない。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from comic_checker import wikipedia_client as wc  # noqa: E402

SAMPLE_FILE = _REPO_ROOT / "docs/holdout2_measurement_2026-08/holdout2_sample_titles.json"
OUT_FILE = _REPO_ROOT / "docs/holdout2_measurement_2026-08/holdout2_wikitext.json"

sample = json.load(open(SAMPLE_FILE, encoding="utf-8"))
titles = sample["sample_titles"]
assert len(titles) == 120, f"想定120件のところ{len(titles)}件"

_orig_api_get = wc._api_get
_orig_requests_get = wc.requests.get
api_calls = [0]
http_429 = [0]


def _counting_requests_get(*args, **kwargs):
    response = _orig_requests_get(*args, **kwargs)
    if response.status_code == 429:
        http_429[0] += 1
    return response


def _counting_api_get(params):
    api_calls[0] += 1
    return _orig_api_get(params)


wc._api_get = _counting_api_get
wc.requests.get = _counting_requests_get


def _fetch_revid(page_title):
    data = wc._api_get({
        "action": "query", "prop": "revisions", "rvprop": "ids",
        "titles": page_title, "redirects": "1",
    })
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    revisions = page.get("revisions")
    if not revisions:
        return None
    return revisions[0].get("revid")


started_at = datetime.now(timezone.utc)
rows = []
not_found_titles = []

for i, input_title in enumerate(titles, 1):
    article, trace = wc._pick_article(input_title)
    if article is None:
        not_found_titles.append(input_title)
        rows.append({
            "source": "holdout2",
            "input_title": input_title,
            "matched_title": None,
            "extract": None,
            "url": None,
            "wikitext": None,
            "revision_id": None,
        })
        print(f"[{i}/{len(titles)}] {input_title} -> 記事なし", file=sys.stderr)
        continue

    matched_title, extract, url = article
    wikitext = wc._fetch_wikitext(matched_title)
    revid = _fetch_revid(matched_title)

    rows.append({
        "source": "holdout2",
        "input_title": input_title,
        "matched_title": matched_title,
        "extract": extract,
        "url": url,
        "wikitext": wikitext,
        "revision_id": revid,
    })
    print(f"[{i}/{len(titles)}] {input_title} -> matched={matched_title} "
          f"revid={revid} wikitext_len={len(wikitext) if wikitext else 0}",
          file=sys.stderr)

finished_at = datetime.now(timezone.utc)

retrieval_metadata = {
    "retrieval_window_utc": {
        "start": started_at.isoformat().replace("+00:00", "Z"),
        "end": finished_at.isoformat().replace("+00:00", "Z"),
    },
    "elapsed_seconds": round((finished_at - started_at).total_seconds(), 1),
    "api_requests_total": api_calls[0],
    "http_429_count": http_429[0],
    "articles_not_found_count": len(not_found_titles),
    "not_found_titles": not_found_titles,
}

with open(OUT_FILE, "w", encoding="utf-8") as f:
    json.dump({
        "purpose": (
            "docs/code_defects_2026-08/prereg_corpus_expansion_holdout2.md "
            "に基づくholdout2（120件抽出、記事あり件数は下記メタデータ参照）の"
            "生wikitextスナップショット。comic_checker/本体は変更していない。"
        ),
        "retrieval_metadata": retrieval_metadata,
        "rows": rows,
    }, f, ensure_ascii=False, indent=2)

print("", file=sys.stderr)
print("=== 完了 ===", file=sys.stderr)
print(f"rows: {len(rows)}", file=sys.stderr)
print(f"api_requests: {api_calls[0]}  http_429: {http_429[0]}", file=sys.stderr)
print(f"elapsed: {retrieval_metadata['elapsed_seconds']}s", file=sys.stderr)
print(f"articles_not_found: {len(not_found_titles)}", file=sys.stderr)
print(f"not_found_titles: {not_found_titles}", file=sys.stderr)
print(f"wrote: {OUT_FILE}", file=sys.stderr)
