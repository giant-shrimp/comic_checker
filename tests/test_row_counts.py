"""Issue #32: 実行前の行数スキャン（_collect_rows / count_rows）のテスト。

GUIが実行前に「N行は判定済みのためスキップされます」と警告するための土台。
警告の件数と実際の処理件数がずれないことが要点なので、run() が使うのと同じ
_collect_rows() を経由していることを前提に検証する。
"""
from unittest.mock import patch

import pytest
from openpyxl import Workbook

from comic_checker.excel_io import ensure_column, find_column, open_workbook
from comic_checker.main import RowCounts, _collect_rows, count_rows


def make_workbook(tmp_path, rows, headers=("タイトル", "連載状況"), name="test.xlsx"):
    """rows は (タイトル, 連載状況) のタプル列。連載状況にNoneを渡せば未判定行になる。"""
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for row in rows:
        ws.append(list(row))
    path = tmp_path / name
    wb.save(path)
    return path


def open_sheet(path):
    wb = open_workbook(path)
    ws = wb.active
    return ws, find_column(ws, "タイトル"), ensure_column(ws, "連載状況")


# ------------------------------------------------------------------ _collect_rows


def test_collect_rows_excludes_filled_rows_when_skipping(tmp_path):
    path = make_workbook(tmp_path, [("A", "連載中"), ("B", None), ("C", "完結")])
    ws, title_col, status_col = open_sheet(path)

    rows = _collect_rows(ws, title_col, status_col, header_row=1, skip_filled=True)

    assert [title for _row, title in rows] == ["B"]


def test_collect_rows_includes_filled_rows_when_not_skipping(tmp_path):
    path = make_workbook(tmp_path, [("A", "連載中"), ("B", None), ("C", "完結")])
    ws, title_col, status_col = open_sheet(path)

    rows = _collect_rows(ws, title_col, status_col, header_row=1, skip_filled=False)

    assert [title for _row, title in rows] == ["A", "B", "C"]


@pytest.mark.parametrize("skip_filled", [True, False])
def test_collect_rows_always_excludes_blank_titles(tmp_path, skip_filled):
    # タイトル空欄・空白のみの行は、skip_filledの値に関わらず対象外。
    path = make_workbook(
        tmp_path, [("A", None), (None, None), ("   ", None), ("B", None)]
    )
    ws, title_col, status_col = open_sheet(path)

    rows = _collect_rows(ws, title_col, status_col, header_row=1, skip_filled=skip_filled)

    assert [title for _row, title in rows] == ["A", "B"]


def test_collect_rows_strips_surrounding_whitespace_from_titles(tmp_path):
    path = make_workbook(tmp_path, [("  ONE PIECE  ", None)])
    ws, title_col, status_col = open_sheet(path)

    rows = _collect_rows(ws, title_col, status_col, header_row=1, skip_filled=True)

    assert rows == [(2, "ONE PIECE")]


# --------------------------------------------------------------------- count_rows


def test_count_rows_when_every_row_is_already_judged(tmp_path):
    # 今回のIssueで実際に踏んだ状況（再実行しても全行スキップされる）。
    path = make_workbook(tmp_path, [("A", "連載中"), ("B", "完結"), ("C", "記事なし")])

    assert count_rows(path) == RowCounts(pending=0, filled=3)


def test_count_rows_when_some_rows_are_judged(tmp_path):
    path = make_workbook(tmp_path, [("A", "連載中"), ("B", None), ("C", None)])

    counts = count_rows(path)

    assert counts == RowCounts(pending=2, filled=1)
    assert counts.total == 3


def test_count_rows_when_no_row_is_judged(tmp_path):
    path = make_workbook(tmp_path, [("A", None), ("B", None)])

    assert count_rows(path) == RowCounts(pending=2, filled=0)


def test_count_rows_treats_missing_status_column_as_nothing_judged(tmp_path):
    # 初回実行のファイルには「連載状況」列がまだ無い。列が無い＝判定済みは存在しない。
    path = make_workbook(tmp_path, [("A",), ("B",)], headers=("タイトル",))

    assert count_rows(path) == RowCounts(pending=2, filled=0)


def test_count_rows_does_not_create_the_status_column(tmp_path):
    # 数えるだけの関数がファイルを書き換えないこと（run()と違い列を作らない）。
    path = make_workbook(tmp_path, [("A",)], headers=("タイトル",))

    count_rows(path)

    ws = open_workbook(path).active
    assert [cell.value for cell in ws[1]] == ["タイトル"]


def test_count_rows_does_not_perform_any_judgement(tmp_path):
    # ネットワークアクセスを伴わないこと。実行ボタン押下時に同期で呼ぶため、
    # ここで判定が走ると画面が固まる。
    path = make_workbook(tmp_path, [("A", None), ("B", "連載中")])

    with patch("comic_checker.wikipedia_client.judge") as mock_judge:
        count_rows(path)

    mock_judge.assert_not_called()


def test_count_rows_ignores_blank_title_rows(tmp_path):
    path = make_workbook(tmp_path, [("A", "連載中"), (None, None), ("B", None)])

    assert count_rows(path) == RowCounts(pending=1, filled=1)
