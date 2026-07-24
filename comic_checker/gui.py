import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont, ttk
from tkinter.scrolledtext import ScrolledText

from comic_checker.main import run

# サマリに表示する判定結果。main.py の run() が on_progress へ渡す status 値のうち、
# 利用者が件数を知りたいものを並べている。ここに無い値（manba経路の「ヒットなし」
# 「不明」等）は「その他」にまとめる（0件のときは表示しない）。
SUMMARY_STATUSES = ("完結", "連載中", "判定不能", "記事なし", "エラー")
OTHER_STATUS_LABEL = "その他"

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


def _apply_theme(root):
    """ttkテーマと既定フォントを設定する。

    失敗してもGUIは動くべきなので、例外は握りつぶす（素のテーマ・既定
    フォントで表示される）。
    """
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
                    tkfont.nametofont(name, root=root).configure(family=ui_font, size=10)
                except tk.TclError:
                    pass

        # 見出し・補助テキスト用のスタイル。色は明示せず、テーマ既定の
        # 前景色との差を太字/サイズだけで付ける（ダークテーマでも破綻しない）。
        style.configure("Heading.TLabel", font=(ui_font or "TkDefaultFont", 10, "bold"))
        style.configure("Hint.TLabel", font=(ui_font or "TkDefaultFont", 8))
        style.configure("Status.TLabel", font=(ui_font or "TkDefaultFont", 10))
    except Exception:
        pass


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
        self._counts = {}
        _apply_theme(master)
        self._build_widgets()
        self.excel_path.trace_add("write", self._on_path_changed)

    # ------------------------------------------------------------------ 画面構築

    def _build_widgets(self):
        self.columnconfigure(0, weight=1)
        # ログ欄（row=3）だけが縦に伸びる。
        self.rowconfigure(3, weight=1)

        self._build_file_section()
        self._build_run_section()
        self._build_progress_section()
        self._build_log_section()

    def _build_file_section(self):
        frame = ttk.LabelFrame(self, text="対象ファイル", padding=(12, 8, 12, 12))
        frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 0))
        frame.columnconfigure(0, weight=1)

        # フルパスではなくファイル名を主に見せる（長いパスで欄が埋まらないように）。
        ttk.Entry(
            frame, textvariable=self.file_label, state="readonly"
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(frame, text="ファイルを選択…", command=self._choose_file).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        # フルパスは補助情報として小さく添える。
        ttk.Label(
            frame, textvariable=self.file_hint, style="Hint.TLabel", anchor="w"
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    def _build_run_section(self):
        frame = ttk.Frame(self)
        frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(12, 0))

        self.run_button = ttk.Button(frame, text="実行", command=self._on_run)
        self.run_button.pack(side="left")
        ttk.Label(
            frame,
            text="「タイトル」列のある .xlsx を選んで実行してください。",
            style="Hint.TLabel",
        ).pack(side="left", padx=(12, 0))

    def _build_progress_section(self):
        frame = ttk.LabelFrame(self, text="進捗", padding=(12, 8, 12, 12))
        frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(12, 0))
        frame.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(
            frame, textvariable=self.status_text, style="Status.TLabel", anchor="w"
        )
        self.status_label.grid(row=0, column=0, sticky="ew")

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100, value=0)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        ttk.Label(frame, text="内訳", style="Heading.TLabel").grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )
        self.summary_label = ttk.Label(
            frame, textvariable=self.summary_text, anchor="w", justify="left"
        )
        self.summary_label.grid(row=3, column=0, sticky="ew", pady=(2, 0))

    def _build_log_section(self):
        frame = ttk.LabelFrame(self, text="ログ", padding=(8, 4, 8, 8))
        frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=12)
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
            filetypes=[("Excelファイル", "*.xlsx")],
        )
        if path:
            self.excel_path.set(path)

    def _on_run(self):
        if not self.excel_path.get():
            self._log("Excelファイルを選択してください")
            return
        self.run_button.config(state="disabled")
        threading.Thread(target=self._run_worker, daemon=True).start()

    def _run_worker(self):
        excel_path = self.excel_path.get()
        self._reset_run_state()
        self._log_threadsafe(f"実行開始: {excel_path}")
        try:
            total = run(excel_path, on_progress=self._on_progress)
            self._log_threadsafe(f"完了しました（{total}件処理、保存先: {excel_path}）")
            self._set_status_threadsafe(f"完了しました（{total}件処理）")
        except Exception as exc:
            self._log_threadsafe(f"エラーが発生しました: {exc}")
            self._set_status_threadsafe("エラーで中断しました")
        finally:
            self.after(0, lambda: self.run_button.config(state="normal"))

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

    def _reset_run_state(self):
        self._counts = {}
        self.after(0, self._update_progress, 0, 0)
        self.after(0, self._update_summary)
        self._set_status_threadsafe("処理中…")

    def _update_progress(self, index, total):
        # totalが0（対象行なし・実行前）のときは空のバーにする。
        self.progress.config(maximum=max(total, 1), value=index)

    def _update_summary(self):
        if not self._counts:
            self.summary_text.set("—")
            return
        parts = [
            f"{name} {self._counts[name]}"
            for name in SUMMARY_STATUSES
            if self._counts.get(name)
        ]
        other = sum(
            count
            for name, count in self._counts.items()
            if name not in SUMMARY_STATUSES
        )
        if other:
            parts.append(f"{OTHER_STATUS_LABEL} {other}")
        self.summary_text.set(" ／ ".join(parts) if parts else "—")

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

    root = tk.Tk()
    root.title("コミックチェッカー")
    root.minsize(720, 560)

    app = App(master=root)
    app.pack(fill="both", expand=True)

    _center_window(root)
    root.mainloop()


if __name__ == "__main__":
    main()
