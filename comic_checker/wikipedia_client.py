import re
import unicodedata
from urllib.parse import quote

import requests

API_URL = "https://ja.wikipedia.org/w/api.php"
USER_AGENT = "comic-checker/0.1 (https://github.com/; local tool, contact via repo issues)"
REQUEST_TIMEOUT = 15

# 「連載中」が現在の連載状況を表すのは述語位置にあるときだけで、直後に助詞や名詞が続く形は
# 「連載していた期間」を指す修飾語か、他作品への言及である。除外する形は、M6-D-2（Issue #35）
# の実測57件で実際に誤爆したものだけに限定している（Issue #36）。未観測の形まで一律に落とすと、
# 正当な「連載中」を取りこぼした結果、別の文の弱シグナルに完結を奪われる（＝最も避けたい偽陽性
# に倒れる）ため、除外は実例のあるものに絞る方針を採る。
#   連載中から     … 大奥「連載中から多くの日本の漫画賞を受賞し」（受賞したのは連載期間中）
#   連載中は       … こち亀「単行本は連載中は全200巻」（連載していた期間の話）
#   連載中作品     … 鋼の錬金術師「同誌の連載中作品の中では最長連載」（他作品への言及）
#   連載中の＋数字 … 小田扉「『団地ともお』連載中の2016年より…在住」（時期の修飾）
# 「連載中の漫画である」のように後ろに名詞が続く正当な形を巻き込まないため、「の」は後続が
# 数字のときだけ除外する。「連載中だった」「連載中であった」は過去の状態を表す形で、現在
# 連載中であることを意味しうる余地が無いため、実例は未観測だが除外に含めている。
ONGOING_RE = re.compile(r"連載中(?!から|は|作品|の[0-9０-９]|だっ|であっ)|連載されている")

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

# --- タイトルの表記ゆれ吸収（M6-E-1 / Issue #30） ---------------------------------------
#
# Excelの入力タイトルは「買い物リスト」として人が手で書いたものであり、Wikipediaの記事名
# とは体系的にずれる。実データ73件で観測した3種類のずれに対応する。
#
# (1) 全角/半角: 「私の百合はお仕事です！」「ヤンキーＪＫクズハナちゃん」に対し、記事名は
#     「私の百合はお仕事です!」「ヤンキーJKクズハナちゃん」。Wikipediaの記事名は感嘆符・
#     疑問符・英数字を半角で立てる慣習があるが、`titles=`での参照はUnicode正規化を
#     してくれないため、こちらでNFKC正規化した変種も試す必要がある。
# (2) 購入メモの注記: 「カッコウの許嫁　(特装版ない場合通常版)」「触手魔術師の成り上がり
#     （電子版のみ【最終巻】5巻が発売済）」のように、括弧書きの注記が付く。
# (3) 版・シリーズ表記の後置: 「月曜日のたわわ　青版」「姫騎士がクラスメート！　ＴＨＥ
#     ＣＯＭＩＣ」のように、全角スペースや波ダッシュ以降が本編の記事名には含まれない。
#
# 開き括弧・閉じ括弧は全角/半角が混在し（「(特装版がない場合通常版）」のように片方だけ
# 全角の実例がある）、括弧が入れ子になることもある（「（電子版のみ【最終巻】5巻が発売済）」）。
# そのため単発の正規表現ではなく、括弧を含まない最内側のペアを消せなくなるまで繰り返す。
_INNERMOST_BRACKET_RE = re.compile(r"[（(【［\[][^（(【［\[）)】］\]]*[）)】］\]]")

# 全角スペース・タブ、および波ダッシュ（全角/半角/WAVE DASH）を後置注記の区切りとみなす。
# 半角スペース単独は区切りにしない（「after the rain」のように記事名の一部として半角
# スペースを含む正規のタイトルを壊してしまうため）。
_TRAILING_NOTE_SEPARATOR_RE = re.compile(r"[　\t]|\s*[~〜～]")

DISAMBIGUATION_SUFFIX = " (漫画)"

# リダイレクト/正規化の連鎖をたどる上限。Wikipediaは二重リダイレクトを解決しないため
# 実際には1〜2ホップで足りるが、循環リダイレクトで無限ループしないよう上限を設ける。
_MAX_REDIRECT_HOPS = 5

# 検索フォールバックで投げるクエリ数の上限。変種をすべて検索に回すとタイトル1件あたりの
# API呼び出しが増えすぎるため、原文と注記除去後の2つまでに絞る。
MAX_SEARCH_QUERIES = 2

# 「ワンピース」（衣類の記事）のように、作品名と同名の無関係な記事を掴んでしまうリスクへの
# 歯止め（Issue #8・#9で確立したfail-closed方針の延長）。曖昧さ回避表記「〜 (漫画)」は
# 編集者が明示的に漫画版を指して作った表記なのでそのまま信用するが、それ以外の経路
# （タイトル直参照・検索）で記事を採用するときは、その記事が漫画（またはコミカライズ元の
# 小説）に関するものであることをリード文で確認する。
ARTICLE_RELEVANCE_MARKERS = ("漫画", "マンガ", "コミック", "ライトノベル", "小説")

# 検索候補が「利用者の書いたタイトル＋サブタイトル」の形かを判定するときに、両者の境目と
# して認める文字。区切りを要求することで、単に同じ語で始まるだけの別作品を弾く。
SUBTITLE_SEPARATORS = "〜~～-－―—:：(（[［ 　"


def _normalize(text):
    """全角/半角・互換文字の違いを吸収した比較用の文字列を返す。"""
    return unicodedata.normalize("NFKC", text).strip()


def _strip_annotations(title):
    """括弧書きの注記を取り除く（入れ子・全角半角混在に対応）。"""
    previous = None
    text = title
    while previous != text:
        previous = text
        text = _INNERMOST_BRACKET_RE.sub("", text)
    return text.strip()


def _strip_trailing_note(title):
    """全角スペース・波ダッシュ以降の後置注記を取り除く。"""
    return _TRAILING_NOTE_SEPARATOR_RE.split(title, maxsplit=1)[0].strip()


def _title_variants(title):
    """記事を直接参照するときに試すタイトルの変種を、確信度の高い順に返す。

    原文（＝利用者が書いた通り）を最優先し、注記除去・後置注記除去と、確信度を下げる
    加工を後ろに置く。同じ文字列は先に出た順序を保って1回だけ返す。
    """
    variants = []

    def add(candidate):
        candidate = candidate.strip()
        if candidate and candidate not in variants:
            variants.append(candidate)

    for base in (title, _strip_annotations(title)):
        add(base)
        add(_normalize(base))
    for base in (title, _strip_annotations(title)):
        trimmed = _strip_trailing_note(base)
        add(trimmed)
        add(_normalize(trimmed))

    return variants


def _search_queries(variants):
    """検索フォールバックで投げるクエリを選ぶ。

    Wikipediaの全文検索は全角/半角の違いを自前で吸収するため、NFKC正規化した変種を
    別クエリとして投げても結果はほぼ変わらない。原文と、そこから注記を落としたものだけを
    最大MAX_SEARCH_QUERIES件まで使う。
    """
    queries = []
    for variant in variants:
        if _normalize(variant) not in {_normalize(q) for q in queries}:
            queries.append(variant)
        if len(queries) >= MAX_SEARCH_QUERIES:
            break
    return queries


def _is_about_manga(extract):
    return any(marker in extract for marker in ARTICLE_RELEVANCE_MARKERS)


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


def _has_ongoing_signal(extract):
    """走査範囲内に、明確な現在形の連載シグナルが1文でもあるか（M6-B-3）。"""
    return any(ONGOING_RE.search(sentence) for sentence in _split_sentences(extract))


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

    # M6-B-3（Issue #30）: CONTINUATION_VETO_REは同一文内しか見ないため、掲載誌の移籍を
    # 「Aまで連載。その後Bに移籍し、Cから連載されている。」と2文に分けて書く記事で、
    # 前半の文だけを見て完結と誤判定していた（実データで2件確認:
    # 「一緒に暮らしていいですか?」を誤って完結と断定、「サタノファニ」は本編の文が
    # 曖昧扱いでスキップされた結果、別作品『DEATHTOPIA』の連載終了文を掴んでいた）。
    # HUNTER×HUNTER（Issue #8）と同クラスの誤りが、文をまたいで再発していたことになる。
    # そのため、走査範囲（リード文＋最初のセクション）のどこかに明確な現在形の継続
    # シグナルがあれば、弱シグナル由来の完結は信用しない。
    # 強シグナル（COMPLETED_STRONG_RE＝「完結」）はこの無効化の対象外とする。Issue #8以来
    # 一貫して、無効化は弱シグナルにのみ適用する方針であり、「〜は完結した。アニメは
    # 連載中。」のような文章を壊さないため。
    sentences = _split_sentences(extract)
    has_ongoing_elsewhere = _has_ongoing_signal(extract)

    for sentence in sentences:
        ongoing = bool(ONGOING_RE.search(sentence))
        weak_completed = bool(COMPLETED_WEAK_RE.search(sentence)) and not CONTINUATION_VETO_RE.search(
            sentence
        )
        if weak_completed and has_ongoing_elsewhere and not ongoing:
            weak_completed = False
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


def _resolve_titles(titles):
    """複数タイトルの実在確認を1回のAPI呼び出しでまとめて行う。

    戻り値は {要求したタイトル: 実在する記事名}。存在しないタイトルはキーに現れない。
    リダイレクト（`redirects`）とタイトル正規化（`normalized`）の連鎖をたどることで、
    要求した文字列と最終的な記事名を対応付ける。

    タイトルごとに変種を1件ずつ問い合わせるとAPI呼び出しが変種の数だけ増えてしまうため、
    `titles=`のパイプ区切り（1リクエストあたり最大50件）でまとめて投げる。prop指定を
    付けない軽量な問い合わせなので、変種を増やしても応答サイズはほとんど増えない。
    """
    if not titles:
        return {}

    data = _api_get({"action": "query", "titles": "|".join(titles), "redirects": "1"})
    query = data.get("query", {})

    forward = {}
    for entry in list(query.get("normalized", [])) + list(query.get("redirects", [])):
        if entry.get("from") is not None and entry.get("to") is not None:
            forward[entry["from"]] = entry["to"]

    existing = {
        page["title"]
        for page in query.get("pages", {}).values()
        if "title" in page and "missing" not in page and "invalid" not in page
    }

    resolved = {}
    for title in titles:
        current = title
        for _ in range(_MAX_REDIRECT_HOPS):
            if current in existing:
                resolved[title] = current
                break
            following = forward.get(current)
            if following is None or following == current:
                break
            current = following
    return resolved


def _accept_article(page_title, trusted):
    """記事を取得し、判定対象として採用してよければ (タイトル, リード文, URL) を返す。

    trusted=True（曖昧さ回避表記「〜 (漫画)」で辿り着いた場合）は内容を確認せずに
    採用する。それ以外は無関係な同名記事を掴んでいないかを`_is_about_manga`で確認する。
    """
    article = _fetch_extract(page_title)
    if article is None:
        return None
    if trusted or _is_about_manga(article[1]):
        return article
    return None


def _pick_via_direct_lookup(probes):
    """タイトルの変種をそのまま記事名として参照し、最初に採用できた記事を返す。

    「{変種} (漫画)」という曖昧さ回避表記は、Wikipedia編集者が意図的に「この作品の
    漫画版」を指すために作った表記なので最優先で信用する。その次に変種そのものを試す。
    どちらもWikipedia側のリダイレクト解決を経由するため、「彼女、人見知ります」→
    「彼女、お借りします」のような編集者による意図的な対応付けもここで拾える。
    """
    resolved = _resolve_titles(probes)

    tried = set()
    for probe in probes:
        page_title = resolved.get(probe)
        if page_title is None or page_title in tried:
            continue
        tried.add(page_title)
        article = _accept_article(page_title, trusted=probe.endswith(DISAMBIGUATION_SUFFIX))
        if article is not None:
            return article
    return None


def _subtitle_prefix_match(candidate, variant):
    """候補名が「変種＋区切り記号＋サブタイトル」の形かどうか。

    **実データ73件では未発火（2026年時点）。** M6-E-1の計測では、解決できた行はすべて
    `_pick_via_direct_lookup`（タイトル直参照）で決着しており、この副題付き一致も
    `_pick_via_search`自体も一度も採用に至っていない。単体テストで挙動は固定して
    あるが、実戦での裏付けはまだ無い。将来のデータでここが発火した際は、
    どのタイトルがどの候補に一致したかと、その判定が正しかったかをIssueに記録すること
    （誤マッチが出た場合、区切り記号の集合SUBTITLE_SEPARATORSを狭めるのが最初の手当て）。

    利用者の入力（買い物リスト）には主題名しか書かれていない一方、Wikipediaの記事名は
    サブタイトル込みで立っていることがある（例: 「〜」で続く副題、「 -…-」形式）。
    区切り記号を挟んでいることを要求するので、「ギャルせん」に対して「ギャル文字」の
    ような別作品が一致することはない。
    """
    if len(candidate) <= len(variant) or not candidate.startswith(variant):
        return False
    return candidate[len(variant)] in SUBTITLE_SEPARATORS


def _pick_via_search(variants, already_probed):
    """全文検索の結果から記事を選ぶ。裏付けが取れない候補は採用しない。

    **実データ73件では未発火（2026年時点）。** 解決できた行はすべて直参照で決着し、
    この経路が採用に至ったことは一度も無い。直参照が変種（NFKC正規化形を含む）を
    総当たりするようになったため、検索が拾えて直参照が拾えない記事名は、
    「NFKC正規化しても入力と一致しないが、副題を除けば一致する」形に限られる。
    将来この経路が発火した際は、その判定根拠をIssueに記録すること。

    検索の関連度ランキングだけを根拠にすると、「ワンピース」（衣類の記事）のような
    無関係な同名記事を拾ってしまう（Issue #8・#9）。そのため、候補名が（NFKC正規化後に）
    変種そのもの・「変種 (漫画)」と一致するか、変種にサブタイトルが続く形である場合のみ
    採用する。リダイレクトによる裏付けは`_pick_via_direct_lookup`が先に済ませているため、
    ここでは重ねて確認しない。

    候補は上位1件だけでなく全件を見る。実データでは「釣って食べたいギャル澤さん」の
    記事が検索3位（1位は無関係な「ギャル」）に沈んでおり、上位1件しか見ないと
    完全一致する記事が存在するのに取りこぼしていた。
    """
    normalized_variants = {_normalize(variant) for variant in variants}
    exact = normalized_variants | {
        _normalize(f"{variant}{DISAMBIGUATION_SUFFIX}") for variant in variants
    }

    for query in _search_queries(variants):
        for candidate in _search_titles(query):
            # 直参照で既に解決を試みた記事名は、そこで採用されなかった（存在しない、
            # または漫画の記事ではなかった）ことが確定しているので取得し直さない。
            if candidate in already_probed:
                continue
            normalized_candidate = _normalize(candidate)
            if normalized_candidate not in exact and not any(
                _subtitle_prefix_match(normalized_candidate, variant)
                for variant in normalized_variants
            ):
                continue
            article = _accept_article(
                candidate, trusted=candidate.endswith(DISAMBIGUATION_SUFFIX)
            )
            if article is not None:
                return article
    return None


def _pick_article(title):
    """判定対象の記事(タイトル・リード文・URL)を選ぶ。見つからなければNone。

    確信度の高い順に、タイトル直参照 → 全文検索の順で試す。どちらでも裏付けが取れない
    場合は、無関係な記事を確信を持って誤答するより記事なし（None）を優先する
    （Issue #8・#9で確立した設計指針）。
    """
    variants = _title_variants(title)
    probes = [f"{variant}{DISAMBIGUATION_SUFFIX}" for variant in variants] + list(variants)
    return _pick_via_direct_lookup(probes) or _pick_via_search(variants, set(probes))


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
            # M6-B-3（Issue #30）: 本文に明確な現在形の連載シグナルがあるのに本文解析が
            # 決着しなかった場合、インフォボックスの終了系フィールドを根拠に完結と
            # 断定してはならない。
            # 実データ「サタノファニ」の終了日フィールドは
            # 「2023年34号<br />[[ヤンマガWeb]]：2023年9月6日 -」で、移籍後も継続中である
            # ことを末尾の「-」で表している。つまり「終了系フィールドが空でない＝完結」は
            # 移籍作品では成り立たない。本文と矛盾する以上、判定不能のまま維持する。
            # 逆方向（インフォボックスが連載中を示す）は本文の連載シグナルと矛盾しないため
            # 抑止しない。
            if infobox_status == "完結" and _has_ongoing_signal(extract):
                infobox_status = None
            if infobox_status is not None:
                status, evidence = infobox_status, infobox_evidence

    return WikipediaJudgment(
        query=title,
        status=status,
        matched_title=matched_title,
        url=url,
        evidence=evidence,
    )
