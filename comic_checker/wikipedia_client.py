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

# 「連載(を)?終了」「連載された」「まで連載」「打ち切り」は完結を示唆するが、「週刊連載を
# 終了し、週刊連載ではない掲載形態で継続」のように、連載の頻度・掲載形態の変更を指して
# いるに過ぎず、作品自体は終わっていないケースがある（HUNTER×HUNTERで実際に誤判定した
# 事例）。「打ち切り」も同様に、「打ち切りの危機に瀕したが連載は継続した」「打ち切りが
# 検討された」のように、打ち切られなかったことを述べる文脈が頻出する（M6-B-1）。
# そのため、同じ文中に継続を示す語（CONTINUATION_VETO_RE）がある場合は、
# このシグナルを完結とはみなさない。
# なお「打ち切り」は仕様上、円満な完結と同じ`完結`ステータスとして扱う（利用者が知りたい
# のは「続きが出るか」であり、終わり方の円満さではないため）。打ち切りだった事実は
# 判定根拠（evidence）にそのまま残る一文を通じて伝わる。
# 「まで...連載」は、「まで」と「連載」の間に語が挟まる言い回し（例:「2017年3月23日まで
# 毎週木曜更新で連載。」実際に「とんかつDJアゲ太郎」の本編完結文で確認した形）にも
# 対応するため、間に任意の語（句点をまたがない範囲）を許容する。ただし無関係な離れた
# 箇所同士が拾われないよう、間隔は短く区切って（{0,20}）制限している。
COMPLETED_WEAK_RE = re.compile(
    r"連載(?:が|を)?終了(?:した)?|連載された|まで[^。]{0,20}?連載(?:された)?|打ち切(?:り|られ)"
)
CONTINUATION_VETO_RE = re.compile(r"継続|再開|引き続き|連載を?続け|掲載を?続け")

MANGA_MARKERS = ("漫画", "コミカライズ", "コミック版", "漫画版")
NOVEL_MARKERS = ("小説", "ライトノベル")

# is_multimedia=False（一次分類が漫画そのもの）の経路では、_judge_extract()は
# MANGA_MARKERS/NOVEL_MARKERSによる主語チェックを行わず、最初に見つかった判定文を
# そのまま本編の判定として採用する。しかし「番外編」「スピンオフ」「外伝」等の語を
# 含む文は、本編ではなく派生読み切り・短期集中連載の状況を述べているに過ぎない
# ことがある（実際に確認した事例:「とんかつDJアゲ太郎」で、本編自身の完結文が
# 「まで連載」系正規表現に一致せず取りこぼされた結果、代わりに番外編の連載終了文が
# 本編の判定文として採用されてしまっていた）。そのため、この経路ではスピンオフを
# 示す語を含む文を候補から除外する。除外した結果、本編の判定文が1件も見つからない
# 場合は、無理に他の文を代用せず判定不能に倒す（Issue #8以来の fail-closed 方針）。
SPINOFF_MARKERS = ("番外編", "スピンオフ", "外伝")

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

# Issue #12: 本文解析（_judge_extract）が判定不能のときだけ参照する補助情報源。
# {{Infobox animanga/Manga}}テンプレートの終了系フィールドが空欄かどうかは、本文解析より
# 頑健な連載中/完結シグナルになりうることを実現可能性検証で確認した一方、記事内に
# 本編とスピンオフ両方のインフォボックスが存在しうる（例: 転生したらスライムだった件は
# 本編1件+スピンオフ8件、計9個）ため、本編ブロックを誤って取り違えると
# HUNTER×HUNTERと同様の危険側の誤り（連載中の本編を完結と誤判定）になりうる。
MANGA_INFOBOX_MARKER = "{{Infobox animanga/Manga"

# 事前調査（転生したらスライムだった件・呪術廻戦・NARUTO -ナルト-の3作品、計11個の
# インフォボックス）で一貫して確認した手がかり: 本編ブロックには`タイトル`フィールドが
# 無く（記事タイトルと暗黙に一致するため）、スピンオフブロックには明示的な`タイトル`
# フィールドがある。
TITLE_FIELD_NAME = "タイトル"

# 終了系フィールドの名称は記事によって揺れる。`終了号`・`終了日`は実データ
# （HUNTER×HUNTER・こち亀等）で確認済み。`終了`は念のため追加した未確認の候補で、
# 実際のインフォボックスで観測できたわけではない。
END_FIELD_NAMES = ("終了号", "終了日", "終了")


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
            if any(marker in sentence for marker in SPINOFF_MARKERS):
                continue
            return status, sentence.strip()

        has_manga = any(marker in sentence for marker in MANGA_MARKERS)
        has_novel = any(marker in sentence for marker in NOVEL_MARKERS)
        if has_manga and not has_novel:
            return status, sentence.strip()

    return STATUS_UNKNOWN, None


def _extract_braced_blocks(wikitext, marker):
    """wikitext中に複数回出現しうるmarker（テンプレート開始文字列）ごとに、対応する
    閉じ括弧までのブロックを切り出す。

    テンプレート内に`{{small|...}}`等がネストしていても壊れないよう、単純な文字列
    マッチではなく`{`/`}`の出現数で深さを数える。閉じ括弧が見つからない不正なwikitext
    の場合、その出現はスキップして次を探す。
    """
    blocks = []
    start = 0
    while True:
        idx = wikitext.find(marker, start)
        if idx == -1:
            break
        depth = 0
        end = None
        for i in range(idx, len(wikitext)):
            if wikitext[i] == "{":
                depth += 1
            elif wikitext[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            start = idx + len(marker)
            continue
        blocks.append(wikitext[idx:end])
        start = end
    return blocks


def _infobox_has_field(block, field_name):
    # 行内の空白（インデント・"="前後のスペース）だけを許容し、\sは使わない。\sは改行にも
    # マッチするため、値が空欄で直後に改行が続く行（例:「|終了号 = 」の直後で改行）で、
    # 次の行の内容まで巻き込んで一致してしまうバグを踏んだ経緯がある。
    return bool(re.search(r"^\|[ \t]*" + re.escape(field_name) + r"[ \t]*=", block, re.MULTILINE))


def _infobox_field(block, field_name):
    """1ブロック内から`| フィールド名 = 値`形式の行を探し、値をstrip()して返す。

    フィールド自体が存在しない場合、および存在するが値が空欄の場合のどちらも
    Noneを返す（呼び出し側にとってはどちらも「値が無い」という点で同じ扱いのため）。
    """
    # _infobox_has_fieldと同じ理由で、行内の空白のみ（[ \t]*）を使い、\sは使わない。
    match = re.search(
        r"^\|[ \t]*" + re.escape(field_name) + r"[ \t]*=[ \t]*(.*)$", block, re.MULTILINE
    )
    if match is None:
        return None
    value = match.group(1).strip()
    return value or None


def _find_main_manga_block(blocks):
    """`タイトル`フィールドが無いブロックがちょうど1つの場合のみ、それを本編として返す。

    0個・2個以上の場合は本編を確信を持って特定できないため、Noneを返す
    （Issue #8以来のfail-closed方針。無理にどれかを本編とみなさない）。
    """
    titleless = [block for block in blocks if _infobox_field(block, TITLE_FIELD_NAME) is None]
    if len(titleless) != 1:
        return None
    return titleless[0]


def _judge_via_infobox(wikitext):
    """wikitextから本編漫画のインフォボックスを特定し、連載中/完結を判定する。

    本編を確信を持って特定できない場合、または終了系フィールドが1つも存在せず
    判定材料が無い場合は、(None, None)を返す（呼び出し側は判定不能のまま維持する）。
    """
    blocks = _extract_braced_blocks(wikitext, MANGA_INFOBOX_MARKER)
    main_block = _find_main_manga_block(blocks)
    if main_block is None:
        return None, None

    if not any(_infobox_has_field(main_block, field_name) for field_name in END_FIELD_NAMES):
        return None, None

    for field_name in END_FIELD_NAMES:
        value = _infobox_field(main_block, field_name)
        if value:
            return "完結", f"インフォボックス: {field_name} = {value}"

    return "連載中", "インフォボックス: 終了号/終了日等が空欄"


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


def _fetch_wikitext(page_title):
    """指定タイトルのraw wikitextを取得する。取得できなければNone。

    Issue #12: インフォボックスのraw wikitextを取得するための専用エンドポイント
    （action=parse&prop=wikitext）。prop=extractsとは別のAPI呼び出しになる。
    """
    data = _api_get(
        {
            "action": "parse",
            "page": page_title,
            "prop": "wikitext",
            "redirects": "1",
        }
    )
    parse = data.get("parse")
    if parse is None:
        return None
    wikitext = parse.get("wikitext", {}).get("*")
    if not wikitext:
        return None
    return wikitext


def _redirects_to(title, expected_target):
    """titleがWikipediaの正規のリダイレクトでexpected_targetへ解決されるかどうか。

    prop=extractsを使わない軽量な問い合わせ（リダイレクト解決の確認のみが目的）。
    """
    data = _api_get(
        {
            "action": "query",
            "titles": title,
            "redirects": "1",
        }
    )
    redirects = data.get("query", {}).get("redirects")
    if not redirects:
        return False
    return redirects[-1].get("to") == expected_target


def _pick_article(title):
    """判定対象の記事(タイトル・リード文・URL)を選ぶ。見つからなければNone。

    「{title} (漫画)」という曖昧さ回避表記は、Wikipedia編集者が意図的に「この作品の漫画版」
    を指すために作った表記なので、直接一致・リダイレクトのどちらで解決してもそのまま
    信用する。それ以外（`_search_titles`の関連度ランキングによる候補選定）は、
    「ワンピース」（衣類の記事）のような無関係な同名記事を拾ってしまうリスクがあるため、
    以下のいずれかで裏付けが取れる場合のみ信用する:
      - 検索結果がクエリ文字列と完全一致するタイトルである（曖昧さの介在余地が小さい）
      - クエリがWikipedia自身の正規リダイレクトでその候補へ解決する（編集者による
        意図的な対応付けであり、検索の関連度ランキングだけを根拠にしていない）
    どちらの裏付けも取れない場合は、無関係な記事を確信を持って誤答するより、
    記事なし（Noneを返し判定不能に倒す）を優先する（Issue #8・#9で確立した設計指針）。
    """
    direct = _fetch_extract(f"{title} (漫画)")
    if direct is not None:
        return direct

    candidates = _search_titles(title)
    if not candidates:
        return None

    chosen = next((c for c in candidates if "(漫画)" in c), candidates[0])
    if chosen != title and not _redirects_to(title, chosen):
        return None

    return _fetch_extract(chosen)


def judge(title, use_infobox=True):
    """タイトルからWikipedia記事を探し、連載中/完結を判定する。

    use_infobox=False にすると、Issue #12のインフォボックス補助経路を無効化し、本文解析
    のみで判定する（Issue #16: 補助経路のOn/Off比較計測専用のフラグ。判定条件そのものは
    変更しない）。
    """
    article = _pick_article(title)
    if article is None:
        return WikipediaJudgment(query=title, status=STATUS_NOT_FOUND)

    matched_title, extract, url = article
    status, evidence = _judge_extract(extract)

    if use_infobox and status == STATUS_UNKNOWN:
        wikitext = _fetch_wikitext(matched_title)
        if wikitext is not None:
            infobox_status, infobox_evidence = _judge_via_infobox(wikitext)
            if infobox_status is not None:
                status, evidence = infobox_status, infobox_evidence

    return WikipediaJudgment(
        query=title,
        status=status,
        matched_title=matched_title,
        url=url,
        evidence=evidence,
    )
