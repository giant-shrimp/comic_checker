"""GUI の「設定」の画面の「読み取る列とシート」のテスト。作品名・ファイル名はすべて架空。"""
import tkinter as tk
from unittest.mock import patch

import pytest

from comic_checker import gui, user_config
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


def type_and_save(app, title_column, sheet):
    form = app.target_form
    for key, text in ((gui.KEY_TITLE_COLUMN, title_column), (gui.KEY_SHEET, sheet)):
        entry = form.entries[key]
        entry.delete(0, "end")
        entry.insert(0, text)
    form.save_button.invoke()
    app.update()


def entry_values(app):
    form = app.target_form
    return (
        form.entries[gui.KEY_TITLE_COLUMN].get(),
        form.entries[gui.KEY_SHEET].get(),
    )


def test_item_names_are_fixed():
    assert gui.KEY_TITLE_COLUMN == "title_column"
    assert gui.KEY_SHEET == "sheet"
    assert gui.DEFAULT_TITLE_COLUMN == "タイトル"


def test_starting_the_app_does_not_create_config_file(app):
    assert not user_config.config_path().exists()


def test_entries_show_defaults_when_nothing_saved(app):
    assert entry_values(app) == ("タイトル", "")


def test_entries_show_saved_values_when_screen_is_built():
    user_config.save_values({gui.KEY_TITLE_COLUMN: "作品名", gui.KEY_SHEET: "シートB"})
    root = tk.Tk()
    try:
        widget = App(master=root)
        assert entry_values(widget) == ("作品名", "シートB")
        widget._stop_elapsed()
    finally:
        root.destroy()


def test_save_stores_stripped_values_and_shows_message(app):
    type_and_save(app, "  作品名  ", "  シートB ")
    assert user_config.get_value(gui.KEY_TITLE_COLUMN) == "作品名"
    assert user_config.get_value(gui.KEY_SHEET) == "シートB"
    assert app.target_form.message.get() == "保存しました"


def test_save_failure_shows_permission_message(app):
    with patch("comic_checker.gui.user_config.save_values", side_effect=OSError("x")):
        type_and_save(app, "作品名", "シートB")
    assert app.target_form.message.get() == (
        "保存できませんでした。保存先のフォルダの権限を確認してください"
    )


def test_save_button_uses_outline_style(app):
    assert str(app.target_form.save_button.cget("style")) == app._outline_style()


def test_saved_values_are_passed_to_count_rows_run_and_next_release(app):
    type_and_save(app, "作品名", "シートB")
    app.excel_path.set("/tmp/list.xlsx")

    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=3, filled=0)) as count:
        with patch("comic_checker.gui.threading.Thread") as thread_cls:
            app._on_run()
    count.assert_called_once_with("/tmp/list.xlsx", sheet="シートB", title_column="作品名")
    run_kwargs = thread_cls.call_args.kwargs["kwargs"]
    assert run_kwargs["title_column"] == "作品名"
    assert run_kwargs["sheet"] == "シートB"

    with patch("comic_checker.gui.run", return_value=1) as mock_run:
        app._run_worker(**run_kwargs)
        app.update()
    assert mock_run.call_args.kwargs["title_column"] == "作品名"
    assert mock_run.call_args.kwargs["sheet"] == "シートB"

    app._reset_buttons_after_run()
    with patch("comic_checker.gui.threading.Thread") as thread_cls:
        app._on_next_release()
    next_kwargs = thread_cls.call_args.kwargs["kwargs"]
    assert next_kwargs["title_column"] == "作品名"
    assert next_kwargs["sheet"] == "シートB"
    with patch("comic_checker.gui.next_release.run", return_value=1) as mock_next:
        app._next_release_worker(**next_kwargs)
        app.update()
    assert mock_next.call_args.kwargs["title_column"] == "作品名"
    assert mock_next.call_args.kwargs["sheet"] == "シートB"


def test_defaults_are_passed_when_nothing_saved(app):
    app.excel_path.set("/tmp/list.xlsx")
    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=3, filled=0)) as count:
        with patch("comic_checker.gui.threading.Thread") as thread_cls:
            app._on_run()
    count.assert_called_once_with("/tmp/list.xlsx", sheet=None, title_column="タイトル")
    run_kwargs = thread_cls.call_args.kwargs["kwargs"]
    assert run_kwargs["title_column"] == "タイトル"
    assert run_kwargs["sheet"] is None

    app._reset_buttons_after_run()
    with patch("comic_checker.gui.threading.Thread") as thread_cls:
        app._on_next_release()
    next_kwargs = thread_cls.call_args.kwargs["kwargs"]
    assert next_kwargs["title_column"] == "タイトル"
    assert next_kwargs["sheet"] is None


def test_saving_blank_values_restores_defaults(app):
    type_and_save(app, "作品名", "シートB")
    type_and_save(app, "", "")
    assert user_config.get_value(gui.KEY_TITLE_COLUMN) is None
    assert user_config.get_value(gui.KEY_SHEET) is None
    assert gui.load_read_target() == ("タイトル", None)
    assert entry_values(app) == ("タイトル", "")

    app.excel_path.set("/tmp/list.xlsx")
    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=3, filled=0)):
        with patch("comic_checker.gui.threading.Thread") as thread_cls:
            app._on_run()
    run_kwargs = thread_cls.call_args.kwargs["kwargs"]
    assert run_kwargs["title_column"] == "タイトル"
    assert run_kwargs["sheet"] is None


def test_leaving_settings_screen_restores_saved_values_and_clears_message(app):
    type_and_save(app, "作品名", "シートB")
    form = app.target_form
    form.entries[gui.KEY_TITLE_COLUMN].delete(0, "end")
    form.entries[gui.KEY_TITLE_COLUMN].insert(0, "未保存の列")
    form.entries[gui.KEY_SHEET].delete(0, "end")
    form.message.set("保存しました")

    app._select_screen(gui.SETTINGS_SCREEN_INDEX)
    app._select_screen(0)
    app.update()

    assert entry_values(app) == ("作品名", "シートB")
    assert form.message.get() == ""
    assert user_config.get_value(gui.KEY_TITLE_COLUMN) == "作品名"
