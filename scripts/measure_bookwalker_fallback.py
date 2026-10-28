"""BOOK☆WALKER を情報源に足すと判定がどう変わるかを測る（事前登録つきの測定）。

事前登録は docs/bookwalker_measurement_2026-10/preregistration.json。

Wikipedia の judge() と BOOK☆WALKER の検索結果を、利用者の実際の一覧の全行で取り、
次の3つのやり方を、事前に凍結した正解ラベルと比べる。

    W  : 今のまま（Wikipedia だけ）
    ①  : Wikipedia が「記事なし」の行だけ BOOK☆WALKER を見る
    ③  : BOOK☆WALKER を先に見て、一致なし・複数一致・エラーの行だけ Wikipedia を見る

一覧と正解ラベルは実在の作品名を含むので、リポジトリの外に置く。このスクリプトは
作品名を画面に出さない（番号と数だけ）。行ごとの詳細は --out の下に書く。

BOOK☆WALKER の読み取り（parse_results 以下）は、実装（comic_checker/ 側）の前の試作である。
実装はこの読み取りと同じ結果を返すことを、実装の Issue で確かめる。

実ネットワーク呼び出しを伴う一回限りの測定スクリプトのため、pytest の対象にはしていない。

使い方:
    .venv/bin/python scripts/measure_bookwalker_fallback.py <一覧> <正解ラベル> <出力先のディレクトリ>
        一覧: 1行に「番号|一覧の文字列」
        正解ラベル: 1行に「番号|ラベル」（ラベルは 完結・連載中・判定不能）
"""
import json
import os
import re
import sys
import time
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from comic_checker.wikipedia_client import (  # noqa: E402
    STATUS_NOT_FOUND,
    STATUS_UNKNOWN,
    _strip_annotations,
    _strip_trailing_note,
    _title_variants,
    judge,
)

# wikipedia_client は「完結」「連載中」を定数にしていない（_judge_extract が文字列で返す）。
STATUS_COMPLETED = "完結"
STATUS_ONGOING = "連載中"
STATUS_NO_ARTICLE = STATUS_NOT_FOUND

SEARCH_URL = "https://bookwalker.jp/search/"
HEADERS = {
    "User-Agent": (
        "comic-checker/0.1 "
        "(https://github.com/giant-shrimp/comic_checker; contact via repo issues)"
    )
}
WAIT_SECONDS = 3.0
RETRY_BACKOFF_SECONDS = 5.0
MAX_ATTEMPTS = 6
MAX_RETRY_AFTER = 60.0

BW_COMPLETED = "完結"
BW_ONGOING = "連載中"
BW_NO_MATCH = "一致なし"
BW_MULTIPLE = "複数一致"
BW_ERROR = "エラー"
BW_DECIDED = (BW_COMPLETED, BW_ONGOING)

LABELS = (STATUS_COMPLETED, STATUS_ONGOING, STATUS_UNKNOWN)

_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "source", "track", "wbr",
}
_LABEL_SUFFIX_RE = re.compile(r"[（(][^（()）]*[）)]\s*$")


# ---------------------------------------------------------------- BOOK☆WALKER の読み取り


class _SearchResultParser(HTMLParser):
    """検索結果ページの本来の結果（t-main-column 直下の最初の o-contents-section）だけを読む。

    「検索キーワードに関連がある作品」の欄（p-related-search-shelf）は読まない。
    1項目は m-book-item。題は m-book-item__title、マンガの札は a-tag-comic、完結の札は a-tag-comp。
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack = []
        self._main_depth = None
        self._main_done = False
        self._item_depth = None
        self._title_depth = None
        self._current = None
        self.items = []

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            return
        classes = set((dict(attrs).get("class") or "").split())
        parent = self._stack[-1] if self._stack else set()
        self._stack.append(classes)
        depth = len(self._stack)
        if (
            not self._main_done
            and self._main_depth is None
            and tag == "section"
            and "o-contents-section" in classes
            and "t-main-column" in parent
        ):
            self._main_depth = depth
            return
        if self._main_depth is None:
            return
        if self._item_depth is None and "m-book-item" in classes:
            self._item_depth = depth
            self._current = {"name": "", "comic": False, "complete": False}
            return
        if self._current is None:
            return
        if "a-tag-comic" in classes:
            self._current["comic"] = True
        if "a-tag-comp" in classes:
            self._current["complete"] = True
        if "m-book-item__title" in classes:
            self._title_depth = depth

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS or not self._stack:
            return
        depth = len(self._stack)
        if self._title_depth == depth:
            self._title_depth = None
        if self._item_depth == depth:
            self._current["name"] = self._current["name"].strip()
            self.items.append(self._current)
            self._current = None
            self._item_depth = None
        if self._main_depth == depth:
            self._main_depth = None
            self._main_done = True
        self._stack.pop()

    def handle_data(self, data):
        if self._current is not None and self._title_depth is not None:
            self._current["name"] += data


def parse_results(html):
    """本来の検索結果の項目を [{"name", "comic", "complete"}] で返す。"""
    parser = _SearchResultParser()
    parser.feed(html)
    parser.close()
    return parser.items


def series_title(name):
    """末尾のレーベル名のかっこ（「（マガジンポケット）」など）を1つ外す。"""
    return _LABEL_SUFFIX_RE.sub("", name).strip()


def _norm(text):
    return unicodedata.normalize("NFKC", text).strip()


def match_items(items, variants):
    """変種を確信度の高い順に試し、マンガで題が一致した項目を返す。

    最初に1件以上一致した変種の結果だけを使う（後ろの変種で一致を増やさない）。
    """
    for variant in variants:
        hits = [
            item for item in items
            if item["comic"] and _norm(series_title(item["name"])) == _norm(variant)
        ]
        if hits:
            return hits
    return []


def classify(hits):
    if not hits:
        return BW_NO_MATCH
    if len(hits) > 1:
        return BW_MULTIPLE
    return BW_COMPLETED if hits[0]["complete"] else BW_ONGOING


def bw_queries(title):
    """検索に使う文字列（多くて2つ）。注記を外したもの、次に後置注記も外したもの。"""
    first = _strip_annotations(title)
    queries = [first]
    second = _strip_trailing_note(first)
    if second and second != first:
        queries.append(second)
    return queries


# ---------------------------------------------------------------- 通信


def _retry_wait(response, attempt):
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        seconds = RETRY_BACKOFF_SECONDS * (attempt + 1)
    return min(max(seconds, RETRY_BACKOFF_SECONDS), MAX_RETRY_AFTER)


def fetch_search_page(query):
    """検索結果の HTML を返す。失敗したら例外の種類名だけを持つ RuntimeError。"""
    for attempt in range(MAX_ATTEMPTS):
        time.sleep(WAIT_SECONDS)
        try:
            response = requests.get(
                SEARCH_URL, params={"word": query}, headers=HEADERS, timeout=30
            )
        except requests.RequestException as exc:
            raise RuntimeError(type(exc).__name__) from None
        if response.status_code == 429 and attempt < MAX_ATTEMPTS - 1:
            time.sleep(_retry_wait(response, attempt))
            continue
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        return response.content.decode("utf-8", errors="replace")
    raise RuntimeError("やり直しの上限")


def lookup_bookwalker(title, fetch=fetch_search_page, save=None):
    """(結果, 一致した BOOK☆WALKER の作品名, 使った検索の回数) を返す。"""
    variants = _title_variants(title)
    used = 0
    for index, query in enumerate(bw_queries(title)):
        used += 1
        try:
            html = fetch(query)
        except RuntimeError:
            return BW_ERROR, "", used
        if save is not None:
            save(index, html)
        hits = match_items(parse_results(html), variants)
        if hits:
            return classify(hits), hits[0]["name"] if len(hits) == 1 else "", used
    return BW_NO_MATCH, "", used


# ---------------------------------------------------------------- 3つのやり方と数え方


def combine_w(wiki, bw):
    return wiki


def combine_fallback(wiki, bw):
    """①: 記事なしのときだけ BOOK☆WALKER。決められなければ記事なしのまま。"""
    if wiki == STATUS_NO_ARTICLE and bw in BW_DECIDED:
        return bw
    return wiki


def combine_bw_first(wiki, bw):
    """③: BOOK☆WALKER が決められればそれ。決められなければ Wikipedia。"""
    if bw in BW_DECIDED:
        return bw
    return wiki


CONFIGS = (("W", combine_w), ("①", combine_fallback), ("③", combine_bw_first))

# BOOK☆WALKER の読み取りを作るときに検索結果ページを見た行（事前登録の 1_population.contamination）。
CONTAMINATED_NUMBERS = ("2", "8", "9", "11", "12", "13", "14")


def bucket(label, output):
    """事前登録の分け方（A 正答・D 誤答・E 取りこぼし・F 検証不能）。"""
    if label == STATUS_UNKNOWN:
        return "A" if output == STATUS_UNKNOWN else "F"
    if output == label:
        return "A"
    if output in (STATUS_COMPLETED, STATUS_ONGOING):
        return "D"
    return "E"


def summarize(rows, combine):
    counts = {"A": 0, "D": 0, "E": 0, "F": 0, "偽完結": 0, "偽連載中": 0}
    for row in rows:
        output = combine(row["wiki"], row["bw"])
        b = bucket(row["label"], output)
        counts[b] += 1
        if b == "D" and output == STATUS_COMPLETED:
            counts["偽完結"] += 1
        if b == "D" and output == STATUS_ONGOING:
            counts["偽連載中"] += 1
    return counts


# ---------------------------------------------------------------- 実行


def read_pairs(path):
    pairs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            number, value = line.split("|", 1)
            pairs.append((number.strip(), value.strip()))
    return pairs


def main():
    list_path, labels_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    targets = read_pairs(list_path)
    labels = dict(read_pairs(labels_path))
    if sorted(labels) != sorted(n for n, _ in targets):
        print("一覧と正解ラベルの番号が合いません")
        return 2
    bad = sorted(n for n, v in labels.items() if v not in LABELS)
    if bad:
        print("正解ラベルの値が不正な番号: " + ",".join(bad))
        return 2
    html_dir = os.path.join(out_dir, "html")
    os.makedirs(html_dir, exist_ok=True)

    print(f"行数: {len(targets)}")
    print("番号\t正解\tWikipedia\tBOOK☆WALKER\t検索回数")
    rows = []
    for number, title in targets:
        wiki = judge(title).status

        def save(index, html, number=number):
            path = os.path.join(html_dir, f"{number}_{index + 1}.html")
            with open(path, "w", encoding="utf-8") as out:
                out.write(html)

        bw, bw_name, used = lookup_bookwalker(title, save=save)
        rows.append({
            "number": number, "title": title, "label": labels[number],
            "wiki": wiki, "bw": bw, "bw_name": bw_name, "queries": used,
        })
        print(f"{number}\t{labels[number]}\t{wiki}\t{bw}\t{used}")

    clean = [row for row in rows if row["number"] not in CONTAMINATED_NUMBERS]
    summary = {}
    for set_name, subset in ((f"全{len(rows)}行", rows), (f"汚染を除く{len(clean)}行", clean)):
        print(f"[{set_name}]")
        print("やり方\tA正答\tD誤答\tE取りこぼし\tF検証不能\t偽完結\t偽連載中")
        summary[set_name] = {}
        for name, combine in CONFIGS:
            counts = summarize(subset, combine)
            summary[set_name][name] = counts
            print(
                f"{name}\t{counts['A']}\t{counts['D']}\t{counts['E']}\t{counts['F']}"
                f"\t{counts['偽完結']}\t{counts['偽連載中']}"
            )
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as out:
        json.dump({"rows": rows, "summary": summary}, out, ensure_ascii=False, indent=1)
    print("書き出し: " + os.path.join(out_dir, "result.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
