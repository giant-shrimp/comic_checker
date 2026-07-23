import tkinter as tk
from unittest.mock import patch

import pytest

from comic_checker.gui import App


@pytest.fixture
def app():
    root = tk.Tk()
    root.withdraw()
    widget = App(master=root)
    yield widget
    root.destroy()


def log_text(widget):
    return widget.log_area.get("1.0", "end")


def test_run_worker_calls_run_with_excel_path_and_on_progress(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.run", return_value=3) as mock_run:
        app._run_worker()
        app.master.update()

    mock_run.assert_called_once_with("/tmp/対象.xlsx", on_progress=app._on_progress)


def test_run_worker_streams_progress_to_log(app):
    app.excel_path.set("/tmp/対象.xlsx")

    def fake_run(excel_path, on_progress=None):
        on_progress(1, 2, "ONE PIECE", "連載中", "ONE PIECE", error=None)
        on_progress(2, 2, "謎の作品", "エラー", "", error=RuntimeError("boom"))
        return 2

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker()
        app.master.update()

    text = log_text(app)
    assert "[1/2] ONE PIECE -> 連載中 (ONE PIECE)" in text
    assert "[2/2] 謎の作品 -> エラー (boom)" in text


def test_run_worker_logs_completion_with_count_and_path(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.run", return_value=5):
        app._run_worker()
        app.master.update()

    text = log_text(app)
    assert "完了しました" in text
    assert "5件処理" in text
    assert "/tmp/対象.xlsx" in text


def test_run_worker_reenables_button_after_success(app):
    app.excel_path.set("/tmp/対象.xlsx")
    app.run_button.config(state="disabled")

    with patch("comic_checker.gui.run", return_value=1):
        app._run_worker()
        app.master.update()

    assert str(app.run_button["state"]) == "normal"


def test_run_worker_logs_error_and_reenables_button_on_exception(app):
    app.excel_path.set("/tmp/対象.xlsx")
    app.run_button.config(state="disabled")

    with patch("comic_checker.gui.run", side_effect=ValueError("列「タイトル」が見つかりません")):
        app._run_worker()
        app.master.update()

    text = log_text(app)
    assert "エラーが発生しました" in text
    assert "列「タイトル」が見つかりません" in text
    assert str(app.run_button["state"]) == "normal"


def test_on_run_disables_button_and_starts_worker_thread(app):
    # 実スレッドは起動せず、Threadの生成・startだけを検証する
    # （_run_worker自体の挙動は他のテストで直接呼び出して検証済み）。
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.threading.Thread") as mock_thread_cls:
        app._on_run()

    assert str(app.run_button["state"]) == "disabled"
    mock_thread_cls.assert_called_once_with(target=app._run_worker, daemon=True)
    mock_thread_cls.return_value.start.assert_called_once()
