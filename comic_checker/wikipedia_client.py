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
#   連載中に       … ARIA「連載中にエニックスお家騒動が起こり」（連載していた期間中の話）
# 「連載中の漫画である」のように後ろに名詞が続く正当な形を巻き込まないため、「の」は後続が
# 数字のときだけ除外する。「連載中だった」「連載中であった」は過去の状態を表す形で、現在
# 連載中であることを意味しうる余地が無いため、実例は未観測だが除外に含めている。
#
# 「連載中に」はIssue #37の作業中に見つかった、#36と同クラスの取りこぼしである。それまでは
# 同じ記事（ARIA）の「1話完結形式で…連載された」が強シグナルとして先に決着していたため
# 表面化していなかった。#37でその強シグナルの誤爆を止めると、隠れていたこちらが露出して
# 『ARIA (漫画)』が`完結`→`連載中`に転ぶ（＝最も避けたい誤った断定）ため、#37と不可分の
# 修正として同じ変更に含めている。「連載中に」は副詞的用法しかなく述語位置になり得ない。
ONGOING_RE = re.compile(r"連載中(?!から|は|に|作品|の[0-9０-９]|だっ|であっ)|連載されている")

# 「完結」は日本語として「作品自体が終わった」ことをほぼ一意に意味する強いシグナルとして、
# そのまま信用する（CONTINUATION_VETO_REによる無効化の対象外）。
#
# ただし「完結」を含む複合語には、作品の終了とは無関係のもの・むしろ正反対の意味のものが
# あり、これらはそもそも強シグナルに一致させない（Issue #37）。無効化（veto）を強シグナルに
# 広げるのではなく一致自体を避けているのは、Issue #8以来の「無効化は弱シグナルにのみ適用
# する」方針を崩さないため（強シグナルをvetoの対象にすると「〜は完結した。アニメは連載中。」
# のような文章が壊れる）。除外する形はIssue #36と同じ方針で、実測で走査範囲内に実在を
# 確認できたものに限る。
#
# (1) 直前が「話」「回」… 各話が独立して終わる作品形式を指す定型句で、作品の終了とは無関係。
#     漫画記事に頻出し、以下が走査範囲内に実在した。
#       一話完結 … こち亀「基本的に一話完結だが」、絶体絶命でんぢゃらすじーさん、
#                  ケロロ軍曹、ギャグマンガ日和、いとしのムーコ、あたしンち、GOLDEN BOY
#       1話完結  … ARIA「2001年から2008年にかけて、1話完結形式で月刊誌に連載された」
#       各話完結 … アウターゾーン「基本的には各話完結であり」、こもれびの国
#       一回完結 … まほろばきっさ「…を一回完結形式で描く」
#     逆に「全100話完結」のように本当に作品の完結を意味しうる形は、走査範囲内には1件も
#     観測できなかったため、直前1文字だけで落とす形を安全とみなしている。
#     「完結する回」だけ後読みではなく先読み側に入っているのは、意味は上の4語と同じ
#     「各話が独立して終わる」なのに語順が逆で、`(?<![話回])`では捕まらないためである。
#     この形はIssueの起票時にも着手時の調査一覧にも挙がっておらず、修正後の実記事確認で
#     アウターゾーン「それらの世界の中だけで完結する回もあれば」が判定根拠に残っている
#     のを見つけて追加した（＝走査範囲内の実例あり。他の4語と同じ基準を満たす）。
#     「最終回で完結する」のように本当の完結を述べる形は「完結する」の直後に「回」が
#     来ないので巻き込まない。
# (2) 直前が「未」／直後が否定形 … 「未完結」「完結していない」「完結しない」「完結せず」は
#     完結の*否定*であり、完結シグナルになる余地が論理的に無い。走査範囲内の実例3件
#     （GOLDEN BOY・8マン インフィニティ・BUILD KING）はいずれも同じ文に「打ち切り」
#     「連載終了」を含んでいたため結論は偶然一致していたが、「まだ完結していない」とだけ
#     書かれた連載中の作品に当たれば誤った`完結`を断定する。Issue #36で「連載中だっ」
#     「連載中であっ」を実例なしに除外したのと同じ論法で含めている。
# (3) 直後が「させ」… 「ページ内の1コマを1コママンガとして完結させる」のような使役形は
#     作風の説明であって連載状況ではない。作者記事『吾妻ひでお』（Excelの`リングサイド
#     クレイジー`の行が着地する記事）で、実際にこの文が判定根拠に採用されていた。
#
# 「完結編」は除外しない。物語が実際に終わることを含意しうるうえ、走査範囲内の実例が
# 0件だったためである（実例のない曖昧な語には手を出さない、というIssue #36と同じ方針）。
COMPLETED_STRONG_RE = re.compile(r"(?<![話回未])完結(?!させ|し(?:ていな|な)い|せず|する回)")

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


# Issue #45: 作品の記事が存在しない入力は、Wikipediaのリダイレクトでその作者の記事に
# 着地することがある。作者記事のリード文は「…は、日本の漫画家。」なので`_is_about_manga`
# （「漫画」を含むか）を素通りしてしまい、そのまま採用された結果、記事中にある*別作品*の
# 連載状況を根拠に確信を持って誤答していた。M6-D-2（Issue #35）の実測ではカテゴリ2
# （作者記事へのリダイレクト・10件、期待は全件「記事なし」）のD率が9/10 = 90.0%で、
# 9件の根拠文は1件も入力作品の話ではなかった。
#
# 重要: これは「作品記事かどうかの門番」ではなく、既知の悪いパターンだけを名指しで
# 除外する装置である。正の証拠が取れない限り、従来の挙動を一切変えない（fail-open）。
# 判定条件は次の3段構え。
#   (a) リード文が「『」で始まるなら人物ではない。Wikipediaの作品記事は慣例的に
#       『タイトル』で始まる（実測: 作品記事200件中195件が該当、人物記事200件中0件）。
#       これは`魔法少女メルル`「『魔法少女メルル』は、日本の漫画家・ねこしたPONGによる
#       成人向け漫画」のような、作品記事なのに一次分類が「漫画家…」で始まる実在の形を
#       誤除外しないためのガードである。
#   (b) 一次分類は冒頭1文からのみ読む。走査範囲全体を見ると、記事の後方にある無関係な
#       「日本の漫画家である〜」を拾いうるため。
#   (c) 一次分類の先頭セグメント（「・」等で区切った1つ目）の語尾が「家」なら人物記事と
#       みなす。人物記事の一次分類は`漫画家`/`男性漫画家`/`女性漫画家`/`風刺漫画家`/
#       `漫画家・歌手`（押切蓮介）/`漫画家・イラストレーター`のように語尾が一貫して
#       「家」になる一方、作品記事の一次分類は`漫画`/`漫画作品`/`少年漫画`/`4コマ漫画`/
#       `推理漫画`/`テレビアニメ作品`等で、「家」で終わるものは1件も無い。
#
# 【`_is_novel_primary()`と既定値を揃えてはならない】両者は`_PRIMARY_TYPE_RE`を共有するが、
# 判定できないときの倒し方が意図的に逆である。`_is_novel_primary()`は判定不能時にfail-closed
# （小説主体とみなして主語チェックを要求する）だが、この関数は必ずfail-openにすること。
# 根拠となる実測値（400記事、`generator=search`で取得。手法はERRORS.md参照）:
#   - 作品記事200件のうち**35件は冒頭文に「日本の<種別>」が無い**（`陰陽師 (漫画)`
#     「夢枕獏の小説『陰陽師』を原作とする岡野玲子の漫画。」、`ベルセルク`など）。
#     ここをfail-closedにすると、この35件が軒並み「記事なし」に落ちる。
#   - 本条件による作品記事の誤除外は200件中**0件**。
#   - 人物記事の検出は200件中**163件**。残り37件は一次分類が`アイドル`/`女性声優`/
#     `アニメ監督`/`漫画家ユニット`等で「家」で終わらないもの。漫画タイトルのリダイレクト先に
#     なる母集団ではないので、fail-openの方針どおり検出しないままでよい。
PERSON_TYPE_SUFFIX = "家"
WORK_TITLE_PREFIX = "『"
_PRIMARY_TYPE_SEPARATOR_RE = re.compile(r"[・、／/]")


def _is_person_article(extract):
    """リード文から、この記事が作品ではなく人物（漫画家等）の記事かを判定する。

    判定できない場合はFalse（人物ではない）を返す。上のコメントの「fail-openにすること」
    の実装であり、この既定値を変えてはならない。
    """
    stripped = extract.lstrip()
    if stripped.startswith(WORK_TITLE_PREFIX):
        return False
    # 冒頭1文が切り出せない（空文字・句点が1つも無い）場合は、リード文の形を確認できて
    # いないので人物とはみなさない。句点が無いときに全文を1文として扱うと、走査範囲の
    # 後方にある「日本の漫画家…」を拾って誤除外しうるため、ここでも倒す先はfail-open側。
    end = stripped.find("。")
    if end == -1:
        return False
    match = _PRIMARY_TYPE_RE.search(stripped[: end + 1])
    if match is None:
        return False
    first_segment = _PRIMARY_TYPE_SEPARATOR_RE.split(match.group(1))[0]
    return first_segment.endswith(PERSON_TYPE_SUFFIX)


# Issue #51 (M6-A-2): カテゴリ3 ——「作品の記事が存在しない入力が、Wikipediaのリダイレクトで
# *親作品*の記事に着地し、親作品の連載状況を根拠に確信を持って誤答する」系統への対処。
# #45で潰したカテゴリ2（作者記事）と構造は同じだが、着地先が体裁の正しい作品記事なので
# `_is_person_article()`では原理的に弾けない。実分布（#47拡張群72行）では2件（`彼女、
# 人見知ります`・`お隣の天使様に…件　after the rain`）で、どちらもD（確信を持った誤答）。
#
# 【`_accept_article()`のuntrusted経路にのみ接続してある】trusted経路（「〜 (漫画)」で
# 辿り着いた場合）は#45と同じ理由で素通しにする。編集者が「これは作品の記事だ」と明示した
# 表記なので、そこに別作品が来ることはなく、誤除外の機会だけが増える。
#
# 判定は「ゲート」と「照合」の2段。どちらも実測（着地63行）で外せないことを確認済み。
#   ゲート: NFKC(接尾辞を除いた着地先タイトル) != NFKC(入力原文) のときだけ照合に進む。
#     - **変種ではなく入力原文と比べる**。`[47]`（本編）と`[55]`（スピンオフ）は同じ記事に
#       着地するので、分ける鍵は入力側にしかない。変種と比べると`[55]`の後置注記除去変種が
#       着地先と一致してゲートが閉じ、規則が発動しなくなる。
#     - 曖昧さ回避接尾辞は除く。`日常`→`日常 (漫画)`のように入力が正しくても常にゲートが
#       開く行が生まれるため（実測7行）。`(漫画)`は`_pick_article()`自身がprobeとして
#       組み立て`_accept_article()`が信頼している表記なので、ここで差異扱いすると一貫しない。
#   照合: リード文の1文ごとに、入力タイトルが『』に囲まれ、かつ同じ文に派生作品マーカーが
#     あるかを見る。**『』内と入力はNFKC完全一致でなければならない。** 部分一致にすると
#     実測で2件壊れる: (1)`[47]`の入力は`[55]`の『』内の前方部分文字列なのでゲートだけが
#     頼りになる、(2)`[111]`（精霊の守り人→守り人シリーズ・期待は完結）が
#     『ジン～アニメ精霊の守り人外伝～』に引っかかり、**ゲートが開いているので守れない**。
#
# 【なぜ言及の有無を条件にしないか】言及は「入力の作品である」証拠にも「別作品である」
# 証拠にもならない。`幽遊白書`は着地先`幽☆遊☆白書`のリードに文字列として現れず（装飾記号）、
# 逆に`彼女、人見知ります`は現れる。倒す向きが逆になるので、*どういう文脈で*言及されて
# いるかだけが情報を持つ。
#
# 【fail-open】`_is_person_article()`と同じく、既知の悪いパターンだけを名指しで除外する
# 装置である。正の証拠が取れない限り従来の挙動を変えない。既定値をfail-closedにすると、
# 別名・略称・シリーズ着地（ワンピース→ONE PIECE、こち亀→こちら葛飾区亀有公園前派出所、
# 精霊の守り人→守り人シリーズ等）がまとめて落ちる。
# 採用語彙。Issue #51 の敵対群調査（1,462行）で、実文から回収した候補のうち発動実績が
# あったものだけを採る。候補にあった`派生`・`スピンアウト`は**1,462行で発動0件**だった
# ため採らない（#36 の除外リストと同じ方針で、観測された実例のある形だけを名指しする）。
# 不採用にした語と理由は Issue #51 に記録してある。とくに`コミカライズ`は入力作品*そのもの*
# の説明として現れるため、加えると`[47]`が誤除外になる。
DERIVATIVE_WORK_MARKERS = ("スピンオフ", "続編", "外伝", "番外編", "前日譚")
_QUOTED_WORK_RE = re.compile(r"『([^』]*)』")

# 【条件A】マーカーが*その言及を修飾している*ことを要求する。「文中のどこかにマーカーが
# あれば発動」では足りないことが、敵対群の本調査（作品記事150件・被リダイレクト1,462行）
# で確定した。7語の候補語彙で掃くと32件発動し、人手ラベルで10件が(a)＝誤除外だった。
# 内訳は「マーカーが入力名の一部」1件・「マーカーが後方にある共起」3件・「併合記事型」5件・
# 「記事名の略称」1件で、前2者と最後の1件は条件Aで消える。
#
# MARKER_MAX_DISTANCE は**実データの距離分布から決めた。決め打ちではない。**
# マーカー末尾から『までの字数を、人手ラベル別に並べると:
#   (b) 検出すべき: 1, 2, 2, 2, 3, 3, 3, 4, 5, 5, 9, 11 ‖ 27, 51, 66, 102
#   (a) 誤除外    : 3 ‖ 15, 16, 27, 48, 92（＋前方にマーカーが無いもの4件）
# **11 と 15 の間が唯一の切れ目**なので 12 とした。10 にすると(b)の1件（距離11）を落とし、
# 15 にすると(a)の1件（距離15）が残る。将来この値を動かすときは、同じ距離分布を測り直して
# 切れ目が動いたことを示すこと。「キリのいい数字に揃える」類の変更をしてはならない。
MARKER_MAX_DISTANCE = 12

# 【条件B】着地先が「複数の作品を併せて解説する記事」なら発動させない。
# 条件Aだけでは救えない形があるため必要になった。`グラップラー刃牙`の
# 「続編として『バキ』、…があり本項ではこれらも併せて解説する。」は、マーカー「続編」が
# 『バキ』の3字前にあって条件Aを全て満たすが、記事が各作品の連載状況を実際に解説している
# ので入力`バキ`に対して採用してよい行（(a)）である。
#
# 語彙は150記事のリード＋最初のセクションから**実文で回収した**（決め打ちしていない）。
# 回収元の記事名を残す:
#   本項では/本項目では : グラップラー刃牙・賭博黙示録カイジ・CLANNAD (ゲーム)・
#                        おジャ魔女どれみ・ふたりはプリキュア・魔法つかいプリキュア!
#   の総称              : 最遊記シリーズ・ゲゲゲの鬼太郎
#   も併せて/併せて取り扱/併せて解説 : ふたりはプリキュア・Yes!プリキュア5・グラップラー刃牙
#   についても解説/についても記述     : 賭博黙示録カイジ・CLANNAD (ゲーム)
#   詳述するものとする/ここでは       : 魔法つかいプリキュア!・ダンボール戦機
#
# 【重要・この条件は安全側に倒れない】語彙が当たらなくなる（＝併合宣言を見落とす）と
# 併合記事で発動してしまい、**誤除外が出る危険側**に倒れる。過剰に当たった場合は発動しなく
# なるだけで取りこぼし（安全側）。Wikipediaの編集で言い回しが変わりうるので、
# `docs/known_limitations.md` に記載してある。語彙を削るときは特に注意すること。
MERGED_COVERAGE_MARKERS = (
    "本項では",
    "本項目では",
    "の総称",
    "も併せて",
    "併せて取り扱",
    "併せて解説",
    "についても解説",
    "についても記述",
    "詳述するものとする",
    "ここでは",
)


def _declares_merged_coverage(extract):
    """記事が「複数の作品を併せて解説する」と宣言しているか（条件B）。"""
    if not extract:
        return False
    return any(marker in extract for marker in MERGED_COVERAGE_MARKERS)


def _marker_modifies_mention(sentence, mention, markers, max_distance,
                             require_outside_quote, require_before):
    """マーカーがこの『』の言及を修飾しているか（条件A）。"""
    for marker in markers:
        position = sentence.find(marker)
        while position != -1:
            end = position + len(marker)
            inside_quote = mention.start() <= position < mention.end()
            before = end <= mention.start()
            if (not (require_outside_quote and inside_quote)
                    and not (require_before and not before)):
                if before:
                    distance = mention.start() - end
                elif inside_quote:
                    distance = 0
                else:
                    distance = position - mention.end()
                if max_distance is None or distance <= max_distance:
                    return True
            position = sentence.find(marker, position + 1)
    return False


# 末尾の丸括弧1組だけを落とす。`(漫画)`固定にしないのは`風光る (渡辺多恵子の漫画)`のような
# 形があるため。入れ子や本文中の括弧まで落とさないよう、末尾かつ1組に限定している。
_DISAMBIGUATION_SUFFIX_RE = re.compile(r"\s*[（(][^（()）]*[)）]\s*$")


def _strip_disambiguation_suffix(page_title):
    """記事名から曖昧さ回避の接尾辞（「 (漫画)」等）を取り除く。"""
    return _DISAMBIGUATION_SUFFIX_RE.sub("", page_title).strip()


def _mentions_as_derivative_work(extract, input_title, markers=DERIVATIVE_WORK_MARKERS,
                                 max_distance=MARKER_MAX_DISTANCE,
                                 require_outside_quote=True, require_before=True,
                                 skip_merged_articles=True):
    """リード文が入力タイトルを「派生作品」として紹介しているかを判定する。

    Trueなら、この記事は入力タイトルの作品についての記事ではない（＝別作品の記事に
    着地している）。判定できない場合はFalse（上のコメントの「fail-open」の実装であり、
    この既定値を変えてはならない）。

    条件A（`max_distance` / `require_outside_quote` / `require_before`）と条件B
    （`skip_merged_articles`）は**それぞれ独立に無効化できる**。どの条件がどの行を
    落としているかをコーパス調査で切り分けるためで、既定値のまま使うのが出荷時の挙動。
    `markers`も同じ理由で引数にしてある（語彙の候補を差し替えながら同じ関数で掃く）。
    """
    if not extract or not input_title:
        return False
    normalized_title = _normalize(input_title)
    if not normalized_title:
        return False
    if skip_merged_articles and _declares_merged_coverage(extract):
        return False
    for sentence in _split_sentences(extract):
        if not any(marker in sentence for marker in markers):
            continue
        for mention in _QUOTED_WORK_RE.finditer(sentence):
            if _normalize(mention.group(1)) != normalized_title:
                continue
            if _marker_modifies_mention(sentence, mention, markers, max_distance,
                                        require_outside_quote, require_before):
                return True
    return False


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


def _lands_on_a_different_work(page_title, extract, input_title):
    """着地した記事が、入力タイトルとは*別の作品*についての記事かを判定する（Issue #51）。

    ゲート（着地先タイトルが入力原文と違うときだけ照合に進む）と、リード文での言及の
    仕方を見る照合の2段。詳細は`_mentions_as_derivative_work`の上のコメントを参照。

    ゲートを**変種ではなく入力原文**と比べるのが要点である。`お隣の天使様に…件`（本編・
    正常系）と`お隣の天使様に…件　after the rain`（スピンオフ）は**同じ記事に着地する**
    ので、記事側の情報だけでは分けられない。分ける鍵は入力側にしかない。
    """
    if _normalize(_strip_disambiguation_suffix(page_title)) == _normalize(input_title):
        return False
    return _mentions_as_derivative_work(extract, input_title)


def _accept_article(page_title, trusted, input_title):
    """記事を取得し、判定対象として採用してよければ (タイトル, リード文, URL) を返す。

    trusted=True（曖昧さ回避表記「〜 (漫画)」で辿り着いた場合）は内容を確認せずに
    採用する。それ以外は無関係な同名記事を掴んでいないかを`_is_about_manga`で、
    作者の記事に着地していないかを`_is_person_article`で（Issue #45）、入力とは別作品の
    記事に着地していないかを`_lands_on_a_different_work`で確認する（Issue #51）。

    人物記事チェックと別作品チェックを信頼経路（trusted=True）に適用しないのは意図的で
    ある。「〜 (漫画)」はWikipedia編集者が「これは作品の記事だ」と明示した表記であり、
    そこに人物記事が来ることはない。得るものが無い一方で、これらの判定の偽陽性
    （正しい記事を弾いて記事なしに落とす）だけを新たに晒すことになる。
    """
    article = _fetch_extract(page_title)
    if article is None:
        return None
    if trusted:
        return article
    if not _is_about_manga(article[1]) or _is_person_article(article[1]):
        return None
    if _lands_on_a_different_work(article[0], article[1], input_title):
        return None
    return article


def _pick_via_direct_lookup(probes, input_title):
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
        article = _accept_article(
            page_title, trusted=probe.endswith(DISAMBIGUATION_SUFFIX),
            input_title=input_title,
        )
        if article is not None:
            return article
    return None


def _subtitle_prefix_match(candidate, variant):
    """候補名が「変種＋区切り記号＋サブタイトル」の形かどうか。

    **発火実績あり（2026-07-28、Issue #51の調査で確認）。** 以前のコメントは「実データ
    73件では未発火」としていたが、これは実運用Excelの73行についての話で、その記述自体は
    今も正しい。#51で#35の回帰群22行を`_pick_article()`ごと再実行したところ、**この経路で
    2件が着地し、どちらも正しい記事だった**。

      `バジリスク`    -> `バジリスク 〜甲賀忍法帖〜`        （期待どおり `完結`）
      `フラジャイル`  -> `フラジャイル 病理医岸京一郎の所見`（期待どおり `連載中`）

    どちらも入力が主題名だけで、記事名が区切り記号（`〜`・半角スペース）を挟んで副題を
    持つ形である。想定していた形がそのまま出た。**誤マッチは0件。** 区切り記号の集合
    `SUBTITLE_SEPARATORS`を狭める必要は現時点で無い（誤マッチが出た場合はそこを狭めるのが
    最初の手当てになる）。

    利用者の入力（買い物リスト）には主題名しか書かれていない一方、Wikipediaの記事名は
    サブタイトル込みで立っていることがある（例: 「〜」で続く副題、「 -…-」形式）。
    区切り記号を挟んでいることを要求するので、「ギャルせん」に対して「ギャル文字」の
    ような別作品が一致することはない。
    """
    if len(candidate) <= len(variant) or not candidate.startswith(variant):
        return False
    return candidate[len(variant)] in SUBTITLE_SEPARATORS


def _pick_via_search(variants, already_probed, input_title):
    """全文検索の結果から記事を選ぶ。裏付けが取れない候補は採用しない。

    **発火実績あり（2026-07-28、Issue #51の調査で確認）。** 実運用Excelの73行では依然として
    未発火で、そこは以前のコメントのとおり。ただし#35の回帰群22行では**この経路で2件が
    着地し、どちらも正しかった**（`バジリスク`・`フラジャイル`。詳細は
    `_subtitle_prefix_match`のコメント）。直参照が変種（NFKC正規化形を含む）を総当たり
    するので、検索が拾えて直参照が拾えない記事名は「NFKC正規化しても入力と一致しないが、
    副題を除けば一致する」形に限られる、という見立ても実データで裏付けられた形になる。

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
                candidate, trusted=candidate.endswith(DISAMBIGUATION_SUFFIX),
                input_title=input_title,
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
    return (_pick_via_direct_lookup(probes, title)
            or _pick_via_search(variants, set(probes), title))


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
