"""楽天APIキーが未設定のまま「次巻発売日を確認」を押したときの案内のテスト（Issue #565）。

キーの値はすべて架空。
"""
import tkinter as tk
from unittest.mock import patch

import pytest

from comic_checker import gui, user_config
from comic_checker.gui import App, MISSING_RAKUTEN_KEYS_MESSAGE, has_rakuten_keys
from comic_checker.main import RowCounts

EXPECTED_MESSAGE = (
    "楽天APIキーが設定されていません。"
    "「設定」の画面でアプリIDとアクセスキーを保存してください。"
)


@pytest.fixture(autouse=True)
def _no_env_keys(monkeypatch):
    # 開発機の環境変数に左右されないようにする（値は読まない）。
    monkeypatch.delenv("RAKUTEN_APP_ID", raising=False)
    monkeypatch.delenv("RAKUTEN_ACCESS_KEY", raising=False)


@pytest.fixture
def app():
    root = tk.Tk()
    widget = App(master=root)
    widget.pack(fill="both", expand=True)
    root.update()
    yield widget
    widget._stop_elapsed()
    root.destroy()


def invoke(app, method_name):
    """指定の入口を呼び、(Thread のモック, count_rows のモック) を返す。"""
    with patch(
        "comic_checker.gui.count_rows", return_value=RowCounts(pending=3, filled=0)
    ) as count:
        with patch("comic_checker.gui.threading.Thread") as thread_cls:
            getattr(app, method_name)()
    return thread_cls, count


def log_messages(app):
    return [(level, message) for _time, level, message in app._log_entries]


def test_message_text_is_fixed():
    assert MISSING_RAKUTEN_KEYS_MESSAGE == EXPECTED_MESSAGE


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"RAKUTEN_APP_ID": "dummy-app-id"},
        {"RAKUTEN_ACCESS_KEY": "dummy-access-key"},
    ],
    ids=["neither", "app_id_only", "access_key_only"],
)
def test_missing_keys_stops_before_starting(app, monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    app.excel_path.set("/tmp/list.xlsx")
    thread_cls, _count = invoke(app, "_on_next_release")
    thread_cls.assert_not_called()
    assert log_messages(app) == [("ERROR", EXPECTED_MESSAGE)]
    assert app.status_text.get() == EXPECTED_MESSAGE
    assert str(app.run_button.cget("state")) == "normal"
    assert str(app.next_button.cget("state")) == "normal"
    assert str(app.cancel_button.cget("state")) == "disabled"
    assert app._elapsed_after_id is None


def test_keys_saved_in_config_start_worker(app):
    user_config.save_values(
        {
            user_config.KEY_RAKUTEN_APP_ID: "dummy-app-id",
            user_config.KEY_RAKUTEN_ACCESS_KEY: "dummy-access-key",
        }
    )
    app.excel_path.set("/tmp/list.xlsx")
    thread_cls, _count = invoke(app, "_on_next_release")
    thread_cls.assert_called_once()
    assert EXPECTED_MESSAGE not in [m for _level, m in log_messages(app)]


def test_keys_in_env_start_worker(app, monkeypatch):
    monkeypatch.setenv("RAKUTEN_APP_ID", "dummy-app-id")
    monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "dummy-access-key")
    app.excel_path.set("/tmp/list.xlsx")
    thread_cls, _count = invoke(app, "_on_next_release")
    thread_cls.assert_called_once()
    assert EXPECTED_MESSAGE not in [m for _level, m in log_messages(app)]


def test_run_button_does_not_need_keys(app):
    app.excel_path.set("/tmp/list.xlsx")
    thread_cls, _count = invoke(app, "_on_run")
    thread_cls.assert_called_once()
    assert EXPECTED_MESSAGE not in [m for _level, m in log_messages(app)]


def test_no_file_selected_keeps_existing_warning(app):
    thread_cls, _count = invoke(app, "_on_next_release")
    thread_cls.assert_not_called()
    assert log_messages(app) == [("WARNING", "Excelファイルを選択してください")]


def test_missing_keys_skip_sheet_check(app):
    app.excel_path.set("/tmp/list.xlsx")
    with patch("comic_checker.gui.find_missing_sheet") as finder:
        invoke(app, "_on_next_release")
    finder.assert_not_called()


def test_has_rakuten_keys_follows_env_then_config(monkeypatch):
    assert has_rakuten_keys() is False
    monkeypatch.setenv("RAKUTEN_APP_ID", "dummy-app-id")
    assert has_rakuten_keys() is False
    user_config.save_values({user_config.KEY_RAKUTEN_ACCESS_KEY: "dummy-access-key"})
    assert has_rakuten_keys() is True
