import threading
import tkinter as tk
from tkinter import filedialog
from tkinter.scrolledtext import ScrolledText


class App(tk.Frame):
    """Excelファイルを選択して読み込みを実行するGUI画面。"""

    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.excel_path = tk.StringVar()
        self._build_widgets()

    def _build_widgets(self):
        path_frame = tk.Frame(self)
        path_frame.pack(fill="x", padx=8, pady=8)

        tk.Entry(path_frame, textvariable=self.excel_path, state="readonly").pack(
            side="left", fill="x", expand=True
        )
        tk.Button(path_frame, text="ファイルを選択", command=self._choose_file).pack(
            side="left", padx=(8, 0)
        )

        self.run_button = tk.Button(self, text="実行", command=self._on_run)
        self.run_button.pack(padx=8, pady=(0, 8))

        self.log_area = ScrolledText(self, state="disabled", height=20, width=80)
        self.log_area.pack(fill="both", expand=True, padx=8, pady=(0, 8))

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
        # TODO(T1.2): main.pyの実処理ロジック（進捗コールバック化後）に接続する。
        self._log_threadsafe(f"実行開始: {self.excel_path.get()}")
        self._log_threadsafe("（処理ロジックは未接続です）")
        self.after(0, lambda: self.run_button.config(state="normal"))

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
    root = tk.Tk()
    root.title("コミックチェッカー")
    app = App(master=root)
    app.pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
