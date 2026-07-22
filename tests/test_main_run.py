from unittest.mock import MagicMock, patch

from openpyxl import Workbook

from comic_checker.main import run
from comic_checker.manba_client import LookupResult


def make_workbook(tmp_path, titles):
    wb = Workbook()
    ws = wb.active
    ws.append(["タイトル", "連載状況"])
    for title in titles:
        ws.append([title, None])
    path = tmp_path / "test.xlsx"
    wb.save(path)
    return path


def make_fake_client(lookup_side_effect):
    fake_client = MagicMock()
    fake_client.lookup.side_effect = lookup_side_effect
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    return fake_client


def test_run_calls_on_progress_for_each_row(tmp_path):
    excel_path = make_workbook(tmp_path, ["ONE PIECE", "NARUTO"])
    fake_client = make_fake_client(
        [
            LookupResult(
                query="ONE PIECE",
                matched_title="ONE PIECE",
                board_id="1",
                url="https://manba.co.jp/boards/1",
                status="連載中",
            ),
            LookupResult(
                query="NARUTO",
                matched_title="NARUTO",
                board_id="2",
                url="https://manba.co.jp/boards/2",
                status="完結",
            ),
        ]
    )

    calls = []

    def on_progress(index, total, title, status, matched_title, error=None):
        calls.append((index, total, title, status, matched_title, error))

    with patch("comic_checker.main.ManbaClient", return_value=fake_client):
        total = run(excel_path, on_progress=on_progress)

    assert total == 2
    assert calls == [
        (1, 2, "ONE PIECE", "連載中", "ONE PIECE", None),
        (2, 2, "NARUTO", "完結", "NARUTO", None),
    ]


def test_run_passes_error_to_on_progress_and_continues(tmp_path):
    excel_path = make_workbook(tmp_path, ["ONE PIECE", "NARUTO"])
    boom = RuntimeError("boom")
    fake_client = make_fake_client(
        [
            boom,
            LookupResult(
                query="NARUTO",
                matched_title="NARUTO",
                board_id="2",
                url="https://manba.co.jp/boards/2",
                status="完結",
            ),
        ]
    )

    calls = []

    def on_progress(index, total, title, status, matched_title, error=None):
        calls.append((index, total, title, status, matched_title, error))

    with patch("comic_checker.main.ManbaClient", return_value=fake_client):
        total = run(excel_path, on_progress=on_progress)

    assert total == 2
    assert calls[0] == (1, 2, "ONE PIECE", "エラー", "", boom)
    assert calls[1] == (2, 2, "NARUTO", "完結", "NARUTO", None)


def test_run_without_on_progress_does_not_raise(tmp_path):
    excel_path = make_workbook(tmp_path, ["ONE PIECE"])
    fake_client = make_fake_client(
        [
            LookupResult(
                query="ONE PIECE",
                matched_title="ONE PIECE",
                board_id="1",
                url="https://manba.co.jp/boards/1",
                status="連載中",
            )
        ]
    )

    with patch("comic_checker.main.ManbaClient", return_value=fake_client):
        total = run(excel_path)

    assert total == 1
