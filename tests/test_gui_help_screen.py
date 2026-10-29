"""GUI の「ヘルプ」「バージョン情報」「設定」の画面のテスト。作品名はすべて架空。"""
import tkinter as tk
from unittest.mock import patch

import pytest

from comic_checker import gui, version_string
from comic_checker.gui import App

HELP_INDEX = 2
URL = "https://github.com/giant-shrimp/comic_checker/blob/main/docs/user_guide.md"

EXPECTED_CARDS = [
    (
        "使い方",
        [
            "1. 「タイトル」列のある .xlsx を、「ファイルを選択…」ボタンかドラッグ＆ドロップで指定します。",
            "2. 「実行」を押します。対象の Excel は閉じておいてください。",
            "3. 終わると、結果は元の Excel に保存されています。",
            "・列名が「タイトル」でないときや、2枚目以降のシートを使うときは、「設定」の画面で変えられます。",
            "・「中断」を押すと、いま調べている行を終えたところで止まり、そこまでの結果は Excel に保存されます。",
        ],
    ),
    (
        "結果の見方",
        [
            "・完結／連載中：判定の結果です。",
            "・判定不能：記事はありましたが、完結か連載中かを確信できませんでした。手動で確認してください。",
            "・記事なし：日本語版 Wikipedia に記事がなく、BOOK☆WALKER でも判定できませんでした。多くは異常ではありません。",
            "・「判定方法」列が BOOK☆WALKER の行は、Wikipedia に記事が無かったため、BOOK☆WALKER の「完結」の札で判定しています。札が無ければ連載中としています。",
            "・エラー：その行の処理中に問題が起きました。次の行は続けて処理します。",
            "・「参照タイトル」列が入力したタイトルと違う行は、別の記事で判定しています。確認してください。",
        ],
    ),
    (
        "困ったときは",
        [
            "・すべて「エラー」になる：Excel を閉じているか、インターネットにつながっているかを確かめてください。",
            "・列が見つからないと出る：1行目の見出しが、「設定」の画面のタイトル列名と同じかを確かめてください。",
            "・「処理対象の行がありません」と出る：すべての行が判定済みです。確認画面で「すべて再判定する」を選ぶと調べ直せます。",
        ],
    ),
    (
        "次巻発売日の確認",
        [
            "・楽天ブックスのキーが必要です。「楽天APIキーの設定…」で設定してください。",
            "・結果は Excel の「次巻発売日」などの4つの列に書き込みます。実行するたびに上書きします。",
            "・次巻あり：発売前の次の巻が見つかりました。",
            "・未定：発売済みの巻はありましたが、次の巻の発売予定は見つかりませんでした。",
            "・要確認：候補を絞りきれませんでした。商品ページを見て確認してください。",
            "・ヒットなし：楽天ブックスでその作品の商品が見つかりませんでした。",
        ],
    ),
]


@pytest.fixture
def app():
    root = tk.Tk()
    widget = App(master=root)
    widget.pack(fill="both", expand=True)
    root.update()
    yield widget
    widget._stop_elapsed()
    root.destroy()


def show(app, index):
    app.nav_items[index].event_generate("<Button-1>")
    app.update()


def card_of(screen_children_owner, title_text):
    for outer in screen_children_owner.winfo_children():
        if not isinstance(outer, tk.Frame):
            continue
        inner = outer.winfo_children()[0]
        header, content = inner.winfo_children()
        titles = [str(w.cget("text")) for w in header.winfo_children() if "text" in w.keys()]
        if titles and titles[0] == title_text:
            return [str(w.cget("text")) for w in content.winfo_children()]
    raise AssertionError(title_text)


def test_help_cards_headings_and_lines_match_spec(app):
    actual = [
        (str(heading.cget("text")), [str(label.cget("text")) for label in labels])
        for heading, labels in app.help_cards
    ]
    assert actual == EXPECTED_CARDS


def test_help_cards_are_stacked_top_to_bottom(app):
    show(app, HELP_INDEX)
    tops = [labels[0].winfo_rooty() for _heading, labels in app.help_cards]
    assert tops == sorted(tops)


def test_guide_url_constant_matches_spec():
    assert gui.USER_GUIDE_URL == URL


def test_guide_button_opens_url_constant(app):
    with patch("comic_checker.gui.webbrowser.open", return_value=True) as opened:
        with patch("comic_checker.gui.messagebox.showwarning") as warned:
            app.help_guide_button.invoke()
    opened.assert_called_once_with(gui.USER_GUIDE_URL)
    warned.assert_not_called()


def test_guide_button_text(app):
    assert str(app.help_guide_button.cget("text")) == "利用ガイドを開く（ブラウザ）"


@pytest.mark.parametrize("failure", [{"return_value": False}, {"side_effect": OSError("x")}])
def test_guide_open_failure_warns_with_url(app, failure):
    with patch("comic_checker.gui.webbrowser.open", **failure):
        with patch("comic_checker.gui.messagebox.showwarning") as warned:
            app.help_guide_button.invoke()
    warned.assert_called_once()
    assert gui.USER_GUIDE_URL in " ".join(str(a) for a in warned.call_args.args)


def test_help_screen_scrolls_to_guide_button_in_small_window(app):
    root = app.winfo_toplevel()
    root.geometry("1100x560")
    show(app, HELP_INDEX)
    app.update()
    canvas = app.help_canvas
    region_height = canvas.bbox("all")[3]
    assert region_height > canvas.winfo_height()
    canvas.yview_moveto(1.0)
    app.update()
    button = app.help_guide_button
    bottom = button.winfo_rooty() + button.winfo_height()
    assert bottom <= canvas.winfo_rooty() + canvas.winfo_height()
    assert button.winfo_rooty() >= canvas.winfo_rooty()


def test_help_wheel_scrolls_only_help_screen(app):
    root = app.winfo_toplevel()
    root.geometry("1100x560")
    show(app, HELP_INDEX)
    app.update()
    event = tk.Event()
    event.delta = -120
    event.num = 0
    app._on_help_wheel(event)
    app.update()
    assert app.help_canvas.yview()[0] > 0


def test_help_has_no_horizontal_scroll(app):
    show(app, HELP_INDEX)
    assert app.help_body.winfo_width() == app.help_canvas.winfo_width()
    assert app.help_canvas.cget("xscrollcommand") == ""


def test_about_card_has_heading_name_version_and_copy(app):
    show(app, 3)
    screen = app._screens[3]
    assert card_of(screen, "バージョン情報") == ["コミックチェッカー", version_string(), "コピー"]
    assert str(app.about_version_label.cget("text")) == version_string()
    app.clipboard_clear()
    app.copy_version_button.invoke()
    assert app.clipboard_get() == version_string()


def test_settings_card_heading_is_rakuten_key(app):
    titles = [
        str(w.cget("text"))
        for outer in app.settings_body.winfo_children()
        if isinstance(outer, tk.Frame)
        for w in outer.winfo_children()[0].winfo_children()[0].winfo_children()
        if "text" in w.keys()
    ]
    assert titles == ["楽天APIキーの設定", "読み取る列とシート", "詳しいログ"]
