"""GUI の左のメニューによる画面の切り替えのテスト。作品名はすべて架空。"""
import tkinter as tk
from unittest.mock import patch

import pytest

from comic_checker import gui, version_string
from comic_checker.gui import App
from comic_checker.main import RowCounts


@pytest.fixture
def app():
    root = tk.Tk()
    widget = App(master=root)
    widget.pack(fill="both", expand=True)
    root.update()
    yield widget
    widget._stop_elapsed()
    root.destroy()


def click(app, index):
    app.nav_items[index].event_generate("<Button-1>")
    app.update()


def visible(widget):
    return widget.winfo_manager() == "grid"


def screens(app):
    return app._screens


def card_texts(screen):
    """画面の中のカードを（見出し, 中身の文言の並び）で返す。上から順。"""
    result = []
    for outer in sorted(
        screen.winfo_children(), key=lambda w: w.winfo_y() if w.winfo_ismapped() else 0
    ):
        if not isinstance(outer, tk.Frame):
            continue
        inner = outer.winfo_children()[0]
        header, content = inner.winfo_children()
        title = [str(w.cget("text")) for w in header.winfo_children() if "text" in w.keys()]
        lines = [str(w.cget("text")) for w in content.winfo_children()]
        result.append((title[0], lines))
    return result


def test_main_screen_is_selected_at_start(app):
    assert [visible(s) for s in screens(app)] == [True, False, False, False]
    assert app.run_button.winfo_toplevel() is app.winfo_toplevel()


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_clicking_item_shows_only_its_screen(app, index):
    click(app, (index + 1) % 4)
    click(app, index)
    assert [visible(s) for s in screens(app)] == [n == index for n in range(4)]


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_only_selected_item_has_accent_background(app, index):
    click(app, index)
    backgrounds = [str(item.cget("background")) for item in app.nav_items]
    assert backgrounds == [
        gui.COLOR_ACCENT if n == index else gui.COLOR_NAV_BG for n in range(4)
    ]
    foregrounds = [str(item.cget("foreground")) for item in app.nav_items]
    assert foregrounds[index] == gui.COLOR_ON_ACCENT


def test_clicking_icon_also_switches(app):
    app._nav_icons[1].event_generate("<Button-1>")
    app.update()
    assert app.selected_screen == 1


def test_settings_screen_has_rakuten_key_card(app):
    cards = [
        outer
        for outer in app.settings_body.winfo_children()
        if isinstance(outer, tk.Frame)
    ]
    assert len(cards) == 3
    header, content = cards[0].winfo_children()[0].winfo_children()
    titles = [str(w.cget("text")) for w in header.winfo_children() if "text" in w.keys()]
    assert titles == ["楽天APIキーの設定"]
    assert content.winfo_children() == [app.key_form]
    header, content = cards[1].winfo_children()[0].winfo_children()
    titles = [str(w.cget("text")) for w in header.winfo_children() if "text" in w.keys()]
    assert titles == ["読み取る列とシート"]
    assert content.winfo_children() == [app.target_form]
    header, content = cards[2].winfo_children()[0].winfo_children()
    titles = [str(w.cget("text")) for w in header.winfo_children() if "text" in w.keys()]
    assert titles == ["詳しいログ"]
    assert content.winfo_children()[0] == app.adoption_trace_check


def test_showing_settings_screen_calls_refresh_status(app):
    with patch.object(app.key_form, "refresh_status") as refresh:
        click(app, 1)
    refresh.assert_called_once_with()


def test_leaving_settings_screen_clears_entries(app):
    click(app, 1)
    for entry in app.key_form.entries.values():
        entry.insert(0, "架空の入力")
    click(app, 2)
    for entry in app.key_form.entries.values():
        assert entry.get() == ""


def test_leaving_settings_screen_clears_message(app):
    click(app, 1)
    next(iter(app.key_form.entries.values())).insert(0, "架空の入力")
    with patch("comic_checker.gui.user_config.save_values"):
        app.key_form.save()
    assert app.key_form.message.get() == "保存しました"
    click(app, 2)
    assert app.key_form.message.get() == ""


def test_help_scrollbar_hidden_when_content_fits(app):
    click(app, 2)
    app.master.geometry("1000x4000")
    app.update()
    assert not app.help_scrollbar.winfo_ismapped()


def test_help_scrollbar_shown_when_content_does_not_fit(app):
    click(app, 2)
    app.master.geometry("1000x200")
    app.update()
    assert app.help_scrollbar.winfo_ismapped()


def test_secondary_buttons_use_outline_style(app):
    expected = "Outline.TButton" if app._theme.get("secondary_button") else "TButton"
    assert expected == app._outline_style()
    for button in (app.copy_version_button, app.help_guide_button, app.key_form.save_button):
        assert str(button.cget("style")) == expected


def test_outline_style_is_used_when_available(app):
    app._theme["secondary_button"] = True
    assert app._outline_style() == "Outline.TButton"
    app._theme["secondary_button"] = False
    assert app._outline_style() == "TButton"


def test_copy_button_puts_version_string_on_clipboard(app):
    click(app, 3)
    assert str(app.about_version_label.cget("text")) == version_string()
    app.copy_version_button.invoke()
    assert app.clipboard_get() == version_string()


@pytest.mark.parametrize("method", ["_on_run", "_on_next_release"])
def test_run_continues_while_other_screen_is_shown(app, method):
    app.excel_path.set("/tmp/dir/list.xlsx")
    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=3, filled=0)):
        with patch("comic_checker.gui.threading.Thread"):
            getattr(app, method)()
    click(app, 3)
    if method == "_on_run":
        app._on_progress(1, 3, "架空の作品", "完結", "架空の作品")
    else:
        app._on_next_progress(1, 3, "架空の作品", "発売済み", "2026-01-01")
    app.update()
    assert visible(app.status_bar)
    assert not visible(screens(app)[0])
    click(app, 0)
    assert visible(app.status_bar)
    assert "架空の作品" in app.log_area.get("1.0", "end")
    assert float(app.progress.cget("value")) > 0


def test_status_bar_visible_on_every_screen(app):
    for index in range(4):
        click(app, index)
        assert visible(app.status_bar)
