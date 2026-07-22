import argparse
import sys
import traceback
from pathlib import Path

from comic_checker.excel_io import ensure_column, find_column, open_workbook
from comic_checker.manba_client import ManbaClient

DEFAULT_STATE_FILE = ".manba_state.json"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Excelの漫画タイトル一覧をmanba.co.jpで検索し、完結/連載中をExcelに書き戻す"
    )
    parser.add_argument("excel_path", help="対象のExcelファイルパス")
    parser.add_argument("--sheet", default=None, help="対象シート名（省略時はアクティブシート）")
    parser.add_argument("--header-row", type=int, default=1, help="ヘッダー行番号（デフォルト:1）")
    parser.add_argument("--title-column", default="タイトル", help="タイトルが入っている列のヘッダー名")
    parser.add_argument("--status-column", default="連載状況", help="判定結果を書き込む列のヘッダー名")
    parser.add_argument(
        "--matched-title-column",
        default="マンバ上のタイトル",
        help="マンバでの一致タイトルを書き込む列のヘッダー名",
    )
    parser.add_argument("--url-column", default="マンバURL", help="作品ページURLを書き込む列のヘッダー名")
    parser.add_argument(
        "--skip-filled",
        action="store_true",
        default=True,
        help="判定結果が既に入っている行はスキップする（デフォルト:有効）",
    )
    parser.add_argument("--no-skip-filled", dest="skip_filled", action="store_false")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="ブラウザを表示して実行する（動作確認に便利）",
    )
    parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_FILE,
        help="Cloudflare通過後のセッション情報(Cookie)の保存先",
    )
    parser.add_argument("--min-delay", type=float, default=3.0, help="リクエスト間の最小待機秒数")
    parser.add_argument("--max-delay", type=float, default=6.0, help="リクエスト間の最大待機秒数")
    parser.add_argument("--save-every", type=int, default=5, help="何件ごとにExcelを保存するか")
    return parser.parse_args(argv)


def run(
    excel_path,
    sheet=None,
    header_row=1,
    title_column="タイトル",
    status_column="連載状況",
    matched_title_column="マンバ上のタイトル",
    url_column="マンバURL",
    skip_filled=True,
    headless=True,
    state_file=DEFAULT_STATE_FILE,
    min_delay=3.0,
    max_delay=6.0,
    save_every=5,
    on_progress=None,
):
    """Excelを読み込み、manba.co.jpを検索して連載状況を書き戻す。

    1行処理するごとに on_progress(index, total, title, status, matched_title, error=None)
    を呼び出す。成功時は error=None、行単位で例外が起きた場合は捕捉した例外を渡す。
    on_progress が None の場合は何もしない。戻り値は処理対象だった行数。
    """
    if on_progress is None:
        on_progress = lambda *args, **kwargs: None

    excel_path = Path(excel_path)
    wb = open_workbook(excel_path)
    ws = wb[sheet] if sheet else wb.active

    title_col = find_column(ws, title_column, header_row)
    status_col = ensure_column(ws, status_column, header_row)
    matched_col = ensure_column(ws, matched_title_column, header_row)
    url_col = ensure_column(ws, url_column, header_row)

    rows = []
    for row in range(header_row + 1, ws.max_row + 1):
        title = ws.cell(row=row, column=title_col).value
        if title is None or str(title).strip() == "":
            continue
        if skip_filled and ws.cell(row=row, column=status_col).value:
            continue
        rows.append((row, str(title).strip()))

    if not rows:
        print("処理対象の行がありません（タイトル未入力、または既に判定済み）")
        return 0

    total = len(rows)
    print(f"{total}件を処理します")

    with ManbaClient(
        headless=headless,
        state_path=state_file,
        min_delay=min_delay,
        max_delay=max_delay,
    ) as client:
        for i, (row, title) in enumerate(rows, start=1):
            error = None
            try:
                result = client.lookup(title)
                status = result.status
                matched_title = result.matched_title or ""
                url = result.url or ""
            except Exception as exc:
                status, matched_title, url = "エラー", "", ""
                error = exc

            ws.cell(row=row, column=status_col, value=status)
            ws.cell(row=row, column=matched_col, value=matched_title)
            ws.cell(row=row, column=url_col, value=url)
            on_progress(i, total, title, status, matched_title, error=error)

            if i % save_every == 0:
                wb.save(excel_path)

    wb.save(excel_path)
    print("完了しました")
    return total


def _print_progress(index, total, title, status, matched_title, error=None):
    if error is not None:
        print(f"[{index}/{total}] {title} -> エラー", file=sys.stderr)
        traceback.print_exception(type(error), error, error.__traceback__)
    else:
        print(f"[{index}/{total}] {title} -> {status} ({matched_title})")


def main(argv=None):
    args = parse_args(argv)
    excel_path = Path(args.excel_path)
    if not excel_path.exists():
        print(f"ファイルが見つかりません: {excel_path}", file=sys.stderr)
        return 1

    run(
        excel_path,
        sheet=args.sheet,
        header_row=args.header_row,
        title_column=args.title_column,
        status_column=args.status_column,
        matched_title_column=args.matched_title_column,
        url_column=args.url_column,
        skip_filled=args.skip_filled,
        headless=args.headless,
        state_file=args.state_file,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        save_every=args.save_every,
        on_progress=_print_progress,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
