"""BOOK☆WALKER の検索結果ページから、作品の「完結」の札を読む。

Wikipedia で「記事なし」になった行だけで使う（`main._judge_row`）。事前登録つきの測定
（`docs/bookwalker_measurement_2026-10/`）では、利用者の実際の一覧73行で、記事なしの
行のうち BOOK☆WALKER で決められた行の答えを足すと、正答が 38 → 58 に増え、誤答が
1 → 4 に増えた（増えた3件はすべて「完結の札が付いていない完結作品」＝偽連載中。
偽完結は増えなかった）。事前登録の採用の基準（誤答が増えないこと）は満たさなかったが、
正答が増えることを重く見て、ユーザの判断で採用した。結果は同じディレクトリの result.md。

## 読み方

検索 `https://bookwalker.jp/search/?word=<題>` の結果ページのうち、本来の検索結果
（`t-main-column` 直下の最初の `o-contents-section`）だけを読む。同じページの
「検索キーワードに関連がある作品」の欄（`p-related-search-shelf`）は読まない。
1項目は `m-book-item`。題は `m-book-item__title`、マンガの札は `a-tag-comic`、
完結の札は `a-tag-comp`。HTML は標準ライブラリの `html.parser` だけで読む
（軽量ビルドの EXE に新しい依存を入れないため）。

題は末尾のレーベル名のかっこ（「（マガジンポケット）」など）を1つ外して NFKC で比べる。
ただし、かっこの中に版の名前（新装版・完全版など）があるときは外さない（別の版の
シリーズに一致させないため。PR #572 の review の指摘）。

## 答え方

- 1件だけ一致して完結の札がある → 完結
- 1件だけ一致して完結の札が無い → 連載中
- 一致が0件 → 一致なし、2件以上 → 複数一致、通信の失敗 → エラー

一致なし・複数一致・エラーのとき、呼び出し側は Wikipedia の答え（記事なし）のままにする。

## 既知の性質（測定で分かったこと）

- 完結した作品でも、完結の札が付いていないことがある（測定では3件。偽連載中になる）。
- 最終巻が予約の段階で、完結の札が付くことがある（測定では1件。発売前の偽完結になりうる）。
"""
import re
import time
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser

import requests

from comic_checker.wikipedia_client import (
    USER_AGENT,
    _strip_annotations,
    _strip_trailing_note,
    _title_variants,
)

SOURCE = "BOOK☆WALKER"
SEARCH_URL = "https://bookwalker.jp/search/"

# 1回の問い合わせごとに、問い合わせの前に待つ秒数。測定（事前登録）と同じ値。
REQUEST_INTERVAL_SECONDS = 3.0
RETRY_BACKOFF_SECONDS = 5.0
MAX_ATTEMPTS = 6
MAX_RETRY_AFTER_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 30

STATUS_COMPLETED = "完結"
STATUS_ONGOING = "連載中"
STATUS_NO_MATCH = "一致なし"
STATUS_MULTIPLE = "複数一致"
STATUS_ERROR = "エラー"
DECIDED_STATUSES = (STATUS_COMPLETED, STATUS_ONGOING)

# 末尾のかっこの中にこれらの語があれば、レーベル名ではなく版の名前とみなして外さない。
EDITION_WORDS = (
    "新装版", "完全版", "愛蔵版", "特装版", "限定版", "分冊版", "単話版", "合本版",
    "カラー版", "文庫版", "電子版", "総集編",
)

_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "source", "track", "wbr",
}
_LAST_BRACKET_RE = re.compile(r"[（(]([^（()）]*)[）)]\s*$")
_SERIES_COUNT_RE = re.compile(r"シリーズ\s*([0-9,]+)\s*冊")


@dataclass
class BookwalkerResult:
    status: str
    matched_title: str = ""
    url: str = ""
    evidence: str = ""


class _SearchResultParser(HTMLParser):
    """検索結果ページの本来の結果だけを [{"name", "url", "comic", "complete", "text"}] で集める。"""

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
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
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
            self._current = {"name": "", "url": "", "comic": False, "complete": False, "text": ""}
            return
        if self._current is None:
            return
        if "a-tag-comic" in classes:
            self._current["comic"] = True
        if "a-tag-comp" in classes:
            self._current["complete"] = True
        if "m-book-item__title" in classes:
            self._title_depth = depth
        if tag == "a" and self._title_depth is not None and not self._current["url"]:
            self._current["url"] = attributes.get("href") or ""

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
        if self._current is None:
            return
        self._current["text"] += data
        if self._title_depth is not None:
            self._current["name"] += data


def parse_results(html):
    """本来の検索結果の項目を返す（関連作品の欄は含めない）。"""
    parser = _SearchResultParser()
    parser.feed(html)
    parser.close()
    return parser.items


def series_title(name):
    """末尾のレーベル名のかっこを1つ外す。版の名前のかっこは外さない。"""
    match = _LAST_BRACKET_RE.search(name)
    if match is None:
        return name.strip()
    if any(word in match.group(1) for word in EDITION_WORDS):
        return name.strip()
    return name[: match.start()].strip()


def _normalize(text):
    return unicodedata.normalize("NFKC", text).strip()


def match_items(items, variants):
    """変種を確信度の高い順に試し、マンガで題が一致した項目を返す。

    最初に1件以上一致した変種の結果だけを使う（後ろの変種で一致を増やさない）。
    """
    for variant in variants:
        hits = [
            item for item in items
            if item["comic"] and _normalize(series_title(item["name"])) == _normalize(variant)
        ]
        if hits:
            return hits
    return []


def search_queries(title):
    """検索に使う文字列（多くて2つ）。注記を外したもの、次に後置注記も外したもの。"""
    first = _strip_annotations(title)
    queries = [first]
    second = _strip_trailing_note(first)
    if second and second != first:
        queries.append(second)
    return queries


def _evidence(item):
    tag = "完結の札あり" if item["complete"] else "完結の札なし"
    match = _SERIES_COUNT_RE.search(item["text"])
    if match:
        return f"{tag}（シリーズ{match.group(1)}冊）"
    return tag


def _retry_wait(response, attempt):
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        seconds = RETRY_BACKOFF_SECONDS * (attempt + 1)
    return min(max(seconds, RETRY_BACKOFF_SECONDS), MAX_RETRY_AFTER_SECONDS)


def fetch_search_page(query):
    """検索結果の HTML を返す。

    失敗したら RuntimeError を投げる。文面は例外の種類名か HTTP の状態コードだけにする
    （URL には入力の題が入るので、文面に出さない）。
    """
    for attempt in range(MAX_ATTEMPTS):
        time.sleep(REQUEST_INTERVAL_SECONDS)
        try:
            response = requests.get(
                SEARCH_URL,
                params={"word": query},
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT_SECONDS,
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


def lookup(title, fetch=None):
    """BOOK☆WALKER で題を検索し、BookwalkerResult を返す。"""
    if fetch is None:
        fetch = fetch_search_page
    variants = _title_variants(title)
    for query in search_queries(title):
        try:
            html = fetch(query)
        except RuntimeError as exc:
            return BookwalkerResult(STATUS_ERROR, evidence=f"取得できませんでした（{exc}）")
        hits = match_items(parse_results(html), variants)
        if len(hits) > 1:
            return BookwalkerResult(STATUS_MULTIPLE)
        if len(hits) == 1:
            item = hits[0]
            status = STATUS_COMPLETED if item["complete"] else STATUS_ONGOING
            return BookwalkerResult(status, item["name"], item["url"], _evidence(item))
    return BookwalkerResult(STATUS_NO_MATCH)
