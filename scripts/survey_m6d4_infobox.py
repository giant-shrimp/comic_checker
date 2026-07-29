"""Issue #53 (M6-D-4) の調査。インフォボックスの「終了系が空欄 ⇒ 連載中」が誤る例を探す。

**これは pytest の対象ではない**（実ネットワークI/Oを伴う）。
`scripts/measure_false_negative_rate.py` と同じ扱いで、必要なときに手で走らせる。

    python scripts/survey_m6d4_infobox.py [--pilot | --holdout | --verify]

`--verify` は**API を叩かない**。`scripts/m6d4_labels.py` の人手ラベル96行に対して
出荷中の `_has_continuation_evidence()` を当て、検出力と副作用を出す。Issue #56 の
ゲートを触ったあとの回帰確認はこれで足りる。

## 母集団は「弱い推論が実際に決めている行」そのもの

インフォボックス経路は `_judge_extract()` が `判定不能` を返したときにしか走らない。
だから地の文の完結シグナルで母集団を絞ると、**そもそもこの経路に到達しない記事**ばかりが
集まる。代わりに判定の分岐点そのものを母集団にする。

    hastemplate:"Infobox animanga/Manga" から N 件
      -> extract を取り `_judge_extract()`  … 判定不能の記事だけ残す
      -> wikitext を取り `_judge_via_infobox()` … 連載中を返した記事だけ残す
      -> この行を人手判定（実際に連載中か完結か）

判定は `wikipedia_client` の関数をそのまま import して呼ぶ。調査したコードと出荷する
コードが同一でなければ意味が無い（#51 で採った方針と同じ）。
"""
import json
import os
import re
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from m6d4_labels import COMPLETED, HOLDOUT, LABELS, MAIN
from comic_checker.wikipedia_client import (
    END_FIELD_NAMES,
    MANGA_INFOBOX_MARKER,
    STATUS_UNKNOWN,
    _api_get,
    _extract_braced_blocks,
    _fetch_extract,
    _fetch_wikitext,
    _find_main_manga_block,
    _has_ongoing_signal,
    _infobox_field,
    _judge_extract,
    _judge_via_infobox,
)

BASE_QUERY = 'hastemplate:"Infobox animanga/Manga"'
PILOT_ARTICLES = 30
FULL_ARTICLES = 1800  # 人手判定 N>=60 が目標（歩留まり3.3%想定）
PAGE_SIZE = 50
REQUEST_INTERVAL = 1.0  # Issue #40 が未対応なので、間隔はこのスクリプト側で持つ
PROGRESS_EVERY = 100    # 進捗報告と打ち切り判定の間隔
HOLDOUT_ARTICLES = 500  # 閾値の検証用。本調査(1800件)の先から取る

CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".m6d4_infobox_cache.json",
)

_cache = {}
if os.path.exists(CACHE_PATH):
    with open(CACHE_PATH, encoding="utf-8") as fh:
        _cache = json.load(fh)

_stats = {"requests": 0, "429": 0}

# 完結シグナルの語彙は判定側と重複させない。ここでは「案Aで救えるか」の材料として、
# 地の文に完結を述べる文があるかだけを見る。
_COMPLETION_HINT_RE = re.compile(r"完結|連載(?:が|を)?終了|打ち切|最終回")


def _save_cache():
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(_cache, fh, ensure_ascii=False)


def _get(params, cache_key):
    if cache_key in _cache:
        return _cache[cache_key]
    for attempt in range(6):
        time.sleep(REQUEST_INTERVAL)
        _stats["requests"] += 1
        try:
            data = _api_get(params)
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                _stats["429"] += 1
                print(f"  !! HTTP 429（{_stats['429']}回目）", flush=True)
                time.sleep(5.0 * (attempt + 1))
                continue
            raise
        _cache[cache_key] = data
        _save_cache()
        return data
    raise RuntimeError("429 が解消しないので中止する")


def _cached(key, producer):
    if key not in _cache:
        time.sleep(REQUEST_INTERVAL)
        _stats["requests"] += 1
        _cache[key] = producer()
        _save_cache()
    return _cache[key]


def _require_population(query):
    """母集団の件数を先に確認する（ERRORS.md の教訓をコードで守らせる）。"""
    data = _get({"action": "query", "list": "search", "srsearch": query,
                 "srlimit": 1, "srinfo": "totalhits"}, f"totalhits:{query}")
    hits = data.get("query", {}).get("searchinfo", {}).get("totalhits", 0)
    print(f"  母集団 {hits:>7,} 件  {query}")
    if not hits:
        raise SystemExit(f"母集団が0件です。クエリを疑ってください: {query}")
    return hits


def collect_articles(count, start_offset=0):
    """`start_offset` から `count` 件。ホールドアウト標本は本調査の先から取る。

    **閾値を選んだ標本と、閾値を評価する標本は分けなければならない。** 同じ標本で
    「副作用が最小になる閾値」を選ぶと、報告される検出力・副作用は実力より良く出る。
    Issue #53 の日付閾値は失敗側2023年・正解側2022年で分布が重なっており、
    1〜2件の当たり外れで数字が動く領域にある（#51 の距離12は完全な切れ目があったので
    この問題が無かった）。
    """
    _require_population(BASE_QUERY)
    titles, offset = [], start_offset
    while len(titles) < count:
        data = _get({"action": "query", "list": "search", "srsearch": BASE_QUERY,
                     "srlimit": PAGE_SIZE, "sroffset": offset},
                    f"search:{offset}")
        hits = [h["title"] for h in data.get("query", {}).get("search", [])]
        if not hits:
            break
        titles.extend(hits)
        offset += PAGE_SIZE
    return titles[:count]


def volume_field(wikitext):
    """本編インフォボックスの `巻数` フィールドの実値。継続表現の語彙回収に使う。"""
    blocks = _extract_braced_blocks(wikitext, MANGA_INFOBOX_MARKER)
    main = _find_main_manga_block(blocks)
    if main is None:
        return None, {}
    ends = {name: _infobox_field(main, name) for name in END_FIELD_NAMES}
    return _infobox_field(main, "巻数"), ends


LABEL_OBSERVED_ON = date(2026, 7, 29)  # ラベルを付けた日。巻数の日付判定の基準にする


def verify_against_labels():
    """人手ラベル96行に対して、出荷中の判定を当てて検出力と副作用を出す（API不使用）。

    **ラベルは `scripts/m6d4_labels.py` にあり、このスクリプトは読むだけで書かない。**
    調査の出力（`.m6d4_*.json`）とは別物なので、調査を何度再実行してもラベルは動かない。
    """
    # 遅延 import。この関数は Issue #56 で追加されるので、ゲート未導入の時点でも
    # スクリプト自体は（--pilot 等で）動くようにしておく。
    try:
        from comic_checker.wikipedia_client import _has_continuation_evidence
    except ImportError:
        raise SystemExit(
            "_has_continuation_evidence() がありません。--verify は Issue #56 の"
            "ゲート導入後に使えます。"
        )

    print("Issue #53 のラベル96行に対する検証（APIは使わない）")
    print(f"基準日: {LABEL_OBSERVED_ON}（ラベルを付けた日）\n")
    totals = {"det": 0, "fail": 0, "side": 0, "ok": 0}
    for group in (MAIN, HOLDOUT):
        rows = [label for label in LABELS if label.group == group]
        det = fail = side = ok = 0
        for label in rows:
            evidence = _has_continuation_evidence(label.volumes, today=LABEL_OBSERVED_ON)
            if label.label == COMPLETED:      # 実際は完結 ＝ 実装の誤答
                fail += 1
                det += not evidence           # ゲートが発動すれば誤答を潰せる
            else:                             # 実際に連載中 ＝ 実装は正しい
                ok += 1
                side += not evidence          # ゲートが発動すると判定不能に倒れる
        print(f"  {group:8} 検出 {det:2d}/{fail:2d} ({det / fail * 100:5.1f}%)"
              f"   副作用 {side}/{ok} ({side / ok * 100:5.1f}%)")
        totals["det"] += det
        totals["fail"] += fail
        totals["side"] += side
        totals["ok"] += ok
    print(f"  {'合算':8} 検出 {totals['det']:2d}/{totals['fail']:2d}"
          f" ({totals['det'] / totals['fail'] * 100:5.1f}%)"
          f"   副作用 {totals['side']}/{totals['ok']}"
          f" ({totals['side'] / totals['ok'] * 100:5.1f}%)")

    print("\n  副作用（実際は連載中だが判定不能に倒れる行）:")
    for label in LABELS:
        if label.label != COMPLETED and not _has_continuation_evidence(
                label.volumes, today=LABEL_OBSERVED_ON):
            print(f"    {label.title}  {label.volumes!r}")
    print("  取りこぼし（実際は完結だが連載中のまま残る行）:")
    for label in LABELS:
        if label.label == COMPLETED and _has_continuation_evidence(
                label.volumes, today=LABEL_OBSERVED_ON):
            print(f"    {label.title}  {label.volumes!r}")


def main():
    if "--verify" in sys.argv:
        verify_against_labels()
        return
    if "--pilot" in sys.argv:
        count, start, label = PILOT_ARTICLES, 0, "パイロット"
    elif "--holdout" in sys.argv:
        count, start, label = HOLDOUT_ARTICLES, FULL_ARTICLES, "ホールドアウト標本"
    else:
        count, start, label = FULL_ARTICLES, 0, "本調査"
    print(f"Issue #53 (M6-D-4) {label}: 作品記事 {count} 件"
          f"（sroffset {start} から）\n")

    titles = collect_articles(count, start_offset=start)
    print(f"  {len(titles)} 件を取得\n")

    unknown, decided = [], []
    aborted = None
    for index, title in enumerate(titles, 1):
        # --- 進捗報告と打ち切り条件（100記事ごと） ---
        if index > 1 and (index - 1) % PROGRESS_EVERY == 0:
            processed = index - 1
            print(f"  [{processed}/{len(titles)}] 判定不能 {len(unknown)} / "
                  f"人手判定に回る行 {len(decided)} / 429 {_stats['429']}回", flush=True)
            yield_rate = len(decided) / processed
            # 400記事時点で、1800記事でも N が30に届かない見込みなら続けない
            if processed >= 400 and yield_rate * FULL_ARTICLES < 30:
                aborted = (f"400記事時点の歩留まり {yield_rate*100:.2f}% から外挿すると"
                           f" {FULL_ARTICLES} 記事でも N は約 {yield_rate*FULL_ARTICLES:.0f} 行"
                           f"にしかならず、目標の60行どころか30行にも届かない")
                break
            # 想定と逆方向のずれ: 歩留まりが想定(約4%)の倍以上なら、母集団か判定の理解が
            # 誤っている可能性がある。**累計件数ではなく率で見ること。** 累計で見ると調査が
            # 進むだけで必ず閾値を超え、正常な進行を異常として打ち切ってしまう
            # （実際に一度そうなった: 1,301記事・55行＝率4.2%の正常な進行を打ち切った）。
            if processed >= 500 and yield_rate > 0.10:
                aborted = (f"歩留まりが {yield_rate*100:.1f}% と想定(約4%)の倍以上ある。"
                           f"母集団か判定の理解が誤っている可能性がある")
                break
        if _stats["429"]:
            aborted = f"HTTP 429 が {_stats['429']} 回発生した"
            break

        extract = _cached(f"extract:{title}",
                          lambda t=title: (_fetch_extract(t) or (None, "", None))[1])
        if not extract:
            continue
        status, _evidence = _judge_extract(extract)
        if status != STATUS_UNKNOWN:
            continue
        unknown.append(title)
        wikitext = _cached(f"wikitext:{title}",
                           lambda t=title: _fetch_wikitext(t) or "")
        if not wikitext:
            continue
        infobox_status, infobox_evidence = _judge_via_infobox(wikitext)
        if infobox_status != "連載中":
            continue
        volumes, ends = volume_field(wikitext)
        decided.append({
            "title": title,
            "volumes": volumes,
            "ends": ends,
            "evidence": infobox_evidence,
            # 案Aで救えるか: 地の文に完結を述べる文があるか（veto されて判定不能になった形）
            "completion_hint": bool(_COMPLETION_HINT_RE.search(extract)),
            "has_ongoing_signal": _has_ongoing_signal(extract),
        })
        print(f"  ★ [{index}] {title!r}  巻数={volumes!r}", flush=True)

    total = index if aborted else len(titles)
    print("\n" + "=" * 72)
    if aborted:
        print(f"⚠ 打ち切りました: {aborted}")
        print(f"  処理した記事: {total} / {len(titles)}")
    print(f"取得記事                         : {total}")
    print(f"地の文が判定不能                 : {len(unknown)} "
          f"({len(unknown)/max(1,total)*100:.1f}%)")
    print(f"うちインフォボックスが連載中     : {len(decided)} "
          f"({len(decided)/max(1,total)*100:.1f}%)  ← 人手判定に回る行")
    print(f"リクエスト {_stats['requests']} 回 / 429 {_stats['429']} 回")
    print("=" * 72)

    if decided:
        print("\n--- 人手判定に回る行（実際に完結しているかの2択） ---")
        for row in decided:
            print(f"  {row['title']!r}")
            print(f"      巻数 = {row['volumes']!r}")
            print(f"      終了系 = {row['ends']}")
            print(f"      地の文に完結の記述あり = {row['completion_hint']}"
                  f" / 連載シグナルあり = {row['has_ongoing_signal']}")

    out = ".m6d4_holdout.json" if "--holdout" in sys.argv else ".m6d4_result.json"
    json.dump({"titles": titles, "unknown": unknown, "decided": decided},
              open(os.path.join(os.path.dirname(CACHE_PATH), out), "w", encoding="utf-8"),
              ensure_ascii=False)


if __name__ == "__main__":
    main()
