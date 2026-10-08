"""rakuten_books_client のテスト。ネットワークには出ない（requests をモンキーパッチする）。

応答のJSONに使う作品名はすべて架空のもの。
"""
from datetime import date

import pytest
import requests

from comic_checker import rakuten_books_client as rbc
from comic_checker.rakuten_books_client import find_next_release

TODAY = date(2026, 10, 8)
TITLE = "空飛ぶ茶碗の冒険"
APP_ID = "test-app-id-0001"
ACCESS_KEY = "test-access-key-0002"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=False):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._payload


class FakeTime:
    """モジュールの time だけを差し替える（プロセス全域の time.sleep には触れない）。"""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def _env_and_time(monkeypatch):
    monkeypatch.setenv(rbc.APP_ID_ENV, APP_ID)
    monkeypatch.setenv(rbc.ACCESS_KEY_ENV, ACCESS_KEY)
    fake_time = FakeTime()
    monkeypatch.setattr(rbc, "time", fake_time)
    monkeypatch.setattr(rbc, "_last_call_time", None)
    return fake_time


def book(name, sales="2026年05月01日", availability="1", author="作者甲", url=None):
    return {
        "title": name,
        "author": author,
        "salesDate": sales,
        "availability": availability,
        "itemUrl": url or f"https://example.invalid/item/{abs(hash(name)) % 10000}",
    }


def serve(monkeypatch, items=None, response=None, calls=None):
    """requests.get を差し替える。呼び出しの引数は calls に積む。"""

    def fake_get(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        if isinstance(response, Exception):
            raise response
        if response is not None:
            return response
        return FakeResponse(payload={"Items": [{"Item": i} for i in items]})

    monkeypatch.setattr(rbc.requests, "get", fake_get)


def run(monkeypatch, items, title=TITLE):
    serve(monkeypatch, items)
    return find_next_release(title, today=TODAY)


def test_next_volume_available(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2"),
        book(f"{TITLE} 3", url="https://example.invalid/v3"),
        book(f"{TITLE} 4", sales="2026年12月05日", availability="5", url="https://example.invalid/v4"),
        book(f"{TITLE} 5", sales="2027年03月05日", availability="5"),
    ])
    assert info.status == "次巻あり"
    assert info.query == TITLE
    assert info.next_title == f"{TITLE} 4"
    assert info.next_sales_date == "2026年12月05日"
    assert info.next_has_special_edition is False
    assert info.latest_title == f"{TITLE} 3"
    assert info.latest_sales_date == "2026年05月01日"
    assert info.url == "https://example.invalid/v4"


def test_undecided_when_only_released_volumes(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2", url="https://example.invalid/v2"),
    ])
    assert info.status == "未定"
    assert info.next_title == ""
    assert info.next_sales_date == ""
    assert info.latest_title == f"{TITLE} 2"
    assert info.url == "https://example.invalid/v2"


@pytest.mark.parametrize("rest, expected", [
    ("12", 12), ("(12)", 12), ("12巻", 12), ("第12巻", 12), ("第 12 巻", 12), ("（12）", 12),
])
def test_volume_notations(monkeypatch, rest, expected):
    info = run(monkeypatch, [
        book(f"{TITLE} 11"),
        book(f"{TITLE} {rest}", sales="2026年12月05日", availability="5"),
    ])
    assert info.status == "次巻あり"
    assert info.next_title == f"{TITLE} {rest}"


def test_smallest_upcoming_volume_is_next(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 6", sales="2027年04月01日", availability="5"),
        book(f"{TITLE} 5", sales="2027年01月01日", availability="5"),
        book(f"{TITLE} 4"),
    ])
    assert info.next_title == f"{TITLE} 5"


def test_special_edition_with_regular(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 3"),
        book(f"{TITLE} 4", sales="2026年12月05日", availability="5"),
        book(f"{TITLE} 4 特装版", sales="2026年12月05日", availability="5"),
    ])
    assert info.status == "次巻あり"
    assert info.next_title == f"{TITLE} 4"
    assert info.next_has_special_edition is True


def test_special_edition_only(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 3"),
        book(f"{TITLE} 4 限定版", sales="2026年12月05日", availability="5"),
    ])
    assert info.status == "次巻あり"
    assert info.next_title == f"{TITLE} 4 限定版"
    assert info.next_has_special_edition is True


def test_special_edition_in_brackets_is_not_unexpected(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 3"),
        book(f"{TITLE} 4", sales="2026年12月05日", availability="5"),
        book(f"{TITLE}（4）【同梱版】", sales="2026年12月05日", availability="5"),
    ])
    assert info.status == "次巻あり"
    assert info.next_has_special_edition is True


def test_related_books_and_other_works_are_excluded(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 3"),
        book(f"{TITLE} 公式ガイド", sales="2026年12月01日", availability="5"),
        book(f"{TITLE} 画集 1", sales="2026年12月01日", availability="5"),
        book(f"{TITLE} 5 ファンブック", sales="2026年12月01日", availability="5"),
        book(f"{TITLE} 小説版 2", sales="2026年12月01日", availability="5"),
        book(f"{TITLE} 4 アンソロジー", sales="2026年12月01日", availability="5"),
        book(f"{TITLE}外伝 7", sales="2026年12月01日", availability="5"),
        book(f"{TITLE}の裏側 8", sales="2026年12月01日", availability="5"),
        book("別の作品 9", sales="2026年12月01日", availability="5"),
    ])
    assert info.status == "未定"
    assert info.latest_title == f"{TITLE} 3"


def test_no_hit_when_zero_results(monkeypatch):
    assert run(monkeypatch, []).status == "ヒットなし"


def test_no_hit_when_nothing_remains_after_exclusion(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 公式ガイド"),
        book(f"{TITLE}外伝 1"),
        book("全く別の作品 1"),
    ])
    assert info.status == "ヒットなし"
    assert info.latest_title == ""
    assert info.url == ""


def test_missing_items_key_is_no_hit(monkeypatch):
    serve(monkeypatch, response=FakeResponse(payload={"count": 0}))
    assert find_next_release(TITLE, today=TODAY).status == "ヒットなし"


def test_unexpected_note_on_upcoming_volume_needs_check(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2"),
        book(f"{TITLE} 3 記念キャンペーン付き", sales="2026年12月05日", availability="5"),
    ])
    assert info.status == "要確認"
    assert info.next_title == ""
    assert info.next_sales_date == ""
    assert info.latest_title == ""
    assert info.url == ""


def test_unexpected_note_on_undecidable_volume_needs_check(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2 おまけ付き", sales="", availability=""),
    ])
    assert info.status == "要確認"


def test_unexpected_note_on_volume_beyond_latest_needs_check(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2"),
        book(f"{TITLE} 3 おまけ付き"),
    ])
    assert info.status == "要確認"


def test_unexpected_note_on_released_back_issue_is_ignored(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2"),
        book(f"{TITLE} 1 重版記念版"),
    ])
    assert info.status == "未定"
    assert info.latest_title == f"{TITLE} 2"


def test_no_volume_number_needs_check(monkeypatch):
    info = run(monkeypatch, [book(TITLE)])
    assert info.status == "要確認"
    assert info.latest_title == ""


def test_no_volume_item_is_ignored_when_volumes_exist(monkeypatch):
    info = run(monkeypatch, [book(TITLE), book(f"{TITLE} 1")])
    assert info.status == "未定"


def test_same_volume_different_authors_needs_check(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 1", author="作者甲"),
        book(f"{TITLE} 1", author="作者乙"),
    ])
    assert info.status == "要確認"


def test_same_volume_same_author_is_fine(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 1", author="作者甲"),
        book(f"{TITLE} 1", author="作者甲"),
    ])
    assert info.status == "未定"


@pytest.mark.parametrize("sales", ["2026年12月上旬", "2026年12月", "2026年12月頃", "2026年12月05日頃"])
def test_ambiguous_sales_date_is_kept_as_is(monkeypatch, sales):
    info = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2", sales=sales, availability="5"),
    ])
    assert info.status == "次巻あり"
    assert info.next_sales_date == sales


def test_ambiguous_future_month_is_unreleased_without_availability(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2", sales="2026年12月上旬", availability=""),
    ])
    assert info.status == "次巻あり"


def test_ambiguous_past_month_is_released(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2", sales="2026年09月下旬", availability=""),
    ])
    assert info.status == "未定"
    assert info.latest_sales_date == "2026年09月下旬"


def test_ambiguous_this_month_uses_availability(monkeypatch):
    released = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2", sales="2026年10月下旬", availability="2"),
    ])
    assert released.status == "未定"
    undecided = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2", sales="2026年10月下旬", availability="9"),
    ])
    assert undecided.status == "要確認"
    assert undecided.next_title == ""


def test_full_date_is_compared_with_today(monkeypatch):
    on_today = run(monkeypatch, [book(f"{TITLE} 1", sales="2026年10月08日")])
    assert on_today.status == "未定"
    tomorrow = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2", sales="2026年10月09日", availability="1"),
    ])
    assert tomorrow.status == "次巻あり"


def test_preorder_availability_is_unreleased_even_with_past_date(monkeypatch):
    info = run(monkeypatch, [
        book(f"{TITLE} 1"),
        book(f"{TITLE} 2", sales="2026年09月01日", availability="5"),
    ])
    assert info.status == "次巻あり"


def test_today_defaults_to_current_date(monkeypatch):
    serve(monkeypatch, [book(f"{TITLE} 1", sales="2000年01月01日")])
    assert find_next_release(TITLE).status == "未定"


@pytest.mark.parametrize("response", [
    FakeResponse(status_code=429),
    FakeResponse(status_code=500),
    FakeResponse(status_code=503),
    FakeResponse(status_code=404, payload={"error": "not_found"}),
    FakeResponse(status_code=200, json_error=True),
    FakeResponse(status_code=200, payload=["not", "a", "dict"]),
    requests.ConnectionError("接続できません"),
    requests.Timeout("時間切れ"),
])
def test_failures_return_error_status(monkeypatch, response):
    serve(monkeypatch, response=response)
    info = find_next_release(TITLE, today=TODAY)
    assert info.status == "エラー"
    assert info.next_title == ""
    assert info.next_sales_date == ""
    assert info.latest_title == ""
    assert info.url == ""


def test_error_does_not_retry(monkeypatch):
    calls = []
    serve(monkeypatch, response=FakeResponse(status_code=429), calls=calls)
    find_next_release(TITLE, today=TODAY)
    assert len(calls) == 1


def test_exception_text_with_keys_is_not_leaked(monkeypatch, caplog):
    leaky = requests.ConnectionError(f"https://example.invalid/?applicationId={APP_ID}")
    serve(monkeypatch, response=leaky)
    info = find_next_release(TITLE, today=TODAY)
    assert info.status == "エラー"
    assert APP_ID not in repr(info)
    assert ACCESS_KEY not in repr(info)
    assert APP_ID not in caplog.text
    assert ACCESS_KEY not in caplog.text


@pytest.mark.parametrize("unset", [rbc.APP_ID_ENV, rbc.ACCESS_KEY_ENV])
def test_missing_key_raises_runtime_error_without_key_value(monkeypatch, unset):
    monkeypatch.delenv(unset)
    calls = []
    serve(monkeypatch, [], calls=calls)
    with pytest.raises(RuntimeError) as excinfo:
        find_next_release(TITLE, today=TODAY)
    message = str(excinfo.value)
    assert unset in message
    assert APP_ID not in message
    assert ACCESS_KEY not in message
    assert calls == []


def test_minimum_interval_between_calls(monkeypatch, _env_and_time):
    fake_time = _env_and_time
    serve(monkeypatch, [])
    find_next_release(TITLE, today=TODAY)
    assert fake_time.sleeps == []
    find_next_release(TITLE, today=TODAY)
    assert fake_time.sleeps == [pytest.approx(1.0)]


def test_interval_counts_from_previous_call(monkeypatch, _env_and_time):
    fake_time = _env_and_time
    serve(monkeypatch, [])
    find_next_release(TITLE, today=TODAY)
    fake_time.now += 0.4
    find_next_release(TITLE, today=TODAY)
    assert fake_time.sleeps == [pytest.approx(0.6)]
    fake_time.now += 5
    find_next_release(TITLE, today=TODAY)
    assert len(fake_time.sleeps) == 1


def test_interval_applies_after_failed_call(monkeypatch, _env_and_time):
    fake_time = _env_and_time
    serve(monkeypatch, response=requests.Timeout("時間切れ"))
    find_next_release(TITLE, today=TODAY)
    find_next_release(TITLE, today=TODAY)
    assert fake_time.sleeps == [pytest.approx(1.0)]


def test_request_parameters_and_header(monkeypatch):
    calls = []
    serve(monkeypatch, [], calls=calls)
    find_next_release("ＡＢＣ冒険譚（全角注記）", today=TODAY)
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "https://openapi.rakuten.co.jp/services/api/BooksBook/Search/20170404"
    params = kwargs["params"]
    assert params["title"] == "ABC冒険譚"
    assert params["size"] == 9
    assert params["sort"] == "-releaseDate"
    assert params["outOfStockFlag"] == 1
    assert params["hits"] == 30
    assert params["format"] == "json"
    assert params["applicationId"] == APP_ID
    assert "accessKey" not in params
    assert ACCESS_KEY not in params.values()
    assert kwargs["headers"] == {"accessKey": ACCESS_KEY}
    assert kwargs["timeout"] > 0


def test_all_title_variants_are_used_for_matching(monkeypatch):
    # クエリは末尾の変種（注記・後置注記を除いて正規化）だが、商品名の照合には全変種を使う。
    info = run(
        monkeypatch,
        [book("ＡＢＣ冒険譚（新装版） 1"), book("ＡＢＣ冒険譚（新装版） 2", sales="2026年12月05日", availability="5")],
        title="ＡＢＣ冒険譚（新装版）",
    )
    assert info.query == "ABC冒険譚"
    assert info.status == "次巻あり"


def test_flat_item_format_is_accepted(monkeypatch):
    serve(monkeypatch, response=FakeResponse(payload={"Items": [book(f"{TITLE} 1")]}))
    assert find_next_release(TITLE, today=TODAY).status == "未定"
