"""GUI の進捗カードの3つの欄（対象ファイル・処理件数・経過時間）のテスト。作品名はすべて架空。"""
import tkinter as tk
from unittest.mock import patch

import pytest

from comic_checker import gui
from comic_checker.gui import App, CHOICE_CANCEL, _format_elapsed
from comic_checker.main import RowCounts


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def app():
    root = tk.Tk()
    root.withdraw()
    widget = App(master=root)
    widget._clock = FakeClock()
    yield widget
    # 時計の予約が残らないようにしてから破棄し、破棄後に予約が走らないことを確かめる。
    widget._stop_elapsed()
    assert widget._elapsed_after_id is None
    root.destroy()


def start_run(app, method):
    app.excel_path.set("/tmp/dir/list.xlsx")
    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=3, filled=0)):
        with patch("comic_checker.gui.threading.Thread"):
            getattr(app, method)()


# ---------------------------------------------------------------- 書式


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "00:00"),
        (59, "00:59"),
        (60, "01:00"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3723, "1:02:03"),
    ],
)
def test_format_elapsed(seconds, expected):
    assert _format_elapsed(seconds) == expected


# ---------------------------------------------------------------- 経過時間


@pytest.mark.parametrize("method", ["_on_run", "_on_next_release"])
def test_start_shows_zero_and_schedules_tick(app, method):
    start_run(app, method)
    assert app.stat_elapsed_value.get() == "00:00"
    assert app._elapsed_after_id is not None


@pytest.mark.parametrize("method", ["_on_run", "_on_next_release"])
def test_tick_advances_by_clock_difference(app, method):
    start_run(app, method)
    app._clock.now += 125
    app._tick_elapsed()
    assert app.stat_elapsed_value.get() == "02:05"
    assert app._elapsed_after_id is not None


@pytest.mark.parametrize("method", ["_on_run", "_on_next_release"])
def test_reset_stops_clock_and_keeps_last_value(app, method):
    start_run(app, method)
    app._clock.now += 7
    app._reset_buttons_after_run()
    assert app._elapsed_after_id is None
    assert app.stat_elapsed_value.get() == "00:07"
    app._clock.now += 100
    app.master.update()
    assert app.stat_elapsed_value.get() == "00:07"


def test_keeps_counting_until_reset_even_after_cancel_request(app):
    start_run(app, "_on_run")
    app._on_cancel()
    app._clock.now += 3
    app._tick_elapsed()
    assert app.stat_elapsed_value.get() == "00:03"


def test_reset_without_run_does_nothing(app):
    app._reset_buttons_after_run()
    assert app.stat_elapsed_value.get() == "-"
    assert app._elapsed_after_id is None


def test_not_started_when_confirmation_cancelled(app):
    app.excel_path.set("/tmp/dir/list.xlsx")
    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=1, filled=2)):
        with patch("comic_checker.gui.FilledRowsDialog") as dialog:
            dialog.return_value.show.return_value = CHOICE_CANCEL
            with patch("comic_checker.gui.threading.Thread") as thread_cls:
                app._on_run()
    thread_cls.assert_not_called()
    assert app.stat_elapsed_value.get() == "-"
    assert app._elapsed_after_id is None


@pytest.mark.parametrize("method", ["_on_run", "_on_next_release"])
def test_not_started_without_file(app, method):
    with patch("comic_checker.gui.threading.Thread") as thread_cls:
        getattr(app, method)()
    thread_cls.assert_not_called()
    assert app.stat_elapsed_value.get() == "-"
    assert app._elapsed_after_id is None


def test_tick_interval_constant_is_used(app):
    with patch.object(app, "after", wraps=app.after) as after:
        start_run(app, "_on_run")
    assert after.call_args.args[0] == gui.ELAPSED_TICK_MS
    assert gui.ELAPSED_TICK_MS == 1000


# ---------------------------------------------------------------- 件数


def fake_run(app, calls):
    def _run(*args, on_progress=None, **kwargs):
        for index, total in calls:
            # 完結チェックは matched_title、次巻確認は next_sales_date が5つ目の引数。
            on_progress(index, total, "題名", "完結", None)
        return len(calls)

    return _run


def test_count_after_complete_check_run(app):
    with patch("comic_checker.gui.run", side_effect=fake_run(app, [(1, 4), (2, 4)])):
        app._run_worker(excel_path="/tmp/list.xlsx")
        app.master.update()
    assert app.stat_count_value.get() == "2 / 4"


def test_count_after_next_release_run(app):
    with patch(
        "comic_checker.gui.next_release.run", side_effect=fake_run(app, [(1, 4), (2, 4)])
    ):
        app._next_release_worker(excel_path="/tmp/list.xlsx")
        app.master.update()
    assert app.stat_count_value.get() == "2 / 4"


def test_count_is_dash_when_no_rows(app):
    with patch("comic_checker.gui.run", side_effect=fake_run(app, [])):
        app._run_worker(excel_path="/tmp/list.xlsx")
        app.master.update()
    assert app.stat_count_value.get() == "-"


def test_count_dash_at_start_of_next_run_then_progress(app):
    app._update_progress(2, 4)
    assert app.stat_count_value.get() == "2 / 4"
    app._update_progress(0, 0)
    assert app.stat_count_value.get() == "-"


# ---------------------------------------------------------------- ファイル名


def test_file_name_shows_basename_only(app):
    app.excel_path.set("/tmp/some/dir/list.xlsx")
    assert app.stat_file_value.get() == "list.xlsx"
    app.excel_path.set("")
    assert app.stat_file_value.get() == "-"
