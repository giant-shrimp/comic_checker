import re
from urllib.parse import quote

import requests

API_URL = "https://ja.wikipedia.org/w/api.php"
USER_AGENT = "comic-checker/0.1 (https://github.com/; local tool, contact via repo issues)"
REQUEST_TIMEOUT = 15

ONGOING_RE = re.compile(r"連載中|連載されている")

# 「完結」は日本語として「作品自体が終わった」ことをほぼ一意に意味する強いシグナル
# として、そのまま信用する。
COMPLETED_STRONG_RE = re.compile(r"完結(?:した)?")

# 「連載(を)?終了」「連載された」「まで連載」は完結を示唆するが、「週刊連載を終了し、
# 週刊連載ではない掲載形態で継続」のように、連載の頻度・掲載形態の変更を指しているに
# 過ぎず、作品自体は終わっていないケースがある（HUNTER×HUNTERで実際に誤判定した
# 事例）。そのため、同じ文中に継続を示す語（CONTINUATION_VETO_RE）がある場合は、
# このシグナルを完結とはみなさない。
COMPLETED_WEAK_RE = re.compile(r"連載(?:が|を)?終了(?:した)?|連載された|まで連載(?:された)?")
CONTINUATION_VETO_RE = re.compile(r"継続|再開|引き続き|連載を?続け|掲載を?続け")

MANGA_MARKERS = ("漫画", "コミカライズ", "コミック版", "漫画版")
NOVEL_MARKERS = ("小説", "ライトノベル")

# 記事冒頭文の「〜による日本の<種別>」の<種別>を、作品そのものの一次分類として見る。
# 「進撃の巨人」のように漫画が原作でアニメ化・小説化もされている場合、冒頭文に「小説」
# という語自体は出現する（派生作品の列挙として）が、一次分類はあくまで「漫画」であり、
# 完結/連載中の判定文に毎回「漫画」という語が繰り返される保証はない。単純に記事全体に
# 「小説」の語があるかどうかだけでメディアミックス扱いすると、こうした「漫画が原作」の
# 記事まで誤って判定不能にしてしまう。そのため、一次分類が「小説」「ライトノベル」で
# あり、かつ「漫画」を含まない場合だけをメディアミックス（主語の確認が必要）とみなす。
_PRIMARY_TYPE_RE = re.compile(r"日本の([^、。]+)")

STATUS_NOT_FOUND = "記事なし"
STATUS_UNKNOWN = "判定不能"


class WikipediaJudgment:
    def __init__(self, query, status, matched_title=None, url=None, evidence=None):
        self.query = query
        self.status = status
        self.matched_title = matched_title
        self.url = url
        self.evidence = evidence


def _split_sentences(text):
    return [s for s in re.split(r"(?<=。)", text) if s.strip()]


def _is_novel_primary(extract):
    """作品自体の一次分類が小説/ライトノベルかどうかを、冒頭文の「日本の<種別>」から見る。

    判定できない場合（想定外の冒頭文形式など）は、安全側に倒して小説主体とみなす
    （＝主語チェックを要求する側に倒し、判定不能で終わるリスクを許容する）。
    """
    match = _PRIMARY_TYPE_RE.search(extract)
    if match is None:
        return any(marker in extract for marker in NOVEL_MARKERS)
    primary_type = match.group(1)
    has_novel = any(marker in primary_type for marker in NOVEL_MARKERS)
    has_manga = any(marker in primary_type for marker in MANGA_MARKERS)
    return has_novel and not has_manga


def _judge_extract(extract):
    """リード文から連載中/完結を判定する。

    メディアミックス作品（原作小説とコミカライズが併存する等）では、判定文の主語が
    漫画かどうかを文単位でチェックし、確信が持てない場合は判定不能として扱う。
    """
    is_multimedia = _is_novel_primary(extract)

    for sentence in _split_sentences(extract):
        ongoing = bool(ONGOING_RE.search(sentence))
        weak_completed = bool(COMPLETED_WEAK_RE.search(sentence)) and not CONTINUATION_VETO_RE.search(
            sentence
        )
        completed = bool(COMPLETED_STRONG_RE.search(sentence)) or weak_completed
        if ongoing == completed:
            continue
        status = "連載中" if ongoing else "完結"

        if not is_multimedia:
            return status, sentence.strip()

        has_manga = any(marker in sentence for marker in MANGA_MARKERS)
        has_novel = any(marker in sentence for marker in NOVEL_MARKERS)
        if has_manga and not has_novel:
            return status, sentence.strip()

    return STATUS_UNKNOWN, None


def _api_get(params):
    headers = {"User-Agent": USER_AGENT}
    query = {"format": "json", **params}
    response = requests.get(API_URL, params=query, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


# exintro=true (段落見出しの手前まで)だけでは、連載状況が最初の段落ではなく最初の
# セクション（多くは「概要」）に書かれている記事で判定不能になる（例:
# 「進撃の巨人」は導入部が1文だけで、完結時期は「== 概要 ==」節にある）。かといって
# 記事全文まで対象を広げると、スピンオフ/派生作品ごとの個別の連載状況（本編とは別の
# 連載中・完結）を誤って本編の状況として拾ってしまうリスクがある（実際に確認済み:
# 「転生したらスライムだった件」は本編漫画の連載状況を述べる文が記事中に存在しない
# 一方、傍系のスピンオフ漫画には「連載中」「連載された」という文がいくつもある）。
# そのため、範囲は「導入部 + 最初のセクションのみ」に限定する。
_LEVEL2_HEADING_RE = re.compile(r"^==(?!=)(.+?)(?<!=)==$", re.MULTILINE)


def _lead_and_first_section(text):
    headings = list(_LEVEL2_HEADING_RE.finditer(text))
    if len(headings) < 2:
        return text
    return text[: headings[1].start()]


def _fetch_extract(page_title):
    """指定タイトルの導入部+最初のセクションを取得する。記事が存在しなければNone。"""
    data = _api_get(
        {
            "action": "query",
            "titles": page_title,
            "prop": "extracts",
            "explaintext": "true",
            "redirects": "1",
        }
    )
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    if "missing" in page:
        return None
    full_extract = page.get("extract", "")
    if not full_extract.strip():
        return None
    extract = _lead_and_first_section(full_extract)
    resolved_title = page.get("title", page_title)
    url = f"https://ja.wikipedia.org/wiki/{quote(resolved_title.replace(' ', '_'))}"
    return resolved_title, extract, url


def _search_titles(title, limit=5):
    data = _api_get(
        {
            "action": "query",
            "list": "search",
            "srsearch": title,
            "srlimit": limit,
        }
    )
    hits = data.get("query", {}).get("search", [])
    return [hit["title"] for hit in hits]


def _pick_article(title):
    """判定対象の記事(タイトル・リード文・URL)を選ぶ。見つからなければNone。"""
    direct = _fetch_extract(f"{title} (漫画)")
    if direct is not None:
        return direct

    candidates = _search_titles(title)
    if not candidates:
        return None

    chosen = next((c for c in candidates if "(漫画)" in c), candidates[0])
    return _fetch_extract(chosen)


def judge(title):
    """タイトルからWikipedia記事を探し、連載中/完結を判定する。"""
    article = _pick_article(title)
    if article is None:
        return WikipediaJudgment(query=title, status=STATUS_NOT_FOUND)

    matched_title, extract, url = article
    status, evidence = _judge_extract(extract)
    return WikipediaJudgment(
        query=title,
        status=status,
        matched_title=matched_title,
        url=url,
        evidence=evidence,
    )
