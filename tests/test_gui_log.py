import datetime
import re
import tkinter as tk
from unittest.mock import patch

import pytest

from comic_checker.gui import (
    COLOR_ACCENT,
    COLOR_ERROR,
    COLOR_LOG_ERROR_BG,
    COLOR_LOG_INFO_BG,
    COLOR_LOG_SUCCESS_BG,
    COLOR_LOG_WARNING_BG,
    COLOR_SUCCESS,
    COLOR_WARNING,
    LOG_FILTER_ALL,
    LOG_LEVELS,
    LOG_TIME_FORMAT,
    App,
)

FIXED_TIME = datetime.datetime(2026, 10, 12, 9, 30, 5)
FIXED_TEXT = "2026-10-12 09:30:05"


@pytest.fixture
def app():
    root = tk.Tk()
    root.withdraw()
    widget = App(master=root)
    widget._now = lambda: FIXED_TIME
    yield widget
    root.destroy()


def lines(widget):
    text = widget.log_area.get("1.0", "end")
    return [line for line in text.split("\n") if line != ""]


def select_filter(widget, value):
    widget.log_filter.set(value)
    widget.log_filter.event_generate("<<ComboboxSelected>>")
    widget.master.update()


def write_one_of_each(widget):
    widget._log("情報の行", "INFO")
    widget._log("成功の行", "SUCCESS")
    widget._log("警告の行", "WARNING")
    widget._log("異常の行", "ERROR")


def test_line_starts_with_time_in_the_format(app):
    app._log("本文")

    assert lines(app)[0].startswith(FIXED_TEXT + " ")
    assert FIXED_TIME.strftime(LOG_TIME_FORMAT) == FIXED_TEXT


def test_line_shape_is_time_padded_mark_then_body(app):
    app._log("本文", "ERROR")
    app._log("本文", "SUCCESS")

    assert lines(app) == [
        f"{FIXED_TEXT} ERROR   本文",
        f"{FIXED_TEXT} SUCCESS 本文",
    ]


def test_level_defaults_to_info(app):
    app._log("既定")

    assert lines(app) == [f"{FIXED_TEXT} INFO    既定"]
    assert app._log_entries == [(FIXED_TEXT, "INFO", "既定")]


@pytest.mark.parametrize(
    "level, background, foreground",
    [
        ("INFO", COLOR_LOG_INFO_BG, COLOR_ACCENT),
        ("SUCCESS", COLOR_LOG_SUCCESS_BG, COLOR_SUCCESS),
        ("WARNING", COLOR_LOG_WARNING_BG, COLOR_WARNING),
        ("ERROR", COLOR_LOG_ERROR_BG, COLOR_ERROR),
    ],
)
def test_mark_range_has_the_level_tag_with_its_colors(app, level, background, foreground):
    app._log("本文", level)

    ranges = app.log_area.tag_ranges(f"log_{level}")
    assert len(ranges) == 2
    marked = app.log_area.get(ranges[0], ranges[1])
    assert marked == level.ljust(7)
    assert str(app.log_area.tag_cget(f"log_{level}", "background")) == background
    assert str(app.log_area.tag_cget(f"log_{level}", "foreground")) == foreground
    # 他のレベルのタグは付かない。
    for other in LOG_LEVELS:
        if other != level:
            assert not app.log_area.tag_ranges(f"log_{other}")


def test_color_constants_have_the_agreed_values():
    assert COLOR_LOG_INFO_BG == "#e3eefb"
    assert COLOR_LOG_SUCCESS_BG == "#e1f1e6"
    assert COLOR_LOG_WARNING_BG == "#f8eddb"
    assert COLOR_LOG_ERROR_BG == "#f9e1df"
    assert COLOR_WARNING == "#a2660a"
    assert COLOR_ERROR == "#b3261e"
    assert LOG_LEVELS == ("INFO", "SUCCESS", "WARNING", "ERROR")
    assert LOG_FILTER_ALL == "すべて"
    assert LOG_TIME_FORMAT == "%Y-%m-%d %H:%M:%S"


def test_unknown_level_raises_value_error_and_writes_nothing(app):
    with pytest.raises(ValueError):
        app._log("本文", "DEBUG")

    assert lines(app) == []
    assert app._log_entries == []


def test_log_threadsafe_passes_the_level_through_after_to_log(app):
    with patch.object(app, "after") as mock_after:
        app._log_threadsafe("本文", level="WARNING")
        app._log_threadsafe("既定")

    assert mock_after.call_args_list[0].args == (0, app._log, "本文", "WARNING")
    assert mock_after.call_args_list[1].args == (0, app._log, "既定", "INFO")


def test_log_threadsafe_writes_the_level_when_the_main_loop_runs(app):
    app._log_threadsafe("異常の行", level="ERROR")
    app.master.update()

    assert lines(app) == [f"{FIXED_TEXT} ERROR   異常の行"]


@pytest.mark.parametrize("level", LOG_LEVELS)
def test_filter_shows_only_the_selected_level(app, level):
    write_one_of_each(app)

    select_filter(app, level)

    shown = lines(app)
    assert len(shown) == 1
    assert level.ljust(7) in shown[0]


def test_filter_back_to_all_shows_every_line_in_the_original_order(app):
    write_one_of_each(app)
    before = lines(app)

    select_filter(app, "WARNING")
    select_filter(app, "すべて")

    assert lines(app) == before
    assert [entry[2] for entry in app._log_entries] == [
        "情報の行",
        "成功の行",
        "警告の行",
        "異常の行",
    ]


def test_filtering_keeps_the_held_lines(app):
    write_one_of_each(app)

    select_filter(app, "ERROR")

    assert len(app._log_entries) == 4


def test_line_added_while_filtering_is_shown_only_if_it_matches(app):
    write_one_of_each(app)
    select_filter(app, "ERROR")

    app._log("追加の警告", "WARNING")
    app._log("追加の異常", "ERROR")

    shown = lines(app)
    assert len(shown) == 2
    assert shown[0].endswith("異常の行")
    assert shown[1].endswith("追加の異常")
    assert "追加の警告" not in "\n".join(shown)
    assert len(app._log_entries) == 6

    select_filter(app, "WARNING")
    assert [line.split("WARNING ")[1] for line in lines(app)] == ["警告の行", "追加の警告"]


def test_clear_empties_the_display_and_the_held_lines_without_a_dialog(app):
    write_one_of_each(app)

    with patch("tkinter.messagebox.askyesno") as ask, patch(
        "tkinter.messagebox.askokcancel"
    ) as ok, patch("tkinter.messagebox.askyesnocancel") as ask3:
        app.log_clear_button.invoke()

    assert lines(app) == []
    assert app._log_entries == []
    assert not (ask.called or ok.called or ask3.called)


def test_lines_after_clear_are_shown_alone_and_the_filter_still_applies(app):
    write_one_of_each(app)
    select_filter(app, "WARNING")
    app.log_clear_button.invoke()

    assert app.log_filter.get() == "WARNING"

    app._log("クリア後の情報", "INFO")
    app._log("クリア後の警告", "WARNING")

    shown = lines(app)
    assert len(shown) == 1
    assert shown[0].endswith("クリア後の警告")
    assert len(app._log_entries) == 2

    select_filter(app, "すべて")
    assert [line.split(" ", 2)[2] for line in lines(app)] == [
        "INFO    クリア後の情報",
        "WARNING クリア後の警告",
    ]


def test_clear_button_is_enabled_while_running(app):
    app.cancel_button.config(state="normal")

    assert str(app.cancel_button.cget("state")) == "normal"
    assert str(app.log_clear_button.cget("state")) == "normal"


def test_clear_button_stays_enabled_during_a_run(app):
    app.excel_path.set("/tmp/対象.xlsx")
    states = []

    def fake_run(*args, **kwargs):
        states.append(str(app.log_clear_button.cget("state")))
        return 0

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    assert states == ["normal"]
    assert re.search(r"INFO +実行開始", "\n".join(lines(app)))
