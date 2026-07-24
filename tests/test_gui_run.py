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


# --------------------------------------------------------------- 既存の回帰テスト
# GUIの見た目を刷新（ttk化・進捗バー・サマリ追加）しても、下記の振る舞いは
# 変わってはいけない。Issue #24の制約により、これらは削除・skipしない。


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


# ------------------------------------------------------------------ 進捗バー


def test_progress_bar_tracks_index_and_total(app):
    app.excel_path.set("/tmp/対象.xlsx")

    def fake_run(excel_path, on_progress=None):
        on_progress(1, 4, "A", "完結", "A", error=None)
        on_progress(2, 4, "B", "連載中", "B", error=None)
        return 4

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker()
        app.master.update()

    assert int(app.progress["maximum"]) == 4
    assert int(app.progress["value"]) == 2


def test_progress_bar_resets_at_the_start_of_each_run(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.run", side_effect=lambda p, on_progress=None: (
        on_progress(1, 1, "A", "完結", "A", error=None), 1
    )[1]):
        app._run_worker()
        app.master.update()
    assert int(app.progress["value"]) == 1

    # 2回目の実行では、進捗が持ち越されずに0から始まる。
    with patch("comic_checker.gui.run", return_value=0):
        app._run_worker()
        app.master.update()
    assert int(app.progress["value"]) == 0


# ------------------------------------------------------------------ 結果サマリ


def test_summary_counts_each_status(app):
    app.excel_path.set("/tmp/対象.xlsx")

    def fake_run(excel_path, on_progress=None):
        on_progress(1, 5, "A", "完結", "A", error=None)
        on_progress(2, 5, "B", "連載中", "B", error=None)
        on_progress(3, 5, "C", "完結", "C", error=None)
        on_progress(4, 5, "D", "判定不能", "D", error=None)
        on_progress(5, 5, "E", "エラー", "", error=RuntimeError("boom"))
        return 5

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker()
        app.master.update()

    summary = app.summary_text.get()
    assert "完結 2" in summary
    assert "連載中 1" in summary
    assert "判定不能 1" in summary
    assert "エラー 1" in summary
    # 0件の項目は並べない（「記事なし 0」のようなノイズを出さない）。
    assert "記事なし" not in summary


def test_summary_groups_unlisted_statuses_into_other(app):
    # manba経路の「ヒットなし」「不明」等は「その他」にまとめる。
    app.excel_path.set("/tmp/対象.xlsx")

    def fake_run(excel_path, on_progress=None):
        on_progress(1, 2, "A", "ヒットなし", "", error=None)
        on_progress(2, 2, "B", "不明", "", error=None)
        return 2

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker()
        app.master.update()

    assert "その他 2" in app.summary_text.get()


def test_summary_is_reset_between_runs(app):
    app.excel_path.set("/tmp/対象.xlsx")

    def fake_run(excel_path, on_progress=None):
        on_progress(1, 1, "A", "完結", "A", error=None)
        return 1

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker()
        app.master.update()
    assert "完結 1" in app.summary_text.get()

    with patch("comic_checker.gui.run", return_value=0):
        app._run_worker()
        app.master.update()
    assert app.summary_text.get() == "—"


# ------------------------------------------------------------------ 状態表示


def test_status_shows_progress_while_running_and_completion_at_the_end(app):
    app.excel_path.set("/tmp/対象.xlsx")

    seen = []

    def fake_run(excel_path, on_progress=None):
        on_progress(1, 2, "ONE PIECE", "連載中", "ONE PIECE", error=None)
        app.master.update()
        seen.append(app.status_text.get())
        on_progress(2, 2, "進撃の巨人", "完結", "進撃の巨人", error=None)
        return 2

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker()
        app.master.update()

    assert seen == ["処理中… 1/2 件（ONE PIECE）"]
    assert app.status_text.get() == "完了しました（2件処理）"


def test_status_shows_failure_on_exception(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.run", side_effect=ValueError("boom")):
        app._run_worker()
        app.master.update()

    assert app.status_text.get() == "エラーで中断しました"


# -------------------------------------------------------- ファイル名の表示


def test_selected_file_shows_basename_and_full_path(app):
    app.excel_path.set("/home/someone/books/対象ファイル.xlsx")
    app.master.update()

    assert app.file_label.get() == "対象ファイル.xlsx"
    assert app.file_hint.get() == "/home/someone/books/対象ファイル.xlsx"


def test_no_file_selected_shows_placeholder(app):
    assert app.file_label.get() == "（未選択）"
    assert app.file_hint.get() == ""


# ----------------------------------------------------------------- ログ欄


def test_long_log_lines_stay_readable(app):
    # ScrolledTextの付属スクロールバーは縦だけなので、wrap="none"にすると
    # 欄幅を超えた行が横スクロールできず読めなくなる（実際に検出した不具合）。
    app._log("あ" * 300)
    app.master.update()

    assert app.log_area.cget("wrap") != "none"
    # 行全体が折り返されて表示範囲に収まっている（横方向に隠れていない）。
    first, last = app.log_area.xview()
    assert (first, last) == (0.0, 1.0)


# ------------------------------------------------- High-DPI設定（Windows専用）


def test_dpi_awareness_is_skipped_on_non_windows():
    from comic_checker import gui

    with patch.object(gui.sys, "platform", "linux"):
        # ctypesに触れずに戻ること（触れれば ImportError/AttributeError になる環境がある）。
        gui._enable_dpi_awareness()


def test_dpi_awareness_does_not_raise_when_windows_api_is_unavailable():
    from comic_checker import gui

    # Windows判定にしたうえでctypes呼び出しを失敗させ、例外が漏れないことを確認する。
    # GUIが起動しない方が困るので、ここでの失敗は握りつぶす仕様。
    with patch.object(gui.sys, "platform", "win32"):
        with patch.dict("sys.modules", {"ctypes": None}):
            gui._enable_dpi_awareness()
