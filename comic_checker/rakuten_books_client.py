"""楽天ブックス書籍検索APIで、作品の次巻の発売日を調べる。

HTTPを呼ぶ部分（`_fetch_items`）と、応答を解釈する純粋な関数（`_interpret`）を分けてある。
キー（applicationId・accessKey）の値は、ログ・例外の文面・戻り値のどこにも出さない。
`requests`の例外の文面はクエリにapplicationIdを含みうるため、外に出さずに「エラー」とだけ返す。
"""
from dataclasses import dataclass
from datetime import date
import os
import re
import threading
import time
import unicodedata

import requests

from comic_checker import user_config
from comic_checker.wikipedia_client import _title_variants

SEARCH_URL = "https://openapi.rakuten.co.jp/services/api/BooksBook/Search/20170404"

APP_ID_ENV = "RAKUTEN_APP_ID"
ACCESS_KEY_ENV = "RAKUTEN_ACCESS_KEY"
# 公式ドキュメント上のaccessKeyのヘッダ名。ここ1か所にまとめる。
ACCESS_KEY_HEADER = "accessKey"

# 呼び出しの最小間隔（秒）。前回の呼び出しの終了時刻から数える。
MIN_INTERVAL_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 15

SEARCH_SIZE = 9
SEARCH_HITS = 30
SEARCH_SORT = "-releaseDate"

STATUS_NEXT = "次巻あり"
STATUS_UNDECIDED = "未定"
STATUS_CHECK = "要確認"
STATUS_NO_HIT = "ヒットなし"
STATUS_ERROR = "エラー"

# 商品名の巻数の後ろに付いていても通常の候補として扱う版の表記。
EDITION_WORDS = ("特装版", "限定版", "特別版", "同梱版")
# 変種の後ろにこれらの語を含む商品は、関連書籍として除く。
RELATED_WORDS = (
    "画集", "ファンブック", "公式ガイド", "公式ブック", "ガイドブック",
    "小説版", "ノベライズ", "アンソロジー", "設定資料", "イラスト集",
)

# availability: 1〜4は在庫あり・取り寄せなど（発売済み）、5は予約受付中（発売前）。
_PREORDER_AVAILABILITY = "5"
_RELEASED_AVAILABILITY = ("1", "2", "3", "4")

_VOLUME_RE = re.compile(r"^(?:第\s*(\d+)\s*巻|\(\s*(\d+)\s*\)|(\d+)\s*巻|(\d+))")
_EDITION_ONLY_RE = re.compile("^(?:" + "|".join(EDITION_WORDS) + ")+$")
_SUFFIX_NOISE_RE = re.compile(r"[\s()\[\]【】「」『』]")
_FULL_DATE_RE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$")
_YEAR_MONTH_RE = re.compile(r"^(\d{4})年(\d{1,2})月")

_last_call_time = None
_call_lock = threading.Lock()


@dataclass
class ReleaseInfo:
    query: str
    status: str
    next_title: str = ""
    next_sales_date: str = ""
    next_has_special_edition: bool = False
    latest_title: str = ""
    latest_sales_date: str = ""
    url: str = ""


@dataclass
class _Entry:
    volume: object  # int、または巻数がないとき None
    kind: str  # "normal" | "special" | "unexpected"
    title: str
    sales_date: str
    availability: str
    url: str
    author: str
    variant: str = ""  # 一致した変種


def _nfkc(text):
    return unicodedata.normalize("NFKC", text or "").strip()


def _load_keys():
    """キーごとに「環境変数 → 設定ファイル」の順で読む。環境変数が空でなければそれを使う。"""
    app_id = os.environ.get(APP_ID_ENV) or user_config.get_value(user_config.KEY_RAKUTEN_APP_ID)
    access_key = os.environ.get(ACCESS_KEY_ENV) or user_config.get_value(
        user_config.KEY_RAKUTEN_ACCESS_KEY
    )
    missing = [
        name for name, value in ((APP_ID_ENV, app_id), (ACCESS_KEY_ENV, access_key))
        if not value
    ]
    if missing:
        names = "・".join(missing)
        raise RuntimeError(
            f"楽天ブックスのキー（{names}）が設定されていません。"
            "楽天ウェブサービスで取得したアプリIDとアクセスキーを、"
            "画面の「楽天APIキーの設定」で設定するか、"
            f"環境変数で設定してください（例: export {APP_ID_ENV}=... ・ export {ACCESS_KEY_ENV}=... ）。"
        )
    return app_id, access_key


def _wait_for_interval():
    if _last_call_time is None:
        return
    remaining = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_call_time)
    if remaining > 0:
        time.sleep(remaining)


def _fetch_items(query, app_id, access_key):
    """APIを1回呼び、商品（dict）のリストを返す。失敗したら None（理由は外に出さない）。"""
    global _last_call_time
    params = {
        "applicationId": app_id,
        "title": query,
        "size": SEARCH_SIZE,
        "sort": SEARCH_SORT,
        "outOfStockFlag": 1,
        "hits": SEARCH_HITS,
        "format": "json",
    }
    # 待機・API呼び出し・_last_call_time の更新をまとめて囲み、複数のスレッドから
    # 呼ばれても呼び出しの間隔が MIN_INTERVAL_SECONDS 以上になるようにする。
    with _call_lock:
        _wait_for_interval()
        try:
            resp = requests.get(
                SEARCH_URL,
                params=params,
                headers={ACCESS_KEY_HEADER: access_key},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            return None
        finally:
            _last_call_time = time.monotonic()

    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    raw_items = data.get("Items") or []
    if not isinstance(raw_items, list):
        return None
    items = []
    for raw in raw_items:
        if isinstance(raw, dict) and isinstance(raw.get("Item"), dict):
            raw = raw["Item"]
        if isinstance(raw, dict):
            items.append(raw)
    return items


def _classify_suffix(suffix):
    """巻数の後ろの文字列を "normal"（空）・"special"（版の表記）・"unexpected" に分ける。"""
    compact = _SUFFIX_NOISE_RE.sub("", suffix)
    if not compact:
        return "normal"
    if _EDITION_ONLY_RE.match(compact):
        return "special"
    return "unexpected"


def _to_entry(product, variants):
    """商品を候補にする。変種と無関係・関連書籍・変種の後ろが巻数で始まらないものは None。"""
    name = _nfkc(product.get("title"))
    for variant in sorted(variants, key=len, reverse=True):
        if not name.startswith(variant):
            continue
        rest = name[len(variant):].lstrip()
        if any(word in rest for word in RELATED_WORDS):
            continue
        common = dict(
            title=str(product.get("title") or ""),
            sales_date=str(product.get("salesDate") or ""),
            availability=str(product.get("availability") or "").strip(),
            url=str(product.get("itemUrl") or ""),
            author=_nfkc(product.get("author")),
            variant=variant,
        )
        match = _VOLUME_RE.match(rest)
        if match:
            volume = int(next(g for g in match.groups() if g is not None))
            kind = _classify_suffix(rest[match.end():])
            return _Entry(volume=volume, kind=kind, **common)
        if _classify_suffix(rest) != "unexpected":
            return _Entry(volume=None, kind="normal", **common)
    return None


def _is_released(entry, today):
    """発売済みなら True、発売前なら False、決められなければ None。"""
    if entry.availability == _PREORDER_AVAILABILITY:
        return False
    sales_date = _nfkc(entry.sales_date)
    match = _FULL_DATE_RE.match(sales_date)
    if match:
        try:
            return date(*(int(g) for g in match.groups())) <= today
        except ValueError:
            return None
    match = _YEAR_MONTH_RE.match(sales_date)
    if match:
        sales_month = (int(match.group(1)), int(match.group(2)))
        this_month = (today.year, today.month)
        if sales_month < this_month:
            return True
        if sales_month > this_month:
            return False
        if entry.availability in _RELEASED_AVAILABILITY:
            return True
    return None


def _interpret(query, variants, products, today):
    """商品のリストから ReleaseInfo を作る（ネットワークに出ない純粋な関数）。"""
    entries = [e for e in (_to_entry(p, variants) for p in products) if e]
    if not entries:
        return ReleaseInfo(query=query, status=STATUS_NO_HIT)
    # 最も長い変種から見て、一致した商品がある最初の変種の商品だけを候補にする。
    # 派生シリーズの行で、本編名だけの変種に一致する本編の商品が混ざるのを防ぐ。
    matched = {e.variant for e in entries}
    best = next(v for v in sorted(variants, key=len, reverse=True) if v in matched)
    entries = [e for e in entries if e.variant == best]

    volumed = [e for e in entries if e.volume is not None]
    if not volumed:
        return ReleaseInfo(query=query, status=STATUS_CHECK)

    by_volume = {}
    for entry in volumed:
        if entry.kind != "unexpected":
            by_volume.setdefault(entry.volume, []).append(entry)

    chosen = {}  # 巻数 -> (採る商品, 特装版などがあるか)
    for volume, group in by_volume.items():
        plain = [e for e in group if e.kind == "normal"]
        specials = [e for e in group if e.kind == "special"]
        picked = plain or specials
        if plain and len({e.author for e in plain}) > 1:
            return ReleaseInfo(query=query, status=STATUS_CHECK)
        # 同じ巻の候補で発売日が食い違うなら絞りきれない（重版・新装版など）。
        if len({e.sales_date for e in picked}) > 1:
            return ReleaseInfo(query=query, status=STATUS_CHECK)
        chosen[volume] = (picked[0], bool(specials) if plain else True)

    released = {v: _is_released(e, today) for v, (e, _) in chosen.items()}
    if any(r is None for r in released.values()):
        return ReleaseInfo(query=query, status=STATUS_CHECK)

    max_volume = max(chosen, default=-1)
    for entry in volumed:
        if entry.kind != "unexpected":
            continue
        if _is_released(entry, today) is not True or entry.volume > max_volume:
            return ReleaseInfo(query=query, status=STATUS_CHECK)

    upcoming = sorted(v for v, r in released.items() if not r)
    past = sorted(v for v, r in released.items() if r)
    latest = chosen[past[-1]][0] if past else None
    latest_fields = {}
    if latest:
        latest_fields = dict(latest_title=latest.title, latest_sales_date=latest.sales_date)

    if upcoming:
        entry, has_special = chosen[upcoming[0]]
        return ReleaseInfo(
            query=query,
            status=STATUS_NEXT,
            next_title=entry.title,
            next_sales_date=entry.sales_date,
            next_has_special_edition=has_special,
            url=entry.url,
            **latest_fields,
        )
    return ReleaseInfo(
        query=query,
        status=STATUS_UNDECIDED,
        url=latest.url,
        **latest_fields,
    )


def find_next_release(title, today=None):
    """作品名から次巻の発売情報を調べる。`today`は日付の注入用（None なら今日）。"""
    app_id, access_key = _load_keys()
    if today is None:
        today = date.today()
    variants = _title_variants(title)
    if not variants:
        return ReleaseInfo(query="", status=STATUS_NO_HIT)
    query = _nfkc(variants[-1])
    normalized = []
    for variant in variants:
        variant = _nfkc(variant)
        if variant and variant not in normalized:
            normalized.append(variant)

    products = _fetch_items(query, app_id, access_key)
    if products is None:
        return ReleaseInfo(query=query, status=STATUS_ERROR)
    return _interpret(query, normalized, products, today)
