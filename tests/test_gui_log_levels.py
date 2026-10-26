"""1行ごとの結果と中断の要求のログのレベル（Issue #557）。

判定不能・要確認の行は WARNING、それ以外の結果は INFO、エラーは ERROR。
中断の要求は利用者の操作を受け付けたことを知らせる行なので INFO。
"""
import threading
import tkinter as tk
from unittest.mock import patch

import pytest

from comic_checker import gui
from comic_checker.gui import App


@pytest.fixture
def app():
    root = tk.Tk()
    root.withdraw()
    widget = App(master=root)
    yield widget
    root.destroy()


def entries(widget):
    return [(level, message) for _time, level, message in widget._log_entries]


def row_entries(widget):
    return [(level, message) for level, message in entries(widget) if message.startswith("[")]


def test_log_warning_statuses_value():
    assert gui.LOG_WARNING_STATUSES == ("判定不能", "要確認")


def test_run_row_log_levels(app):
    def fake_run(excel_path, on_progress=None, **kwargs):
        on_progress(1, 6, "作品A", "完結", "作品A", error=None)
        on_progress(2, 6, "作品B", "連載中", "作品B", error=None)
        on_progress(3, 6, "作品C", "判定不能", "作品C", error=None)
        on_progress(4, 6, "作品D", "記事なし", "", error=None)
        on_progress(5, 6, "作品E", "不明", "", error=None)
        on_progress(6, 6, "作品F", "エラー", "", error=RuntimeError("boom"))
        return 6

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    assert row_entries(app) == [
        ("INFO", "[1/6] 作品A -> 完結 (作品A)"),
        ("INFO", "[2/6] 作品B -> 連載中 (作品B)"),
        ("WARNING", "[3/6] 作品C -> 判定不能 (作品C)"),
        ("INFO", "[4/6] 作品D -> 記事なし ()"),
        ("INFO", "[5/6] 作品E -> 不明 ()"),
        ("ERROR", "[6/6] 作品F -> エラー (boom)"),
    ]


def test_next_release_row_log_levels(app):
    def fake_run(excel_path, on_progress=None, **kwargs):
        on_progress(1, 5, "作品A", "次巻あり", "2026-12-01", error=None)
        on_progress(2, 5, "作品B", "未定", "", error=None)
        on_progress(3, 5, "作品C", "要確認", "", error=None)
        on_progress(4, 5, "作品D", "ヒットなし", "", error=None)
        on_progress(5, 5, "作品E", "エラー", "", error=RuntimeError("boom"))
        return 5

    with patch("comic_checker.gui.next_release.run", side_effect=fake_run):
        app._next_release_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    assert row_entries(app) == [
        ("INFO", "[1/5] 作品A -> 次巻あり (2026-12-01)"),
        ("INFO", "[2/5] 作品B -> 未定 ()"),
        ("WARNING", "[3/5] 作品C -> 要確認 ()"),
        ("INFO", "[4/5] 作品D -> ヒットなし ()"),
        ("ERROR", "[5/5] 作品E -> エラー RuntimeError"),
    ]


def test_cancel_request_is_info(app):
    app._cancel_event = threading.Event()

    app._on_cancel()

    assert entries(app) == [("INFO", "中断します（現在の行の処理を終えるまでお待ちください）")]


def test_warning_filter_shows_only_rows_to_check(app):
    def fake_run(excel_path, on_progress=None, **kwargs):
        on_progress(1, 3, "作品A", "完結", "作品A", error=None)
        on_progress(2, 3, "作品C", "判定不能", "作品C", error=None)
        on_progress(3, 3, "作品D", "記事なし", "", error=None)
        return 3

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    app.log_filter.set("WARNING")
    app._on_log_filter_changed()

    text = app.log_area.get("1.0", "end")
    assert "作品C -> 判定不能" in text
    assert "作品A -> 完結" not in text
    assert "作品D -> 記事なし" not in text
