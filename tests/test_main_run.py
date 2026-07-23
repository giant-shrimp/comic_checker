from unittest.mock import MagicMock, patch

from openpyxl import Workbook

from comic_checker.main import run
from comic_checker.manba_client import LookupResult
from comic_checker.wikipedia_client import WikipediaJudgment


def make_workbook(tmp_path, titles):
    wb = Workbook()
    ws = wb.active
    ws.append(["タイトル", "連載状況"])
    for title in titles:
        ws.append([title, None])
    path = tmp_path / "test.xlsx"
    wb.save(path)
    return path


def make_fake_manba_client(lookup_side_effect):
    fake_client = MagicMock()
    fake_client.lookup.side_effect = lookup_side_effect
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    return fake_client


def read_header(ws):
    return [cell.value for cell in ws[1]]


def read_row(ws, row):
    return {header: ws.cell(row=row, column=col).value for col, header in enumerate(read_header(ws), start=1)}


def test_run_uses_wikipedia_and_never_touches_manba_by_default(tmp_path):
    excel_path = make_workbook(tmp_path, ["ONE PIECE", "進撃の巨人"])

    wiki_results = [
        WikipediaJudgment(
            query="ONE PIECE",
            status="連載中",
            matched_title="ONE PIECE",
            url="https://ja.wikipedia.org/wiki/ONE_PIECE",
            evidence="1997年34号から連載中。",
        ),
        WikipediaJudgment(
            query="進撃の巨人",
            status="完結",
            matched_title="進撃の巨人",
            url="https://ja.wikipedia.org/wiki/進撃の巨人",
            evidence="5月号をもって完結した。",
        ),
    ]

    calls = []

    def on_progress(index, total, title, status, matched_title, error=None):
        calls.append((index, total, title, status, matched_title, error))

    with patch("comic_checker.main.wikipedia_client.judge", side_effect=wiki_results), patch(
        "comic_checker.main.ManbaClient"
    ) as mock_manba_client_cls:
        total = run(excel_path, on_progress=on_progress)

    assert total == 2
    mock_manba_client_cls.assert_not_called()
    assert calls == [
        (1, 2, "ONE PIECE", "連載中", "ONE PIECE", None),
        (2, 2, "進撃の巨人", "完結", "進撃の巨人", None),
    ]

    wb = _reload(excel_path)
    ws = wb.active
    row1 = read_row(ws, 2)
    assert row1["連載状況"] == "連載中"
    assert row1["判定方法"] == "Wikipedia"
    assert row1["判定根拠"] == "1997年34号から連載中。"
    assert row1["参照タイトル"] == "ONE PIECE"
    assert row1["参照URL"] == "https://ja.wikipedia.org/wiki/ONE_PIECE"


def test_run_records_unknown_status_without_fallback_by_default(tmp_path):
    excel_path = make_workbook(tmp_path, ["謎の作品"])

    wiki_result = WikipediaJudgment(query="謎の作品", status="判定不能")

    with patch("comic_checker.main.wikipedia_client.judge", return_value=wiki_result), patch(
        "comic_checker.main.ManbaClient"
    ) as mock_manba_client_cls:
        total = run(excel_path)

    assert total == 1
    mock_manba_client_cls.assert_not_called()

    wb = _reload(excel_path)
    ws = wb.active
    row1 = read_row(ws, 2)
    assert row1["連載状況"] == "判定不能"
    assert row1["判定方法"] == "Wikipedia"


def test_run_falls_back_to_manba_when_enabled_and_reuses_client(tmp_path):
    excel_path = make_workbook(tmp_path, ["謎の作品1", "謎の作品2"])

    wiki_results = [
        WikipediaJudgment(query="謎の作品1", status="判定不能"),
        WikipediaJudgment(query="謎の作品2", status="記事なし"),
    ]
    fake_manba_client = make_fake_manba_client(
        [
            LookupResult(
                query="謎の作品1",
                matched_title="謎の作品1（マンバ）",
                board_id="1",
                url="https://manba.co.jp/boards/1",
                status="連載中",
            ),
            LookupResult(
                query="謎の作品2",
                matched_title="謎の作品2（マンバ）",
                board_id="2",
                url="https://manba.co.jp/boards/2",
                status="完結",
            ),
        ]
    )

    with patch("comic_checker.main.wikipedia_client.judge", side_effect=wiki_results), patch(
        "comic_checker.main.ManbaClient", return_value=fake_manba_client
    ) as mock_manba_client_cls:
        total = run(excel_path, fallback_to_manba=True)

    assert total == 2
    # 遅延生成: 1行目のフォールバック発生時に一度だけ生成され、2行目は使い回される。
    mock_manba_client_cls.assert_called_once()
    fake_manba_client.__exit__.assert_called_once()

    wb = _reload(excel_path)
    ws = wb.active
    row1 = read_row(ws, 2)
    row2 = read_row(ws, 3)
    assert row1["連載状況"] == "連載中"
    assert row1["判定方法"] == "manba.co.jp"
    assert row1["参照タイトル"] == "謎の作品1（マンバ）"
    assert row2["連載状況"] == "完結"
    assert row2["判定方法"] == "manba.co.jp"


def test_run_passes_error_to_on_progress_and_continues(tmp_path):
    excel_path = make_workbook(tmp_path, ["ONE PIECE", "NARUTO"])
    boom = RuntimeError("boom")

    with patch(
        "comic_checker.main.wikipedia_client.judge",
        side_effect=[boom, WikipediaJudgment(query="NARUTO", status="完結", matched_title="NARUTO")],
    ):
        calls = []

        def on_progress(index, total, title, status, matched_title, error=None):
            calls.append((index, total, title, status, matched_title, error))

        total = run(excel_path, on_progress=on_progress)

    assert total == 2
    assert calls[0] == (1, 2, "ONE PIECE", "エラー", "", boom)
    assert calls[1] == (2, 2, "NARUTO", "完結", "NARUTO", None)


def test_run_without_on_progress_does_not_raise(tmp_path):
    excel_path = make_workbook(tmp_path, ["ONE PIECE"])

    with patch(
        "comic_checker.main.wikipedia_client.judge",
        return_value=WikipediaJudgment(query="ONE PIECE", status="連載中", matched_title="ONE PIECE"),
    ):
        total = run(excel_path)

    assert total == 1


def _reload(excel_path):
    from openpyxl import load_workbook

    return load_workbook(excel_path)
