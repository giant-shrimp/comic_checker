"""次巻発売日の確認（CLI）。

完結チェック（main.py）とは別の実行で、Excelのタイトル列の全行について楽天ブックス
書籍検索APIで次巻の発売日を調べ、4つの列に書き込む。Wikipediaは呼ばない。
"""

import argparse
import sys
from pathlib import Path

from comic_checker import positive_int, rakuten_books_client, version_string
from comic_checker.excel_io import ensure_column, find_column, open_workbook

DEFAULT_NEXT_DATE_COLUMN = "次巻発売日"
DEFAULT_NEXT_TITLE_COLUMN = "次巻タイトル"
DEFAULT_LATEST_COLUMN = "最新既刊"
DEFAULT_URL_COLUMN = "発売日参照URL"

SPECIAL_EDITION_NOTE = "（特装版あり）"


def _collect_rows(ws, title_col, header_row):
    """(行番号, タイトル) のリストを返す。タイトルが空（None・空白だけ）の行は除く。"""
    rows = []
    for row in range(header_row + 1, ws.max_row + 1):
        title = ws.cell(row=row, column=title_col).value
        if title is None:
            continue
        title = str(title).strip()
        if title == "":
            continue
        rows.append((row, title))
    return rows


def _latest_text(info):
    if not info.latest_title:
        return ""
    if not info.latest_sales_date:
        return info.latest_title
    return f"{info.latest_title}（{info.latest_sales_date}）"


def _row_values(info):
    """ReleaseInfo から (次巻発売日, 次巻タイトル, 最新既刊, 発売日参照URL) を作る。"""
    if info.status == rakuten_books_client.STATUS_NEXT:
        next_title = info.next_title
        if info.next_has_special_edition:
            next_title += SPECIAL_EDITION_NOTE
        return info.next_sales_date, next_title, _latest_text(info), info.url
    if info.status == rakuten_books_client.STATUS_UNDECIDED:
        return rakuten_books_client.STATUS_UNDECIDED, "", _latest_text(info), info.url
    return info.status, "", "", ""


def run(
    excel_path,
    sheet=None,
    header_row=1,
    title_column="タイトル",
    next_date_column=DEFAULT_NEXT_DATE_COLUMN,
    next_title_column=DEFAULT_NEXT_TITLE_COLUMN,
    latest_column=DEFAULT_LATEST_COLUMN,
    url_column=DEFAULT_URL_COLUMN,
    save_every=5,
    on_progress=None,
    cancel_event=None,
):
    """Excelの全タイトルについて次巻発売日を調べ、4列を毎回書き直す。

    1行処理するごとに on_progress(index, total, title, status, next_sales_date, error=None)
    を呼ぶ。想定外の例外が起きた行は「エラー」として書き、error に例外を渡して次の行へ進む。
    cancel_event が立つと、次の行の切れ目で止めて、そこまでの結果を保存する。
    戻り値は実際に処理した行数。
    """
    if on_progress is None:
        on_progress = lambda *args, **kwargs: None

    # Excelを開く前にキーの有無を確かめる（未設定ならRuntimeError）
    rakuten_books_client._load_keys()

    excel_path = Path(excel_path)
    wb = open_workbook(excel_path)
    ws = wb[sheet] if sheet else wb.active

    title_col = find_column(ws, title_column, header_row)
    date_col = ensure_column(ws, next_date_column, header_row)
    next_title_col = ensure_column(ws, next_title_column, header_row)
    latest_col = ensure_column(ws, latest_column, header_row)
    url_col = ensure_column(ws, url_column, header_row)

    rows = _collect_rows(ws, title_col, header_row)
    if not rows:
        print("処理対象の行がありません（タイトル未入力）")
        wb.save(excel_path)
        return 0

    total = len(rows)
    print(f"{total}件を処理します")

    processed = 0
    for i, (row, title) in enumerate(rows, start=1):
        # 行の切れ目で中断要求を見る（main.run() と同じ）。
        if cancel_event is not None and cancel_event.is_set():
            break
        error = None
        try:
            info = rakuten_books_client.find_next_release(title)
            status = info.status
            values = _row_values(info)
        except Exception as exc:
            status = rakuten_books_client.STATUS_ERROR
            values = (status, "", "", "")
            error = exc

        for col, value in zip((date_col, next_title_col, latest_col, url_col), values):
            ws.cell(row=row, column=col, value=value)
        on_progress(i, total, title, status, values[0], error=error)
        processed = i

        if i % save_every == 0:
            wb.save(excel_path)

    wb.save(excel_path)
    if processed < total:
        print(f"中断しました（{processed}件処理・保存済み）")
    else:
        print("完了しました")
    return processed


def _print_progress(index, total, title, status, next_sales_date, error=None):
    if error is not None:
        # 例外の文面にはキーを含むURLが入りうるため、型の名前だけを出す
        print(f"[{index}/{total}] {title} -> エラー {type(error).__name__}", file=sys.stderr)
    else:
        print(f"[{index}/{total}] {title} -> {status} ({next_sales_date})")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Excelの漫画タイトル一覧について、楽天ブックスで次巻の発売日を調べてExcelに書き込む"
    )
    parser.add_argument(
        "--version", action="version", version=f"comic_checker {version_string()}"
    )
    parser.add_argument("excel_path", help="対象のExcelファイルパス")
    parser.add_argument("--sheet", default=None, help="対象シート名（省略時はアクティブシート）")
    parser.add_argument("--header-row", type=int, default=1, help="ヘッダー行番号（デフォルト:1）")
    parser.add_argument("--title-column", default="タイトル", help="タイトルが入っている列のヘッダー名")
    parser.add_argument("--save-every", type=positive_int, default=5, help="何件ごとにExcelを保存するか")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    excel_path = Path(args.excel_path)
    if not excel_path.exists():
        print(f"ファイルが見つかりません: {excel_path}", file=sys.stderr)
        return 1

    try:
        run(
            excel_path,
            sheet=args.sheet,
            header_row=args.header_row,
            title_column=args.title_column,
            save_every=args.save_every,
            on_progress=_print_progress,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
