"""GUI の「次巻発売日を確認」と「楽天APIキーの設定」のテスト。作品名・キーはすべて架空。"""
import tkinter as tk
from unittest.mock import MagicMock, patch

import pytest

from comic_checker import user_config
from comic_checker.gui import App, RakutenKeyDialog

SECRET_ID = "secret-app-id-9911"
SECRET_KEY = "secret-access-key-9922"


@pytest.fixture(autouse=True)
def _no_env_keys(monkeypatch):
    # 開発機の環境変数に左右されないようにする（値は読まない）。
    monkeypatch.delenv("RAKUTEN_APP_ID", raising=False)
    monkeypatch.delenv("RAKUTEN_ACCESS_KEY", raising=False)


@pytest.fixture
def app():
    root = tk.Tk()
    root.withdraw()
    widget = App(master=root)
    yield widget
    root.destroy()


def log_text(widget):
    return widget.log_area.get("1.0", "end")


def run_worker(app, side_effect=None, return_value=0, cancel_event=None):
    with patch("comic_checker.gui.next_release.run", side_effect=side_effect,
               return_value=return_value) as mock_run:
        app._next_release_worker(excel_path="/tmp/list.xlsx", cancel_event=cancel_event)
        app.master.update()
    return mock_run


# ---------------------------------------------------------------- ボタンと実行


def test_button_starts_next_release_with_cancel_event(app):
    app.excel_path.set("/tmp/list.xlsx")
    with patch("comic_checker.gui.threading.Thread") as thread_cls:
        app._on_next_release()
    kwargs = thread_cls.call_args.kwargs
    assert kwargs["target"] == app._next_release_worker
    assert kwargs["kwargs"]["excel_path"] == "/tmp/list.xlsx"
    assert kwargs["kwargs"]["cancel_event"] is app._cancel_event

    with patch("comic_checker.gui.next_release.run", return_value=2) as mock_run:
        app._next_release_worker(**kwargs["kwargs"])
        app.master.update()
    mock_run.assert_called_once_with(
        "/tmp/list.xlsx",
        on_progress=app._on_next_progress,
        cancel_event=kwargs["kwargs"]["cancel_event"],
    )


def test_both_run_buttons_disabled_while_running(app):
    app.excel_path.set("/tmp/list.xlsx")
    with patch("comic_checker.gui.threading.Thread"):
        app._on_next_release()
    assert str(app.run_button["state"]) == "disabled"
    assert str(app.next_button["state"]) == "disabled"
    assert str(app.cancel_button["state"]) == "normal"

    app._reset_buttons_after_run()
    assert str(app.run_button["state"]) == "normal"
    assert str(app.next_button["state"]) == "normal"
    assert str(app.cancel_button["state"]) == "disabled"


def test_complete_check_also_disables_next_button(app):
    app.excel_path.set("/tmp/list.xlsx")
    with patch("comic_checker.gui.threading.Thread"), patch(
        "comic_checker.gui.count_rows", return_value=None
    ):
        app._on_run()
    assert str(app.run_button["state"]) == "disabled"
    assert str(app.next_button["state"]) == "disabled"


def test_no_file_selected_does_not_start(app):
    with patch("comic_checker.gui.threading.Thread") as thread_cls:
        app._on_next_release()
    thread_cls.assert_not_called()
    assert "Excelファイルを選択してください" in log_text(app)


def test_buttons_restored_after_worker(app):
    app.run_button.config(state="disabled")
    app.next_button.config(state="disabled")
    run_worker(app, return_value=1)
    assert str(app.run_button["state"]) == "normal"
    assert str(app.next_button["state"]) == "normal"


def test_completion_and_cancel_messages(app):
    run_worker(app, return_value=4)
    assert "完了しました（4件処理" in log_text(app)
    assert "完了しました" in app.status_text.get()

    import threading

    event = threading.Event()
    event.set()

    def fake_run(path, on_progress=None, cancel_event=None):
        on_progress(1, 5, "架空の作品A", "未確認", None)
        on_progress(2, 5, "架空の作品B", "未確認", None)
        return 2

    run_worker(app, side_effect=fake_run, cancel_event=event)
    assert "中断しました（2件処理・保存済み" in log_text(app)


def test_cancel_during_last_row_is_reported_as_complete(app):
    import threading

    event = threading.Event()

    def fake_run(path, on_progress=None, cancel_event=None):
        on_progress(1, 2, "架空の作品A", "未確認", None)
        on_progress(2, 2, "架空の作品B", "未確認", None)
        event.set()  # 最後の行の処理中に中断が要求された
        return 2

    run_worker(app, side_effect=fake_run, cancel_event=event)
    assert "完了しました（2件処理" in log_text(app)
    assert "中断しました" not in log_text(app)
    assert "完了しました" in app.status_text.get()


# ---------------------------------------------------------------- 集計・ログ


def test_summary_uses_next_release_statuses(app):
    def fake_run(path, on_progress=None, cancel_event=None):
        on_progress(1, 5, "架空甲", "次巻あり", "2030年1月5日", error=None)
        on_progress(2, 5, "架空乙", "未定", "未定", error=None)
        on_progress(3, 5, "架空丙", "要確認", "要確認", error=None)
        on_progress(4, 5, "架空丁", "ヒットなし", "ヒットなし", error=None)
        on_progress(5, 5, "架空戊", "エラー", "エラー", error=RuntimeError("x"))
        return 5

    run_worker(app, side_effect=fake_run)
    assert app.summary_text.get() == (
        "次巻あり 1 ／ 未定 1 ／ 要確認 1 ／ ヒットなし 1 ／ エラー 1"
    )


def test_summary_of_complete_check_is_unchanged_after_next_release(app):
    run_worker(app, return_value=0)
    assert app._summary_statuses == (
        "次巻あり", "未定", "要確認", "ヒットなし", "エラー"
    )
    with patch("comic_checker.gui.run", return_value=1):
        app._run_worker(excel_path="/tmp/list.xlsx", cancel_event=None)
        app.master.update()
    assert app._summary_statuses == ("完結", "連載中", "判定不能", "記事なし", "エラー")


def test_row_error_log_shows_type_name_only(app):
    def fake_run(path, on_progress=None, cancel_event=None):
        on_progress(
            1, 1, "架空甲", "エラー", "エラー",
            error=ConnectionError(f"https://example.invalid/?applicationId={SECRET_ID}"),
        )
        return 1

    run_worker(app, side_effect=fake_run)
    text = log_text(app)
    assert "[1/1] 架空甲 -> エラー ConnectionError" in text
    assert SECRET_ID not in text
    assert "applicationId" not in text


def test_progress_line_for_normal_row(app):
    def fake_run(path, on_progress=None, cancel_event=None):
        on_progress(1, 1, "架空甲", "次巻あり", "2030年1月5日", error=None)
        return 1

    run_worker(app, side_effect=fake_run)
    assert "[1/1] 架空甲 -> 次巻あり (2030年1月5日)" in log_text(app)


# ---------------------------------------------------------------- エラー表示


def test_missing_key_message_is_shown_as_is(app):
    message = "楽天ブックスのキー（RAKUTEN_APP_ID）が設定されていません。"
    run_worker(app, side_effect=RuntimeError(message))
    assert message in log_text(app)
    assert app.status_text.get() == message
    assert "Traceback" not in log_text(app)


def test_missing_title_column_message_is_shown_as_is(app):
    message = "ヘッダー行に「タイトル」列が見つかりません"
    run_worker(app, side_effect=ValueError(message))
    assert message in log_text(app)
    assert app.status_text.get() == message


def test_permission_error_message(app):
    run_worker(app, side_effect=PermissionError("/tmp/list.xlsx"))
    text = log_text(app)
    assert "Excel を保存できません" in text
    assert "Excel で開いたまま" in text
    assert "Excel で開いたまま" in app.status_text.get()
    assert "Traceback" not in text


def test_other_exception_shows_type_name_only(app):
    run_worker(app, side_effect=KeyError(f"applicationId={SECRET_ID}"))
    text = log_text(app)
    assert "KeyError" in text
    assert SECRET_ID not in text
    assert SECRET_ID not in app.status_text.get()
    assert str(app.next_button["state"]) == "normal"


# ---------------------------------------------------------------- キー設定のウィンドウ


def test_key_dialog_entries_are_masked_and_empty(app):
    user_config.save_values({user_config.KEY_RAKUTEN_APP_ID: SECRET_ID})
    dialog = RakutenKeyDialog(app.master)
    for entry in dialog.entries.values():
        assert entry.cget("show") == "*"
        assert entry.get() == ""
    assert dialog.status_vars[user_config.KEY_RAKUTEN_APP_ID].get().startswith("設定済み")
    assert dialog.status_vars[user_config.KEY_RAKUTEN_ACCESS_KEY].get().startswith("未設定")
    dialog.destroy()


def test_key_dialog_save_clears_entries_and_hides_values(app):
    dialog = RakutenKeyDialog(app.master)
    dialog.entries[user_config.KEY_RAKUTEN_APP_ID].insert(0, SECRET_ID)
    dialog.entries[user_config.KEY_RAKUTEN_ACCESS_KEY].insert(0, SECRET_KEY)
    dialog.save()
    app.master.update()

    assert user_config.get_value(user_config.KEY_RAKUTEN_APP_ID) == SECRET_ID
    assert user_config.get_value(user_config.KEY_RAKUTEN_ACCESS_KEY) == SECRET_KEY
    for entry in dialog.entries.values():
        assert entry.get() == ""
    shown = [dialog.message.get()] + [v.get() for v in dialog.status_vars.values()]
    shown.append(log_text(app))
    for text in shown:
        assert SECRET_ID not in text
        assert SECRET_KEY not in text
    assert dialog.message.get() == "保存しました"
    assert all(v.get() == "設定済み" for v in dialog.status_vars.values())
    dialog.destroy()


def test_key_dialog_blank_field_keeps_existing_value(app):
    user_config.save_values({user_config.KEY_RAKUTEN_APP_ID: SECRET_ID})
    dialog = RakutenKeyDialog(app.master)
    dialog.entries[user_config.KEY_RAKUTEN_ACCESS_KEY].insert(0, SECRET_KEY)
    dialog.save()
    assert user_config.get_value(user_config.KEY_RAKUTEN_APP_ID) == SECRET_ID
    assert user_config.get_value(user_config.KEY_RAKUTEN_ACCESS_KEY) == SECRET_KEY
    dialog.destroy()


def test_key_dialog_all_blank_changes_nothing(app):
    dialog = RakutenKeyDialog(app.master)
    dialog.save()
    assert not user_config.config_path().exists()
    assert "何も変更しませんでした" in dialog.message.get()
    dialog.destroy()


def test_key_dialog_save_failure_hides_values(app):
    dialog = RakutenKeyDialog(app.master)
    dialog.entries[user_config.KEY_RAKUTEN_APP_ID].insert(0, SECRET_ID)
    with patch.object(user_config, "save_values", side_effect=OSError(SECRET_ID)):
        dialog.save()
    assert SECRET_ID not in dialog.message.get()
    assert "保存できませんでした" in dialog.message.get()
    dialog.destroy()


def test_key_dialog_notes_env_priority(app, monkeypatch):
    monkeypatch.setenv("RAKUTEN_APP_ID", "env-app-id-value")
    dialog = RakutenKeyDialog(app.master)
    text = dialog.status_vars[user_config.KEY_RAKUTEN_APP_ID].get()
    assert "環境変数 RAKUTEN_APP_ID" in text
    assert "優先" in text
    assert "env-app-id-value" not in text
    dialog.destroy()


def test_key_button_opens_dialog(app):
    with patch("comic_checker.gui.RakutenKeyDialog", MagicMock()) as dialog_cls:
        app._open_key_dialog()
    dialog_cls.assert_called_once_with(app.master)


def test_next_release_chips_are_colour_coded(app):
    from tkinter import ttk

    def fake_run(path, on_progress=None, cancel_event=None):
        on_progress(1, 4, "架空甲", "次巻あり", "2030年1月5日", error=None)
        on_progress(2, 4, "架空乙", "未定", "未定", error=None)
        on_progress(3, 4, "架空丙", "要確認", "要確認", error=None)
        on_progress(4, 4, "架空丁", "ヒットなし", "ヒットなし", error=None)
        return 4

    run_worker(app, side_effect=fake_run)
    style = ttk.Style(app.master)
    colors = {
        chip.cget("text"): style.lookup(str(chip.cget("style")), "foreground")
        for chip in app._summary_chips
        if chip.cget("text") != "／"
    }
    assert colors == {
        "次巻あり 1": "#1f7a3d",
        "未定 1": "#5f6b7a",
        "要確認 1": "#a2660a",
        "ヒットなし 1": "#5f6b7a",
    }
