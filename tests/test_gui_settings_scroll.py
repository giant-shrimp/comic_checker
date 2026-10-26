"""設定の画面が、縦に収まらないときだけスクロールすることのテスト。"""
import tkinter as tk

import pytest

from comic_checker.gui import App

SETTINGS_INDEX = 1
MAIN_INDEX = 0


@pytest.fixture
def app():
    root = tk.Tk()
    widget = App(master=root)
    widget.pack(fill="both", expand=True)
    root.update()
    yield widget
    widget._stop_elapsed()
    root.destroy()


def resize(app, geometry):
    app.winfo_toplevel().geometry(geometry)
    app.update()


def wheel_down():
    event = tk.Event()
    event.delta = -120
    event.num = 0
    return event


def is_inside(widget, ancestor):
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.master
    return False


def test_forms_are_inside_settings_body(app):
    assert is_inside(app.key_form, app.settings_body)
    assert is_inside(app.target_form, app.settings_body)
    assert is_inside(app.target_form.save_button, app.settings_body)


def test_scrollbar_hidden_when_tall_and_shown_when_short(app):
    app._select_screen(SETTINGS_INDEX)
    resize(app, "1000x4000")
    assert not app.settings_scrollbar.winfo_ismapped()
    resize(app, "1000x300")
    assert app.settings_scrollbar.winfo_ismapped()


def test_scrolled_to_bottom_shows_target_save_button(app):
    app._select_screen(SETTINGS_INDEX)
    resize(app, "1100x400")
    canvas = app.settings_canvas
    assert canvas.bbox("all")[3] > canvas.winfo_height()
    canvas.yview_moveto(1.0)
    app.update()
    button = app.target_form.save_button
    assert button.winfo_rooty() >= canvas.winfo_rooty()
    bottom = button.winfo_rooty() + button.winfo_height()
    assert bottom <= canvas.winfo_rooty() + canvas.winfo_height()


def test_wheel_scrolls_when_settings_screen_shown(app):
    app._select_screen(SETTINGS_INDEX)
    resize(app, "1100x400")
    app._on_settings_wheel(wheel_down())
    app.update()
    assert app.settings_canvas.yview()[0] > 0


def test_wheel_does_not_scroll_when_other_screen_shown(app):
    app._select_screen(SETTINGS_INDEX)
    resize(app, "1100x400")
    app._select_screen(MAIN_INDEX)
    app.update()
    app._on_settings_wheel(wheel_down())
    app.update()
    assert app.settings_canvas.yview()[0] == 0


def test_no_horizontal_scroll(app):
    app._select_screen(SETTINGS_INDEX)
    app.update()
    assert app.settings_body.winfo_width() == app.settings_canvas.winfo_width()
    assert app.settings_canvas.cget("xscrollcommand") == ""


@pytest.mark.parametrize("sequence", ["<MouseWheel>", "<Button-4>", "<Button-5>"])
def test_wheel_is_bound_with_bind_all(app, sequence):
    # bind_all のスクリプトには、登録した関数の名前（メソッド名）が含まれる。
    assert "_on_settings_wheel" in app.bind_all(sequence)
