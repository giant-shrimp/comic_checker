import json
import os
import random
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

TOP_URL = "https://manba.co.jp/"
SEARCH_URL = "https://search.manba.co.jp/multi-search"
# manba.co.jp のトップページのキーワード検索ボックス(オートコンプリート)が
# 実際に使っている公開検索キー。訪問者のブラウザが毎回叩くのと同じもの。
# 取得方法はREADMEを参照。環境変数 MANBA_SEARCH_API_KEY で指定する。
SEARCH_API_KEY_ENV = "MANBA_SEARCH_API_KEY"
BOARD_INDEX = "Board_production"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

CHALLENGE_TITLES = {"Just a moment...", "Just a moment…"}


class LookupResult:
    def __init__(self, query, matched_title=None, board_id=None, url=None, status="不明"):
        self.query = query
        self.matched_title = matched_title
        self.board_id = board_id
        self.url = url
        self.status = status


class ManbaClient:
    """manba.co.jp をヘッドレスブラウザ経由で検索し、連載状況を取得するクライアント。

    manba.co.jpはCloudflareのボット対策下にあるため、requestsではなく実ブラウザ
    (Playwright)でアクセスする。間隔を空けずに連続アクセスするとチャレンジページ
    が再度表示されるため、リクエスト間にウェイトを入れ、検知したらリトライする。
    """

    def __init__(self, headless=True, state_path=None, min_delay=3.0, max_delay=6.0):
        api_key = os.environ.get(SEARCH_API_KEY_ENV)
        if not api_key:
            raise RuntimeError(
                f"環境変数 {SEARCH_API_KEY_ENV} が設定されていません。"
                "README記載の手順で検索専用キーを取得し、設定してください"
                f"（例: export {SEARCH_API_KEY_ENV}=... ）。"
            )
        self.api_key = api_key
        self.headless = headless
        self.state_path = Path(state_path) if state_path else None
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._search_page = None

    def __enter__(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        storage_state = str(self.state_path) if self.state_path and self.state_path.exists() else None
        self._context = self._browser.new_context(user_agent=USER_AGENT, storage_state=storage_state)

        try:
            self._page = self._context.new_page()
            if not self._goto_with_retry(self._page, TOP_URL):
                raise RuntimeError(self._challenge_error_message())

            # search()はトップページ（オートコンプリートの検索ボックスがあるページ）でしか
            # search.manba.co.jpへのfetchが許可されない(CSPの都合と見られる)。fetch_status()が
            # self._pageを作品詳細ページへ遷移させても影響を受けないよう、検索専用のページを
            # トップページに固定したまま別途確保しておく。
            self._search_page = self._context.new_page()
            if not self._goto_with_retry(self._search_page, TOP_URL):
                raise RuntimeError(self._challenge_error_message())
        except Exception:
            self._cleanup()
            raise

        return self

    def __exit__(self, exc_type, exc, tb):
        if self.state_path:
            self._context.storage_state(path=str(self.state_path))
        self._cleanup()

    def _cleanup(self):
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    @staticmethod
    def _challenge_error_message():
        return (
            "manba.co.jpのCloudflareチャレンジを自動突破できませんでした。"
            "「Verify you are human」のようなチェックボックスをクリックする必要がある"
            "インタラクティブなチャレンジが表示されている場合、待っても自動では解決しません。"
            "--no-headless を付けて実行し、表示されたブラウザで手動でチェックボックスを"
            "クリックしてください。一度突破すればCookieが state_path "
            "（デフォルト: .manba_state.json）に保存され、次回以降のヘッドレス実行で"
            "再利用されます。頻発する場合は --min-delay / --max-delay を広げて"
            "アクセス頻度を下げることも検討してください。"
        )

    def _sleep(self):
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def _is_challenge(self, page):
        return page.title().strip() in CHALLENGE_TITLES

    def _goto_with_retry(self, page, url, retries=3):
        for attempt in range(retries):
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            if not self._is_challenge(page):
                return True
            time.sleep(8 * (attempt + 1))
        return False

    def search(self, title, limit=5):
        """タイトルで検索し、ヒットのリスト([{"id":..., "title":...}, ...])を返す。"""
        payload = {
            "queries": [
                {
                    "indexUid": BOARD_INDEX,
                    "q": title,
                    "filter": ["is_suggestable = true"],
                    "limit": limit,
                    "offset": 0,
                }
            ]
        }
        result_text = self._search_page.evaluate(
            """
            async ({url, apiKey, body}) => {
                const res = await fetch(url, {
                    method: "POST",
                    headers: {
                        "content-type": "application/json",
                        "authorization": "Bearer " + apiKey,
                    },
                    body: JSON.stringify(body),
                });
                return await res.text();
            }
            """,
            {"url": SEARCH_URL, "apiKey": self.api_key, "body": payload},
        )
        data = json.loads(result_text)
        hits = data["results"][0]["hits"]
        return [{"id": h["id"], "title": h["title"]} for h in hits]

    def fetch_status(self, board_id):
        """作品ページの<title>タグが「[完結] 」で始まるかどうかで連載状況を判定する。"""
        url = f"https://manba.co.jp/boards/{board_id}"
        ok = self._goto_with_retry(self._page, url)
        if not ok:
            return "不明", url
        page_title = self._page.title()
        if page_title.startswith("[完結]"):
            return "完結", url
        return "連載中", url

    def lookup(self, title):
        """タイトルを検索し、最上位ヒットの連載状況を取得する。"""
        self._sleep()
        hits = self.search(title)
        if not hits:
            return LookupResult(query=title, status="ヒットなし")
        top = hits[0]
        self._sleep()
        status, url = self.fetch_status(top["id"])
        return LookupResult(
            query=title,
            matched_title=top["title"],
            board_id=top["id"],
            url=url,
            status=status,
        )
