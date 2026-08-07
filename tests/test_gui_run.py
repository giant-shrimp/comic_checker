import threading
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

import pytest

from comic_checker.gui import App, _parse_dropped_paths
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


# --------------------------------------------------------------- 既存の回帰テスト
# GUIの見た目を刷新（ttk化・進捗バー・サマリ追加）しても、下記の振る舞いは
# 変わってはいけない。Issue #24の制約により、これらは削除・skipしない。


def test_run_worker_calls_run_with_excel_path_and_on_progress(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.run", return_value=3) as mock_run:
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    # Issue #32: skip_filled を明示的に渡すようになった（GUIから再判定を選べるようにするため）。
    # 既定値は従来どおり True で、判定済みの行はスキップされる。
    # Issue #61: cancel_event も run() へそのまま渡す（ここでは中断なし＝None）。
    mock_run.assert_called_once_with(
        "/tmp/対象.xlsx",
        on_progress=app._on_progress,
        skip_filled=True,
        cancel_event=None,
        adoption_trace_file=None,
    )


def test_run_worker_streams_progress_to_log(app):
    app.excel_path.set("/tmp/対象.xlsx")

    def fake_run(excel_path, on_progress=None, skip_filled=True, cancel_event=None, adoption_trace_file=None):
        on_progress(1, 2, "ONE PIECE", "連載中", "ONE PIECE", error=None)
        on_progress(2, 2, "謎の作品", "エラー", "", error=RuntimeError("boom"))
        return 2

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    text = log_text(app)
    assert "[1/2] ONE PIECE -> 連載中 (ONE PIECE)" in text
    assert "[2/2] 謎の作品 -> エラー (boom)" in text


def test_run_worker_logs_completion_with_count_and_path(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.run", return_value=5):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    text = log_text(app)
    assert "完了しました" in text
    assert "5件処理" in text
    assert "/tmp/対象.xlsx" in text


def test_run_worker_reenables_button_after_success(app):
    app.excel_path.set("/tmp/対象.xlsx")
    app.run_button.config(state="disabled")

    with patch("comic_checker.gui.run", return_value=1):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    assert str(app.run_button["state"]) == "normal"


def test_run_worker_logs_error_and_reenables_button_on_exception(app):
    app.excel_path.set("/tmp/対象.xlsx")
    app.run_button.config(state="disabled")

    with patch("comic_checker.gui.run", side_effect=ValueError("列「タイトル」が見つかりません")):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    text = log_text(app)
    assert "エラーが発生しました" in text
    assert "列「タイトル」が見つかりません" in text
    assert str(app.run_button["state"]) == "normal"


def test_on_run_disables_button_and_starts_worker_thread(app):
    # 実スレッドは起動せず、Threadの生成・startだけを検証する
    # （_run_worker自体の挙動は他のテストで直接呼び出して検証済み）。
    app.excel_path.set("/tmp/対象.xlsx")

    # Issue #32: 実行前に count_rows() で判定済み行を数えるようになった。ここでは
    # スレッド起動の検証が目的なので、判定済み0件＝ダイアログ無しの経路に固定する。
    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=3, filled=0)):
        with patch("comic_checker.gui.threading.Thread") as mock_thread_cls:
            app._on_run()

    assert str(app.run_button["state"]) == "disabled"
    # Issue #61: 中断用の Event はメインスレッド（_on_run）で作り、ワーカーへ引数で渡す。
    assert app._cancel_event is not None
    mock_thread_cls.assert_called_once_with(
        target=app._run_worker,
        kwargs={
            "excel_path": "/tmp/対象.xlsx",
            "skip_filled": True,
            "cancel_event": app._cancel_event,
            "adoption_trace_file": None,
        },
        daemon=True,
    )
    mock_thread_cls.return_value.start.assert_called_once()


def test_run_worker_uses_excel_path_captured_at_launch_even_if_changed_later(app):
    # Issue #33: _run_worker はワーカースレッドから self.excel_path を直接読んで
    # はいけない。_on_run が起動時に捕捉した値だけを使うことを、実スレッドを使わずに
    # 確認する（Threadをモックし、捕捉したkwargsを後から同期的に渡すだけなので
    # タイミング依存がなく再現性がある）。
    app.excel_path.set("/tmp/最初のファイル.xlsx")

    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=1, filled=0)):
        with patch("comic_checker.gui.threading.Thread") as mock_thread_cls:
            app._on_run()
    captured_kwargs = mock_thread_cls.call_args.kwargs["kwargs"]

    # 実行開始後にユーザーがファイルを変更した状況を模擬する。
    app.excel_path.set("/tmp/別のファイル.xlsx")

    with patch("comic_checker.gui.run", return_value=0) as mock_run:
        app._run_worker(**captured_kwargs)
        app.master.update()

    mock_run.assert_called_once()
    assert mock_run.call_args.args[0] == "/tmp/最初のファイル.xlsx"
    text = log_text(app)
    assert "最初のファイル.xlsx" in text
    assert "別のファイル.xlsx" not in text


# ------------------------------------------------------------ 中断（Issue #61）


def start_run_without_thread(app):
    """_on_run をワーカー抜きで走らせ、生成された cancel_event を返す。

    中断ボタンの状態遷移だけを見たいので、実スレッドは起動しない。
    """
    app.excel_path.set("/tmp/対象.xlsx")
    with patch("comic_checker.gui.count_rows", return_value=RowCounts(pending=3, filled=0)):
        with patch("comic_checker.gui.threading.Thread"):
            app._on_run()
    app.master.update()
    return app._cancel_event


def test_cancel_button_is_disabled_until_a_run_starts(app):
    assert str(app.cancel_button["state"]) == "disabled"

    start_run_without_thread(app)

    assert str(app.cancel_button["state"]) == "normal"


def test_cancel_sets_the_event_and_says_so_before_the_run_actually_stops(app):
    cancel_event = start_run_without_thread(app)

    app._on_cancel()
    app.master.update()

    assert cancel_event.is_set()
    # 押した瞬間に応答を返す（無反応に見せない）。実際に止まるのは行の切れ目。
    assert str(app.cancel_button["state"]) == "disabled"
    message = "中断します（現在の行の処理を終えるまでお待ちください）"
    assert message in log_text(app)
    assert app.status_text.get() == message


def test_cancel_does_nothing_when_no_run_is_in_flight(app):
    # ボタンは無効なので通常は押せないが、押されても落ちないことを固定する。
    app._on_cancel()
    app.master.update()

    assert app._cancel_event is None
    assert log_text(app).strip() == ""


def test_run_worker_reports_interruption_instead_of_completion(app):
    app.excel_path.set("/tmp/対象.xlsx")
    cancel_event = threading.Event()

    def fake_run(excel_path, on_progress=None, skip_filled=True, cancel_event=None, adoption_trace_file=None):
        # 2行処理したところで中断され、run() は「実際に処理した行数」を返す。
        on_progress(1, 5, "A", "完結", "A", error=None)
        on_progress(2, 5, "B", "連載中", "B", error=None)
        cancel_event.set()
        return 2

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=cancel_event)
        app.master.update()

    assert app.status_text.get() == "中断しました（2件処理・保存済み）"
    text = log_text(app)
    assert "中断しました（2件処理・保存済み" in text
    assert "/tmp/対象.xlsx" in text
    # 途中で止めたのに「完了」と出してはいけない。
    assert "完了しました" not in text


def test_run_worker_reports_completion_when_cancel_event_is_never_set(app):
    app.excel_path.set("/tmp/対象.xlsx")
    cancel_event = threading.Event()

    with patch("comic_checker.gui.run", return_value=3):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=cancel_event)
        app.master.update()

    assert app.status_text.get() == "完了しました（3件処理）"
    assert "中断しました" not in log_text(app)


def test_buttons_are_restored_after_a_cancelled_run(app):
    cancel_event = start_run_without_thread(app)
    app._on_cancel()

    with patch("comic_checker.gui.run", return_value=1):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=cancel_event)
        app.master.update()

    assert str(app.run_button["state"]) == "normal"
    assert str(app.cancel_button["state"]) == "disabled"
    # 次の実行のために持ち越さない（前回の中断要求が効いたままにならない）。
    assert app._cancel_event is None


# ------------------------------------------------------------------ 進捗バー


def test_progress_bar_tracks_index_and_total(app):
    app.excel_path.set("/tmp/対象.xlsx")

    def fake_run(excel_path, on_progress=None, skip_filled=True, cancel_event=None, adoption_trace_file=None):
        on_progress(1, 4, "A", "完結", "A", error=None)
        on_progress(2, 4, "B", "連載中", "B", error=None)
        return 4

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    assert int(app.progress["maximum"]) == 4
    assert int(app.progress["value"]) == 2


def test_progress_bar_resets_at_the_start_of_each_run(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.run", side_effect=lambda p, on_progress=None, skip_filled=True, cancel_event=None, adoption_trace_file=None: (
        on_progress(1, 1, "A", "完結", "A", error=None), 1
    )[1]):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()
    assert int(app.progress["value"]) == 1

    # 2回目の実行では、進捗が持ち越されずに0から始まる。
    with patch("comic_checker.gui.run", return_value=0):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()
    assert int(app.progress["value"]) == 0


# ------------------------------------------------------------------ 結果サマリ


def test_summary_counts_each_status(app):
    app.excel_path.set("/tmp/対象.xlsx")

    def fake_run(excel_path, on_progress=None, skip_filled=True, cancel_event=None, adoption_trace_file=None):
        on_progress(1, 5, "A", "完結", "A", error=None)
        on_progress(2, 5, "B", "連載中", "B", error=None)
        on_progress(3, 5, "C", "完結", "C", error=None)
        on_progress(4, 5, "D", "判定不能", "D", error=None)
        on_progress(5, 5, "E", "エラー", "", error=RuntimeError("boom"))
        return 5

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
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

    def fake_run(excel_path, on_progress=None, skip_filled=True, cancel_event=None, adoption_trace_file=None):
        on_progress(1, 2, "A", "ヒットなし", "", error=None)
        on_progress(2, 2, "B", "不明", "", error=None)
        return 2

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    assert "その他 2" in app.summary_text.get()


def test_summary_is_reset_between_runs(app):
    app.excel_path.set("/tmp/対象.xlsx")

    def fake_run(excel_path, on_progress=None, skip_filled=True, cancel_event=None, adoption_trace_file=None):
        on_progress(1, 1, "A", "完結", "A", error=None)
        return 1

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()
    assert "完結 1" in app.summary_text.get()

    with patch("comic_checker.gui.run", return_value=0):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()
    assert app.summary_text.get() == "—"


# ------------------------------------------------------------------ 状態表示


def test_status_shows_progress_while_running_and_completion_at_the_end(app):
    app.excel_path.set("/tmp/対象.xlsx")

    seen = []

    def fake_run(excel_path, on_progress=None, skip_filled=True, cancel_event=None, adoption_trace_file=None):
        on_progress(1, 2, "ONE PIECE", "連載中", "ONE PIECE", error=None)
        app.master.update()
        seen.append(app.status_text.get())
        on_progress(2, 2, "進撃の巨人", "完結", "進撃の巨人", error=None)
        return 2

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    assert seen == ["処理中… 1/2 件（ONE PIECE）"]
    assert app.status_text.get() == "完了しました（2件処理）"


def test_status_shows_failure_on_exception(app):
    app.excel_path.set("/tmp/対象.xlsx")

    with patch("comic_checker.gui.run", side_effect=ValueError("boom")):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
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


# ------------------------------------------- ドロップされたパスの解釈
# OSレベルのD&D操作はXvfb上で再現できないため、tkdndから渡ってくる
# event.data の解釈と、それを受けたハンドラの振る舞いだけを検証する。
# 実際のドラッグ＆ドロップ操作そのものは実機確認に委ねる（Issue #26）。


def test_parse_dropped_paths_handles_plain_path():
    assert _parse_dropped_paths("/home/u/a.xlsx") == ["/home/u/a.xlsx"]


def test_parse_dropped_paths_handles_braced_path_with_spaces():
    # 空白を含むパスは中括弧で囲まれて渡ってくる。単純なsplitでは壊れる。
    assert _parse_dropped_paths(r"{C:\My Files\蔵書 一覧.xlsx}") == [
        r"C:\My Files\蔵書 一覧.xlsx"
    ]


def test_parse_dropped_paths_handles_multiple_mixed_entries():
    data = r"{C:\My Files\a b.xlsx} D:\c.xlsx {E:\d e.txt}"
    assert _parse_dropped_paths(data) == [
        r"C:\My Files\a b.xlsx",
        r"D:\c.xlsx",
        r"E:\d e.txt",
    ]


def test_parse_dropped_paths_returns_empty_for_blank_input():
    assert _parse_dropped_paths("") == []
    assert _parse_dropped_paths(None) == []


def test_parse_dropped_paths_accepts_list_input():
    # tkdndの実装によってはPython側のリストで渡ることがある。
    assert _parse_dropped_paths(["/a.xlsx", "/b.xlsx"]) == ["/a.xlsx", "/b.xlsx"]


def test_handle_drop_selects_xlsx_file(app):
    accepted = app._handle_drop("/home/u/蔵書リスト.xlsx")
    app.master.update()

    assert accepted == "/home/u/蔵書リスト.xlsx"
    assert app.excel_path.get() == "/home/u/蔵書リスト.xlsx"
    assert app.file_label.get() == "蔵書リスト.xlsx"
    assert "ファイルを選択しました" in log_text(app)


def test_handle_drop_rejects_non_xlsx_and_keeps_selection_unchanged(app):
    app.excel_path.set("/home/u/元の.xlsx")

    accepted = app._handle_drop("/home/u/メモ.txt")
    app.master.update()

    assert accepted is None
    # 不正なファイルで既存の選択を壊さない。
    assert app.excel_path.get() == "/home/u/元の.xlsx"
    text = log_text(app)
    assert "Excelファイル" in text
    assert "メモ.txt" in text


def test_handle_drop_rejects_non_xlsx_without_selecting_anything(app):
    accepted = app._handle_drop("/home/u/メモ.txt")
    app.master.update()

    assert accepted is None
    # 何も選択していない状態が維持される。
    assert app.excel_path.get() == ""
    assert app.file_label.get() == "（未選択）"


def test_handle_drop_uses_first_file_when_multiple_are_dropped(app):
    accepted = app._handle_drop(r"{/home/u/一冊目.xlsx} {/home/u/二冊目.xlsx}")
    app.master.update()

    assert accepted == "/home/u/一冊目.xlsx"
    assert app.excel_path.get() == "/home/u/一冊目.xlsx"
    assert "最初の1件だけを使います" in log_text(app)


def test_handle_drop_logs_when_nothing_is_recognised(app):
    accepted = app._handle_drop("")
    app.master.update()

    assert accepted is None
    assert "認識できませんでした" in log_text(app)


def test_on_drop_never_raises_even_if_handling_fails(app):
    # tkdndのコールバック内で例外を投げるとTcl側にエラーが出るため、
    # 何があってもログに出して飲み込む仕様。
    class FakeEvent:
        data = "/home/u/a.xlsx"
        action = "copy"

    with patch.object(app, "_handle_drop", side_effect=RuntimeError("boom")):
        result = app._on_drop(FakeEvent())
    app.master.update()

    assert result == "copy"
    assert "ドロップの処理に失敗しました" in log_text(app)


def test_dnd_is_disabled_gracefully_when_tkinterdnd2_is_missing(app):
    # tkinterdnd2が入っていない環境でも、D&Dが無効になるだけで落ちない。
    with patch.dict("sys.modules", {"tkinterdnd2": None}):
        assert app._init_dnd() is False


# ------------------------------------------------------ 配色・アイコン


def test_summary_chips_are_colour_coded_per_status(app):
    app.excel_path.set("/tmp/対象.xlsx")

    def fake_run(excel_path, on_progress=None, skip_filled=True, cancel_event=None, adoption_trace_file=None):
        on_progress(1, 2, "A", "完結", "A", error=None)
        on_progress(2, 2, "B", "エラー", "", error=RuntimeError("boom"))
        return 2

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()

    from comic_checker.gui import STATUS_COLORS

    styles = {
        chip.cget("text"): str(chip.cget("style"))
        for chip in app._summary_chips
        if chip.cget("text") != "／"
    }
    assert "完結 1" in styles and "エラー 1" in styles
    # 完結とエラーは別々のスタイル＝別々の色が当たっている。
    assert styles["完結 1"] != styles["エラー 1"]

    style = ttk.Style(app.master)
    assert style.lookup(styles["エラー 1"], "foreground") == STATUS_COLORS["エラー"]
    assert style.lookup(styles["完結 1"], "foreground") == STATUS_COLORS["完結"]


def test_summary_chips_are_cleared_between_runs(app):
    app.excel_path.set("/tmp/対象.xlsx")

    def fake_run(excel_path, on_progress=None, skip_filled=True, cancel_event=None, adoption_trace_file=None):
        on_progress(1, 1, "A", "完結", "A", error=None)
        return 1

    with patch("comic_checker.gui.run", side_effect=fake_run):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()
    assert app._summary_chips

    with patch("comic_checker.gui.run", return_value=0):
        app._run_worker(excel_path="/tmp/対象.xlsx", cancel_event=None)
        app.master.update()
    assert app._summary_chips == []
    assert app.summary_text.get() == "—"


def test_section_titles_fall_back_to_plain_text_without_emoji_font(app):
    # 絵文字フォントが無い環境ではアイコンを付けない（豆腐□を並べない）。
    app._theme["emoji"] = False
    assert app._decorate("file", "対象ファイル") == "対象ファイル"

    app._theme["emoji"] = True
    assert app._decorate("file", "対象ファイル") == "📁 対象ファイル"
    # 未知のキーではアイコンを足さない（レイアウトが崩れない）。
    assert app._decorate("unknown", "その他") == "その他"


def test_run_button_falls_back_to_plain_style_without_accent_support():
    # アクセント配色を作れない環境では通常のttkボタンで組み立てる。
    root = tk.Tk()
    root.withdraw()
    try:
        with patch(
            "comic_checker.gui._apply_theme",
            return_value={"accent_button": False, "accent_progress": False, "emoji": False},
        ):
            widget = App(master=root)
        assert str(widget.run_button.cget("style")) in ("", "TButton")
    finally:
        root.destroy()
