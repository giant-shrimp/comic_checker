"""BOOK☆WALKER の検索結果ページの読み取りと取得のテスト。作品名・レーベル名はすべて架空。"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from comic_checker import bookwalker_client
from comic_checker.bookwalker_client import (
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_MULTIPLE,
    STATUS_NO_MATCH,
    STATUS_ONGOING,
    lookup,
    parse_results,
    search_queries,
    series_title,
)
from comic_checker.wikipedia_client import USER_AGENT


def item(name, series_id, kind="comic", complete=False, count=3):
    """検索結果の1項目（実際のページと同じクラス名の骨組み）。"""
    kind_label = {"comic": "マンガ", "other": "実用", "LN": "ラノベ"}[kind]
    comp = '<span class="a-tag-comp">完結</span>' if complete else ""
    return f"""
<li class="m-tile">
  <div class="m-book-item">
    <div class="m-book-item__info-block">
      <div class="m-book-item__secondary">
        <div class="m-book-item__tag-box">
          <span class="a-tag-{kind}">{kind_label}</span>
          {comp}
        </div>
        <p class="m-book-item__title">
          <a href="https://bookwalker.jp/series/{series_id}/list/">{name}</a>
        </p>
        <p class="m-book-item__series">シリーズ{count}冊</p>
      </div>
    </div>
  </div>
</li>"""


def page(main_items, related_items=(), side_items=()):
    """本来の検索結果と、「検索キーワードに関連がある作品」の欄を持つページ。

    side_items を渡すと、本来の検索結果より前（横の欄）にも項目の並ぶ欄を置く。
    """
    related = "".join(related_items)
    side = "".join(side_items)
    return f"""<html><body>
<div class="t-wrapper">
  <aside class="t-side-column">
    <ul><li><a href="./?qcpl=1">完結<span class="search-bookNum">(1)</span></a></li></ul>
    <section class="o-contents-section"><ul class="m-tile-list">{side}</ul></section>
  </aside>
  <div class="t-main-column">
    <section class="o-contents-section">
      <div class="o-contents-section__header"><h2>検索結果</h2></div>
      <div class="o-contents-section__body">
        <ul class="m-tile-list">{"".join(main_items)}</ul>
      </div>
    </section>
    <div class="p-related-search-shelf">
      <section class="o-contents-section">
        <div class="o-contents-section__header"><h2>検索キーワードに関連がある作品</h2></div>
        <div class="o-contents-section__body"><ul class="m-tile-list">{related}</ul></div>
      </section>
    </div>
  </div>
</div>
</body></html>"""


def fixed(html, calls=None):
    """常に同じページを返す取得関数。calls を渡すと検索の文字列を記録する。"""

    def fetch(query):
        if calls is not None:
            calls.append(query)
        return html

    return fetch


# ---------------------------------------------------------------- 読み取り


def test_parse_results_reads_only_the_main_results():
    html = page(
        [item("作品A（架空レーベル）", 1, complete=True), item("架空の雑誌", 2, kind="other")],
        related_items=[item("作品B（架空レーベル）", 3, complete=True)],
    )
    items = parse_results(html)
    assert [i["name"] for i in items] == ["作品A（架空レーベル）", "架空の雑誌"]
    assert [i["comic"] for i in items] == [True, False]
    assert [i["complete"] for i in items] == [True, False]
    assert items[0]["url"] == "https://bookwalker.jp/series/1/list/"


def test_sections_outside_the_main_column_are_not_read():
    html = page(
        [item("作品A（架空レーベル）", 4)],
        side_items=[item("作品A（架空レーベル）", 5, complete=True)],
    )
    assert [i["url"] for i in parse_results(html)] == ["https://bookwalker.jp/series/4/list/"]


def test_parse_results_of_a_page_without_results_is_empty():
    assert parse_results("<html><body><p>見つかりませんでした</p></body></html>") == []


@pytest.mark.parametrize(
    "name, expected",
    [
        ("作品A（架空レーベル）", "作品A"),
        ("作品A(架空レーベル)", "作品A"),
        ("作品A", "作品A"),
        ("作品A（新装版）", "作品A（新装版）"),
        ("作品A（新装版）（架空レーベル）", "作品A（新装版）"),
        ("作品A　完全版（架空レーベル）", "作品A　完全版"),
        ("作品A（完全版）", "作品A（完全版）"),
    ],
)
def test_series_title_strips_only_a_label_bracket(name, expected):
    assert series_title(name) == expected


def test_search_queries():
    assert search_queries("作品A") == ["作品A"]
    assert search_queries("作品A　(特装版ない場合通常版)") == ["作品A"]
    assert search_queries("作品A　③～定期") == ["作品A　③～定期", "作品A"]


# ---------------------------------------------------------------- 答え


def test_completed_tag_answers_completed():
    html = page([item("作品A（架空レーベル）", 11, complete=True, count=8)])
    result = lookup("作品A", fetch=fixed(html))
    assert result.status == STATUS_COMPLETED
    assert result.matched_title == "作品A（架空レーベル）"
    assert result.url == "https://bookwalker.jp/series/11/list/"
    assert result.evidence == "完結の札あり（シリーズ8冊）"


def test_no_completed_tag_answers_ongoing():
    html = page([item("作品A（架空レーベル）", 12, count=19)])
    result = lookup("作品A", fetch=fixed(html))
    assert result.status == STATUS_ONGOING
    assert result.evidence == "完結の札なし（シリーズ19冊）"


def test_completed_item_in_the_related_shelf_is_not_used():
    html = page(
        [item("作品A（架空レーベル）", 13)],
        related_items=[item("作品A（架空レーベル）", 14, complete=True)],
    )
    assert lookup("作品A", fetch=fixed(html)).status == STATUS_ONGOING


def test_non_manga_items_are_not_matched():
    html = page([item("作品A", 15, kind="other", complete=True), item("作品A（架空文庫）", 16, kind="LN")])
    assert lookup("作品A", fetch=fixed(html)).status == STATUS_NO_MATCH


def test_width_differences_are_normalized():
    html = page([item("作品ＪＫ（架空レーベル）", 17, complete=True)])
    assert lookup("作品JK", fetch=fixed(html)).status == STATUS_COMPLETED


def test_edition_series_is_not_matched_to_the_plain_title():
    html = page([item("作品A（新装版）", 18, complete=True), item("作品A（架空レーベル）", 19)])
    result = lookup("作品A", fetch=fixed(html))
    assert result.status == STATUS_ONGOING
    assert result.url == "https://bookwalker.jp/series/19/list/"


def test_two_matching_series_answer_multiple():
    html = page([item("作品A（架空レーベル）", 20), item("作品A（別の架空レーベル）", 21, complete=True)])
    assert lookup("作品A", fetch=fixed(html)).status == STATUS_MULTIPLE


def test_annotation_is_removed_from_the_query():
    calls = []
    html = page([item("作品A（架空レーベル）", 22, complete=True)])
    result = lookup("作品A　(特装版ない場合通常版)", fetch=fixed(html, calls))
    assert calls == ["作品A"]
    assert result.status == STATUS_COMPLETED


def test_trailing_note_is_removed_in_the_second_query_only_when_the_first_fails():
    calls = []
    pages = {
        "作品A　③～定期": page([]),
        "作品A": page([item("作品A（架空レーベル）", 23)]),
    }

    def fetch(query):
        calls.append(query)
        return pages[query]

    result = lookup("作品A　③～定期", fetch=fetch)
    assert calls == ["作品A　③～定期", "作品A"]
    assert result.status == STATUS_ONGOING


def test_second_query_is_not_made_after_a_match():
    calls = []
    html = page([item("作品A　副題（架空レーベル）", 24)])
    lookup("作品A　副題", fetch=fixed(html, calls))
    assert calls == ["作品A　副題"]


def test_no_match_after_all_queries():
    calls = []
    assert lookup("作品A　副題", fetch=fixed(page([]), calls)).status == STATUS_NO_MATCH
    assert calls == ["作品A　副題", "作品A"]


def test_fetch_error_answers_error_without_the_title():
    def fetch(query):
        raise RuntimeError("HTTP 403")

    result = lookup("作品A", fetch=fetch)
    assert result.status == STATUS_ERROR
    assert result.evidence == "取得できませんでした（HTTP 403）"
    assert "作品A" not in result.evidence


def test_lookup_uses_the_blocked_fetch_by_default():
    # conftest の _no_bookwalker_network が既定の取得関数を「取得できない」に差し替えている。
    assert lookup("作品A").status == STATUS_ERROR


# ---------------------------------------------------------------- 取得


def response(status_code, text="", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = text.encode("utf-8")
    resp.headers = headers or {}
    return resp


@pytest.mark.bookwalker_fetch
def test_fetch_sends_the_query_and_user_agent():
    with patch("comic_checker.bookwalker_client.requests.get", return_value=response(200, "<html>本文</html>")) as get:
        html = bookwalker_client.fetch_search_page("作品A")
    assert html == "<html>本文</html>"
    assert get.call_args.args == (bookwalker_client.SEARCH_URL,)
    assert get.call_args.kwargs["params"] == {"word": "作品A"}
    assert get.call_args.kwargs["headers"]["User-Agent"] == USER_AGENT
    assert get.call_args.kwargs["timeout"] == 30


@pytest.mark.bookwalker_fetch
def test_fetch_retries_after_429():
    replies = [response(429), response(429), response(200, "ok")]
    with patch("comic_checker.bookwalker_client.requests.get", side_effect=replies) as get:
        assert bookwalker_client.fetch_search_page("作品A") == "ok"
    assert get.call_count == 3


@pytest.mark.bookwalker_fetch
def test_fetch_succeeds_on_the_sixth_attempt():
    replies = [response(429)] * 5 + [response(200, "ok")]
    with patch("comic_checker.bookwalker_client.requests.get", side_effect=replies):
        assert bookwalker_client.fetch_search_page("作品A") == "ok"


@pytest.mark.bookwalker_fetch
def test_fetch_gives_up_after_the_attempt_limit():
    replies = [response(429)] * 6
    with patch("comic_checker.bookwalker_client.requests.get", side_effect=replies):
        with pytest.raises(RuntimeError, match="HTTP 429"):
            bookwalker_client.fetch_search_page("作品A")


@pytest.mark.bookwalker_fetch
def test_fetch_does_not_retry_other_errors():
    with patch("comic_checker.bookwalker_client.requests.get", return_value=response(403)) as get:
        with pytest.raises(RuntimeError, match="HTTP 403"):
            bookwalker_client.fetch_search_page("作品A")
    assert get.call_count == 1


@pytest.mark.bookwalker_fetch
def test_fetch_reports_only_the_exception_type():
    error = requests.ConnectionError("https://bookwalker.jp/search/?word=作品A に接続できません")
    with patch("comic_checker.bookwalker_client.requests.get", side_effect=error):
        with pytest.raises(RuntimeError) as info:
            bookwalker_client.fetch_search_page("作品A")
    assert str(info.value) == "ConnectionError"


@pytest.mark.real_wait_settings
@pytest.mark.bookwalker_fetch
def test_fetch_waits_before_every_request():
    sleeps = []
    replies = [response(429), response(200, "ok")]
    with patch("comic_checker.bookwalker_client.time.sleep", side_effect=sleeps.append):
        with patch("comic_checker.bookwalker_client.requests.get", side_effect=replies):
            bookwalker_client.fetch_search_page("作品A")
    assert sleeps == [3.0, 5.0, 3.0]


@pytest.mark.real_wait_settings
@pytest.mark.bookwalker_fetch
def test_retry_after_is_honored_up_to_a_limit():
    sleeps = []
    replies = [response(429, headers={"Retry-After": "20"}), response(429, headers={"Retry-After": "600"}), response(200, "ok")]
    with patch("comic_checker.bookwalker_client.time.sleep", side_effect=sleeps.append):
        with patch("comic_checker.bookwalker_client.requests.get", side_effect=replies):
            bookwalker_client.fetch_search_page("作品A")
    assert sleeps == [3.0, 20.0, 3.0, 60.0, 3.0]
