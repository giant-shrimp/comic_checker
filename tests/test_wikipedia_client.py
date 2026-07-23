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

# 幽☆遊★白書のケース: COMPLETED_WEAK_RE（「まで連載された」）が実際に完結を意味する
# 場合は、継続を示す語が無ければ従来通り完結と判定できることの確認（HUNTER×HUNTERの
# 修正が過剰に厳格化していないことの回帰テスト）。
YU_YU_HAKUSHO_EXTRACT = (
    "『幽☆遊☆白書』は、冨樫義博による日本の漫画作品。"
    "『週刊少年ジャンプ』（集英社）にて、1990年51号から1994年32号にかけて連載された。"
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
    missing_direct = MagicMock()
    missing_direct.json.return_value = _extract_response("ダミー (漫画)", "", missing=True)
    missing_direct.raise_for_status.return_value = None

    search_response = MagicMock()
    search_response.json.return_value = _search_response(["ダミー", "ダミー (漫画)", "ダミー (小説)"])
    search_response.raise_for_status.return_value = None

    extract_response = MagicMock()
    extract_response.json.return_value = _extract_response("ダミー (漫画)", ONE_PIECE_EXTRACT)
    extract_response.raise_for_status.return_value = None

    with patch(
        "comic_checker.wikipedia_client.requests.get",
        side_effect=[missing_direct, search_response, extract_response],
    ) as mock_get:
        result = judge("ダミー")

    assert result.matched_title == "ダミー (漫画)"
    assert result.status == "連載中"
    assert mock_get.call_count == 3


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
