import json
from unittest.mock import MagicMock, patch

import pytest

from comic_checker.manba_client import ManbaClient


def make_fake_page(title="manba.co.jp", evaluate_result=None):
    page = MagicMock()
    page.title.return_value = title
    page.evaluate.return_value = evaluate_result
    return page


@pytest.fixture
def api_key_env(monkeypatch):
    monkeypatch.setenv("MANBA_SEARCH_API_KEY", "test-key")


def make_search_result_json():
    return json.dumps({"results": [{"hits": [{"id": "1", "title": "ONE PIECE"}]}]})


def test_search_uses_dedicated_search_page_pinned_to_top(api_key_env):
    top_page = make_fake_page(title="manba.co.jp")
    search_page = make_fake_page(title="manba.co.jp", evaluate_result=make_search_result_json())

    fake_context = MagicMock()
    fake_context.new_page.side_effect = [top_page, search_page]

    fake_browser = MagicMock()
    fake_browser.new_context.return_value = fake_context

    fake_playwright = MagicMock()
    fake_playwright.chromium.launch.return_value = fake_browser

    with patch("comic_checker.manba_client.sync_playwright") as mock_sync_playwright:
        mock_sync_playwright.return_value.start.return_value = fake_playwright

        with ManbaClient() as client:
            hits = client.search("ONE PIECE")

    assert hits == [{"id": "1", "title": "ONE PIECE"}]
    # 検索は検索専用ページに対して行われ、トップページ用のページは検索処理では触られない。
    search_page.evaluate.assert_called_once()
    top_page.evaluate.assert_not_called()


def test_fetch_status_navigation_does_not_touch_search_page(api_key_env):
    top_page = make_fake_page(title="manba.co.jp")
    search_page = make_fake_page(title="manba.co.jp")

    fake_context = MagicMock()
    fake_context.new_page.side_effect = [top_page, search_page]

    fake_browser = MagicMock()
    fake_browser.new_context.return_value = fake_context

    fake_playwright = MagicMock()
    fake_playwright.chromium.launch.return_value = fake_browser

    with patch("comic_checker.manba_client.sync_playwright") as mock_sync_playwright:
        mock_sync_playwright.return_value.start.return_value = fake_playwright

        with ManbaClient() as client:
            # __enter__時点でのgoto呼び出し回数(トップページへの遷移)を基準にする。
            search_page_goto_calls_before = search_page.goto.call_count

            top_page.title.return_value = "[完結] ONE PIECE"
            status, url = client.fetch_status("1")

    assert status == "完結"
    assert url == "https://manba.co.jp/boards/1"
    # 作品詳細ページへの遷移はトップページ用のページに対してのみ行われる。
    assert search_page.goto.call_count == search_page_goto_calls_before


def test_enter_raises_and_cleans_up_when_challenge_not_passed(api_key_env):
    # インタラクティブなチャレンジ等でタイトルが「Just a moment...」のまま
    # 変わらないケースをシミュレートする（待っても自動では解決しない）。
    stuck_page = make_fake_page(title="Just a moment...")

    fake_context = MagicMock()
    fake_context.new_page.return_value = stuck_page

    fake_browser = MagicMock()
    fake_browser.new_context.return_value = fake_context

    fake_playwright = MagicMock()
    fake_playwright.chromium.launch.return_value = fake_browser

    client = ManbaClient()

    with patch("comic_checker.manba_client.sync_playwright") as mock_sync_playwright, patch(
        "comic_checker.manba_client.time.sleep"
    ):
        mock_sync_playwright.return_value.start.return_value = fake_playwright

        with pytest.raises(RuntimeError):
            client.__enter__()

    # __enter__が例外を送出する場合、__exit__は呼ばれないため、
    # ここでブラウザ/コンテキスト/playwrightが確実に後始末されている必要がある。
    fake_context.close.assert_called_once()
    fake_browser.close.assert_called_once()
    fake_playwright.stop.assert_called_once()


def test_bootstrap_top_page_polls_without_reload_in_no_headless_mode(api_key_env):
    top_page = make_fake_page()
    top_page.title.side_effect = [
        "Just a moment...",  # 初回遷移直後のチェック
        "Just a moment...",  # ポーリング1回目（まだ未解決）
        "manba.co.jp",  # ポーリング2回目で人間がクリックして解決
    ]
    search_page = make_fake_page(title="manba.co.jp")

    fake_context = MagicMock()
    fake_context.new_page.side_effect = [top_page, search_page]

    fake_browser = MagicMock()
    fake_browser.new_context.return_value = fake_context

    fake_playwright = MagicMock()
    fake_playwright.chromium.launch.return_value = fake_browser

    with patch("comic_checker.manba_client.sync_playwright") as mock_sync_playwright, patch(
        "comic_checker.manba_client.time.sleep"
    ):
        mock_sync_playwright.return_value.start.return_value = fake_playwright

        with ManbaClient(headless=False):
            pass

    # ポーリング中はページを一度もリロードしていない（goto()は最初の1回だけ）。
    assert top_page.goto.call_count == 1


def test_bootstrap_top_page_gives_up_after_timeout_in_no_headless_mode(api_key_env):
    # チェックボックスが最後までクリックされないケース。
    stuck_page = make_fake_page(title="Just a moment...")

    fake_context = MagicMock()
    fake_context.new_page.return_value = stuck_page

    fake_browser = MagicMock()
    fake_browser.new_context.return_value = fake_context

    fake_playwright = MagicMock()
    fake_playwright.chromium.launch.return_value = fake_browser

    client = ManbaClient(headless=False)

    with patch("comic_checker.manba_client.sync_playwright") as mock_sync_playwright, patch(
        "comic_checker.manba_client.time.sleep"
    ), patch(
        "comic_checker.manba_client.time.monotonic", side_effect=[0.0, 10.0, 20.0, 200.0]
    ):
        mock_sync_playwright.return_value.start.return_value = fake_playwright

        with pytest.raises(RuntimeError):
            client.__enter__()

    # ポーリング中はページを一度もリロードしていない（goto()は最初の1回だけ）。
    assert stuck_page.goto.call_count == 1
    fake_context.close.assert_called_once()
    fake_browser.close.assert_called_once()
    fake_playwright.stop.assert_called_once()
