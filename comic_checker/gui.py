import datetime
import os
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, font as tkfont, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from openpyxl import load_workbook

from comic_checker import next_release, rakuten_books_client, user_config, version_string
from comic_checker.main import _default_adoption_trace_path, count_rows, run

# サマリに表示する判定結果。main.py の run() が on_progress へ渡す status 値のうち、
# 利用者が件数を知りたいものを並べている。ここに無い値（manba経路の「ヒットなし」
# 「不明」等）は「その他」にまとめる（0件のときは表示しない）。
SUMMARY_STATUSES = ("完結", "連載中", "判定不能", "記事なし", "エラー")
# 次巻発売日の確認で並べる集計（next_release.run() が on_progress へ渡す status 値）。
NEXT_SUMMARY_STATUSES = ("次巻あり", "未定", "要確認", "ヒットなし", "エラー")
LOG_WARNING_STATUSES = ("判定不能", "要確認")
OTHER_STATUS_LABEL = "その他"

# アクセントカラー。彩度を抑えた実用寄りの色にしてある（判定結果を読む画面なので、
# 色そのものより「どれがエラーか」がひと目で分かることを優先する）。
COLOR_ACCENT = "#0b6bcb"
COLOR_ACCENT_HOVER = "#1a7ae0"
COLOR_ACCENT_PRESSED = "#08508f"
COLOR_ACCENT_DISABLED = "#a8c3e0"
COLOR_SUCCESS = "#1f7a3d"
COLOR_ON_ACCENT = "#ffffff"
COLOR_WARNING = "#a2660a"
COLOR_ERROR = "#b3261e"

# ログの各行の形と色。印（レベル）は淡い背景に濃い文字。
LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_LEVELS = ("INFO", "SUCCESS", "WARNING", "ERROR")
LOG_DEFAULT_LEVEL = "INFO"
# 印の文字は最長のレベル名（SUCCESS・WARNING の7文字）に空白で合わせる。
LOG_LEVEL_WIDTH = max(len(level) for level in LOG_LEVELS)
LOG_FILTER_ALL = "すべて"
COLOR_LOG_INFO_BG = "#e3eefb"
COLOR_LOG_SUCCESS_BG = "#e1f1e6"
COLOR_LOG_WARNING_BG = "#f8eddb"
COLOR_LOG_ERROR_BG = "#f9e1df"
# レベル -> (印の背景, 印の文字)。log_area のタグはこの辞書から作る。
LOG_LEVEL_COLORS = {
    "INFO": (COLOR_LOG_INFO_BG, COLOR_ACCENT),
    "SUCCESS": (COLOR_LOG_SUCCESS_BG, COLOR_SUCCESS),
    "WARNING": (COLOR_LOG_WARNING_BG, COLOR_WARNING),
    "ERROR": (COLOR_LOG_ERROR_BG, COLOR_ERROR),
}

# 面の配色。画面の地は淡い灰色、各セクションは白いカードに細い枠線を付ける。
COLOR_BG = "#f1f3f6"
COLOR_CARD = "#ffffff"
COLOR_BORDER = "#d3d8e0"
COLOR_MUTED = "#5f6b7a"
COLOR_BUTTON_DISABLED_FG = "#9aa3af"
COLOR_NAV_BG = "#e8ebf0"
COLOR_ICON_MUTED = "#8a94a3"
COLOR_BUTTON_OUTLINE_ACTIVE = "#f3f5f8"

# 文字の大きさは見出し・本文・補助の3段にそろえる。
FONT_SIZE_HEADING = 11
FONT_SIZE_BODY = 10
FONT_SIZE_HINT = 9

# 余白は外側（セクション間・画面端）と内側（カードの中）の2種類にそろえる。
PAD_OUTER = 12
PAD_INNER = 12

COLOR_DROP_BORDER = "#a9b2bf"
DROP_AREA_HEIGHT = 80
DROP_AREA_MARGIN = 16
RUN_STATE_DOT_SIZE = 12
NAV_WIDTH = 180
# 設定の画面の「詳しいログ」カード（Issue #39 の採用経路のログ）。
ADOPTION_TRACE_LABEL = "採用経路のログを出力する"
ADOPTION_TRACE_HINT = "開発者向けです。オンにして「実行」すると、Excel と同じフォルダに採用経路のログを書き出します。"
ICON_SIZE = 20
# 窓の大きさ。初期値はこの大きさで、画面の作業領域（画面の大きさからタスクバーと
# タイトルバーの分を引いたもの）より大きければ収まるように縮める。
WINDOW_INITIAL_WIDTH = 1240
WINDOW_INITIAL_HEIGHT = 940
SCREEN_MARGIN_WIDTH = 20
SCREEN_MARGIN_HEIGHT = 80
# ログ欄が最小のときの行数。縦が足りないときに縮むのはログ欄だけにする。
LOG_MIN_LINES = 3
# 状態バーの左の表示。status_text（進捗の文言）とは別で、実行中かどうかだけを示す。
RUN_STATE_IDLE = "待機中"
RUN_STATE_RUNNING = "実行中"
# 経過時間の欄を更新する間隔（ミリ秒）。
ELAPSED_TICK_MS = 1000
# 左のメニューの項目（文言, アイコンの種類）。先頭が選択中の表示。
NAV_ITEMS = (
    ("メイン", "home"),
    ("設定", "gear"),
    ("ヘルプ", "help"),
    ("バージョン情報", "info"),
)

# 「ヘルプ」の画面のボタンで開く利用ガイドの URL。
USER_GUIDE_URL = "https://github.com/giant-shrimp/comic_checker/blob/main/docs/user_guide.md"
# 折り返しで行の頭に置かない文字と、行の末尾に置かない文字。
NO_LINE_START ="、。，．・：；？！…ー」』）】〕〉》"
NO_LINE_END = "「『（【〔〈《"


def _is_word_char(char):
    return (char.isascii() and char.isalnum()) or char in "._-"


def _breaks_rule(text, cut):
    """text を cut の位置で区切ると禁則に当たるか。"""
    before, after = text[cut - 1], text[cut]
    if after in NO_LINE_START or before in NO_LINE_END:
        return True
    return _is_word_char(before) and _is_word_char(after)


def wrap_text(text, measure, width):
    """text を幅 width（measure が返すピクセル）に収まるよう、改行（\\n）で区切る。

    Tk の wraplength は句読点や閉じかっこが行の頭に来ることを避けないので、
    区切る位置を自分で決める。改行を除くと元の text と同じになる。
    """
    lines = []
    rest = text
    while rest and measure(rest) > width:
        fit = 1
        while fit < len(rest) and measure(rest[: fit + 1]) <= width:
            fit += 1
        cut = fit
        if fit < len(rest):
            while cut > 1 and _breaks_rule(rest, cut):
                cut -= 1
            if cut <= 1 and _breaks_rule(rest, cut):
                cut = fit
        while cut < len(rest) and rest[cut].isspace():
            cut += 1
        lines.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        lines.append(rest)
    return "\n".join(lines)


# 「ヘルプ」の画面のカード（見出し, アイコンの種類, 中身の行）。上から順に置く。
HELP_CARDS = (
    (
        "使い方",
        "doc",
        (
            "1. 「タイトル」列のある .xlsx を、「ファイルを選択…」ボタンかドラッグ＆ドロップで指定します。",
            "2. 「実行」を押します。対象の Excel は閉じておいてください。",
            "3. 終わると、結果は元の Excel に保存されています。",
            "・列名が「タイトル」でないときや、2枚目以降のシートを使うときは、「設定」の画面で変えられます。",
            "・「中断」を押すと、いま調べている行を終えたところで止まり、そこまでの結果は Excel に保存されます。",
        ),
    ),
    (
        "結果の見方",
        "count",
        (
            "・完結／連載中：判定の結果です。",
            "・判定不能：記事はありましたが、完結か連載中かを確信できませんでした。手動で確認してください。",
            "・記事なし：日本語版 Wikipedia に記事がありませんでした。多くは異常ではありません。",
            "・エラー：その行の処理中に問題が起きました。次の行は続けて処理します。",
            "・「参照タイトル」列が入力したタイトルと違う行は、別の記事で判定しています。確認してください。",
        ),
    ),
    (
        "困ったときは",
        "help",
        (
            "・すべて「エラー」になる：Excel を閉じているか、インターネットにつながっているかを確かめてください。",
            "・列が見つからないと出る：1行目の見出しが、「設定」の画面のタイトル列名と同じかを確かめてください。",
            "・「処理対象の行がありません」と出る：すべての行が判定済みです。確認画面で「すべて再判定する」を選ぶと調べ直せます。",
        ),
    ),
    (
        "次巻発売日の確認",
        "calendar",
        (
            "・楽天ブックスのキーが必要です。「楽天APIキーの設定…」で設定してください。",
            "・結果は Excel の「次巻発売日」などの4つの列に書き込みます。実行するたびに上書きします。",
            "・次巻あり：発売前の次の巻が見つかりました。",
            "・未定：発売済みの巻はありましたが、次の巻の発売予定は見つかりませんでした。",
            "・要確認：候補を絞りきれませんでした。商品ページを見て確認してください。",
            "・ヒットなし：楽天ブックスでその作品の商品が見つかりませんでした。",
        ),
    ),
)
SETTINGS_SCREEN_INDEX = 1
HELP_SCREEN_INDEX = 2

# 「読み取る列とシート」の設定を config.json に保存するときの項目名（user_config.py は変えない）。
KEY_TITLE_COLUMN = "title_column"
KEY_SHEET = "sheet"
# タイトル列名の既定（未保存・空欄のとき）。CLI の --title-column の既定と同じ。
DEFAULT_TITLE_COLUMN = "タイトル"
MISSING_SHEET_MESSAGE = (
    "シート「{sheet}」が見つかりません。「設定」の画面のシート名を確かめてください。"
)
MISSING_TITLE_COLUMN_MESSAGE = (
    "列「{column}」が1行目に見つかりません。「設定」の画面のタイトル列名を確かめてください。"
)
MISSING_RAKUTEN_KEYS_MESSAGE = (
    "楽天APIキーが設定されていません。「設定」の画面でアプリIDとアクセスキーを保存してください。"
)

# カード用スタイルが作れない環境で使う、通常のスタイル名。
_PLAIN_STYLES = {
    "App.TFrame": "TFrame",
    "Card.TFrame": "TFrame",
    "Card.TLabel": "TLabel",
    "CardHeading.TLabel": "Heading.TLabel",
    "CardHint.TLabel": "Hint.TLabel",
    "CardStatus.TLabel": "Status.TLabel",
    "Card.TCheckbutton": "TCheckbutton",
    "Bar.TFrame": "TFrame",
    "Bar.TLabel": "TLabel",
    "BarHint.TLabel": "Hint.TLabel",
}

# 判定結果ごとの文字色。エラーは赤、完結は緑、連載中は青、判定不能は琥珀、
# 記事なし・その他は灰。背景色は付けず文字色だけにしている（背景を塗ると
# Windowsのネイティブテーマの地色とぶつかって浮くため）。
STATUS_COLORS = {
    "完結": "#1f7a3d",
    "連載中": "#0b6bcb",
    "判定不能": "#a2660a",
    "記事なし": "#5f6b7a",
    "エラー": "#b3261e",
    OTHER_STATUS_LABEL: "#5f6b7a",
    # 次巻発売日の確認用。_style_key は出現順の索引なので、既存の並びの後ろに足す。
    "次巻あり": "#1f7a3d",
    "未定": "#5f6b7a",
    "要確認": "#a2660a",
    "ヒットなし": "#5f6b7a",
}

# 各ブロックの見出しに添えるアイコン。絵文字グリフを持つフォントが
# 見つからない環境ではアイコン無しの見出しになる（_decorate() 参照）。
SECTION_ICONS = {
    "file": "📁",
    "run": "▶",
    "cancel": "■",
    "progress": "📊",
    "log": "📝",
}

# 絵文字を描けるフォント。1つでも入っていればアイコンを出す。
# Windows 10/11 には Segoe UI Emoji が標準で入っている。
EMOJI_FONT_FAMILIES = (
    "Segoe UI Emoji",
    "Apple Color Emoji",
    "Noto Color Emoji",
    "Noto Emoji",
    "Symbola",
)

# UIフォントの候補。左から順に探し、最初に見つかったものを使う。
# Yu Gothic UI / Meiryo UI はWindows、Noto/IPA/Takao系はLinux（WSLでの動作確認用）。
# すべて見つからない場合はtkinterの既定フォントのままにする。
UI_FONT_CANDIDATES = (
    "Yu Gothic UI",
    "Meiryo UI",
    "Meiryo",
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "IPAexGothic",
    "TakaoPGothic",
)
# ログ欄用の等幅フォント。日本語が混ざるため、CJK対応の等幅を優先する。
MONO_FONT_CANDIDATES = (
    "BIZ UDGothic",
    "MS Gothic",
    "Consolas",
    "Noto Sans Mono CJK JP",
    "DejaVu Sans Mono",
)

# 受け付けるExcelの拡張子。
EXCEL_SUFFIX = ".xlsx"

# Issue #32: 実行前確認ダイアログの選択結果。
CHOICE_SKIP = "skip"
CHOICE_REJUDGE = "rejudge"
CHOICE_CANCEL = "cancel"


def should_warn_about_filled_rows(counts):
    """実行前に「判定済みの行がある」警告を出すべきか（Issue #32）。

    判定済みが1行でもあれば警告する。全行スキップ（pending=0）のときだけに限らないのは、
    一部だけ埋まっている場合も「何件がスキップされるか」は利用者が知るべき情報のため。
    """
    return counts.filled > 0


def filled_rows_message(counts):
    """実行前確認ダイアログの本文を作る（Issue #32）。

    件数だけでなく「このまま実行すると何件処理されるか」を明示する。今回の失敗モードは
    「実行したのに何も起きなかったように見える」ことなので、処理対象が0件になることを
    押す前に読めるようにするのが肝心。
    """
    lines = [
        f"このファイルには {counts.total} 行中 {counts.filled} 行に判定結果が入っています。"
    ]
    if counts.pending:
        lines.append(f"このまま実行すると、未判定の {counts.pending} 行だけを処理します。")
    else:
        lines.append(
            "このまま実行すると、処理対象は 0 件になります"
            "（すべての行が判定済みのためスキップされます）。"
        )
    lines.append("判定結果を最新の内容に更新したい場合は、すべて再判定してください。")
    return "\n".join(lines)


def _format_elapsed(seconds):
    """経過秒数を「mm:ss」で返す。1時間以上は「h:mm:ss」。"""
    total = max(int(seconds), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _enable_dpi_awareness():
    """Windowsで高DPI対応を有効にする。Windows以外では何もしない。

    PyInstallerでEXE化した場合、DPI awarenessを設定しないとWindowsが
    ビットマップ拡大でごまかすため、文字がぼやける。Tk()を生成する前に
    呼ぶ必要がある。

    ctypes経由でWindows APIを叩くため、Windows以外（WSL/Linux）や、
    APIが無い古いWindowsでは例外になる。GUIが起動しない方が困るので、
    ここでの失敗はすべて握りつぶす（見た目が従来どおりになるだけ）。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            # Windows 8.1以降。1 = PROCESS_SYSTEM_DPI_AWARE
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            # Windows Vista〜8。shcore.dllが無い環境向けのフォールバック。
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _create_root():
    """ドラッグ＆ドロップ対応のルートウィンドウを作る。

    tkinterdnd2 が使えない場合（未インストール、tkdnd拡張の読み込み失敗など）は
    素の Tk() を返す。D&Dが効かなくなるだけで、ファイル選択ボタンからは
    従来どおり使える。EXEが起動しない方が困るので、ここでは落とさない。
    """
    try:
        from tkinterdnd2 import TkinterDnD

        return TkinterDnD.Tk()
    except Exception:
        return tk.Tk()


def _named_font(name, root):
    """名前付きフォントを取得する。root引数の有無はPythonバージョン差を吸収する。

    tkfont.nametofont() の root= キーワードは Python 3.10 で追加されたもの。
    3.8/3.9 では TypeError になるため、その場合は root 無しで取得する
    （このアプリはTk rootが1つなので既定rootと一致する）。root= を素通しで
    渡していた頃は、この TypeError が _apply_theme の except Exception まで
    伝播してテーマ設定が途中で中断していた（Issue: サマリの色が付かない）。
    """
    try:
        return tkfont.nametofont(name, root=root)
    except TypeError:
        return tkfont.nametofont(name)


def _pick_font(root, candidates):
    """candidatesのうち、この環境に実在する最初のフォント名を返す。無ければNone。"""
    try:
        available = {name.lower() for name in tkfont.families(root)}
    except Exception:
        return None
    for name in candidates:
        if name.lower() in available:
            return name
    return None


def _emoji_available(root):
    """絵文字グリフを持つフォントがこの環境にあるか。

    グリフの有無をTk側から確実に判定する手段が無いため、「絵文字フォントが
    入っているか」で代用する。入っていなければアイコンを出さない
    （豆腐□が並ぶより、アイコン無しの方がましなので）。
    """
    return _pick_font(root, EMOJI_FONT_FAMILIES) is not None


def _configure_accent_styles(style, ui_font):
    """アクセント色のボタン・進捗バーのスタイルを定義する。

    vista/winnative テーマのボタンや進捗バーはWindowsがネイティブ描画するため、
    background を configure しても無視される。そこで**そのスタイルだけ**
    レイアウトを差し替えてネイティブ要素を外し、色指定が効く汎用要素で
    描かせる。テーマ全体は差し替えないので、他のウィジェットはネイティブの
    ままになる。

    レイアウト差し替えが通らない環境では、例外を握って通常のボタン・
    進捗バーの見た目にフォールバックする（色は付かないが崩れはしない）。
    """
    accent_ok = False
    try:
        style.layout(
            "Accent.TButton",
            [
                (
                    "Button.padding",
                    {
                        "sticky": "nswe",
                        "children": [("Button.label", {"sticky": "nswe"})],
                    },
                )
            ],
        )
        style.configure(
            "Accent.TButton",
            background=COLOR_ACCENT,
            foreground=COLOR_ON_ACCENT,
            font=(ui_font or "TkDefaultFont", 10, "bold"),
            padding=(18, 7),
            borderwidth=0,
            focusthickness=0,
            relief="flat",
            anchor="center",
        )
        # ホバー（active）と押下（pressed）で色を変える。disabled中も
        # 「押せない」ことが色で分かるようにする。
        style.map(
            "Accent.TButton",
            background=[
                ("disabled", COLOR_ACCENT_DISABLED),
                ("pressed", COLOR_ACCENT_PRESSED),
                ("active", COLOR_ACCENT_HOVER),
            ],
            foreground=[("disabled", COLOR_ON_ACCENT)],
            relief=[("pressed", "flat"), ("active", "flat")],
        )
        accent_ok = True
    except tk.TclError:
        pass

    progress_ok = False
    try:
        style.layout(
            "Accent.Horizontal.TProgressbar",
            [
                (
                    "Horizontal.Progressbar.trough",
                    {
                        "sticky": "nswe",
                        "children": [
                            ("Horizontal.Progressbar.pbar", {"side": "left", "sticky": "ns"})
                        ],
                    },
                )
            ],
        )
        style.configure(
            "Accent.Horizontal.TProgressbar",
            background=COLOR_ACCENT,
            troughcolor="#e4e8ee",
            bordercolor="#cdd4de",
            lightcolor=COLOR_ACCENT,
            darkcolor=COLOR_ACCENT,
            thickness=16,
        )
        # 完了時はグリーンに切り替える（_set_progress_done() から使う）。
        style.configure(
            "Done.Horizontal.TProgressbar",
            background=COLOR_SUCCESS,
            troughcolor="#e4e8ee",
            bordercolor="#cdd4de",
            lightcolor=COLOR_SUCCESS,
            darkcolor=COLOR_SUCCESS,
            thickness=16,
        )
        style.layout(
            "Done.Horizontal.TProgressbar", style.layout("Accent.Horizontal.TProgressbar")
        )
        progress_ok = True
    except tk.TclError:
        pass

    return accent_ok, progress_ok


def _configure_card_styles(style, root, family):
    """画面の地（淡い灰）と、白いカード・状態バー用のスタイルを定義する。

    vista/winnative では Frame や Label の background 指定が効かないことがある。
    その場合も色が付かないだけで画面は崩れない。作れなかった環境では False を返し、
    呼び出し側（App._style）が通常のスタイルに落とす。
    """
    try:
        root.configure(background=COLOR_BG)
        style.configure("App.TFrame", background=COLOR_BG)
        style.configure("Card.TFrame", background=COLOR_CARD)
        style.configure("Card.TLabel", background=COLOR_CARD, font=(family, FONT_SIZE_BODY))
        style.configure(
            "CardHeading.TLabel",
            background=COLOR_CARD,
            font=(family, FONT_SIZE_HEADING, "bold"),
        )
        style.configure(
            "CardHint.TLabel",
            background=COLOR_CARD,
            foreground=COLOR_MUTED,
            font=(family, FONT_SIZE_HINT),
        )
        style.configure(
            "CardStatus.TLabel", background=COLOR_CARD, font=(family, FONT_SIZE_BODY)
        )
        style.configure("Card.TCheckbutton", background=COLOR_CARD)
        style.configure("Bar.TFrame", background=COLOR_BG)
        style.configure("Bar.TLabel", background=COLOR_BG, font=(family, FONT_SIZE_BODY))
        style.configure(
            "BarHint.TLabel",
            background=COLOR_BG,
            foreground=COLOR_MUTED,
            font=(family, FONT_SIZE_HINT),
        )
        return True
    except tk.TclError:
        return False


def _configure_secondary_button_style(style, family):
    """枠線の副ボタン（白地に青の文字と枠）と、無効時の灰色表示を定義する。

    副ボタンは TButton のレイアウトをそのまま使う（名前の接尾辞で継承される）。
    vista/winnative では色指定が効かず通常のボタンの見た目になるが、崩れはしない。
    """
    try:
        style.configure(
            "Secondary.TButton",
            background=COLOR_CARD,
            foreground=COLOR_ACCENT,
            bordercolor=COLOR_ACCENT,
            lightcolor=COLOR_CARD,
            darkcolor=COLOR_CARD,
            focuscolor=COLOR_CARD,
            font=(family, FONT_SIZE_BODY, "bold"),
            padding=(18, 7),
            anchor="center",
        )
        style.map(
            "Secondary.TButton",
            background=[("disabled", COLOR_CARD), ("pressed", "#dbe8f7"), ("active", "#eaf2fc")],
            foreground=[("disabled", COLOR_BUTTON_DISABLED_FG)],
            bordercolor=[("disabled", COLOR_BORDER)],
        )
        # 「中断」だけ、無効のときに灰色の文字にする（ダイアログのボタンには効かせない）。
        style.map("Cancel.TButton", foreground=[("disabled", COLOR_BUTTON_DISABLED_FG)])
        # 白地に細い枠線の副ボタン（「ファイルを選択…」など）。
        style.configure(
            "Outline.TButton",
            background=COLOR_CARD,
            bordercolor=COLOR_BORDER,
            lightcolor=COLOR_CARD,
            darkcolor=COLOR_CARD,
            focuscolor=COLOR_CARD,
            font=(family, FONT_SIZE_BODY),
            padding=(14, 6),
        )
        style.map(
            "Outline.TButton",
            background=[("pressed", "#e4e8ee"), ("active", COLOR_BUTTON_OUTLINE_ACTIVE)],
        )
        return True
    except tk.TclError:
        return False


def _apply_theme(root):
    """ttkテーマ・既定フォント・アクセント配色を設定する。

    設定できたものを dict で返す（呼び出し側がフォールバックの判断に使う）。
    失敗してもGUIは動くべきなので、例外は握りつぶす。
    """
    settings = {
        "accent_button": False,
        "accent_progress": False,
        "emoji": False,
        "card": False,
        "secondary_button": False,
    }
    try:
        style = ttk.Style(root)
        # vista/winnativeはWindowsのネイティブテーマ。無い環境（Linux）では
        # 素のdefaultより見られるclamにする。
        for theme in ("vista", "winnative", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break

        ui_font = _pick_font(root, UI_FONT_CANDIDATES)
        if ui_font:
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                try:
                    _named_font(name, root).configure(family=ui_font, size=10)
                except tk.TclError:
                    pass

        # 見出し・補助テキスト用のスタイル。
        family = ui_font or "TkDefaultFont"
        style.configure("Heading.TLabel", font=(family, FONT_SIZE_HEADING, "bold"))
        style.configure("Hint.TLabel", font=(family, FONT_SIZE_HINT))
        style.configure("Status.TLabel", font=(family, FONT_SIZE_BODY))
        style.configure(
            "SectionTitle.TLabelframe.Label", font=(family, FONT_SIZE_HEADING, "bold")
        )
        card_ok = _configure_card_styles(style, root, family)
        settings["card"] = card_ok
        # サマリの内訳（判定結果ごとの色分け）。カードの白い面に載せる。
        for name, color in STATUS_COLORS.items():
            options = {
                "foreground": color,
                "font": (family, FONT_SIZE_BODY, "bold"),
            }
            if card_ok:
                options["background"] = COLOR_CARD
            style.configure(f"Summary{_style_key(name)}.TLabel", **options)

        accent, progress = _configure_accent_styles(style, ui_font)
        settings["accent_button"] = accent
        settings["accent_progress"] = progress
        settings["secondary_button"] = _configure_secondary_button_style(style, family)
        settings["emoji"] = _emoji_available(root)
    except Exception:
        pass
    return settings


def _style_key(status):
    """判定結果名から、ttkスタイル名に使える識別子を作る。

    ttkのスタイル名に日本語を入れても動くが、名前の衝突と可読性を避けるため
    出現順の索引に置き換える。
    """
    names = list(STATUS_COLORS)
    try:
        return str(names.index(status))
    except ValueError:
        return "Other"


def _parse_dropped_paths(data):
    """<<Drop>> の event.data をファイルパスのリストに変換する。

    tkdndが渡してくるのはTclのリスト文字列で、空白を含むパスは中括弧で
    囲まれる（例: ``{C:\\My Files\\a.xlsx} D:\\b.xlsx``）。単純な split では
    空白入りのパスが壊れるため、中括弧を見ながら分解する。

    壊れた入力でも例外を投げず、取れたものだけを返す。
    """
    if not data:
        return []
    if isinstance(data, (list, tuple)):
        return [str(item) for item in data if str(item).strip()]

    text = str(data)
    paths = []
    buf = []
    depth = 0
    for ch in text:
        if ch == "{":
            if depth == 0 and not buf:
                depth += 1
                continue
            depth += 1
            buf.append(ch)
        elif ch == "}":
            if depth == 1:
                depth = 0
                paths.append("".join(buf))
                buf = []
                continue
            if depth > 1:
                depth -= 1
            buf.append(ch)
        elif ch.isspace() and depth == 0:
            if buf:
                paths.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        paths.append("".join(buf))
    return [p for p in (p.strip() for p in paths) if p]


def _center_window(window):
    """ウィンドウを画面中央に置く。取得に失敗したら何もしない。"""
    try:
        window.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        if width <= 1 or height <= 1:
            width = window.winfo_reqwidth()
            height = window.winfo_reqheight()
        x = max(0, (window.winfo_screenwidth() - width) // 2)
        y = max(0, (window.winfo_screenheight() - height) // 3)
        window.geometry(f"+{x}+{y}")
    except Exception:
        pass


def _compute_window_sizes(screen_width, screen_height, required_width, required_height):
    """窓の初期の大きさと最小の大きさを返す（それぞれ (幅, 高さ)）。

    初期値は WINDOW_INITIAL_WIDTH x WINDOW_INITIAL_HEIGHT。画面の作業領域
    （画面の大きさからタスクバーなどの余白を引いたもの）より大きければ縮める。
    最小の大きさは、ログ欄を最小の行数にしたときの部品の必要な大きさ
    （required_*）で、これも作業領域を超えないようにする。縦が足りないときに
    縮むのはログ欄だけ（他の部品は縦の伸び縮みの重みが無い）。
    """
    avail_width = max(screen_width - SCREEN_MARGIN_WIDTH, 1)
    avail_height = max(screen_height - SCREEN_MARGIN_HEIGHT, 1)
    min_size = (min(required_width, avail_width), min(required_height, avail_height))
    initial = (
        max(min(WINDOW_INITIAL_WIDTH, avail_width), min_size[0]),
        max(min(WINDOW_INITIAL_HEIGHT, avail_height), min_size[1]),
    )
    return initial, min_size


def _draw_icon(canvas, kind, colour, size=ICON_SIZE):
    """Canvas に簡単な図形でアイコンを描く（画像ファイルは使わない）。

    kind が未知なら何も描かない。フォントに依存する記号は最小限にしている。
    """
    s = size
    w = max(s // 10, 1)

    def p(v):
        return v * s / 20

    if kind == "folder":
        canvas.create_polygon(
            p(2), p(5), p(8), p(5), p(10), p(7), p(18), p(7), p(18), p(16), p(2), p(16),
            fill=colour, outline=colour,
        )
    elif kind == "excel":
        canvas.create_rectangle(p(1), p(1), p(19), p(19), fill=COLOR_SUCCESS, outline=COLOR_SUCCESS)
        # 白の格子（2列×3行の表）。線はすべて水平か垂直。40px で線幅2px。
        gw = max(w // 2, 2)
        canvas.create_rectangle(p(4), p(4), p(16), p(16), fill="", outline=COLOR_ON_ACCENT, width=gw)
        canvas.create_line(p(4), p(8), p(16), p(8), fill=COLOR_ON_ACCENT, width=gw)
        canvas.create_line(p(4), p(12), p(16), p(12), fill=COLOR_ON_ACCENT, width=gw)
        canvas.create_line(p(10), p(4), p(10), p(16), fill=COLOR_ON_ACCENT, width=gw)
    elif kind == "refresh":
        canvas.create_arc(
            p(3), p(3), p(17), p(17), start=60, extent=270, style="arc", outline=colour, width=w + 1
        )
        canvas.create_polygon(p(13), p(1), p(19), p(5), p(12), p(7), fill=colour, outline=colour)
    elif kind == "ring":
        canvas.create_oval(p(3), p(3), p(17), p(17), outline="#cdd4de", width=w + 2)
        canvas.create_arc(
            p(3), p(3), p(17), p(17), start=90, extent=-100, style="arc", outline=colour, width=w + 2
        )
    elif kind == "doc":
        canvas.create_rectangle(p(4), p(2), p(16), p(18), outline=colour, width=w)
        for y in (7, 10, 13):
            canvas.create_line(p(7), p(y), p(13), p(y), fill=colour, width=w)
    elif kind == "trash":
        canvas.create_line(p(3), p(5), p(17), p(5), fill=colour, width=w + 1)
        canvas.create_rectangle(p(8), p(2), p(12), p(5), outline=colour, width=w)
        canvas.create_polygon(
            p(5), p(7), p(15), p(7), p(14), p(18), p(6), p(18), outline=colour, fill="", width=w
        )
    elif kind == "calendar":
        canvas.create_rectangle(p(3), p(4), p(17), p(17), outline=colour, width=w)
        canvas.create_rectangle(p(3), p(4), p(17), p(8), fill=colour, outline=colour)
        for x in (7, 10, 13):
            canvas.create_rectangle(p(x), p(11), p(x + 1.5), p(13), fill=colour, outline=colour)
    elif kind == "home":
        canvas.create_polygon(p(2), p(10), p(10), p(3), p(18), p(10), fill=colour, outline=colour)
        canvas.create_rectangle(p(5), p(10), p(15), p(17), fill=colour, outline=colour)
    elif kind == "gear":
        canvas.create_oval(p(3), p(3), p(17), p(17), outline=colour, width=w + 2)
        canvas.create_oval(p(8), p(8), p(12), p(12), fill=colour, outline=colour)
    elif kind in ("help", "info"):
        canvas.create_oval(p(2), p(2), p(18), p(18), outline=colour, width=w)
        canvas.create_text(
            p(10), p(10), text="?" if kind == "help" else "i", fill=colour,
            font=("TkDefaultFont", max(int(p(9)), 6), "bold"),
        )
    elif kind == "count":
        canvas.create_text(
            p(10), p(10), text="#", fill=colour, font=("TkDefaultFont", max(int(p(14)), 6), "bold")
        )
    elif kind == "clock":
        canvas.create_oval(p(2), p(2), p(18), p(18), outline=colour, width=w)
        canvas.create_line(p(10), p(10), p(10), p(5), fill=colour, width=w)
        canvas.create_line(p(10), p(10), p(14), p(12), fill=colour, width=w)
    elif kind == "file":
        canvas.create_rectangle(p(4), p(2), p(16), p(18), outline=colour, width=w)
        canvas.create_line(p(11), p(2), p(16), p(7), fill=colour, width=w)


def _icon_canvas(parent, kind, colour, background, size=ICON_SIZE):
    """アイコンを描いた Canvas を作って返す。"""
    canvas = tk.Canvas(
        parent, width=size, height=size, highlightthickness=0, borderwidth=0, background=background
    )
    _draw_icon(canvas, kind, colour, size)
    return canvas


class FilledRowsDialog(tk.Toplevel):
    """判定済みの行があるときに実行前へ挟む3択ダイアログ（Issue #32）。

    tkinter.messagebox.askyesnocancel を使わずカスタムにしている理由: 3択のラベルが
    「はい/いいえ/キャンセル」固定では、どちらが再判定なのかが本文を読まないと分からず、
    意図しない全件再判定（＝Wikipediaへの再アクセスが件数分発生する）を招きやすい。
    ボタン自体に動作を書く。

    既定（Enter・初期フォーカス）は「スキップして実行」＝従来どおりの挙動にしてある。
    中断・再開の運用で毎回このダイアログを通ることになるため、Enter一回で
    今までと同じ結果になる並びが安全。Escapeはキャンセル。
    """

    def __init__(self, master, counts):
        super().__init__(master)
        self.counts = counts
        self.choice = CHOICE_CANCEL

        self.title("判定済みの行があります")
        self.resizable(False, False)
        self.transient(master)

        body = ttk.Frame(self, padding=(16, 14, 16, 12))
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="判定済みの行があります", style="Heading.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            body, text=filled_rows_message(counts), justify="left", anchor="w"
        ).pack(anchor="w", pady=(8, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(16, 0))

        skip_label = (
            "スキップして実行（処理対象 0 件）"
            if not counts.pending
            else f"判定済みをスキップして実行（{counts.pending}件）"
        )
        self.skip_button = ttk.Button(
            buttons, text=skip_label, command=lambda: self._choose(CHOICE_SKIP)
        )
        self.skip_button.pack(side="left")
        ttk.Button(
            buttons,
            text=f"すべて再判定する（{counts.total}件）",
            command=lambda: self._choose(CHOICE_REJUDGE),
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            buttons, text="キャンセル", command=lambda: self._choose(CHOICE_CANCEL)
        ).pack(side="left", padx=(8, 0))

        self.bind("<Return>", lambda _e: self._choose(CHOICE_SKIP))
        self.bind("<Escape>", lambda _e: self._choose(CHOICE_CANCEL))
        # ウィンドウの×で閉じられた場合もキャンセル扱いにする（choiceの初期値のまま）。
        self.protocol("WM_DELETE_WINDOW", lambda: self._choose(CHOICE_CANCEL))

        _center_window(self)
        self.skip_button.focus_set()

    def _choose(self, choice):
        self.choice = choice
        self.destroy()

    def show(self):
        """モーダルとして開き、閉じられるまで待ってから選択結果を返す。"""
        try:
            self.grab_set()
        except tk.TclError:
            # 他のウィンドウがグラブ中などで掴めないことがある。モーダルにならない
            # だけで選択自体はできるので、続行する。
            pass
        self.wait_window(self)
        return self.choice


class RakutenKeyForm(ttk.Frame):
    """楽天ブックス書籍検索APIのキー（アプリID・アクセスキー）を入力して保存する部品。

    「設定」の画面のカードに埋め込む。
    キーの値は画面にもログにも出さない。入力欄は伏せ字で、既存の値は入れない。
    表示するのは「設定済み／未設定」と、環境変数が優先される場合はその旨だけ。
    空欄のまま保存したキーは変更しない。保存時にAPIは呼ばない。
    """

    # (設定ファイルの項目名, 環境変数名, 表示名)
    FIELDS = (
        (user_config.KEY_RAKUTEN_APP_ID, rakuten_books_client.APP_ID_ENV, "アプリID"),
        (user_config.KEY_RAKUTEN_ACCESS_KEY, rakuten_books_client.ACCESS_KEY_ENV, "アクセスキー"),
    )

    def __init__(self, master, styles=None, button_style="TButton"):
        """styles は部品ごとのスタイル名（frame・label・hint）。無ければ通常のスタイル。"""
        styles = styles or {}
        frame_style = styles.get("frame", "TFrame")
        label_style = styles.get("label", "TLabel")
        hint_style = styles.get("hint", "Hint.TLabel")
        super().__init__(master, style=frame_style)
        self.columnconfigure(1, weight=1)

        ttk.Label(
            self,
            text=(
                "楽天ウェブサービスで取得したキーを入力してください。\n"
                "キーは平文で設定ファイルに保存されます。"
                "空欄のまま保存したキーは変更しません。"
            ),
            justify="left",
            style=label_style,
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        self.entries = {}
        self.status_vars = {}
        for i, (key, _env, label) in enumerate(self.FIELDS):
            row = 1 + i * 2
            ttk.Label(self, text=label, style=label_style).grid(
                row=row, column=0, sticky="w", pady=(10, 0)
            )
            entry = ttk.Entry(self, show="*", width=40)
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))
            self.entries[key] = entry
            var = tk.StringVar()
            self.status_vars[key] = var
            ttk.Label(self, textvariable=var, style=hint_style).grid(
                row=row + 1, column=1, sticky="w", padx=(8, 0)
            )

        self.message = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.message, style=label_style).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

        buttons = ttk.Frame(self, style=frame_style)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.save_button = ttk.Button(
            buttons, text="保存", command=self.save, style=button_style
        )
        self.save_button.pack(side="left")

        self.refresh_status()

    def refresh_status(self):
        """「設定済み／未設定」と、環境変数が優先される場合の注記を更新する。"""
        for key, env_name, _label in self.FIELDS:
            text = "設定済み" if user_config.is_set(key) else "未設定"
            if os.environ.get(env_name):
                text += f"（環境変数 {env_name} が設定されているため、環境変数の値が優先されます）"
            self.status_vars[key].set(text)

    def clear_entries(self):
        """保存していない入力を空にする。"""
        for entry in self.entries.values():
            entry.delete(0, "end")

    def save(self):
        values = {}
        for key, _env, _label in self.FIELDS:
            value = self.entries[key].get().strip()
            if value:
                values[key] = value
        if not values:
            self.message.set("入力がないため、何も変更しませんでした")
            return
        try:
            user_config.save_values(values)
        except OSError:
            # 例外の文面は出さない（値は含まないが、画面に出す必要もない）。
            self.message.set("保存できませんでした。保存先のフォルダの権限を確認してください")
        else:
            self.message.set("保存しました")
        finally:
            self.clear_entries()
            values.clear()
        self.refresh_status()


def load_read_target():
    """保存済みの (タイトル列名, シート名) を返す。

    未保存・空欄のときは、タイトル列名は既定の「タイトル」、シート名は None
    （Excel を開いたときに選ばれているシート）。
    """
    return (
        user_config.get_value(KEY_TITLE_COLUMN) or DEFAULT_TITLE_COLUMN,
        user_config.get_value(KEY_SHEET),
    )


def has_rakuten_keys():
    """楽天APIキーが読めれば True を返す（Issue #565）。

    環境変数 → 設定ファイルの順で読む今の決まりを、rakuten_books_client に任せる。
    """
    try:
        rakuten_books_client._load_keys()
    except RuntimeError:
        return False
    return True


def find_missing_sheet(excel_path, sheet):
    """保存したシート名が Excel に無ければ True を返す（Issue #551）。

    シート名が未指定ならブックを開かず False。開けなかったとき（ファイルが無い・
    壊れているなど）も False を返し、これまでどおりの処理に任せる。
    """
    if not sheet:
        return False
    try:
        wb = load_workbook(excel_path, read_only=True)
    except Exception:
        return False
    try:
        return sheet not in wb.sheetnames
    finally:
        wb.close()


def find_missing_title_column(excel_path, title_column, sheet):
    """タイトル列名が対象のシートの1行目に無ければ True を返す（Issue #553）。

    開けなかったとき・シート名が無いとき（それは find_missing_sheet に任せる）は
    False を返し、これまでどおりの処理に任せる。1行目が無い（空のシート）ときは True。
    """
    try:
        wb = load_workbook(excel_path, read_only=True)
    except Exception:
        return False
    try:
        if sheet and sheet not in wb.sheetnames:
            return False
        ws = wb[sheet] if sheet else wb.active
        for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
            return title_column not in row
        return True
    finally:
        wb.close()


class ReadTargetForm(ttk.Frame):
    """読み取るタイトル列名とシート名を入力して保存する部品。

    「設定」の画面のカードに埋め込む。秘密ではないので伏せ字にせず、
    画面を開いたときは保存済みの値を入力欄に入れる。
    空欄も空文字として保存する（列名は既定に戻り、シートはアクティブシートになる）。
    """

    def __init__(self, master, styles=None, button_style="TButton"):
        styles = styles or {}
        frame_style = styles.get("frame", "TFrame")
        label_style = styles.get("label", "TLabel")
        super().__init__(master, style=frame_style)
        self.columnconfigure(1, weight=1)

        ttk.Label(
            self,
            text=(
                "タイトル列名は1行目の見出しの名前です。"
                "シート名を空欄にすると、Excel を開いたときに選ばれているシートを使います。"
            ),
            justify="left",
            style=label_style,
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        self.entries = {}
        for i, (key, label) in enumerate(
            ((KEY_TITLE_COLUMN, "タイトル列名"), (KEY_SHEET, "シート名"))
        ):
            row = 1 + i
            ttk.Label(self, text=label, style=label_style).grid(
                row=row, column=0, sticky="w", pady=(10, 0)
            )
            entry = ttk.Entry(self, width=40)
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))
            self.entries[key] = entry

        self.message = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.message, style=label_style).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

        buttons = ttk.Frame(self, style=frame_style)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.save_button = ttk.Button(
            buttons, text="保存", command=self.save, style=button_style
        )
        self.save_button.pack(side="left")

        self.reset_entries()

    def reset_entries(self):
        """入力欄を保存済みの値に戻す（未保存なら「タイトル」と空欄）。"""
        title_column, sheet = load_read_target()
        for key, value in (
            (KEY_TITLE_COLUMN, title_column),
            (KEY_SHEET, sheet or ""),
        ):
            entry = self.entries[key]
            entry.delete(0, "end")
            entry.insert(0, value)

    def save(self):
        values = {key: entry.get().strip() for key, entry in self.entries.items()}
        try:
            user_config.save_values(values)
        except OSError:
            self.message.set("保存できませんでした。保存先のフォルダの権限を確認してください")
        else:
            self.message.set("保存しました")
            # 空欄で保存した列名は既定に戻るので、入力欄にもそれを見せる。
            self.reset_entries()


class App(ttk.Frame):
    """Excelファイルを選択して読み込みを実行するGUI画面。"""

    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.excel_path = tk.StringVar()
        self.file_label = tk.StringVar(value="（未選択）")
        self.file_hint = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="待機中")
        self.summary_text = tk.StringVar(value="—")
        # Issue #39: 採用経路トレース。既定オフ。ExcelファイルとはWikipedia記事の
        # 採用経路をデバッグ用ログへ書き出すかどうかだけを切り替え、Excel出力列は
        # 増やさない。
        self.adoption_trace = tk.BooleanVar(value=False)
        self._counts = {}
        self._summary_statuses = SUMMARY_STATUSES
        self._summary_chips = []
        # 実行中の中断要求（Issue #61）。実行していない間は None。生成も差し替えも
        # メインスレッド（_on_run）だけで行い、ワーカーへは引数で渡す。
        self._cancel_event = None
        # 経過時間。時計は1か所から取り、テストで差し替えられるようにする。
        self._clock = time.monotonic
        # ログの行頭の時刻の取り出し口。テストで固定の時刻に差し替える。
        self._now = datetime.datetime.now
        # 書いた行（時刻の文字列, レベル, 本文）。絞り込みで書き直すために全部持つ。
        self._log_entries = []
        self._elapsed_start = 0.0
        self._elapsed_after_id = None
        self._theme = _apply_theme(master)
        self._build_widgets()
        self.excel_path.trace_add("write", self._on_path_changed)
        self.dnd_enabled = self._init_dnd()

    # ------------------------------------------------------------------ 画面構築

    def _decorate(self, key, text):
        """見出しにアイコンを添える。絵文字が使えない環境ではテキストのみ。"""
        if not self._theme.get("emoji"):
            return text
        icon = SECTION_ICONS.get(key)
        return f"{icon} {text}" if icon else text

    def _style(self, name):
        """カード用のスタイル名を返す。作れなかった環境では通常のスタイル名に落とす。

        `_apply_theme()` の戻り値には新しい項目が無いこともある（テストが3項目だけの
        dict に差し替える）ので、`get()` で読む。
        """
        return name if self._theme.get("card") else _PLAIN_STYLES[name]

    def _help_font(self):
        """ヘルプのカードの文言の幅を測るフォント。最初に要ったときに1つ作り、使い回す。"""
        if self._help_measure_font is None:
            spec = ttk.Style(self).lookup(self._style("Card.TLabel"), "font") or "TkDefaultFont"
            try:
                self._help_measure_font = tkfont.Font(root=self, font=spec)
            except tk.TclError:
                self._help_measure_font = tkfont.Font(root=self, font="TkDefaultFont")
        return self._help_measure_font

    def _surface_colour(self, card_colour):
        """tk（ttkでない）部品の背景色。カードの配色が無い環境では既定の地色にする。"""
        if self._theme.get("card"):
            return card_colour
        try:
            return ttk.Style(self).lookup("TFrame", "background") or card_colour
        except tk.TclError:
            return card_colour

    def _build_widgets(self):
        # 左にメニュー（NAV_WIDTH 固定）、右にカード。状態バーは下の端に横いっぱい。
        self.columnconfigure(0, minsize=NAV_WIDTH)
        self.columnconfigure(1, weight=1)
        # 縦に伸び縮みするのはカード側の行だけ（さらにその中ではログ欄だけ）。
        self.rowconfigure(0, weight=1)
        try:
            self.configure(style=self._style("App.TFrame"))
        except tk.TclError:
            pass

        self._build_nav()
        # 右側の画面は同じマスに重ねて置き、選択した1つだけを表示する。
        # 「メイン」の画面（対象ファイル・操作・進捗・ログ）が self._content。
        self._screen_host = ttk.Frame(self, style=self._style("App.TFrame"))
        self._screen_host.grid(row=0, column=1, sticky="nsew")
        self._screen_host.columnconfigure(0, weight=1)
        self._screen_host.rowconfigure(0, weight=1)
        self._content = self._new_screen()
        self._content.columnconfigure(0, weight=1)
        # ログ欄（row=3）だけが縦に伸びる。
        self._content.rowconfigure(3, weight=1)
        self._screens = [self._content]
        self._build_settings_screen()
        self._build_help_screen()
        self._build_about_screen()

        self._build_file_section()
        self._build_run_section()
        self._build_progress_section()
        self._build_log_section()
        self._build_status_bar()
        self._select_screen(0)

    def _new_screen(self):
        screen = ttk.Frame(self._screen_host, style=self._style("App.TFrame"))
        screen.grid(row=0, column=0, sticky="nsew")
        return screen

    def required_size(self):
        """窓に必要な大きさ (幅, 高さ)。表示していない画面も数える。

        Canvas の中身は Tk の必要な大きさに数えられないので、各画面の必要な幅
        （左のメニューの幅を足したもの）の最大を幅とする。
        """
        self.update_idletasks()
        width = max(
            [self.winfo_reqwidth()]
            + [NAV_WIDTH + screen.winfo_reqwidth() for screen in self._screens]
        )
        return width, self.winfo_reqheight()

    def _outline_style(self):
        """メインの「ファイルを選択…」と同じ枠線のボタンのスタイル名。作れない環境では TButton。"""
        return "Outline.TButton" if self._theme.get("secondary_button") else "TButton"

    def _build_settings_screen(self):
        """設定の画面。楽天APIキーの設定と、読み取る列とシートのカード2枚。

        縦に収まらないときはこの画面だけをスクロールする。横にはスクロールしない。
        """
        screen = self._new_screen()
        screen.columnconfigure(0, weight=1)
        screen.rowconfigure(0, weight=1)
        canvas = tk.Canvas(
            screen,
            highlightthickness=0,
            borderwidth=0,
            background=self._surface_colour(COLOR_BG),
        )
        scrollbar = ttk.Scrollbar(screen, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        body = ttk.Frame(canvas, style=self._style("App.TFrame"))
        body.columnconfigure(0, weight=1)
        window = canvas.create_window(0, 0, window=body, anchor="nw")
        self.settings_canvas = canvas
        self.settings_scrollbar = scrollbar
        self.settings_body = body

        def update_scrollbar():
            # 中身が窓に収まっているときはスクロールバーを隠す。
            if body.winfo_reqheight() <= canvas.winfo_height():
                scrollbar.grid_remove()
            else:
                scrollbar.grid()

        def on_canvas_configure(event):
            canvas.itemconfigure(window, width=event.width)
            update_scrollbar()

        def on_body_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            update_scrollbar()

        canvas.bind("<Configure>", on_canvas_configure)
        body.bind("<Configure>", on_body_configure)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(sequence, self._on_settings_wheel, add="+")
        frame = self._make_card(0, "楽天APIキーの設定", icon="calendar", parent=body)
        self.key_form = RakutenKeyForm(
            frame,
            styles={
                "frame": self._style("Card.TFrame"),
                "label": self._style("Card.TLabel"),
                "hint": self._style("CardHint.TLabel"),
            },
            button_style=self._outline_style(),
        )
        self.key_form.pack(fill="x", anchor="w")
        frame = self._make_card(1, "読み取る列とシート", icon="excel", parent=body)
        self.target_form = ReadTargetForm(
            frame,
            styles={
                "frame": self._style("Card.TFrame"),
                "label": self._style("Card.TLabel"),
            },
            button_style=self._outline_style(),
        )
        self.target_form.pack(fill="x", anchor="w")
        frame = self._make_card(2, "詳しいログ", icon="doc", parent=body)
        # Issue #39: 採用経路のログ（開発者向け、既定オフ、値は保存しない）。
        self.adoption_trace_check = ttk.Checkbutton(
            frame,
            text=ADOPTION_TRACE_LABEL,
            variable=self.adoption_trace,
            style=self._style("Card.TCheckbutton"),
        )
        self.adoption_trace_check.pack(anchor="w")
        ttk.Label(
            frame,
            text=ADOPTION_TRACE_HINT,
            style=self._style("CardHint.TLabel"),
        ).pack(anchor="w", pady=(2, 0))
        # Canvas の中身は Tk の必要な大きさに数えられないので、必要な幅を設定しておく。
        try:
            body.update_idletasks()
            canvas.configure(width=body.winfo_reqwidth())
        except tk.TclError:
            pass
        self._screens.append(screen)
        return screen

    def _on_settings_wheel(self, event):
        """設定の画面を表示している間だけ、マウスホイールでその画面をスクロールする。"""
        if self.selected_screen != SETTINGS_SCREEN_INDEX:
            return
        if getattr(event, "num", None) == 4:
            units = -1
        elif getattr(event, "num", None) == 5:
            units = 1
        else:
            delta = getattr(event, "delta", 0)
            units = -1 if delta > 0 else 1 if delta < 0 else 0
        if units:
            self.settings_canvas.yview_scroll(units * 3, "units")

    def _build_help_screen(self):
        """ヘルプの画面。要点のカード4枚と、利用ガイドをブラウザで開くボタン。

        縦に収まらないときはこの画面だけをスクロールする。横には広げず、文言を折り返す。
        """
        screen = self._new_screen()
        screen.columnconfigure(0, weight=1)
        screen.rowconfigure(0, weight=1)
        canvas = tk.Canvas(
            screen,
            highlightthickness=0,
            borderwidth=0,
            background=self._surface_colour(COLOR_BG),
        )
        scrollbar = ttk.Scrollbar(screen, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        body = ttk.Frame(canvas, style=self._style("App.TFrame"))
        body.columnconfigure(0, weight=1)
        window = canvas.create_window(0, 0, window=body, anchor="nw")
        self.help_canvas = canvas
        self.help_scrollbar = scrollbar
        self.help_body = body
        self._help_wrapped_labels = []
        self._help_label_texts = {}
        self._help_measure_font = None
        self.help_cards = []
        for row, (title, icon, lines) in enumerate(HELP_CARDS):
            frame = self._make_card(row, title, icon=icon, parent=body)
            heading = self._card_header.winfo_children()[-1]
            labels = []
            for line in lines:
                label = ttk.Label(frame, text=line, style=self._style("Card.TLabel"))
                label.pack(anchor="w", fill="x", pady=(0, 2))
                labels.append(label)
                self._help_label_texts[label] = line
            self._help_wrapped_labels.extend(labels)
            self.help_cards.append((heading, labels))
        self.help_guide_button = ttk.Button(
            body,
            text="利用ガイドを開く（ブラウザ）",
            command=self._open_user_guide,
            style=self._outline_style(),
        )
        self.help_guide_button.grid(
            row=len(HELP_CARDS), column=0, sticky="w", padx=PAD_OUTER, pady=PAD_OUTER
        )

        def on_canvas_configure(event):
            canvas.itemconfigure(window, width=event.width)
            # カードの左右の余白・枠線・内側の余白を引いた幅で折り返す。
            wrap = max(event.width - 2 * PAD_OUTER - 2 * PAD_INNER - 4, 100)
            measure = self._help_font().measure
            for label in self._help_wrapped_labels:
                label.configure(
                    text=wrap_text(self._help_label_texts[label], measure, wrap), wraplength=0
                )

        def update_scrollbar():
            # 中身が窓に収まっているときはスクロールバーを隠す。
            if body.winfo_reqheight() <= canvas.winfo_height():
                scrollbar.grid_remove()
            else:
                scrollbar.grid()

        self._update_help_scrollbar = update_scrollbar

        def on_body_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            update_scrollbar()

        def on_canvas_configure_all(event):
            on_canvas_configure(event)
            update_scrollbar()

        canvas.bind("<Configure>", on_canvas_configure_all)
        body.bind("<Configure>", on_body_configure)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(sequence, self._on_help_wheel, add="+")
        self._screens.append(screen)
        return screen

    def _on_help_wheel(self, event):
        """ヘルプの画面を表示している間だけ、マウスホイールでその画面をスクロールする。"""
        if self.selected_screen != HELP_SCREEN_INDEX:
            return
        if getattr(event, "num", None) == 4:
            units = -1
        elif getattr(event, "num", None) == 5:
            units = 1
        else:
            delta = getattr(event, "delta", 0)
            units = -1 if delta > 0 else 1 if delta < 0 else 0
        if units:
            self.help_canvas.yview_scroll(units * 3, "units")

    def _open_user_guide(self):
        """利用ガイドを既定のブラウザで開く。開けなければ警告のダイアログで知らせる。"""
        try:
            opened = webbrowser.open(USER_GUIDE_URL)
        except Exception:
            opened = False
        if not opened:
            messagebox.showwarning(
                "利用ガイドを開けません",
                "ブラウザを開けませんでした。次の URL をブラウザに貼り付けて開いてください。\n"
                + USER_GUIDE_URL,
            )

    def _build_about_screen(self):
        """バージョン情報の画面。アプリ名・version_string() の値と、それをコピーするボタン。"""
        screen = self._new_screen()
        screen.columnconfigure(0, weight=1)
        frame = self._make_card(0, "バージョン情報", icon="info", parent=screen)
        ttk.Label(frame, text="コミックチェッカー", style=self._style("Card.TLabel")).pack(anchor="w")
        self.about_version_label = ttk.Label(
            frame, text=version_string(), style=self._style("Card.TLabel")
        )
        self.about_version_label.pack(anchor="w", pady=(4, 8))
        self.copy_version_button = ttk.Button(
            frame, text="コピー", command=self._copy_version, style=self._outline_style()
        )
        self.copy_version_button.pack(anchor="w")
        self._screens.append(screen)

    def _copy_version(self):
        """version_string() の値そのものをクリップボードへ入れる。"""
        self.clipboard_clear()
        self.clipboard_append(version_string())
        self.update_idletasks()

    def _select_screen(self, index):
        """index の画面だけを表示し、メニューの選択表示を合わせる。

        設定の画面から離れるときは保存していない入力を空にし、表示するときは
        「設定済み／未設定」を読み直す。
        """
        previous = getattr(self, "selected_screen", None)
        if previous == SETTINGS_SCREEN_INDEX and index != SETTINGS_SCREEN_INDEX:
            self.key_form.clear_entries()
            self.key_form.message.set("")
            self.target_form.reset_entries()
            self.target_form.message.set("")
        for number, screen in enumerate(self._screens):
            if number == index:
                screen.grid()
            else:
                screen.grid_remove()
        self.selected_screen = index
        if index == SETTINGS_SCREEN_INDEX:
            self.key_form.refresh_status()
        for number, item in enumerate(self.nav_items):
            selected = number == index
            background = COLOR_ACCENT if selected else COLOR_NAV_BG
            foreground = COLOR_ON_ACCENT if selected else "#2b3340"
            item.configure(background=background, foreground=foreground)
            icon = self._nav_icons[number]
            icon.configure(background=background)
            icon.delete("all")
            _draw_icon(icon, NAV_ITEMS[number][1], foreground, 18)

    def _build_nav(self):
        """窓の左の縦のメニュー。項目を押すと、右側の画面がその項目の画面に切り替わる。"""
        nav = tk.Frame(self, width=NAV_WIDTH, background=COLOR_NAV_BG)
        nav.grid(row=0, column=0, sticky="nsew")
        nav.pack_propagate(False)
        self.nav_frame = nav
        self.nav_items = []
        self._nav_icons = []
        for index, (label, icon) in enumerate(NAV_ITEMS):
            selected = index == 0
            background = COLOR_ACCENT if selected else COLOR_NAV_BG
            foreground = COLOR_ON_ACCENT if selected else "#2b3340"
            item = tk.Label(
                nav,
                text=label,
                anchor="w",
                background=background,
                foreground=foreground,
                font="TkDefaultFont",
                padx=44,
                pady=10,
            )
            item.pack(fill="x", padx=8, pady=(16 if index == 0 else 2, 0))
            icon_canvas = _icon_canvas(item, icon, foreground, background, size=18)
            icon_canvas.place(x=14, rely=0.5, anchor="w")
            for widget in (item, icon_canvas):
                widget.bind("<Button-1>", lambda _event, number=index: self._select_screen(number))
            self.nav_items.append(item)
            self._nav_icons.append(icon_canvas)

    def _add_button_icon(self, button, kind, colour):
        """ボタンの左の余白にアイコンを重ねる。アイコンを押してもボタンが押される。"""
        icon = _icon_canvas(button, kind, colour, self._surface_colour(COLOR_CARD), size=16)
        icon.place(x=12, rely=0.5, anchor="w")

        def press(_event):
            if str(button.cget("state")) != "disabled":
                button.invoke()

        icon.bind("<Button-1>", press)
        return icon

    def _make_card(self, row, title, icon=None, sticky="ew", pady=(PAD_OUTER, 0), parent=None):
        """白い面と細い枠線のカードを置き、中身を入れるフレームを返す。

        titleがNoneなら見出しは付けない。見出しの行は self._card_header に残す
        （右側に部品を足せるように。見出しが無いときは None）。vista/winnative で
        背景色が効かない場合は、色が付かないだけで配置は変わらない。
        """
        options = {"highlightthickness": 1}
        if self._theme.get("card"):
            options.update(
                background=COLOR_CARD,
                highlightbackground=COLOR_BORDER,
                highlightcolor=COLOR_BORDER,
            )
        outer = tk.Frame(self._content if parent is None else parent, **options)
        outer.grid(row=row, column=0, sticky=sticky, padx=PAD_OUTER, pady=pady)
        inner = ttk.Frame(outer, style=self._style("Card.TFrame"), padding=PAD_INNER)
        inner.pack(fill="both", expand=True)
        self._card_header = None
        if title is not None:
            header = ttk.Frame(inner, style=self._style("Card.TFrame"))
            header.pack(fill="x", pady=(0, 8))
            if icon:
                _icon_canvas(
                    header, icon, COLOR_ACCENT, self._surface_colour(COLOR_CARD)
                ).pack(side="left", padx=(0, 6))
            ttk.Label(header, text=title, style=self._style("CardHeading.TLabel")).pack(
                side="left"
            )
            self._card_header = header
        content = ttk.Frame(inner, style=self._style("Card.TFrame"))
        content.pack(fill="both", expand=True)
        return content

    def _build_file_section(self):
        frame = self._make_card(0, "対象ファイル", icon="folder")
        frame.columnconfigure(0, weight=1)
        card_colour = self._surface_colour(COLOR_CARD)

        # ドロップ欄。破線の枠をCanvasに描き、中にアイコン・案内・ファイル名・
        # 「ファイルを選択…」ボタンを置く。
        canvas_options = {"height": DROP_AREA_HEIGHT, "highlightthickness": 0}
        canvas_options["background"] = card_colour
        self._drop_canvas = tk.Canvas(frame, **canvas_options)
        self._drop_canvas.grid(row=0, column=0, sticky="ew")
        drop_inner = ttk.Frame(self._drop_canvas, style=self._style("Card.TFrame"))
        drop_inner.columnconfigure(1, weight=1)
        self._drop_window = self._drop_canvas.create_window(0, 0, window=drop_inner)
        self._drop_canvas.bind("<Configure>", self._redraw_drop_area)

        excel_icon = _icon_canvas(drop_inner, "excel", COLOR_SUCCESS, card_colour, size=40)
        excel_icon.grid(row=0, column=0, rowspan=4, sticky="w", padx=(4, 14))

        guide1 = ttk.Label(
            drop_inner,
            text="ここに .xlsx ファイルをドラッグ＆ドロップするか、",
            style=self._style("Card.TLabel"),
            anchor="w",
        )
        guide1.grid(row=0, column=1, sticky="ew")
        guide2 = ttk.Label(
            drop_inner,
            text="「ファイルを選択」ボタンから選んでください。",
            style=self._style("Card.TLabel"),
            anchor="w",
        )
        guide2.grid(row=1, column=1, sticky="ew")
        title_hint = ttk.Label(
            drop_inner,
            text="「タイトル」列のある .xlsx を選んでください（列名は「設定」で変更可）。",
            style=self._style("CardHint.TLabel"),
            anchor="w",
        )
        title_hint.grid(row=2, column=1, sticky="ew", pady=(2, 0))

        # フルパスではなくファイル名を主に見せる（長いパスで欄が埋まらないように）。
        file_row = ttk.Frame(drop_inner, style=self._style("Card.TFrame"))
        file_row.grid(row=3, column=1, sticky="ew", pady=(6, 0))
        file_row.columnconfigure(1, weight=1)
        self.file_entry = ttk.Entry(
            file_row, textvariable=self.file_label, state="readonly", width=28
        )
        self.file_entry.grid(row=0, column=0, sticky="w")
        # フルパスは補助情報として小さく添える。未選択のときは空（案内は上の2行が担う）。
        hint_label = ttk.Label(
            file_row,
            textvariable=self.file_hint,
            style=self._style("CardHint.TLabel"),
            anchor="w",
        )
        hint_label.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        outline = "Outline.TButton" if self._theme.get("secondary_button") else "TButton"
        choose = ttk.Button(
            drop_inner,
            text="ファイルを選択…",
            command=self._choose_file,
            style=outline,
            padding=(34, 6, 14, 6),
        )
        choose.grid(row=0, column=2, rowspan=4, sticky="e", padx=(PAD_INNER, 4))
        self._add_button_icon(choose, "folder", COLOR_ACCENT)

        # 破線の枠の高さは中身の高さに余白を足したものにする（無駄に高くしない）。
        try:
            drop_inner.update_idletasks()
            self._drop_canvas.configure(
                height=max(drop_inner.winfo_reqheight() + DROP_AREA_MARGIN, DROP_AREA_HEIGHT),
                width=drop_inner.winfo_reqwidth() + 2 * PAD_INNER + 8,
            )
        except tk.TclError:
            pass

        # ドロップは広げた欄の全体で受け付ける。file_entry も受け口のまま残す。
        self._drop_targets = [
            self._drop_canvas,
            drop_inner,
            excel_icon,
            guide1,
            guide2,
            title_hint,
            file_row,
            self.file_entry,
            hint_label,
        ]

    def _redraw_drop_area(self, event):
        """ドロップ欄の大きさが変わったら、破線の枠と中身の位置・幅を合わせ直す。"""
        canvas = self._drop_canvas
        canvas.delete("drop_border")
        width, height = event.width, event.height
        canvas.create_rectangle(
            2,
            2,
            max(width - 3, 3),
            max(height - 3, 3),
            outline=COLOR_DROP_BORDER,
            dash=(5, 4),
            tags="drop_border",
        )
        canvas.tag_lower("drop_border")
        canvas.coords(self._drop_window, width // 2, height // 2)
        canvas.itemconfigure(self._drop_window, width=max(width - 2 * PAD_INNER - 8, 1))

    def _build_run_section(self):
        frame = self._make_card(1, None)

        # アクセント配色が使えない環境では通常のttkボタンに落とす。
        button_style = "Accent.TButton" if self._theme.get("accent_button") else "TButton"
        self.run_button = ttk.Button(
            frame,
            text=self._decorate("run", "実行"),
            command=self._on_run,
            style=button_style,
        )
        self.run_button.pack(side="left")

        # 次巻発売日の確認（楽天ブックス）。完結チェックとは別の実行で、どちらかの
        # 実行中は両方の実行ボタンを無効にする。進捗・ログ・中断ボタンは共通。
        # 「実行」を塗りの主ボタン、こちらを枠線の副ボタンにして主従を分ける。
        has_secondary = self._theme.get("secondary_button")
        next_style = "Secondary.TButton" if has_secondary else button_style
        self.next_button = ttk.Button(
            frame,
            text="次巻発売日を確認",
            command=self._on_next_release,
            style=next_style,
            padding=(38, 7, 18, 7),
        )
        self.next_button.pack(side="left", padx=(8, 0))
        self._add_button_icon(self.next_button, "refresh", COLOR_ACCENT)

        # 中断ボタンは実行中だけ有効にする（Issue #61）。数百行の入力では実行が
        # 1時間近くかかるので、強制終了せずに止められる必要がある。
        self.cancel_button = ttk.Button(
            frame,
            text=self._decorate("cancel", "中断"),
            command=self._on_cancel,
            state="disabled",
            style="Cancel.TButton",
        )
        self.cancel_button.pack(side="left", padx=(8, 0))

        outline = "Outline.TButton" if has_secondary else "TButton"
        self.key_button = key_button = ttk.Button(
            frame,
            text="楽天APIキーの設定…",
            command=self._open_key_settings,
            style=outline,
            padding=(34, 6, 14, 6),
        )
        key_button.pack(side="left", padx=(12, 0))
        self._add_button_icon(key_button, "calendar", COLOR_ACCENT)

    def _build_progress_section(self):
        frame = self._make_card(2, "進捗", icon="ring")
        frame.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(
            frame,
            textvariable=self.status_text,
            style=self._style("CardStatus.TLabel"),
            anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="ew")

        self._progress_style = (
            "Accent.Horizontal.TProgressbar"
            if self._theme.get("accent_progress")
            else "Horizontal.TProgressbar"
        )
        self.progress = ttk.Progressbar(
            frame, mode="determinate", maximum=100, value=0, style=self._progress_style
        )
        self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        tk.Frame(frame, height=1, background=COLOR_BORDER).grid(
            row=2, column=0, sticky="ew", pady=(12, 0)
        )

        # 3つの欄。対象ファイルは _on_path_changed()、処理件数は _update_progress()、
        # 経過時間は _start_elapsed()・_tick_elapsed()・_stop_elapsed() が更新する。
        stats = ttk.Frame(frame, style=self._style("Card.TFrame"))
        stats.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.stat_file_value = tk.StringVar(value="-")
        self.stat_count_value = tk.StringVar(value="-")
        self.stat_elapsed_value = tk.StringVar(value="-")
        stat_cells = (
            ("対象ファイル", "file", self.stat_file_value),
            ("処理件数", "count", self.stat_count_value),
            ("経過時間", "clock", self.stat_elapsed_value),
        )
        card_colour = self._surface_colour(COLOR_CARD)
        for index, (name, icon, variable) in enumerate(stat_cells):
            column = index * 2
            stats.columnconfigure(column, weight=1, uniform="stat")
            cell = ttk.Frame(stats, style=self._style("Card.TFrame"))
            cell.grid(row=0, column=column, sticky="ew")
            _icon_canvas(cell, icon, COLOR_ICON_MUTED, card_colour, size=26).grid(
                row=0, column=0, rowspan=2, padx=(10, 10)
            )
            ttk.Label(cell, text=name, style=self._style("CardHint.TLabel")).grid(
                row=0, column=1, sticky="w"
            )
            ttk.Label(cell, textvariable=variable, style=self._style("Card.TLabel")).grid(
                row=1, column=1, sticky="w"
            )
            if index < len(stat_cells) - 1:
                tk.Frame(stats, width=1, background=COLOR_BORDER).grid(
                    row=0, column=column + 1, sticky="ns", padx=4
                )

        # 3つの欄の下に「内訳」を1行で置く（縦の高さを節約する）。
        summary_row = ttk.Frame(frame, style=self._style("Card.TFrame"))
        summary_row.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(summary_row, text="内訳", style=self._style("CardHeading.TLabel")).pack(
            side="left", padx=(0, 12)
        )
        # 判定結果ごとに色を変えるため、1つのLabelではなくFrame＋複数Labelにする。
        self.summary_frame = ttk.Frame(summary_row, style=self._style("Card.TFrame"))
        self.summary_frame.pack(side="left", fill="x")
        self.summary_label = ttk.Label(
            self.summary_frame,
            textvariable=self.summary_text,
            style=self._style("Card.TLabel"),
            anchor="w",
            justify="left",
        )
        self.summary_label.pack(side="left")

    def _build_log_section(self):
        frame = self._make_card(3, "ログ", icon="doc", sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        # 見出しの行の右に、レベルでの絞り込みとクリア。クリアは表示と保持している行を消す
        # （絞り込みの選択と、ファイルに出す採用経路トレースは変えない）。
        header = self._card_header
        outline = "Outline.TButton" if self._theme.get("secondary_button") else "TButton"
        self.log_clear_button = ttk.Button(
            header,
            text="ログをクリア",
            style=outline,
            padding=(30, 4, 12, 4),
            command=self._on_log_clear,
        )
        self.log_clear_button.pack(side="right")
        self._add_button_icon(self.log_clear_button, "trash", COLOR_MUTED)
        self.log_filter = ttk.Combobox(
            header, values=(LOG_FILTER_ALL,) + LOG_LEVELS, state="readonly", width=12
        )
        self.log_filter.current(0)
        self.log_filter.pack(side="right", padx=(0, 8))
        self.log_filter.bind("<<ComboboxSelected>>", self._on_log_filter_changed)

        # ScrolledTextにttk版は無いのでtkのまま使い、枠線は外側のFrameで描く。
        # wrapは"none"にしないこと。ScrolledTextが用意するスクロールバーは
        # 縦だけなので、"none"にすると欄幅を超えた行（長いタイトル＋長い
        # 参照タイトル）が横スクロールできず読めなくなる。
        # 高さの要求はLOG_MIN_LINES行にして、縦が足りないときはこの欄だけが縮む。
        log_border = tk.Frame(
            frame,
            highlightthickness=1,
            background=COLOR_CARD,
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_BORDER,
        )
        log_border.grid(row=0, column=0, sticky="nsew")
        self.log_area = ScrolledText(
            log_border,
            state="disabled",
            height=LOG_MIN_LINES,
            width=80,
            wrap="word",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            spacing1=1,
            spacing3=1,
        )
        self.log_area.pack(fill="both", expand=True)
        for level, (background, foreground) in LOG_LEVEL_COLORS.items():
            self.log_area.tag_configure(
                f"log_{level}", background=background, foreground=foreground
            )

        mono = _pick_font(self.master, MONO_FONT_CANDIDATES)
        if mono:
            try:
                self.log_area.configure(font=(mono, 10))
            except tk.TclError:
                pass

    def _build_status_bar(self):
        """画面の下端の状態バー。左に実行の状態、右にバージョンを置く。

        バージョンは、ウィンドウタイトルが環境によって切り詰められることがあるため、
        不具合報告時にコピーしやすい形でも別途表示しておく。
        """
        bar = ttk.Frame(self, style=self._style("Bar.TFrame"))
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=PAD_OUTER, pady=(6, 6))
        bar.columnconfigure(1, weight=1)
        self.status_bar = bar

        self.run_state_dot = tk.Canvas(
            bar,
            width=RUN_STATE_DOT_SIZE,
            height=RUN_STATE_DOT_SIZE,
            highlightthickness=0,
            background=self._surface_colour(COLOR_BG),
        )
        self.run_state_dot.grid(row=0, column=0, sticky="w")
        self._run_state_dot_item = self.run_state_dot.create_oval(
            1, 1, RUN_STATE_DOT_SIZE - 1, RUN_STATE_DOT_SIZE - 1, outline="", fill=COLOR_SUCCESS
        )
        self.run_state_text = tk.StringVar(value=RUN_STATE_IDLE)
        ttk.Label(
            bar, textvariable=self.run_state_text, style=self._style("Bar.TLabel")
        ).grid(row=0, column=1, sticky="w", padx=(6, 0))

        self.version_label = ttk.Label(
            bar,
            text=f"バージョン: {version_string()}",
            style=self._style("BarHint.TLabel"),
            anchor="e",
        )
        self.version_label.grid(row=0, column=2, sticky="e")

    def _set_run_state(self, running):
        """状態バーの表示を切り替える。実行中は「実行中」、それ以外は「待機中」。

        ボタンの有効・無効を切り替える所（実行の開始と実行後の復帰）からだけ呼び、
        ワーカーの処理には手を入れない。
        """
        self.run_state_text.set(RUN_STATE_RUNNING if running else RUN_STATE_IDLE)
        try:
            self.run_state_dot.itemconfigure(
                self._run_state_dot_item, fill=COLOR_ACCENT if running else COLOR_SUCCESS
            )
        except tk.TclError:
            pass

    # ------------------------------------------------ ドラッグ＆ドロップ

    def _init_dnd(self):
        """ファイル選択欄にドロップを受け付ける。使えない環境では無効化する。

        tkinterdnd2 は tkinter.BaseWidget にメソッドを生やす作りなので、
        未インストールなら AttributeError、ルートが TkinterDnD.Tk() でない
        （＝tkdnd拡張が読み込まれていない）なら TclError になる。どちらの
        場合も「D&Dが使えないだけ」で、ファイル選択ボタンからは従来どおり
        操作できるため、握りつぶして False を返す。
        """
        try:
            from tkinterdnd2 import DND_FILES
        except Exception:
            return False
        try:
            # 広げたドロップ欄の全体（file_entry を含む）を受け口にする。
            for widget in self._drop_targets:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
        except (tk.TclError, AttributeError):
            return False
        return True

    def _on_drop(self, event):
        # tkdndからのコールバック。ここで例外を投げるとTcl側にエラーが出るため、
        # 何があってもログに出して飲み込む。
        try:
            self._handle_drop(getattr(event, "data", ""))
        except Exception as exc:
            self._log(f"ドロップの処理に失敗しました: {exc}", level="ERROR")
        return getattr(event, "action", None)

    def _handle_drop(self, data):
        """ドロップされたデータを解釈してファイルを選択する。

        受け付けたパスを返す。受け付けなかった場合は None を返し、
        **選択状態は変更しない**（不正なファイルで既存の選択を壊さない）。
        """
        paths = _parse_dropped_paths(data)
        if not paths:
            self._log("ドロップされたファイルを認識できませんでした。", level="WARNING")
            return None

        if len(paths) > 1:
            self._log(
                f"{len(paths)}件ドロップされました。最初の1件だけを使います: "
                f"{os.path.basename(paths[0])}",
                level="WARNING",
            )

        path = paths[0]
        if os.path.splitext(path)[1].lower() != EXCEL_SUFFIX:
            self._log(
                f"Excelファイル（{EXCEL_SUFFIX}）ではないため読み込みません: "
                f"{os.path.basename(path)}",
                level="WARNING",
            )
            return None

        self.excel_path.set(path)
        self._log(f"ファイルを選択しました: {os.path.basename(path)}", level="INFO")
        return path

    # -------------------------------------------------------------------- 操作

    def _on_path_changed(self, *_args):
        path = self.excel_path.get()
        if path:
            self.file_label.set(os.path.basename(path))
            self.file_hint.set(path)
            self.stat_file_value.set(os.path.basename(path))
        else:
            self.file_label.set("（未選択）")
            self.file_hint.set("")
            self.stat_file_value.set("-")

    def _choose_file(self):
        path = filedialog.askopenfilename(
            title="Excelファイルを選択",
            filetypes=[("Excelファイル", f"*{EXCEL_SUFFIX}")],
        )
        if path:
            self.excel_path.set(path)

    def _scan_rows(self, excel_path, title_column=DEFAULT_TITLE_COLUMN, sheet=None):
        """実行前に判定済み行数を数える。数えられなければNoneを返す（Issue #32）。

        列が無い・ファイルが壊れている等で数えられなくても、警告をあきらめて従来どおり
        実行に進めるようにする（数えるだけの処理でGUIを止めない。実行時に同じ問題が
        起きれば、そちらのエラー処理が本来のメッセージを出す）。
        """
        try:
            return count_rows(excel_path, sheet=sheet, title_column=title_column)
        except Exception as exc:
            self._log(f"判定済み行数を確認できませんでした（実行は継続します）: {exc}", level="WARNING")
            return None

    def _resolve_skip_filled(self, excel_path, title_column=DEFAULT_TITLE_COLUMN, sheet=None):
        """実行前確認を経て skip_filled を決める。実行しない場合は None を返す。"""
        counts = self._scan_rows(excel_path, title_column=title_column, sheet=sheet)
        if counts is None or not should_warn_about_filled_rows(counts):
            return True

        choice = FilledRowsDialog(self.master, counts).show()
        if choice == CHOICE_CANCEL:
            self._log("実行をキャンセルしました。", level="INFO")
            return None
        if choice == CHOICE_REJUDGE:
            self._log(f"すべて再判定します（{counts.total}件）。", level="INFO")
            return False
        self._log(
            f"{counts.total}行中 {counts.filled}行は判定済みのためスキップします"
            f"（処理対象 {counts.pending}件）。",
            level="INFO",
        )
        return True

    def _show_missing_sheet(self, sheet):
        """保存したシート名が Excel に無いことを、ログと状態表示に出す（Issue #551）。"""
        message = MISSING_SHEET_MESSAGE.format(sheet=sheet)
        self._log(message, level="ERROR")
        self.status_text.set(message)

    def _show_missing_title_column(self, title_column):
        """タイトル列名が1行目に無いことを、ログと状態表示に出す（Issue #553）。"""
        message = MISSING_TITLE_COLUMN_MESSAGE.format(column=title_column)
        self._log(message, level="ERROR")
        self.status_text.set(message)

    def _on_run(self):
        excel_path = self.excel_path.get()
        if not excel_path:
            self._log("Excelファイルを選択してください", level="WARNING")
            return

        # 保存済みの列名・シート名もメインスレッドで読み、ワーカーへは引数で渡す。
        title_column, sheet = load_read_target()
        if find_missing_sheet(excel_path, sheet):
            self._show_missing_sheet(sheet)
            return
        if find_missing_title_column(excel_path, title_column, sheet):
            self._show_missing_title_column(title_column)
            return
        skip_filled = self._resolve_skip_filled(
            excel_path, title_column=title_column, sheet=sheet
        )
        if skip_filled is None:
            return

        # Issue #33と同じ理由で、Tk変数の読み取りはメインスレッド（ここ）だけで行い、
        # ワーカースレッドへは解決済みのプレーンな値（パスまたはNone）で渡す。
        adoption_trace_file = (
            _default_adoption_trace_path(excel_path)
            if self.adoption_trace.get()
            else None
        )

        self._cancel_event = threading.Event()
        self.run_button.config(state="disabled")
        self.next_button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self._set_run_state(True)
        self._start_elapsed()
        threading.Thread(
            target=self._run_worker,
            kwargs={
                "excel_path": excel_path,
                "skip_filled": skip_filled,
                "cancel_event": self._cancel_event,
                "adoption_trace_file": adoption_trace_file,
                "title_column": title_column,
                "sheet": sheet,
            },
            daemon=True,
        ).start()

    def _on_cancel(self):
        """中断を要求する（Issue #61）。実際に止まるのは現在の行を処理し終えてから。"""
        if self._cancel_event is None or self._cancel_event.is_set():
            return
        # 押した瞬間にボタンを落として「効いていない」ように見せない。実際の停止は
        # run() が次の行の切れ目で気づくまで待つことになるので、そのことも書く。
        self.cancel_button.config(state="disabled")
        self._log("中断します（現在の行の処理を終えるまでお待ちください）", level="INFO")
        self.status_text.set("中断します（現在の行の処理を終えるまでお待ちください）")
        self._cancel_event.set()

    def _run_worker(
        self,
        excel_path,
        skip_filled=True,
        cancel_event=None,
        adoption_trace_file=None,
        title_column=DEFAULT_TITLE_COLUMN,
        sheet=None,
    ):
        self._reset_run_state()
        self._log_threadsafe(f"実行開始: {excel_path}", level="INFO")
        if adoption_trace_file is not None:
            self._log_threadsafe(f"採用経路トレースを書き出します: {adoption_trace_file}", level="INFO")
        try:
            total = run(
                excel_path,
                sheet=sheet,
                title_column=title_column,
                on_progress=self._on_progress,
                skip_filled=skip_filled,
                cancel_event=cancel_event,
                adoption_trace_file=adoption_trace_file,
            )
            # 中断で抜けた場合、total は「処理対象の行数」ではなく「実際に処理した行数」。
            # 完了と中断で表示を分けないと、途中で止めたのに完了したように見える。
            if cancel_event is not None and cancel_event.is_set():
                self._log_threadsafe(
                    f"中断しました（{total}件処理・保存済み、保存先: {excel_path}）",
                    level="WARNING",
                )
                self._set_status_threadsafe(f"中断しました（{total}件処理・保存済み）")
                self.after(0, self._set_progress_done, False)
            else:
                self._log_threadsafe(f"完了しました（{total}件処理、保存先: {excel_path}）", level="SUCCESS")
                self._set_status_threadsafe(f"完了しました（{total}件処理）")
                self.after(0, self._set_progress_done, True)
        except Exception as exc:
            self._log_threadsafe(f"エラーが発生しました: {exc}", level="ERROR")
            self._set_status_threadsafe("エラーで中断しました")
            self.after(0, self._set_progress_done, False)
        finally:
            self.after(0, self._reset_buttons_after_run)

    def _reset_buttons_after_run(self):
        """実行後のボタン状態を戻す。ワーカーからは after() 経由でのみ呼ぶこと。"""
        self.run_button.config(state="normal")
        self.next_button.config(state="normal")
        self.cancel_button.config(state="disabled")
        self._set_run_state(False)
        self._stop_elapsed()
        self._cancel_event = None

    # ------------------------------------------------ 経過時間

    def _start_elapsed(self):
        """経過時間の計測を始める（メインスレッドのafterだけで数える）。"""
        if self._elapsed_after_id is not None:
            self.after_cancel(self._elapsed_after_id)
        self._elapsed_start = self._clock()
        self.stat_elapsed_value.set(_format_elapsed(0))
        self._elapsed_after_id = self.after(ELAPSED_TICK_MS, self._tick_elapsed)

    def _tick_elapsed(self):
        # 予約の回数ではなく開始時刻からの差で出す（afterの遅れを積み重ねない）。
        self._refresh_elapsed()
        self._elapsed_after_id = self.after(ELAPSED_TICK_MS, self._tick_elapsed)

    def _refresh_elapsed(self):
        self.stat_elapsed_value.set(
            _format_elapsed(self._clock() - self._elapsed_start)
        )

    def _stop_elapsed(self):
        """計測を止め、その時点の値を最後に1回表示して残す。未開始なら何もしない。"""
        if self._elapsed_after_id is None:
            return
        self.after_cancel(self._elapsed_after_id)
        self._elapsed_after_id = None
        self._refresh_elapsed()

    # ------------------------------------------------ 次巻発売日の確認

    def _open_key_settings(self):
        """「設定」の画面に切り替える（楽天APIキーの設定がある）。"""
        self._select_screen(SETTINGS_SCREEN_INDEX)

    def _on_next_release(self):
        excel_path = self.excel_path.get()
        if not excel_path:
            self._log("Excelファイルを選択してください", level="WARNING")
            return

        if not has_rakuten_keys():
            self._log(MISSING_RAKUTEN_KEYS_MESSAGE, level="ERROR")
            self.status_text.set(MISSING_RAKUTEN_KEYS_MESSAGE)
            return

        title_column, sheet = load_read_target()
        if find_missing_sheet(excel_path, sheet):
            self._show_missing_sheet(sheet)
            return
        if find_missing_title_column(excel_path, title_column, sheet):
            self._show_missing_title_column(title_column)
            return
        self._cancel_event = threading.Event()
        self.run_button.config(state="disabled")
        self.next_button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self._set_run_state(True)
        self._start_elapsed()
        threading.Thread(
            target=self._next_release_worker,
            kwargs={
                "excel_path": excel_path,
                "cancel_event": self._cancel_event,
                "title_column": title_column,
                "sheet": sheet,
            },
            daemon=True,
        ).start()

    def _next_release_worker(
        self, excel_path, cancel_event=None, title_column=DEFAULT_TITLE_COLUMN, sheet=None
    ):
        self._reset_run_state(NEXT_SUMMARY_STATUSES)
        self._log_threadsafe(f"次巻発売日の確認を開始: {excel_path}", level="INFO")
        self._next_total = 0
        try:
            processed = next_release.run(
                excel_path,
                sheet=sheet,
                title_column=title_column,
                on_progress=self._on_next_progress,
                cancel_event=cancel_event,
            )
            # 最後の行の処理中に中断要求が立っても、全件処理済みなら完了として扱う。
            if (
                cancel_event is not None
                and cancel_event.is_set()
                and processed < self._next_total
            ):
                self._log_threadsafe(
                    f"中断しました（{processed}件処理・保存済み、保存先: {excel_path}）",
                    level="WARNING",
                )
                self._set_status_threadsafe(f"中断しました（{processed}件処理・保存済み）")
                self.after(0, self._set_progress_done, False)
            else:
                self._log_threadsafe(f"完了しました（{processed}件処理、保存先: {excel_path}）", level="SUCCESS")
                self._set_status_threadsafe(f"完了しました（{processed}件処理）")
                self.after(0, self._set_progress_done, True)
        except (RuntimeError, ValueError) as exc:
            # キー未設定（_load_keys の文面）・タイトル列なし（find_column の文面）。
            # どちらも文面にキーの値を含まないので、そのまま出す。
            self._log_threadsafe(str(exc), level="ERROR")
            self._set_status_threadsafe(str(exc))
            self.after(0, self._set_progress_done, False)
        except PermissionError:
            message = (
                "Excel を保存できません。ファイルを Excel で開いたままになっていないか"
                "確認してください"
            )
            self._log_threadsafe(message, level="ERROR")
            self._set_status_threadsafe(message)
            self.after(0, self._set_progress_done, False)
        except Exception as exc:
            # 例外の文面にはキーを含むURLが入りうるため、型の名前だけを出す。
            self._log_threadsafe(f"エラーが発生しました: {type(exc).__name__}", level="ERROR")
            self._set_status_threadsafe("エラーで中断しました")
            self.after(0, self._set_progress_done, False)
        finally:
            self.after(0, self._reset_buttons_after_run)

    def _on_next_progress(self, index, total, title, status, next_sales_date, error=None):
        self._next_total = total
        key = "エラー" if error is not None else status
        self._counts[key] = self._counts.get(key, 0) + 1

        if error is not None:
            self._log_threadsafe(f"[{index}/{total}] {title} -> エラー {type(error).__name__}", level="ERROR")
        else:
            level = "WARNING" if status in LOG_WARNING_STATUSES else "INFO"
            self._log_threadsafe(f"[{index}/{total}] {title} -> {status} ({next_sales_date})", level=level)

        self._set_status_threadsafe(f"処理中… {index}/{total} 件（{title}）")
        self.after(0, self._update_progress, index, total)
        self.after(0, self._update_summary)

    def _on_progress(self, index, total, title, status, matched_title, error=None):
        key = "エラー" if error is not None else status
        self._counts[key] = self._counts.get(key, 0) + 1

        if error is not None:
            self._log_threadsafe(f"[{index}/{total}] {title} -> エラー ({error})", level="ERROR")
        else:
            level = "WARNING" if status in LOG_WARNING_STATUSES else "INFO"
            self._log_threadsafe(f"[{index}/{total}] {title} -> {status} ({matched_title})", level=level)

        self._set_status_threadsafe(f"処理中… {index}/{total} 件（{title}）")
        self.after(0, self._update_progress, index, total)
        self.after(0, self._update_summary)

    # ------------------------------------------------------------ 表示の更新

    def _reset_run_state(self, summary_statuses=SUMMARY_STATUSES):
        self._counts = {}
        self._summary_statuses = summary_statuses
        self.after(0, self._update_progress, 0, 0)
        self.after(0, self._update_summary)
        self.after(0, self._set_progress_done, None)
        self._set_status_threadsafe("処理中…")

    def _set_progress_done(self, succeeded):
        """完了時に進捗バーをグリーンへ、実行中/失敗時はアクセント色へ戻す。"""
        if not self._theme.get("accent_progress"):
            return
        style = (
            "Done.Horizontal.TProgressbar"
            if succeeded
            else "Accent.Horizontal.TProgressbar"
        )
        try:
            self.progress.configure(style=style)
        except tk.TclError:
            pass

    def _update_progress(self, index, total):
        # totalが0（対象行なし・実行前）のときは空のバーにする。
        self.progress.config(maximum=max(total, 1), value=index)
        # 処理件数の欄も同じ時点で変える。totalが0のときは「-」。
        self.stat_count_value.set(f"{index} / {total}" if total > 0 else "-")

    def _update_summary(self):
        parts = []
        if self._counts:
            for name in self._summary_statuses:
                if self._counts.get(name):
                    parts.append((name, self._counts[name]))
            other = sum(
                count
                for name, count in self._counts.items()
                if name not in self._summary_statuses
            )
            if other:
                parts.append((OTHER_STATUS_LABEL, other))

        # テキスト版（テスト・読み上げ用）と色付きチップの両方を更新する。
        self.summary_text.set(
            " ／ ".join(f"{name} {count}" for name, count in parts) if parts else "—"
        )
        self._render_summary_chips(parts)

    def _render_summary_chips(self, parts):
        for chip in self._summary_chips:
            chip.destroy()
        self._summary_chips = []

        if not parts:
            # 未実行のときはテキスト版のラベルだけを見せる。
            self.summary_label.pack(side="left")
            return

        self.summary_label.pack_forget()
        for i, (name, count) in enumerate(parts):
            if i:
                sep = ttk.Label(self.summary_frame, text="／", style=self._style("CardHint.TLabel"))
                sep.pack(side="left", padx=4)
                self._summary_chips.append(sep)
            chip = ttk.Label(
                self.summary_frame,
                text=f"{name} {count}",
                style=f"Summary{_style_key(name)}.TLabel",
            )
            chip.pack(side="left")
            self._summary_chips.append(chip)

    def _set_status_threadsafe(self, message):
        self.after(0, self.status_text.set, message)

    def _log_threadsafe(self, message, level=LOG_DEFAULT_LEVEL):
        # tkinterウィジェットはメインスレッド以外から直接操作できないため、
        # ワーカースレッドからのログ出力は after() 経由でメインループに戻す。
        self.after(0, self._log, message, level)

    def _log(self, message, level=LOG_DEFAULT_LEVEL):
        if level not in LOG_LEVELS:
            raise ValueError(f"未知のログのレベル: {level!r}")
        # 時刻はメインスレッドのここで取る（after(0) で戻るまでの遅れは秒の単位では無視できる）。
        entry = (self._now().strftime(LOG_TIME_FORMAT), level, message)
        self._log_entries.append(entry)
        if self._log_entry_matches(entry):
            self.log_area.config(state="normal")
            self._write_log_entry(entry)
            self.log_area.see("end")
            self.log_area.config(state="disabled")

    def _log_entry_matches(self, entry):
        selected = self.log_filter.get()
        return selected == LOG_FILTER_ALL or selected == entry[1]

    def _write_log_entry(self, entry):
        """1行を log_area の末尾に書く。state は呼び出し側が normal にしておく。"""
        time_text, level, message = entry
        self.log_area.insert("end", time_text + " ")
        self.log_area.insert("end", level.ljust(LOG_LEVEL_WIDTH), f"log_{level}")
        self.log_area.insert("end", " " + message + "\n")

    def _on_log_filter_changed(self, _event=None):
        """絞り込みの選択が変わったとき、保持している行から書き直す。"""
        self.log_area.config(state="normal")
        self.log_area.delete("1.0", "end")
        for entry in self._log_entries:
            if self._log_entry_matches(entry):
                self._write_log_entry(entry)
        self.log_area.see("end")
        self.log_area.config(state="disabled")

    def _on_log_clear(self):
        """表示と保持している行を消す。絞り込みの選択は変えない。"""
        self._log_entries.clear()
        self.log_area.config(state="normal")
        self.log_area.delete("1.0", "end")
        self.log_area.config(state="disabled")


def main():
    # Tk()より前に呼ぶ必要がある。
    _enable_dpi_awareness()

    root = _create_root()
    root.title(f"コミックチェッカー v{version_string()}")

    app = App(master=root)
    app.pack(fill="both", expand=True)

    # 窓の大きさ。最小は、ログ欄を最小の行数にした部品の必要な大きさ。
    root.update_idletasks()
    required_width, required_height = app.required_size()
    initial, minimum = _compute_window_sizes(
        root.winfo_screenwidth(),
        root.winfo_screenheight(),
        required_width,
        required_height,
    )
    root.minsize(*minimum)
    root.geometry(f"{initial[0]}x{initial[1]}")

    _center_window(root)
    root.mainloop()


if __name__ == "__main__":
    main()
