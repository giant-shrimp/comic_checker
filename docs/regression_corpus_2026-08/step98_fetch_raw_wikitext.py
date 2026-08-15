# -*- coding: utf-8 -*-
"""holdout100（記事あり99件）・regression94（記事あり61件）の生wikitextを取得する。

【方針転換】これまでの「抽出済みfields/volumesから合成wikitextを再構成する」
方式は、_infobox_field()が「フィールド不在」と「存在するが空欄」の両方でNoneを
返すため区別が付かず、実際に54件で判定が変わりうることが判明したため廃止した。
以降は生wikitextそのものを保存する（ERRORS.md「PR #152の安全性検証で、検証手法の
欠陥が3回連続で見つかった」参照）。

comic_checker/本体は変更しない。matched_titleは既に判明しているため、
_pick_article の再探索（_resolve_titles/_search_titles）は行わず、
_fetch_extract(matched_title) / _fetch_wikitext(matched_title) を直接呼ぶ。

再実行するとWikipediaへの再取得が発生する（2026-08-15時点で160件・約480
リクエスト・約14.6分）。再現用に置いているものであり、通常のverify.sh等では
実行しない。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from comic_checker import wikipedia_client as wc  # noqa: E402

HOLDOUT_RAW = _REPO_ROOT / "docs/holdout_measurement_2026-08/step98_a3_raw_material.json"
REGRESSION_RAW = _REPO_ROOT / "docs/regression_corpus_2026-08/regression_corpus_raw.json"
OUT_HOLDOUT = _REPO_ROOT / "docs/holdout_measurement_2026-08/holdout_wikitext.json"
OUT_REGRESSION = _REPO_ROOT / "docs/regression_corpus_2026-08/regression_corpus_wikitext.json"

holdout = json.load(open(HOLDOUT_RAW, encoding="utf-8"))
regression = json.load(open(REGRESSION_RAW, encoding="utf-8"))

targets = []
for r in holdout["rows"]:
    if r["matched_title"] is not None:
        targets.append({"source": "holdout100", "input_title": r["input_title"],
                         "matched_title": r["matched_title"],
                         "old_extract": r["extract"], "old_url": r["url"]})
for r in regression["rows"]:
    if r["matched_title"] is not None:
        targets.append({"source": "regression94", "group": r["group"],
                         "input_title": r["input_title"], "matched_title": r["matched_title"],
                         "old_extract": r["extract"], "old_url": r["url"],
                         "old_revision_id": r.get("revision_id")})

assert len(targets) == 99 + 61, f"想定160件のはずが{len(targets)}件"

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
not_found_count = 0

for i, t in enumerate(targets, 1):
    matched_title = t["matched_title"]
    extract_result = wc._fetch_extract(matched_title)
    wikitext = wc._fetch_wikitext(matched_title)
    revid = _fetch_revid(matched_title)

    if extract_result is None:
        not_found_count += 1
        new_extract, new_url = None, None
    else:
        resolved_title, new_extract, new_url = extract_result

    rows.append({
        "source": t["source"],
        "group": t.get("group"),
        "input_title": t["input_title"],
        "matched_title": matched_title,
        "extract": new_extract,
        "url": new_url,
        "wikitext": wikitext,
        "revision_id": revid,
        "old_extract": t["old_extract"],
        "old_url": t["old_url"],
    })
    print(f"[{i}/{len(targets)}] ({t['source']}) {t['input_title']} -> "
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
    "articles_not_found_count": not_found_count,
}

holdout_rows = [r for r in rows if r["source"] == "holdout100"]
regression_rows = [r for r in rows if r["source"] == "regression94"]

with open(OUT_HOLDOUT, "w", encoding="utf-8") as f:
    json.dump({
        "purpose": ("ホールドアウト100件（記事あり99件）の生wikitextスナップショット。"
                    "合成wikitext方式を廃止し原本を保存する。comic_checker/本体は"
                    "変更していない。"),
        "retrieval_metadata": retrieval_metadata,
        "rows": holdout_rows,
    }, f, ensure_ascii=False, indent=2)

with open(OUT_REGRESSION, "w", encoding="utf-8") as f:
    json.dump({
        "purpose": ("拡張群72件・回帰群22件（記事あり61件）の生wikitextスナップショット。"
                    "合成wikitext方式を廃止し原本を保存する。comic_checker/本体は"
                    "変更していない。"),
        "retrieval_metadata": retrieval_metadata,
        "rows": regression_rows,
    }, f, ensure_ascii=False, indent=2)

print("", file=sys.stderr)
print("=== 完了 ===", file=sys.stderr)
print(f"rows: {len(rows)} (holdout100: {len(holdout_rows)}, regression94: {len(regression_rows)})",
      file=sys.stderr)
print(f"api_requests: {api_calls[0]}  http_429: {http_429[0]}", file=sys.stderr)
print(f"elapsed: {retrieval_metadata['elapsed_seconds']}s", file=sys.stderr)
print(f"articles_not_found (再取得時): {not_found_count}", file=sys.stderr)
print(f"wrote: {OUT_HOLDOUT}", file=sys.stderr)
print(f"wrote: {OUT_REGRESSION}", file=sys.stderr)
