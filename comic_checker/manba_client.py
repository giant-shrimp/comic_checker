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

# 「Verify you are human」等のインタラクティブなチャレンジは自動では解決しない。
# --no-headless時のみ、この秒数だけページをリロードせずにタイトルをポーリングし、
# 人間が手動でクリックする猶予を与える。
MANUAL_CHALLENGE_TIMEOUT = 90.0
MANUAL_CHALLENGE_POLL_INTERVAL = 2.0


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
            if not self._bootstrap_top_page(self._page):
                raise RuntimeError(self._challenge_error_message())

            # search()はトップページ（オートコンプリートの検索ボックスがあるページ）でしか
            # search.manba.co.jpへのfetchが許可されない(CSPの都合と見られる)。fetch_status()が
            # self._pageを作品詳細ページへ遷移させても影響を受けないよう、検索専用のページを
            # トップページに固定したまま別途確保しておく。
            self._search_page = self._context.new_page()
            if not self._bootstrap_top_page(self._search_page):
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
            "インタラクティブなチャレンジの場合、自動では解決しません。"
            "--no-headless を付けて実行すると、表示されたブラウザ上で最大"
            f"{int(MANUAL_CHALLENGE_TIMEOUT)}秒間、手動でクリックする猶予が与えられます"
            "（すでに --no-headless で実行していた場合は、その猶予内に解決しなかった"
            "ことになります）。それでも解決しない場合は、時間を置いて再実行する、"
            "--min-delay / --max-delay を広げてアクセス頻度を下げる、といった対応を"
            "検討してください。一度突破できればCookieが state_path "
            "（デフォルト: .manba_state.json）に保存され、次回以降のヘッドレス実行でも"
            "再利用されます。"
        )

    def _bootstrap_top_page(self, page):
        """__enter__時のトップページへの初回遷移。

        headless時は人間が操作できないため、既存の短いリトライ(goto()での再読み込みを
        伴う、自動解決型チャレンジ向け)にそのまま任せる。--no-headless時は、goto()に
        よる再読み込みが手動でのチェックボックスクリックを台無しにしてしまうため、
        一度だけ遷移した後はページに触れずにタイトルをポーリングし、人間が操作する
        猶予を与える。
        """
        if self.headless:
            return self._goto_with_retry(page, TOP_URL)

        page.goto(TOP_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        if not self._is_challenge(page):
            return True
        return self._wait_for_manual_challenge(page)

    def _wait_for_manual_challenge(self, page):
        """ページを再読み込みせずにタイトルをポーリングし、手動でのチャレンジ突破を待つ。"""
        print(
            "Cloudflareの確認画面が表示されています。表示されたブラウザで"
            "「Verify you are human」等のチェックボックスを手動でクリックしてください"
            f"（最大{int(MANUAL_CHALLENGE_TIMEOUT)}秒待ちます）..."
        )
        deadline = time.monotonic() + MANUAL_CHALLENGE_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(MANUAL_CHALLENGE_POLL_INTERVAL)
            if not self._is_challenge(page):
                return True
        return False

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
