"""Issue #32: 実行前の「判定済みの行があります」警告のテスト。

症状は「判定済みのファイルをGUIで再実行すると全行スキップされ、何も起きなかったように
見える」こと。スキップされること自体ではなく、それが利用者に伝わらないことが問題なので、
「警告が出ること」と「その場で再判定を選べること」の両方を担保する。

ダイアログ本体（FilledRowsDialog）はTkに依存するため、結線のテストでは選択結果だけを
差し替える。判断と文面生成は純粋関数に出してあり、そちらはTk無しで検証する。
"""
import tkinter as tk
from unittest.mock import patch

import pytest

from comic_checker.gui import (
    CHOICE_CANCEL,
    CHOICE_REJUDGE,
    CHOICE_SKIP,
    App,
    filled_rows_message,
    should_warn_about_filled_rows,
)
from comic_checker.main import RowCounts


@pytest.fixture
def app():
    root = tk.Tk()
    root.withdraw()
    widget = App(master=root)
    yield widget
    root.destroy()


def log_text(widget):
    return widget.log_area.get("1.0", "end")


def patch_choice(choice):
    """FilledRowsDialog(...).show() が choice を返すように差し替える。"""
    return patch("comic_checker.gui.FilledRowsDialog", **{"return_value.show.return_value": choice})


# ------------------------------------------------------------------- 純粋関数


def test_no_warning_when_nothing_is_judged_yet():
    assert should_warn_about_filled_rows(RowCounts(pending=5, filled=0)) is False


def test_warns_when_every_row_is_judged():
    assert should_warn_about_filled_rows(RowCounts(pending=0, filled=73)) is True


def test_warns_even_when_only_some_rows_are_judged():
    # 一部だけ埋まっている場合も、何件がスキップされるかは知らせる。
    assert should_warn_about_filled_rows(RowCounts(pending=2, filled=1)) is True


def test_message_states_that_nothing_will_be_processed_when_all_rows_are_judged():
    # 「実行しても何も起きない」ことを、押す前に読めるようにする。
    message = filled_rows_message(RowCounts(pending=0, filled=73))

    assert "73 行中 73 行" in message
    assert "0 件" in message


def test_message_states_how_many_rows_remain_when_some_are_pending():
    message = filled_rows_message(RowCounts(pending=2, filled=1))

    assert "3 行中 1 行" in message
    assert "2 行だけを処理" in message


# --------------------------------------------------------------------- 結線


def test_runs_without_dialog_when_nothing_is_judged(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=3, filled=0)):
        with patch("comic_checker.gui.FilledRowsDialog") as mock_dialog:
            with patch("comic_checker.gui.threading.Thread") as mock_thread_cls:
                app._on_run()

    mock_dialog.assert_not_called()
    assert mock_thread_cls.call_args.kwargs["kwargs"] == {"skip_filled": True}


def test_skip_choice_runs_with_skip_filled_true(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=0, filled=73)):
        with patch_choice(CHOICE_SKIP):
            with patch("comic_checker.gui.threading.Thread") as mock_thread_cls:
                app._on_run()

    assert mock_thread_cls.call_args.kwargs["kwargs"] == {"skip_filled": True}


def test_rejudge_choice_runs_with_skip_filled_false(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=0, filled=73)):
        with patch_choice(CHOICE_REJUDGE):
            with patch("comic_checker.gui.threading.Thread") as mock_thread_cls:
                app._on_run()

    assert mock_thread_cls.call_args.kwargs["kwargs"] == {"skip_filled": False}


def test_cancel_choice_does_not_run_and_leaves_button_usable(app):
    # キャンセル後に実行ボタンが押せないまま固まらないこと。
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=0, filled=73)):
        with patch_choice(CHOICE_CANCEL):
            with patch("comic_checker.gui.threading.Thread") as mock_thread_cls:
                with patch("comic_checker.gui.run") as mock_run:
                    app._on_run()

    mock_thread_cls.assert_not_called()
    mock_run.assert_not_called()
    assert str(app.run_button["state"]) == "normal"
    assert "キャンセル" in log_text(app)


def test_choice_is_recorded_in_the_log(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=0, filled=73)):
        with patch_choice(CHOICE_SKIP):
            with patch("comic_checker.gui.threading.Thread"):
                app._on_run()

    text = log_text(app)
    assert "73行中 73行は判定済み" in text
    assert "処理対象 0件" in text


def test_rejudge_choice_is_recorded_in_the_log(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=0, filled=73)):
        with patch_choice(CHOICE_REJUDGE):
            with patch("comic_checker.gui.threading.Thread"):
                app._on_run()

    assert "すべて再判定します（73件）" in log_text(app)


def test_run_continues_when_row_count_cannot_be_determined(app):
    # 列が無い・ファイルが壊れている等で数えられなくても、警告をあきらめて実行に進む。
    # 実行時に同じ問題が起きれば、そちらのエラー処理が本来のメッセージを出す。
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.count_rows", side_effect=ValueError("列が見つかりません")):
        with patch("comic_checker.gui.FilledRowsDialog") as mock_dialog:
            with patch("comic_checker.gui.threading.Thread") as mock_thread_cls:
                app._on_run()

    mock_dialog.assert_not_called()
    assert mock_thread_cls.call_args.kwargs["kwargs"] == {"skip_filled": True}
    assert "確認できませんでした" in log_text(app)


def test_no_dialog_and_no_scan_when_no_file_is_selected(app):
    with patch("comic_checker.gui.count_rows") as mock_count:
        with patch("comic_checker.gui.threading.Thread") as mock_thread_cls:
            app._on_run()

    mock_count.assert_not_called()
    mock_thread_cls.assert_not_called()
    assert "Excelファイルを選択してください" in log_text(app)


# ------------------------------------------------------------------ ダイアログ


def test_dialog_returns_the_pressed_choice(app):
    # 実ウィジェットを組み立て、ボタンのコマンドを直接叩いて選択結果を確認する。
    from comic_checker.gui import FilledRowsDialog

    dialog = FilledRowsDialog(app.master, RowCounts(pending=0, filled=73))
    dialog._choose(CHOICE_REJUDGE)

    assert dialog.choice == CHOICE_REJUDGE


def test_dialog_defaults_to_cancel_when_closed_without_choosing(app):
    from comic_checker.gui import FilledRowsDialog

    dialog = FilledRowsDialog(app.master, RowCounts(pending=0, filled=73))
    try:
        assert dialog.choice == CHOICE_CANCEL
    finally:
        dialog.destroy()


def test_dialog_skip_button_shows_zero_when_everything_is_judged(app):
    from comic_checker.gui import FilledRowsDialog

    dialog = FilledRowsDialog(app.master, RowCounts(pending=0, filled=73))
    try:
        assert "0 件" in dialog.skip_button["text"]
    finally:
        dialog.destroy()


def test_dialog_skip_button_shows_remaining_count_when_some_are_pending(app):
    from comic_checker.gui import FilledRowsDialog

    dialog = FilledRowsDialog(app.master, RowCounts(pending=2, filled=1))
    try:
        assert "2件" in dialog.skip_button["text"]
    finally:
        dialog.destroy()
