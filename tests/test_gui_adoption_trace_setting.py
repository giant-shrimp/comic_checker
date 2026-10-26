"""「採用経路のログを出力する」を設定の画面へ移したことと、窓の最小の幅を中身から決めることのテスト。

作品名はすべて架空。合成のイベントは使わず、窓の大きさは geometry で変える。
"""
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

import pytest

from comic_checker import gui, user_config
from comic_checker.gui import App
from comic_checker.main import RowCounts, _default_adoption_trace_path

EXCEL_PATH = "/tmp/対象.xlsx"
SETTINGS_INDEX = 1


@pytest.fixture
def app():
    root = tk.Tk()
    widget = App(master=root)
    widget.pack(fill="both", expand=True)
    root.update()
    yield widget
    widget._stop_elapsed()
    root.destroy()


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def checkbuttons(widget):
    return [w for w in descendants(widget) if isinstance(w, ttk.Checkbutton)]


def run_and_get_trace_file(app):
    app.excel_path.set(EXCEL_PATH)
    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=3, filled=0)):
        with patch("comic_checker.gui.threading.Thread") as mock_thread_cls:
            app._on_run()
    return mock_thread_cls.call_args.kwargs["kwargs"]["adoption_trace_file"]


def resize(app, width, height=None):
    root = app.winfo_toplevel()
    if height is None:
        height = max(root.winfo_height(), 600)
    root.geometry(f"{width}x{height}")
    root.update()


def test_constants_have_the_specified_values():
    assert gui.ADOPTION_TRACE_LABEL == "採用経路のログを出力する"
    assert gui.ADOPTION_TRACE_HINT == (
        "開発者向けです。オンにして「実行」すると、Excel と同じフォルダに採用経路のログを書き出します。"
    )


def test_main_screen_has_no_checkbutton(app):
    assert checkbuttons(app._content) == []


def test_settings_screen_has_only_the_adoption_trace_checkbutton_packed(app):
    found = checkbuttons(app.settings_body)
    assert found == [app.adoption_trace_check]
    assert app.adoption_trace_check.winfo_manager() == "pack"


def test_adoption_trace_card_text_is_label_then_hint(app):
    cards = [w for w in app.settings_body.winfo_children() if isinstance(w, tk.Frame)]
    header, content = cards[2].winfo_children()[0].winfo_children()
    titles = [str(w.cget("text")) for w in header.winfo_children() if "text" in w.keys()]
    assert titles == ["詳しいログ"]
    texts = [str(w.cget("text")) for w in content.winfo_children()]
    assert texts == [gui.ADOPTION_TRACE_LABEL, gui.ADOPTION_TRACE_HINT]


def test_default_is_off_and_run_passes_no_trace_file(app):
    assert app.adoption_trace.get() is False
    assert run_and_get_trace_file(app) is None


def test_turning_on_in_settings_then_run_passes_default_trace_path(app):
    app._select_screen(SETTINGS_INDEX)
    app.adoption_trace_check.invoke()
    app._select_screen(0)
    assert run_and_get_trace_file(app) == _default_adoption_trace_path(EXCEL_PATH)


def test_value_survives_leaving_settings_and_is_not_saved(app):
    app._select_screen(SETTINGS_INDEX)
    app.adoption_trace_check.invoke()
    app._select_screen(0)
    app._select_screen(SETTINGS_INDEX)
    app.update()
    assert app.adoption_trace.get() is True
    assert not user_config.config_path().exists()


def test_required_size_covers_every_screen(app):
    width, height = app.required_size()
    assert width >= app.winfo_reqwidth()
    for screen in app._screens:
        assert width >= gui.NAV_WIDTH + screen.winfo_reqwidth()
    assert height == app.winfo_reqheight()


def test_drop_area_canvas_is_wide_enough_for_its_content(app):
    main_width = app._content.winfo_reqwidth()
    resize(app, gui.NAV_WIDTH + main_width)
    inner = app.nametowidget(app._drop_canvas.itemcget(app._drop_window, "window"))
    assert inner.winfo_width() >= inner.winfo_reqwidth()


def test_settings_canvas_is_wide_enough_for_its_body(app):
    settings_screen = app._screens[SETTINGS_INDEX]
    resize(app, gui.NAV_WIDTH + settings_screen.winfo_reqwidth())
    app._select_screen(SETTINGS_INDEX)
    app.update()
    assert app.settings_canvas.winfo_width() >= app.settings_body.winfo_reqwidth()


def test_main_sets_minsize_from_required_size():
    root = tk.Tk()
    root.withdraw()
    captured = []
    real_app_class = gui.App

    def make_app(*args, **kwargs):
        instance = real_app_class(*args, **kwargs)
        captured.append(instance)
        return instance

    try:
        with patch.object(gui, "_enable_dpi_awareness"), patch.object(
            gui, "_create_root", return_value=root
        ), patch.object(gui, "_center_window"), patch.object(
            root, "mainloop", create=True
        ), patch.object(gui, "App", side_effect=make_app):
            gui.main()
        (instance,) = captured
        _, expected_minimum = gui._compute_window_sizes(
            root.winfo_screenwidth(), root.winfo_screenheight(), *instance.required_size()
        )
        assert tuple(root.minsize()) == tuple(expected_minimum)
    finally:
        for instance in captured:
            instance._stop_elapsed()
        root.destroy()
