"""1行ごとの結果のログに、空のかっこや結果の値の繰り返しを出さない（Issue #569）。値はすべて架空。"""
import tkinter as tk
from unittest.mock import patch

import pytest
from openpyxl import Workbook

from comic_checker import rakuten_books_client
from comic_checker.gui import App, format_result_line
from comic_checker.rakuten_books_client import ReleaseInfo


@pytest.fixture
def app():
    root = tk.Tk()
    root.withdraw()
    widget = App(master=root)
    yield widget
    root.destroy()


def row_entries(widget):
    return [
        (level, message) for _time, level, message in widget._log_entries if message.startswith("[")
    ]


@pytest.mark.parametrize(
    "status, detail, expected",
    [
        ("完結", "作品A", "[1/2] 作品A -> 完結 (作品A)"),
        ("連載中", "作品Aの別名", "[1/2] 作品A -> 連載中 (作品Aの別名)"),
        ("記事なし", "", "[1/2] 作品A -> 記事なし"),
        ("記事なし", None, "[1/2] 作品A -> 記事なし"),
        ("次巻あり", "2030年1月5日", "[1/2] 作品A -> 次巻あり (2030年1月5日)"),
        ("未定", "未定", "[1/2] 作品A -> 未定"),
        ("要確認", "要確認", "[1/2] 作品A -> 要確認"),
        ("ヒットなし", "ヒットなし", "[1/2] 作品A -> ヒットなし"),
    ],
)
def test_format_result_line(status, detail, expected):
    assert format_result_line(1, 2, "作品A", status, detail) == expected


def test_next_release_log_from_real_run_does_not_repeat_status(app, tmp_path, monkeypatch):
    # next_release.run() は、次巻あり以外の行では結果の値そのものを on_progress に渡す。
    monkeypatch.setenv("RAKUTEN_APP_ID", "dummy-app-id")
    monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "dummy-access-key")
    path = tmp_path / "list.xlsx"
    wb = Workbook()
    wb.active.append(["タイトル"])
    for title in ("作品A", "作品B", "作品C", "作品D"):
        wb.active.append([title])
    wb.save(path)

    infos = {
        "作品A": ReleaseInfo(
            query="作品A", status="次巻あり", next_title="作品A 3巻", next_sales_date="2030年1月5日"
        ),
        "作品B": ReleaseInfo(query="作品B", status="未定"),
        "作品C": ReleaseInfo(query="作品C", status="要確認"),
        "作品D": ReleaseInfo(query="作品D", status="ヒットなし"),
    }
    with patch.object(rakuten_books_client, "find_next_release", side_effect=lambda title: infos[title]):
        app._next_release_worker(excel_path=str(path), cancel_event=None)
        app.master.update()

    assert row_entries(app) == [
        ("INFO", "[1/4] 作品A -> 次巻あり (2030年1月5日)"),
        ("INFO", "[2/4] 作品B -> 未定"),
        ("WARNING", "[3/4] 作品C -> 要確認"),
        ("INFO", "[4/4] 作品D -> ヒットなし"),
    ]


def test_run_log_has_no_empty_parentheses(app):
    def fake_run(excel_path, on_progress=None, **kwargs):
        on_progress(1, 2, "作品A", "連載中", "作品A", error=None)
        on_progress(2, 2, "作品D", "記事なし", "", error=None)
        return 2

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    text = app.log_area.get("1.0", "end")
    assert "[2/2] 作品D -> 記事なし\n" in text
    assert "()" not in text
