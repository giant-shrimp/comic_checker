import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont, ttk
from tkinter.scrolledtext import ScrolledText

from comic_checker import next_release, rakuten_books_client, user_config, version_string
from comic_checker.main import _default_adoption_trace_path, count_rows, run

# サマリに表示する判定結果。main.py の run() が on_progress へ渡す status 値のうち、
# 利用者が件数を知りたいものを並べている。ここに無い値（manba経路の「ヒットなし」
# 「不明」等）は「その他」にまとめる（0件のときは表示しない）。
SUMMARY_STATUSES = ("完結", "連載中", "判定不能", "記事なし", "エラー")
# 次巻発売日の確認で並べる集計（next_release.run() が on_progress へ渡す status 値）。
NEXT_SUMMARY_STATUSES = ("次巻あり", "未定", "要確認", "ヒットなし", "エラー")
OTHER_STATUS_LABEL = "その他"

# アクセントカラー。彩度を抑えた実用寄りの色にしてある（判定結果を読む画面なので、
# 色そのものより「どれがエラーか」がひと目で分かることを優先する）。
COLOR_ACCENT = "#0b6bcb"
COLOR_ACCENT_HOVER = "#1a7ae0"
COLOR_ACCENT_PRESSED = "#08508f"
COLOR_ACCENT_DISABLED = "#a8c3e0"
COLOR_SUCCESS = "#1f7a3d"
COLOR_ON_ACCENT = "#ffffff"

# 面の配色。画面の地は淡い灰色、各セクションは白いカードに細い枠線を付ける。
COLOR_BG = "#f1f3f6"
COLOR_CARD = "#ffffff"
COLOR_BORDER = "#d3d8e0"
COLOR_MUTED = "#5f6b7a"
COLOR_BUTTON_DISABLED_FG = "#9aa3af"
COLOR_IDLE = "#8a94a3"

# 文字の大きさは見出し・本文・補助の3段にそろえる。
FONT_SIZE_HEADING = 11
FONT_SIZE_BODY = 10
FONT_SIZE_HINT = 9

# 余白は外側（セクション間・画面端）と内側（カードの中）の2種類にそろえる。
PAD_OUTER = 12
PAD_INNER = 12

COLOR_DROP_BORDER = "#a9b2bf"
DROP_AREA_HEIGHT = 84
RUN_STATE_DOT_SIZE = 12
# 状態バーの左の表示。status_text（進捗の文言）とは別で、実行中かどうかだけを示す。
RUN_STATE_IDLE = "待機中"
RUN_STATE_RUNNING = "実行中"

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
        # 「中断」など通常のボタンは、無効のときに灰色の文字にする。
        style.map("TButton", foreground=[("disabled", COLOR_BUTTON_DISABLED_FG)])
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


class RakutenKeyDialog(tk.Toplevel):
    """楽天ブックス書籍検索APIのキー（アプリID・アクセスキー）を入力して保存する小窓。

    キーの値は画面にもログにも出さない。入力欄は伏せ字で、既存の値は入れない。
    表示するのは「設定済み／未設定」と、環境変数が優先される場合はその旨だけ。
    空欄のまま保存したキーは変更しない。保存時にAPIは呼ばない。
    """

    # (設定ファイルの項目名, 環境変数名, 表示名)
    FIELDS = (
        (user_config.KEY_RAKUTEN_APP_ID, rakuten_books_client.APP_ID_ENV, "アプリID"),
        (user_config.KEY_RAKUTEN_ACCESS_KEY, rakuten_books_client.ACCESS_KEY_ENV, "アクセスキー"),
    )

    def __init__(self, master):
        super().__init__(master)
        self.title("楽天APIキーの設定")
        self.resizable(False, False)
        self.transient(master)

        body = ttk.Frame(self, padding=(16, 14, 16, 12))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(
            body,
            text=(
                "楽天ウェブサービスで取得したキーを入力してください。\n"
                "キーは平文で設定ファイルに保存されます。"
                "空欄のまま保存したキーは変更しません。"
            ),
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        self.entries = {}
        self.status_vars = {}
        for i, (key, _env, label) in enumerate(self.FIELDS):
            row = 1 + i * 2
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=(10, 0))
            entry = ttk.Entry(body, show="*", width=40)
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))
            self.entries[key] = entry
            var = tk.StringVar()
            self.status_vars[key] = var
            ttk.Label(body, textvariable=var, style="Hint.TLabel").grid(
                row=row + 1, column=1, sticky="w", padx=(8, 0)
            )

        self.message = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.message).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.save_button = ttk.Button(buttons, text="保存", command=self.save)
        self.save_button.pack(side="left")
        ttk.Button(buttons, text="閉じる", command=self.destroy).pack(side="left", padx=(8, 0))

        self.bind("<Escape>", lambda _e: self.destroy())
        self.refresh_status()
        _center_window(self)

    def refresh_status(self):
        """「設定済み／未設定」と、環境変数が優先される場合の注記を更新する。"""
        for key, env_name, _label in self.FIELDS:
            text = "設定済み" if user_config.is_set(key) else "未設定"
            if os.environ.get(env_name):
                text += f"（環境変数 {env_name} が設定されているため、環境変数の値が優先されます）"
            self.status_vars[key].set(text)

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
            for entry in self.entries.values():
                entry.delete(0, "end")
            values.clear()
        self.refresh_status()


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

    def _surface_colour(self, card_colour):
        """tk（ttkでない）部品の背景色。カードの配色が無い環境では既定の地色にする。"""
        if self._theme.get("card"):
            return card_colour
        try:
            return ttk.Style(self).lookup("TFrame", "background") or card_colour
        except tk.TclError:
            return card_colour

    def _build_widgets(self):
        self.columnconfigure(0, weight=1)
        # ログ欄（row=3）だけが縦に伸びる。
        self.rowconfigure(3, weight=1)
        try:
            self.configure(style=self._style("App.TFrame"))
        except tk.TclError:
            pass

        self._build_file_section()
        self._build_run_section()
        self._build_progress_section()
        self._build_log_section()
        self._build_status_bar()

    def _make_card(self, row, title, sticky="ew", pady=(PAD_OUTER, 0)):
        """白い面と細い枠線のカードを置き、中身を入れるフレームを返す。

        titleがNoneなら見出しは付けない。vista/winnative で背景色が効かない場合は、
        色が付かないだけで配置は変わらない。
        """
        options = {"highlightthickness": 1}
        if self._theme.get("card"):
            options.update(
                background=COLOR_CARD,
                highlightbackground=COLOR_BORDER,
                highlightcolor=COLOR_BORDER,
            )
        outer = tk.Frame(self, **options)
        outer.grid(row=row, column=0, sticky=sticky, padx=PAD_OUTER, pady=pady)
        inner = ttk.Frame(outer, style=self._style("Card.TFrame"), padding=PAD_INNER)
        inner.pack(fill="both", expand=True)
        if title is not None:
            ttk.Label(inner, text=title, style=self._style("CardHeading.TLabel")).pack(
                anchor="w", pady=(0, 8)
            )
        content = ttk.Frame(inner, style=self._style("Card.TFrame"))
        content.pack(fill="both", expand=True)
        return content

    def _build_file_section(self):
        frame = self._make_card(0, self._decorate("file", "対象ファイル"))
        frame.columnconfigure(0, weight=1)

        # ドロップ欄。破線の枠をCanvasに描き、中にファイル名の欄と案内の文を置く。
        canvas_options = {"height": DROP_AREA_HEIGHT, "highlightthickness": 0}
        canvas_options["background"] = self._surface_colour(COLOR_CARD)
        self._drop_canvas = tk.Canvas(frame, **canvas_options)
        self._drop_canvas.grid(row=0, column=0, sticky="ew")
        drop_inner = ttk.Frame(self._drop_canvas, style=self._style("Card.TFrame"))
        drop_inner.columnconfigure(0, weight=1)
        self._drop_window = self._drop_canvas.create_window(0, 0, window=drop_inner)
        self._drop_canvas.bind("<Configure>", self._redraw_drop_area)

        # フルパスではなくファイル名を主に見せる（長いパスで欄が埋まらないように）。
        self.file_entry = ttk.Entry(drop_inner, textvariable=self.file_label, state="readonly")
        self.file_entry.grid(row=0, column=0, sticky="ew")
        # フルパスは補助情報として小さく添える。D&Dが使えるかもここに出す。
        hint_label = ttk.Label(
            drop_inner,
            textvariable=self.file_hint,
            style=self._style("CardHint.TLabel"),
            anchor="center",
        )
        hint_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        # ドロップは広げた欄の全体で受け付ける。file_entry も受け口のまま残す。
        self._drop_targets = [self._drop_canvas, drop_inner, self.file_entry, hint_label]

        ttk.Button(frame, text="ファイルを選択…", command=self._choose_file).grid(
            row=0, column=1, sticky="e", padx=(PAD_INNER, 0)
        )

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
        next_style = "Secondary.TButton" if self._theme.get("secondary_button") else button_style
        self.next_button = ttk.Button(
            frame,
            text="次巻発売日を確認",
            command=self._on_next_release,
            style=next_style,
        )
        self.next_button.pack(side="left", padx=(8, 0))

        # 中断ボタンは実行中だけ有効にする（Issue #61）。数百行の入力では実行が
        # 1時間近くかかるので、強制終了せずに止められる必要がある。
        self.cancel_button = ttk.Button(
            frame,
            text=self._decorate("cancel", "中断"),
            command=self._on_cancel,
            state="disabled",
        )
        self.cancel_button.pack(side="left", padx=(8, 0))

        # Issue #39: 採用経路トレース（デバッグ用、既定オフ）。
        ttk.Checkbutton(
            frame,
            text="採用経路のログを出力する",
            variable=self.adoption_trace,
            style=self._style("Card.TCheckbutton"),
        ).pack(side="left", padx=(12, 0))

        ttk.Button(
            frame, text="楽天APIキーの設定…", command=self._open_key_dialog
        ).pack(side="left", padx=(12, 0))

        ttk.Label(
            frame,
            text="「タイトル」列のある .xlsx を選んで実行してください。",
            style=self._style("CardHint.TLabel"),
        ).pack(side="left", padx=(12, 0))

    def _build_progress_section(self):
        frame = self._make_card(2, self._decorate("progress", "進捗"))
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

        ttk.Label(frame, text="内訳", style=self._style("CardHeading.TLabel")).grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )
        # 判定結果ごとに色を変えるため、1つのLabelではなくFrame＋複数Labelにする。
        self.summary_frame = ttk.Frame(frame, style=self._style("Card.TFrame"))
        self.summary_frame.grid(row=3, column=0, sticky="ew", pady=(2, 0))
        self.summary_label = ttk.Label(
            self.summary_frame,
            textvariable=self.summary_text,
            style=self._style("Card.TLabel"),
            anchor="w",
            justify="left",
        )
        self.summary_label.pack(side="left")

    def _build_log_section(self):
        frame = self._make_card(
            3, self._decorate("log", "ログ"), sticky="nsew", pady=(PAD_OUTER, 0)
        )
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        # ScrolledTextにttk版は無いのでtkのまま使い、見た目だけ整える。
        # wrapは"none"にしないこと。ScrolledTextが用意するスクロールバーは
        # 縦だけなので、"none"にすると欄幅を超えた行（長いタイトル＋長い
        # 参照タイトル）が横スクロールできず読めなくなる。
        self.log_area = ScrolledText(
            frame,
            state="disabled",
            height=14,
            width=80,
            wrap="word",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            spacing1=1,
            spacing3=1,
        )
        self.log_area.grid(row=0, column=0, sticky="nsew")

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
        bar.grid(row=4, column=0, sticky="ew", padx=PAD_OUTER, pady=(8, 8))
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
            1, 1, RUN_STATE_DOT_SIZE - 1, RUN_STATE_DOT_SIZE - 1, outline="", fill=COLOR_IDLE
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
                self._run_state_dot_item, fill=COLOR_ACCENT if running else COLOR_IDLE
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
            self._set_dnd_hint(False)
            return False
        try:
            # 広げたドロップ欄の全体（file_entry を含む）を受け口にする。
            for widget in self._drop_targets:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
        except (tk.TclError, AttributeError):
            self._set_dnd_hint(False)
            return False
        self._set_dnd_hint(True)
        return True

    def _set_dnd_hint(self, enabled):
        if not self.excel_path.get():
            self.file_hint.set(
                "ここに .xlsx をドラッグ＆ドロップできます" if enabled else ""
            )

    def _on_drop(self, event):
        # tkdndからのコールバック。ここで例外を投げるとTcl側にエラーが出るため、
        # 何があってもログに出して飲み込む。
        try:
            self._handle_drop(getattr(event, "data", ""))
        except Exception as exc:
            self._log(f"ドロップの処理に失敗しました: {exc}")
        return getattr(event, "action", None)

    def _handle_drop(self, data):
        """ドロップされたデータを解釈してファイルを選択する。

        受け付けたパスを返す。受け付けなかった場合は None を返し、
        **選択状態は変更しない**（不正なファイルで既存の選択を壊さない）。
        """
        paths = _parse_dropped_paths(data)
        if not paths:
            self._log("ドロップされたファイルを認識できませんでした。")
            return None

        if len(paths) > 1:
            self._log(
                f"{len(paths)}件ドロップされました。最初の1件だけを使います: "
                f"{os.path.basename(paths[0])}"
            )

        path = paths[0]
        if os.path.splitext(path)[1].lower() != EXCEL_SUFFIX:
            self._log(
                f"Excelファイル（{EXCEL_SUFFIX}）ではないため読み込みません: "
                f"{os.path.basename(path)}"
            )
            return None

        self.excel_path.set(path)
        self._log(f"ファイルを選択しました: {os.path.basename(path)}")
        return path

    # -------------------------------------------------------------------- 操作

    def _on_path_changed(self, *_args):
        path = self.excel_path.get()
        if path:
            self.file_label.set(os.path.basename(path))
            self.file_hint.set(path)
        else:
            self.file_label.set("（未選択）")
            self.file_hint.set("")

    def _choose_file(self):
        path = filedialog.askopenfilename(
            title="Excelファイルを選択",
            filetypes=[("Excelファイル", f"*{EXCEL_SUFFIX}")],
        )
        if path:
            self.excel_path.set(path)

    def _scan_rows(self, excel_path):
        """実行前に判定済み行数を数える。数えられなければNoneを返す（Issue #32）。

        列が無い・ファイルが壊れている等で数えられなくても、警告をあきらめて従来どおり
        実行に進めるようにする（数えるだけの処理でGUIを止めない。実行時に同じ問題が
        起きれば、そちらのエラー処理が本来のメッセージを出す）。
        """
        try:
            return count_rows(excel_path)
        except Exception as exc:
            self._log(f"判定済み行数を確認できませんでした（実行は継続します）: {exc}")
            return None

    def _resolve_skip_filled(self, excel_path):
        """実行前確認を経て skip_filled を決める。実行しない場合は None を返す。"""
        counts = self._scan_rows(excel_path)
        if counts is None or not should_warn_about_filled_rows(counts):
            return True

        choice = FilledRowsDialog(self.master, counts).show()
        if choice == CHOICE_CANCEL:
            self._log("実行をキャンセルしました。")
            return None
        if choice == CHOICE_REJUDGE:
            self._log(f"すべて再判定します（{counts.total}件）。")
            return False
        self._log(
            f"{counts.total}行中 {counts.filled}行は判定済みのためスキップします"
            f"（処理対象 {counts.pending}件）。"
        )
        return True

    def _on_run(self):
        excel_path = self.excel_path.get()
        if not excel_path:
            self._log("Excelファイルを選択してください")
            return

        skip_filled = self._resolve_skip_filled(excel_path)
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
        threading.Thread(
            target=self._run_worker,
            kwargs={
                "excel_path": excel_path,
                "skip_filled": skip_filled,
                "cancel_event": self._cancel_event,
                "adoption_trace_file": adoption_trace_file,
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
        self._log("中断します（現在の行の処理を終えるまでお待ちください）")
        self.status_text.set("中断します（現在の行の処理を終えるまでお待ちください）")
        self._cancel_event.set()

    def _run_worker(self, excel_path, skip_filled=True, cancel_event=None, adoption_trace_file=None):
        self._reset_run_state()
        self._log_threadsafe(f"実行開始: {excel_path}")
        if adoption_trace_file is not None:
            self._log_threadsafe(f"採用経路トレースを書き出します: {adoption_trace_file}")
        try:
            total = run(
                excel_path,
                on_progress=self._on_progress,
                skip_filled=skip_filled,
                cancel_event=cancel_event,
                adoption_trace_file=adoption_trace_file,
            )
            # 中断で抜けた場合、total は「処理対象の行数」ではなく「実際に処理した行数」。
            # 完了と中断で表示を分けないと、途中で止めたのに完了したように見える。
            if cancel_event is not None and cancel_event.is_set():
                self._log_threadsafe(
                    f"中断しました（{total}件処理・保存済み、保存先: {excel_path}）"
                )
                self._set_status_threadsafe(f"中断しました（{total}件処理・保存済み）")
                self.after(0, self._set_progress_done, False)
            else:
                self._log_threadsafe(f"完了しました（{total}件処理、保存先: {excel_path}）")
                self._set_status_threadsafe(f"完了しました（{total}件処理）")
                self.after(0, self._set_progress_done, True)
        except Exception as exc:
            self._log_threadsafe(f"エラーが発生しました: {exc}")
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
        self._cancel_event = None

    # ------------------------------------------------ 次巻発売日の確認

    def _open_key_dialog(self):
        RakutenKeyDialog(self.master)

    def _on_next_release(self):
        excel_path = self.excel_path.get()
        if not excel_path:
            self._log("Excelファイルを選択してください")
            return

        self._cancel_event = threading.Event()
        self.run_button.config(state="disabled")
        self.next_button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self._set_run_state(True)
        threading.Thread(
            target=self._next_release_worker,
            kwargs={"excel_path": excel_path, "cancel_event": self._cancel_event},
            daemon=True,
        ).start()

    def _next_release_worker(self, excel_path, cancel_event=None):
        self._reset_run_state(NEXT_SUMMARY_STATUSES)
        self._log_threadsafe(f"次巻発売日の確認を開始: {excel_path}")
        self._next_total = 0
        try:
            processed = next_release.run(
                excel_path,
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
                    f"中断しました（{processed}件処理・保存済み、保存先: {excel_path}）"
                )
                self._set_status_threadsafe(f"中断しました（{processed}件処理・保存済み）")
                self.after(0, self._set_progress_done, False)
            else:
                self._log_threadsafe(f"完了しました（{processed}件処理、保存先: {excel_path}）")
                self._set_status_threadsafe(f"完了しました（{processed}件処理）")
                self.after(0, self._set_progress_done, True)
        except (RuntimeError, ValueError) as exc:
            # キー未設定（_load_keys の文面）・タイトル列なし（find_column の文面）。
            # どちらも文面にキーの値を含まないので、そのまま出す。
            self._log_threadsafe(str(exc))
            self._set_status_threadsafe(str(exc))
            self.after(0, self._set_progress_done, False)
        except PermissionError:
            message = (
                "Excel を保存できません。ファイルを Excel で開いたままになっていないか"
                "確認してください"
            )
            self._log_threadsafe(message)
            self._set_status_threadsafe(message)
            self.after(0, self._set_progress_done, False)
        except Exception as exc:
            # 例外の文面にはキーを含むURLが入りうるため、型の名前だけを出す。
            self._log_threadsafe(f"エラーが発生しました: {type(exc).__name__}")
            self._set_status_threadsafe("エラーで中断しました")
            self.after(0, self._set_progress_done, False)
        finally:
            self.after(0, self._reset_buttons_after_run)

    def _on_next_progress(self, index, total, title, status, next_sales_date, error=None):
        self._next_total = total
        key = "エラー" if error is not None else status
        self._counts[key] = self._counts.get(key, 0) + 1

        if error is not None:
            self._log_threadsafe(f"[{index}/{total}] {title} -> エラー {type(error).__name__}")
        else:
            self._log_threadsafe(f"[{index}/{total}] {title} -> {status} ({next_sales_date})")

        self._set_status_threadsafe(f"処理中… {index}/{total} 件（{title}）")
        self.after(0, self._update_progress, index, total)
        self.after(0, self._update_summary)

    def _on_progress(self, index, total, title, status, matched_title, error=None):
        key = "エラー" if error is not None else status
        self._counts[key] = self._counts.get(key, 0) + 1

        if error is not None:
            self._log_threadsafe(f"[{index}/{total}] {title} -> エラー ({error})")
        else:
            self._log_threadsafe(f"[{index}/{total}] {title} -> {status} ({matched_title})")

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

    def _log_threadsafe(self, message):
        # tkinterウィジェットはメインスレッド以外から直接操作できないため、
        # ワーカースレッドからのログ出力は after() 経由でメインループに戻す。
        self.after(0, self._log, message)

    def _log(self, message):
        self.log_area.config(state="normal")
        self.log_area.insert("end", message + "\n")
        self.log_area.see("end")
        self.log_area.config(state="disabled")


def main():
    # Tk()より前に呼ぶ必要がある。
    _enable_dpi_awareness()

    root = _create_root()
    root.title(f"コミックチェッカー v{version_string()}")
    root.minsize(720, 560)

    app = App(master=root)
    app.pack(fill="both", expand=True)

    _center_window(root)
    root.mainloop()


if __name__ == "__main__":
    main()
