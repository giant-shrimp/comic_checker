from unittest.mock import MagicMock, patch

from comic_checker.wikipedia_client import (
    STATUS_NOT_FOUND,
    STATUS_UNKNOWN,
    WikipediaJudgment,
    _judge_extract,
    judge,
)

ONE_PIECE_EXTRACT = (
    "『ONE PIECE』（ワンピース）は、尾田栄一郎による日本の漫画作品。"
    "『週刊少年ジャンプ』（集英社）にて1997年34号から連載中。"
)

SHINGEKI_EXTRACT = (
    # 実際のWikipedia記事の冒頭文は、漫画が原作でアニメ化・小説化もされていることを
    # 列挙する形式（「…日本の漫画、およびそれを原作としたアニメ、小説（ライトノベル）、
    # ゲーム、映画などの派生作品。」）になっている。一次分類はあくまで「漫画」であり、
    # 派生作品としての「小説」の語が出現するだけで判定不能に倒れてはならない。
    "『進撃の巨人』は、諫山創による日本の漫画、およびそれを原作としたアニメ、"
    "小説（ライトノベル）、ゲームなどの派生作品。"
    "『別冊少年マガジン』（講談社）にて2021年4月9日発売の5月号をもって完結した。"
)

DANDADAN_EXTRACT = (
    "『ダンダダン』は、龍幸伸による日本の漫画作品。"
    "『少年ジャンプ+』（集英社）にて2021年4月6日から連載中。"
)

AO_NO_HAKO_EXTRACT = (
    "『アオのハコ』は、三浦糀による日本の漫画作品。"
    "『週刊少年ジャンプ』（集英社）にて2021年19号から2026年33号まで連載された。"
)

TENSURA_EXTRACT = (
    "『転生したらスライムだった件』は、伏瀬による日本のライトノベル、およびそれを"
    "原作とするメディアミックス作品。"
    "原作のライトノベルは全21巻で完結した。"
    "川上泰樹による漫画版は『月刊少年シリウス』（講談社）にて連載中で、32巻まで刊行されている。"
)

TENSURA_NO_MANGA_SENTENCE_EXTRACT = (
    "『例のラノベ』は、某作者による日本のライトノベル、およびそれを原作とする"
    "メディアミックス作品。"
    "原作のライトノベルは全10巻で完結した。"
    "コミカライズも展開されている。"
)

# 実際の記事から取得した文言（休載節）そのまま。「週刊連載を終了」という語だけを見ると
# COMPLETED_WEAK_REにマッチするが、文の後半で「継続」を発表しており、作品自体は
# 終わっていない（連載頻度・掲載形態が変わっただけ）。誤って「完結」と判定していた
# 実際のバグの回帰テスト。
HUNTER_HUNTER_EXTRACT = (
    "『HUNTER×HUNTER』（ハンター×ハンター）は、冨樫義博による日本の漫画。"
    "『週刊少年ジャンプ』にて1998年14号より連載を開始。"
    "同年12月26日発売の2023年4・5合併号の第400話を最後に週刊連載を終了し、"
    "第401話以降は冨樫の体調を考慮して「週刊連載ではない掲載形態での継続」を発表した。"
)

# M6-D-1（Issue #11）の実データ調査で確認したケース。「連載されている」という、既存の
# フィクスチャ（「連載中」）とは異なる現在形の表現で連載中と判定できることを確認する。
JOJO_EXTRACT = (
    "『ジョジョの奇妙な冒険』は、荒木飛呂彦による日本の漫画作品。"
    "集英社の『週刊少年ジャンプ』に1986年から2004年まで、2005年からは『ウルトラジャンプ』"
    "に長期にわたって連載されている。"
)

# M6-D-1で確認したケース。作者急逝後も連載が続いているという実世界の事例で、通常の
# 「連載中」判定がそのまま機能することの確認（regexの挙動としては目新しくないが、
# 実際に確認した著名な事例として固定しておく）。
BERSERK_EXTRACT = (
    "『ベルセルク』は、三浦建太郎による日本の漫画作品。"
    "白泉社発行の漫画誌『ヤングアニマル』にて連載中。"
)

# M6-D-1で確認したケース。「まで連載され、その後も約年1回のペースで新作が作られている」
# という文言は、HUNTER×HUNTERと表面的には似た構造（週刊連載終了+その後の展開への言及）
# だが、意図的にCONTINUATION_VETO_REの対象にしていない。週刊連載という一つの物語は
# 完結しており、その後の新作は不定期のアニバーサリー的な追加作品という性質の違いが
# あるため（詳細はCLAUDE.md参照）。この判断そのものが変わらないことを保証する回帰テスト。
KOCHIKAME_EXTRACT = (
    "『こちら葛飾区亀有公園前派出所』は、秋本治による日本の漫画作品。"
    "『週刊少年ジャンプ』において1976年42号から2016年42号まで連載され、"
    "その後も約年1回のペースで新作が作られている。"
)

# M6-D-1で確認したケース。「第一部」「第二部」という語は掲載号の内訳表記であり、
# シリーズの一部だけの完結（M6-B-2で懸念されたパターン）ではない。将来M6-B-2に
# 対応する際、この正当な完結判定を壊さないことを保証する回帰テスト。
DEATH_NOTE_EXTRACT = (
    "『DEATH NOTE』は、大場つぐみ・小畑健による日本の漫画作品。"
    "『週刊少年ジャンプ』（集英社、第一部：2004年1号 - 2005年11号、"
    "第二部：2005年20号 - 2006年24号）において、2003年12月から2006年5月まで連載された。"
)

# M6-B-1: 実際の記事（「ゴタ消し -示談交渉人 白井虎次郎-」）から取得した文言そのまま。
# 「打ち切り」を完結として扱う仕様の回帰テスト。判定根拠に「打ち切り」だった事実が
# そのまま残ることも確認する（新ステータスは追加しない仕様のため）。
GOTAKESHI_EXTRACT = (
    "『ゴタ消し -示談交渉人 白井虎次郎-』は、真鍋昌平による日本の漫画作品。"
    "2011年21・22合併号での同誌の休刊をもって連載は打ち切りとなった。"
)

# M6-B-1: 「打ち切りの危機に瀕したが連載は継続した」のような、打ち切られなかった文脈の
# 回帰テスト。COMPLETED_WEAK_REの「打ち切り」は、同一文に継続を示す語（継続/再開/
# 引き続き等）があれば無効化される（Issue #8の設計指針をそのまま適用）。
# 意図的に他の連載中/完結シグナルを含めていない（無効化が効かなくても別の文で
# たまたま正しい結果になる、という誤ったテストにならないようにするため）。
NEAR_CANCELLATION_EXTRACT = (
    "『例の作品』は、某作者による日本の漫画作品。"
    "人気低迷により打ち切りの危機に瀕したが、読者アンケートの巻き返しにより連載は継続した。"
)

# 幽☆遊★白書のケース: COMPLETED_WEAK_RE（「まで連載された」）が実際に完結を意味する
# 場合は、継続を示す語が無ければ従来通り完結と判定できることの確認（HUNTER×HUNTERの
# 修正が過剰に厳格化していないことの回帰テスト）。
YU_YU_HAKUSHO_EXTRACT = (
    "『幽☆遊☆白書』は、冨樫義博による日本の漫画作品。"
    "『週刊少年ジャンプ』（集英社）にて、1990年51号から1994年32号にかけて連載された。"
)

# Issue #13の実データ調査で確認したケース（is_multimedia=False、実際のWikipedia記事の
# 冒頭文+「概要」節そのまま）。本編自身の完結文「2017年3月23日まで毎週木曜更新で連載。」
# は「まで」と「連載」の間に語が挟まるため、当時のCOMPLETED_WEAK_REでは取りこぼされて
# いた。その結果、本来は対象外のはずの番外編の連載終了文「番外編「とんかつDJアゲ太郎
# B面〜ファッショニスタへの道〜」が本編と並行で連載された。」が代わりに本編の判定文として
# 採用されてしまっていた（is_multimedia=False経路はMANGA_MARKERS等の主語チェックを
# 行わないため）。この回では本編・番外編どちらも完結済みだったため結果的にステータス自体は
# 正しかったが、両者の連載状況が食い違う作品では誤ったステータスを確信を持って返しうる、
# 実在する不具合だった。SPINOFF_MARKERSによる除外と、「まで...連載」の間隔緩和の
# 両方を確認する回帰テスト。
TONKATSU_DJ_AGETARO_EXTRACT = (
    "『とんかつDJアゲ太郎』（とんかつディージェイアゲたろう）は、イーピャオと"
    "小山ゆうじろうによる日本の漫画。\n\n\n"
    "== 概要 ==\n"
    "とんかつ屋の跡取り息子揚太郎がクラブカルチャーに衝撃を受け、とんかつ屋とDJに"
    "数多くの共通点を見出しながら、その両方を目指して奮闘するギャグ漫画。"
    "『少年ジャンプ+』（以下『J+』、集英社）2014年9月22日より2017年3月23日まで"
    "毎週木曜更新で連載。\n"
    "『J+』創刊作品の一つであり、『J+』から最初に単行本化された作品の一つでもある。"
    "『カラダ探し』などと並び初期『J+』を彩り、2016年には『J+』作品初となる"
    "テレビアニメが放送された。2020年10月30日には実写映画が公開された。\n"
    "制作においては、各話のタイトル・人物名は原案担当のイーピャオが考え、それに"
    "漫画担当の小山がセリフを肉付けしていくという形が採られている。画やセリフなどは"
    "ウェブコミックとしての読みやすさを重視して描かれている。単行本ではDJのYummyが"
    "クラブカルチャーについて解説している。\n"
    "『MEN'S NON-NO』（集英社）2015年1月号から12月号まで、番外編"
    "「とんかつDJアゲ太郎 B面〜ファッショニスタへの道〜」が本編と並行で連載された。"
    "また、『週刊少年ジャンプ』（集英社）2015年4・5合併号と12号に出張読切が"
    "掲載された。\n\n\n"
)

# 合成フィクスチャ（実データでは未発見）。本編は連載中、番外編は完結済みという、
# TONKATSU_DJ_AGETARO_EXTRACTとは逆に食い違うパターン。番外編の完結文を本編より先に
# 配置し、番外編の文につられて誤った「完結」を返さないこと（スキップされ、本編自身の
# 「連載中」文まで走査が続くこと）を確認する。
SPINOFF_COMPLETED_MAIN_ONGOING_EXTRACT = (
    "『例の連載作品』は、某作者による日本の漫画。"
    "番外編「例の連載作品外伝」は2021年に連載された。"
    "『週刊少年サンプル』（サンプル社）にて2020年から連載中。"
)


def test_one_piece_is_ongoing():
    status, evidence = _judge_extract(ONE_PIECE_EXTRACT)
    assert status == "連載中"
    assert "連載中" in evidence


def test_shingeki_no_kyojin_is_completed():
    # 回帰テスト: 冒頭文が「小説」を派生作品として列挙しているだけの漫画原作作品を、
    # 一次分類(「日本の漫画」)で正しく単一メディア扱いし、判定不能に倒さないこと。
    status, evidence = _judge_extract(SHINGEKI_EXTRACT)
    assert status == "完結"
    assert "完結した" in evidence


def test_dandadan_is_ongoing():
    status, evidence = _judge_extract(DANDADAN_EXTRACT)
    assert status == "連載中"


def test_ao_no_hako_past_tense_serialization_is_completed():
    # 「〜まで連載された」という過去形は、現在形の「連載中」と誤判定してはならない。
    status, evidence = _judge_extract(AO_NO_HAKO_EXTRACT)
    assert status == "完結"
    assert "まで連載された" in evidence


def test_tensura_manga_status_is_not_confused_with_novel_status():
    # 回帰テスト: 原作ライトノベルは完結しているが、漫画(コミカライズ)は連載中。
    # 単純な語検出だと原作小説側の「完結した」を拾ってしまうリスクがある。
    status, evidence = _judge_extract(TENSURA_EXTRACT)
    assert status == "連載中"
    assert "漫画" in evidence


def test_hunter_hunter_weekly_serialization_ending_is_not_completed():
    # 回帰テスト（実際に本番で誤判定したケース）: 「週刊連載を終了」だけを見て完結と
    # 判定していたが、同じ文で「継続」を発表しており、実際には連載中（休載を繰り返して
    # いるだけで終了していない）。判定不能側に倒すのが正しい（記事内に「連載中」
    # 「連載されている」という明確な現在形の表現が無いため、連載中と断定はできない）。
    status, evidence = _judge_extract(HUNTER_HUNTER_EXTRACT)
    assert status == STATUS_UNKNOWN


def test_yu_yu_hakusho_still_completed_without_continuation_veto():
    # HUNTER×HUNTERの修正（継続の語があるとCOMPLETED_WEAK_REを無効化する）が、
    # 継続を示す語の無い正当な完結判定まで壊していないことの確認。
    status, evidence = _judge_extract(YU_YU_HAKUSHO_EXTRACT)
    assert status == "完結"
    assert "連載された" in evidence


def test_tonkatsu_dj_agetaro_main_completion_not_confused_with_spinoff():
    # 回帰テスト（実際に本番で誤判定していたケース、Issue #13）: 本編自身の完結文
    # 「まで毎週木曜更新で連載。」は当時取りこぼされ、代わりに番外編の連載終了文が
    # 本編の判定文として採用されていた。SPINOFF_MARKERSによる除外と「まで...連載」の
    # 間隔緩和の両方が効いて、正しく本編自身の文から完結と判定できることを確認する。
    status, evidence = _judge_extract(TONKATSU_DJ_AGETARO_EXTRACT)
    assert status == "完結"
    assert "番外編" not in evidence
    assert "毎週木曜更新で連載" in evidence


def test_spinoff_completion_does_not_override_main_series_ongoing_status():
    # 合成フィクスチャ（実データでは未発見）: 本編が連載中、番外編が完結済みという、
    # とんかつDJアゲ太郎の実例とは逆に食い違うパターン。番外編の完結文につられて
    # 誤って「完結」を返さないことを確認する。
    status, evidence = _judge_extract(SPINOFF_COMPLETED_MAIN_ONGOING_EXTRACT)
    assert status == "連載中"
    assert "番外編" not in evidence


def test_jojo_is_ongoing_via_present_progressive_form():
    # 「連載されている」という、既存フィクスチャの「連載中」とは異なる現在形表現でも
    # 連載中と判定できることの確認（M6-D-1）。
    status, evidence = _judge_extract(JOJO_EXTRACT)
    assert status == "連載中"
    assert "連載されている" in evidence


def test_berserk_is_ongoing():
    # 作者急逝後も連載が継続している実世界の事例（M6-D-1）。
    status, evidence = _judge_extract(BERSERK_EXTRACT)
    assert status == "連載中"


def test_kochikame_original_serialization_completion_is_not_vetoed():
    # 回帰テスト（M6-D-1・Issue #11）: 「まで連載され、その後も新作が作られている」は
    # HUNTER×HUNTERと表面的に似た構造だが、意図的にCONTINUATION_VETO_REの対象にして
    # いない。週刊連載という一つの物語は完結しており、その後の新作は不定期の
    # アニバーサリー的な追加作品という性質の違いがあるため（詳細はCLAUDE.md参照）。
    status, evidence = _judge_extract(KOCHIKAME_EXTRACT)
    assert status == "完結"
    assert "新作が作られている" in evidence


def test_death_note_part_numbers_are_not_mistaken_for_partial_completion():
    # 回帰テスト（M6-D-1）: 「第一部」「第二部」は掲載号の内訳表記であり、シリーズの
    # 一部だけの完結ではない。将来M6-B-2に対応する際もこの完結判定を壊してはならない。
    status, evidence = _judge_extract(DEATH_NOTE_EXTRACT)
    assert status == "完結"


def test_gotakeshi_cancellation_is_treated_as_completed():
    # 仕様確定済み（M6-B-1）: 「打ち切り」は円満な完結と同じ「完結」ステータスに含める。
    # ただし判定根拠には打ち切りだった事実がそのまま残る。
    status, evidence = _judge_extract(GOTAKESHI_EXTRACT)
    assert status == "完結"
    assert "打ち切り" in evidence


def test_near_cancellation_that_was_avoided_is_not_completed():
    # 回帰テスト（M6-B-1）: 「打ち切りの危機に瀕したが連載は継続した」のように、
    # 打ち切られなかった文脈では完結と判定してはならない（継続語による無効化）。
    status, evidence = _judge_extract(NEAR_CANCELLATION_EXTRACT)
    assert status == STATUS_UNKNOWN


def test_multimedia_work_with_no_manga_specific_sentence_is_unknown():
    status, evidence = _judge_extract(TENSURA_NO_MANGA_SENTENCE_EXTRACT)
    assert status == STATUS_UNKNOWN
    assert evidence is None


def test_extract_with_no_status_sentence_is_unknown():
    status, evidence = _judge_extract("『何か』は、誰かによる日本の漫画作品。")
    assert status == STATUS_UNKNOWN
    assert evidence is None


def _search_response(titles):
    return {"query": {"search": [{"title": t} for t in titles]}}


def _extract_response(title, extract, missing=False):
    page = {"title": title}
    if missing:
        page["missing"] = ""
    else:
        page["extract"] = extract
    return {"query": {"pages": {"1": page}}}


def _redirect_response(from_title, to_title):
    return {"query": {"redirects": [{"from": from_title, "to": to_title}]}}


def test_judge_prefers_direct_manga_disambiguation_page():
    direct_response = MagicMock()
    direct_response.json.return_value = _extract_response("転生したらスライムだった件 (漫画)", TENSURA_EXTRACT)
    direct_response.raise_for_status.return_value = None

    with patch("comic_checker.wikipedia_client.requests.get", return_value=direct_response) as mock_get:
        result = judge("転生したらスライムだった件")

    assert isinstance(result, WikipediaJudgment)
    assert result.status == "連載中"
    assert result.matched_title == "転生したらスライムだった件 (漫画)"
    # 直接 "(漫画)" 記事が見つかった場合、検索は行わず1回のAPI呼び出しで済む。
    assert mock_get.call_count == 1


def test_judge_falls_back_to_search_and_prefers_manga_candidate():
    # 検索結果の候補("ダミー (漫画)")はクエリ("ダミー")と文字列が異なるため、
    # Wikipedia自身のリダイレクトで裏付けが取れて初めて採用される
    # （M6-A-1: 検索の関連度ランキングだけを根拠にしない）。
    missing_direct = MagicMock()
    missing_direct.json.return_value = _extract_response("ダミー (漫画)", "", missing=True)
    missing_direct.raise_for_status.return_value = None

    search_response = MagicMock()
    search_response.json.return_value = _search_response(["ダミー", "ダミー (漫画)", "ダミー (小説)"])
    search_response.raise_for_status.return_value = None

    redirect_confirmation = MagicMock()
    redirect_confirmation.json.return_value = _redirect_response("ダミー", "ダミー (漫画)")
    redirect_confirmation.raise_for_status.return_value = None

    extract_response = MagicMock()
    extract_response.json.return_value = _extract_response("ダミー (漫画)", ONE_PIECE_EXTRACT)
    extract_response.raise_for_status.return_value = None

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[missing_direct, search_response, redirect_confirmation, extract_response],
    ) as mock_get:
        result = judge("ダミー")

    assert result.matched_title == "ダミー (漫画)"
    assert result.status == "連載中"
    assert mock_get.call_count == 4


def test_judge_rejects_search_candidate_without_exact_match_or_redirect_backing():
    # 回帰テスト（M6-A-1）: 検索結果の候補がクエリと文字列一致せず、かつリダイレクトの
    # 裏付けも取れない場合、無関係な記事を確信を持って誤答するより判定不能に倒す。
    missing_direct = MagicMock()
    missing_direct.json.return_value = _extract_response("謎の作品 (漫画)", "", missing=True)
    missing_direct.raise_for_status.return_value = None

    search_response = MagicMock()
    search_response.json.return_value = _search_response(["無関係な別の記事"])
    search_response.raise_for_status.return_value = None

    no_redirect = MagicMock()
    no_redirect.json.return_value = {"query": {"pages": {"1": {"title": "謎の作品", "missing": ""}}}}
    no_redirect.raise_for_status.return_value = None

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[missing_direct, search_response, no_redirect],
    ):
        result = judge("謎の作品")

    assert result.status == STATUS_NOT_FOUND
    assert result.matched_title is None


def test_judge_returns_not_found_when_no_article_exists():
    missing_direct = MagicMock()
    missing_direct.json.return_value = _extract_response("存在しない作品 (漫画)", "", missing=True)
    missing_direct.raise_for_status.return_value = None

    empty_search = MagicMock()
    empty_search.json.return_value = _search_response([])
    empty_search.raise_for_status.return_value = None

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[missing_direct, empty_search],
    ):
        result = judge("存在しない作品")

    assert result.status == STATUS_NOT_FOUND
    assert result.matched_title is None
