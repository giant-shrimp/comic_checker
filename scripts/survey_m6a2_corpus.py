"""Issue #51 (M6-A-2) のコーパス調査。敵対群と正常群を1本で再実行する。

**これは pytest の対象ではない**（実ネットワークI/Oを伴う）。
`scripts/measure_false_negative_rate.py` と同じ扱いで、必要なときに手で走らせる。

    python scripts/survey_m6a2_corpus.py

## 何のためのスクリプトか

`_mentions_as_derivative_work()` の条件B（併合記事の除外）は、この記事選定経路で**唯一
fail-closed に倒れる**判定である。併合宣言の語彙が Wikipedia の編集で当たらなくなると、
併合記事で規則が発動して**誤除外**（正しく答えられていた行が `記事なし` に落ちる）が出る。
実行時に検知する手段は無く、**この調査の再実行が唯一の緩和策**である
（`docs/known_limitations.md` 参照）。

したがって次の場合に走らせること。

- `MERGED_COVERAGE_MARKERS` や `DERIVATIVE_WORK_MARKERS` を削る／変えるとき
- 「以前は解決していたタイトルが `記事なし` を返すようになった」という報告を受けたとき

## 判定ロジックはここに書かない

`wikipedia_client` の関数をそのまま import して呼ぶ。**調査したコードと出荷するコードが
同一でなければ調査の意味が無い**（プロトタイプと本実装の差分が結果を無効化する）。
NFKC の適用漏れ1つで `[55]` の検出可否がひっくり返るので、ここは譲れない。

## 2つの群

- **敵対群**（誤除外の検出・合格基準は誤除外0）: 作品記事150件の被リダイレクトを全件
  入力にする。構成上ほぼ全件がゲート開になるので、規則が発動しうる母集団だけを効率よく
  集められる。
- **正常群**（副作用の把握・合格基準は誤除外0）: 規則の文条件が成立しうる作品記事200件
  について、(i) 記事名そのもの と (ii) 記事名＋実運用で観測された入力ノイズ を入力にする。
  **(ii) が要**で、これが「ゲートは開くが正常系」という最も危険な形を作る唯一の手段。
  **敵対群と重複させない**（重複させると副作用の検出という目的を果たせない。実際、最初の
  測定では200件中131件が重複した。`ERRORS.md` 参照）。

## 所要（2026-07-29 実測）

API 呼び出し 約370回・1秒間隔で**20〜25分**。取得結果はディスクにキャッシュするので、
中断して再実行しても取り直しにはならない。
"""
import json
import os
import random
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from comic_checker.wikipedia_client import (
    DERIVATIVE_WORK_MARKERS,
    _api_get,
    _fetch_extract,
    _lands_on_a_different_work,
)

# --- 母集団の定義。第三者が同じ集合を再現できるよう、ここに固定する -------------------
BASE_QUERY = 'hastemplate:"Infobox animanga/Manga"'
ADVERSARIAL_ARTICLES = 150
NORMAL_ARTICLES = 200
PAGE_SIZE = 50
SAMPLE_SIZE = 30
SAMPLE_SEED = 20260728  # 取りこぼし率の推定に使う無作為抽出のシード。変えないこと
# Issue #40: リクエスト間隔と429時のバックオフは `wikipedia_client._api_get` が
# 持つようになったので、ここでは持たない。**キャッシュヒット時は `_api_get` を
# 呼ばないので待機も発生しない** ―― この性質が崩れると再実行が実用不能になる。
MAX_NORMAL_OFFSET = 3000

# 入力ノイズは**実運用 Excel（#47 拡張群72行）で観測された文字列のみ**。創作しない。
# セパレータ（全角空白等）まで原文どおりに再現する。
OBSERVED_INPUT_NOISES = (
    "(特装版がない場合通常版）",           # [5] わたしの幸せな結婚
    "　ＴＨＥ　ＣＯＭＩＣ",        # [8] 姫騎士がクラスメート！
    "　(特装版ない場合通常版)",        # [28] カッコウの許嫁
    "　青版",                          # [52] 月曜日のたわわ
    " （特装版ない場合通常版）",           # [65] 僕の心のヤバイやつ
    "　③～定期",                      # [7] 終わりのハテミは繁殖したい
    "（電子版のみ【最終巻】5巻が発売済）",  # [71] 触手魔術師の成り上がり
)

# 2026-07-29 に記録した敵対群の発動13件。再実行時にここからの増減を検出するために置く。
# **増えた行は誤除外の候補**なので、(a)/(b)/(c) を人手で判定すること。判定基準は Issue #51。
RECORDED_ADVERSARIAL_HITS = {
    ("地獄先生ぬ〜べ〜NEO", "地獄先生ぬ〜べ〜"),
    ("地獄先生ぬ〜べ〜怪", "地獄先生ぬ〜べ〜"),
    ("砂鼠ショーン", "機動戦士ガンダム サンダーボルト"),
    ("機動戦士ガンダム サンダーボルト 外伝", "機動戦士ガンダム サンダーボルト"),
    ("FAIRY TAIL 100 YEARS QUEST", "FAIRY TAIL"),
    ("咲-Saki-阿知賀編 episode of side-A", "咲-Saki-"),
    ("シノハユ the dawn of age", "咲-Saki-"),
    ("新・ど根性ガエル", "ど根性ガエル"),
    ("カラブリ!", "BLEACH"),
    ("蒼穹のファフナー BEHIND THE LINE", "蒼穹のファフナー"),
    ("ガールズ&パンツァー 最終章", "ガールズ&パンツァー"),
    ("ちはやふる plus きみがため", "ちはやふる"),
    ("デュラララ!!SH", "デュラララ!!"),
}
RECORDED_NORMAL_HITS = 0  # 正常群は (i)(ii) とも発動0件だった

CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".m6a2_corpus_cache.json",
)

_cache = {}
if os.path.exists(CACHE_PATH):
    with open(CACHE_PATH, encoding="utf-8") as fh:
        _cache = json.load(fh)

_stats = {"requests": 0, "429": 0}


def _normalized(text):
    return unicodedata.normalize("NFKC", text).strip()


def _save_cache():
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(_cache, fh, ensure_ascii=False)


def _get(params, cache_key):
    """APIを叩いて結果をディスクにキャッシュする。

    **リクエスト間隔と429時のバックオフは `wikipedia_client._api_get` が持つ**（Issue #40）。
    ここで待つと二重待ちになる。**キャッシュヒット時は `_api_get` を呼ばないので待機も
    発生しない** ―― この性質が崩れると、キャッシュがあるのに再実行が数十分かかることになり、
    調査が実用不能になる。
    """
    if cache_key in _cache:
        return _cache[cache_key]
    _stats["requests"] += 1
    try:
        data = _api_get(params)
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            _stats["429"] += 1
        raise
    _cache[cache_key] = data
    _save_cache()
    return data


def _extract_of(title):
    key = f"extract:{title}"
    if key not in _cache:
        _stats["requests"] += 1
        article = _fetch_extract(title)
        _cache[key] = article[1] if article else ""
        _save_cache()
    return _cache[key]


def _total_hits(query):
    """母集団の件数を先に確認する。

    ERRORS.md の教訓をコードで守らせるための関門である。CirrusSearch の `insource:` は
    書き方次第で**エラーにならず静かに0件**を返す（`insource:"『"` のような単一のCJK括弧、
    括弧つきの `(insource:"A" OR insource:"B")`）。0件のまま走り切ると「発動0件」という
    *合格に見える*出力が出てしまい、実際に一度そうなった。
    """
    data = _get({"action": "query", "list": "search", "srsearch": query,
                 "srlimit": 1, "srinfo": "totalhits"}, f"totalhits:{query}")
    return data.get("query", {}).get("searchinfo", {}).get("totalhits", 0)


def _require_population(query):
    hits = _total_hits(query)
    print(f"  母集団 {hits:>7,} 件  {query}")
    if not hits:
        raise SystemExit(
            f"母集団が0件です。クエリの書き方を疑ってください（ERRORS.md 参照）: {query}"
        )
    return hits


def _search_titles(query, offset):
    data = _get({"action": "query", "list": "search", "srsearch": query,
                 "srlimit": PAGE_SIZE, "sroffset": offset},
                f"search:{query}:{offset}")
    return [hit["title"] for hit in data.get("query", {}).get("search", [])]


def collect_adversarial_articles():
    """作品記事150件。`BASE_QUERY` の関連度順の先頭から取る。"""
    _require_population(BASE_QUERY)
    titles, offset = [], 0
    while len(titles) < ADVERSARIAL_ARTICLES:
        hits = _search_titles(BASE_QUERY, offset)
        if not hits:
            break
        titles.extend(hits)
        offset += PAGE_SIZE
    return titles[:ADVERSARIAL_ARTICLES]


def collect_normal_articles(exclude):
    """作品記事200件。規則の文条件が成立しうる記事から、敵対群を除外して取る。

    マーカーごとに個別クエリを投げて和集合を取るのは CirrusSearch の制約による
    （`(insource:"A" OR insource:"B")` は0件になる。ERRORS.md 参照）。
    """
    queries = [f'{BASE_QUERY} insource:"{marker}"' for marker in DERIVATIVE_WORK_MARKERS]
    for query in queries:
        _require_population(query)

    titles, seen, offset = [], set(), 0
    while len(titles) < NORMAL_ARTICLES and offset < MAX_NORMAL_OFFSET:
        added = False
        for query in queries:
            if len(titles) >= NORMAL_ARTICLES:
                break
            for title in _search_titles(query, offset):
                added = True
                if title in seen or title in exclude:
                    continue
                seen.add(title)
                titles.append(title)
        if not added:
            break
        offset += PAGE_SIZE
    return titles[:NORMAL_ARTICLES]


def run_adversarial(titles):
    """被リダイレクト元を入力として与え、規則が発動する行を集める。

    除外基準は**実行前に確定してある**（結果を見てから母集団を動かすと、誤除外0の主張が
    弱くなるため）。除外するのは機械判定できるものだけ:
      - タイトルに `/` を含むサブページ（`ONE PIECE/log` 型）
      - 記事名前空間(ns=0)以外
    キャラクター名など人手判断が要るものは**除外しない**。期待値が定義できない行 (c) は
    集計時に別掲する。
    """
    redirects = {}
    for start in range(0, len(titles), PAGE_SIZE):
        chunk = titles[start:start + PAGE_SIZE]
        data = _get({"action": "query", "titles": "|".join(chunk),
                     "prop": "redirects", "rdlimit": "max", "rdnamespace": "*"},
                    f"redirects:{start}")
        for page in data.get("query", {}).get("pages", {}).values():
            redirects[page["title"]] = [
                (r["title"], r.get("ns", 0)) for r in page.get("redirects", [])
            ]

    rows, excluded = [], []
    for title in titles:
        sources = redirects.get(title, [])
        if not sources:
            continue
        extract = _extract_of(title)
        for source, namespace in sources:
            if namespace != 0:
                excluded.append((source, "記事名前空間外"))
                continue
            if "/" in source:
                excluded.append((source, "サブページ"))
                continue
            rows.append({
                "source": source,
                "target": title,
                "fires": bool(extract) and _lands_on_a_different_work(
                    title, extract, source),
            })
    return rows, excluded, sum(len(v) for v in redirects.values())


def run_normal(titles):
    """(i) 記事名そのもの と (ii) 記事名＋入力ノイズ の2形で評価する。"""
    rows = []
    for index, title in enumerate(titles, 1):
        extract = _extract_of(title)
        if not extract:
            continue
        noise = OBSERVED_INPUT_NOISES[index % len(OBSERVED_INPUT_NOISES)]
        for form, value in (("(i)", title), ("(ii)", title + noise)):
            rows.append({
                "form": form,
                "input": value,
                "target": title,
                "fires": _lands_on_a_different_work(title, extract, value),
            })
    return rows


def main():
    print("Issue #51 (M6-A-2) コーパス調査")
    print(f"採用語彙: {DERIVATIVE_WORK_MARKERS}\n")

    print("== 敵対群: 母集団の確認 ==")
    adversarial_titles = collect_adversarial_articles()
    print(f"  作品記事 {len(adversarial_titles)} 件を取得\n")

    print("== 敵対群: 評価 ==", flush=True)
    rows, excluded, total_redirects = run_adversarial(adversarial_titles)
    fired = [r for r in rows if r["fires"]]
    print(f"  被リダイレクト（除外前） {total_redirects} 件")
    print(f"  除外 {len(excluded)} 件 / 評価対象 {len(rows)} 件")
    print(f"  発動 {len(fired)} 件")

    observed = {(r["source"], r["target"]) for r in fired}
    added = sorted(observed - RECORDED_ADVERSARIAL_HITS)
    removed = sorted(RECORDED_ADVERSARIAL_HITS - observed)
    if added or removed:
        print("\n  ⚠ 2026-07-29 の記録と差がある")
        print("     記事は編集されるので、件数が動くこと自体は異常ではない。"
              "**件数ではなく下の行の中身を見ること。**")
        print("     切り分け: 増えた行に Issue #51 の基準で (a)/(b)/(c) を付ける。"
              "(a) が1件でもあれば規則の劣化、")
        print("     (b)/(c) だけなら記事が変わって新しい派生作品が書かれただけで"
              "対応不要。減った行は取りこぼしなので安全側。")
        for source, target in added:
            print(f"    ＋ {source!r} -> {target!r}  ← **人手判定が要る**")
        for source, target in removed:
            print(f"    − {source!r} -> {target!r}  ← 検出しなくなった（取りこぼし・安全側）")
    else:
        print("  ✓ 2026-07-29 の記録と一致（発動13件）")

    not_fired = [r for r in rows if not r["fires"]]
    sample = random.Random(SAMPLE_SEED).sample(
        not_fired, min(SAMPLE_SIZE, len(not_fired)))
    print(f"\n  取りこぼし率推定用の無作為サンプル {len(sample)} 件"
          f"（シード {SAMPLE_SEED}）")

    print("\n== 正常群: 母集団の確認 ==")
    normal_titles = collect_normal_articles(exclude=set(adversarial_titles))
    overlap = [t for t in normal_titles if t in set(adversarial_titles)]
    print(f"  作品記事 {len(normal_titles)} 件を取得 / 敵対群との重複 {len(overlap)} 件\n")

    print("== 正常群: 評価 ==", flush=True)
    normal_rows = run_normal(normal_titles)
    for form in ("(i)", "(ii)"):
        subset = [r for r in normal_rows if r["form"] == form]
        hits = [r for r in subset if r["fires"]]
        print(f"  {form} 入力 {len(subset)} 件 / 発動 {len(hits)} 件")
        for row in hits:
            print(f"    ★ {row['input']!r} -> {row['target']!r}  ← **人手判定が要る**")

    normal_fired = sum(1 for r in normal_rows if r["fires"])
    if normal_fired == RECORDED_NORMAL_HITS:
        print(f"  ✓ 2026-07-29 の記録と一致（発動{RECORDED_NORMAL_HITS}件）")
    else:
        print(f"  ⚠ 記録は発動{RECORDED_NORMAL_HITS}件だが今回は{normal_fired}件")

    print(f"\nリクエスト {_stats['requests']} 回 / 429 {_stats['429']} 回")
    print(f"キャッシュ: {CACHE_PATH}")

    if added or normal_fired != RECORDED_NORMAL_HITS:
        raise SystemExit(
            "\n記録との差を検出しました。**記事が編集されただけの可能性が高い**ので、"
            "件数の変化を即座に不具合と読まないこと。"
            "\n増えた発動行に Issue #51 の (a)/(b)/(c) 判定基準で人手ラベルを付け、"
            "\n  - (a) が1件でもあれば → 規則の劣化。語彙・条件を見直す"
            "\n  - (b)/(c) だけなら   → 記事側の変化。RECORDED_ADVERSARIAL_HITS を"
            " 更新し、観測日を書き換える"
        )


if __name__ == "__main__":
    main()
