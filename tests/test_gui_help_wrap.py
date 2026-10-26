"""ヘルプの文言の折り返し（禁則処理）のテスト。作品名はすべて架空。"""
import tkinter as tk

import pytest

from comic_checker.gui import HELP_CARDS, NO_LINE_END, NO_LINE_START, App, wrap_text

HELP_INDEX = 2


def measure(text):
    """1文字の幅を10とする。"""
    return len(text) * 10


def all_lines():
    return [line for _title, _icon, lines in HELP_CARDS for line in lines]


def test_constants_match_spec():
    assert NO_LINE_START == "、。，．・：；？！…ー」』）】〕〉》"
    assert NO_LINE_END == "「『（【〔〈《"


def test_fitting_text_is_returned_as_is():
    assert wrap_text("あいうえお", measure, 50) == "あいうえお"


def test_breaks_at_width():
    assert wrap_text("あいうえおかきくけこ", measure, 50) == "あいうえお\nかきくけこ"


def test_punctuation_and_closing_bracket_do_not_start_a_line():
    assert wrap_text("あいうえお。かきくけこ", measure, 50) == "あいうえ\nお。かきく\nけこ"
    assert wrap_text("あいうえお」かきくけこ", measure, 50) == "あいうえ\nお」かきく\nけこ"


def test_opening_bracket_does_not_end_a_line():
    assert wrap_text("あいうえ「おかきくけこ", measure, 50) == "あいうえ\n「おかきく\nけこ"


def test_alphanumeric_word_is_not_split():
    assert wrap_text("あいabc.d", measure, 50) == "あい\nabc.d"


def test_whitespace_goes_to_end_of_previous_line():
    assert wrap_text("あいうえお かきくけこ", measure, 50) == "あいうえお \nかきくけこ"


@pytest.mark.parametrize(
    "text",
    ["。。。。。。。。", "abcdefghijkl", "「「「「「「「「"],
)
def test_breaks_at_width_when_rules_cannot_be_kept(text):
    wrapped = wrap_text(text, measure, 50)
    assert wrapped == "\n".join([text[:5], text[5:10], text[10:]]).strip("\n")
    assert wrapped.replace("\n", "") == text


@pytest.mark.parametrize("width", [30, 50, 80, 120, 200, 331])
def test_all_help_sentences_keep_their_text(width):
    for line in all_lines():
        wrapped = wrap_text(line, measure, width)
        assert wrapped.replace("\n", "") == line
        for index, row in enumerate(wrapped.split("\n")):
            if index:
                assert row[0] not in NO_LINE_START
            assert row[-1] not in NO_LINE_END


@pytest.fixture
def app():
    root = tk.Tk()
    widget = App(master=root)
    widget.pack(fill="both", expand=True)
    root.update()
    yield widget
    widget._stop_elapsed()
    root.destroy()


def show_help(app):
    app.nav_items[HELP_INDEX].event_generate("<Button-1>")
    app.update()


def test_labels_at_minimum_size_follow_line_break_rules(app):
    app.winfo_toplevel().geometry("1049x688")
    show_help(app)
    app.update()
    expected = iter(all_lines())
    for _heading, labels in app.help_cards:
        for label in labels:
            text = str(label.cget("text"))
            assert text.replace("\n", "") == next(expected)
            for index, row in enumerate(text.split("\n")):
                if index:
                    assert row[0] not in NO_LINE_START
                assert row[-1] not in NO_LINE_END


def test_narrow_canvas_breaks_text_and_zeroes_wraplength(app):
    app.winfo_toplevel().geometry("1049x688")
    show_help(app)
    # 保留中の実際の Configure を先に処理しきる。合成イベントは同期で処理されるので、
    # 送った後は update を呼ばない（呼ぶと実際の幅で折り返し直される環境がある）。
    app.update()
    app.help_canvas.event_generate("<Configure>", width=300, height=400)
    labels = [label for _heading, labels in app.help_cards for label in labels]
    assert any("\n" in str(label.cget("text")) for label in labels)
    assert all(int(str(label.cget("wraplength"))) == 0 for label in labels)
