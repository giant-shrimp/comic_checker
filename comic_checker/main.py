import argparse
import sys
import traceback
from pathlib import Path
from typing import NamedTuple

from comic_checker import wikipedia_client
from comic_checker.excel_io import ensure_column, find_column, open_workbook

DEFAULT_STATE_FILE = ".manba_state.json"

WIKIPEDIA_SOURCE = "Wikipedia"
MANBA_SOURCE = "manba.co.jp"


def _import_manba_client():
    """ManbaClientを遅延importする。

    manba_clientはplaywrightに依存する。軽量ビルド（Wikipedia経路のみ、
    Playwright/Chromium非同梱）では起動時に落ちないよう、--fallback-to-manba使用時に
    実際に必要になった時点でのみimportする（main.pyの先頭で無条件importすると、
    軽量ビルドではplaywright自体が同梱されないため、既定経路しか使わない場合でも
    起動できなくなってしまう）。
    """
    try:
        from comic_checker.manba_client import ManbaClient
    except ImportError as exc:
        raise RuntimeError(
            "manba.co.jpフォールバック（--fallback-to-manba）にはplaywrightが必要です。"
            "pip install -r requirements-fallback.txt を実行するか、"
            "Playwright/Chromium同梱ビルドを使用してください。"
        ) from exc
    return ManbaClient


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Excelの漫画タイトル一覧をWikipediaで検索し、完結/連載中をExcelに書き戻す"
    )
    parser.add_argument("excel_path", help="対象のExcelファイルパス")
    parser.add_argument("--sheet", default=None, help="対象シート名（省略時はアクティブシート）")
    parser.add_argument("--header-row", type=int, default=1, help="ヘッダー行番号（デフォルト:1）")
    parser.add_argument("--title-column", default="タイトル", help="タイトルが入っている列のヘッダー名")
    parser.add_argument("--status-column", default="連載状況", help="判定結果を書き込む列のヘッダー名")
    parser.add_argument(
        "--source-column",
        default="判定方法",
        help="判定に使った情報源（Wikipedia/manba.co.jp）を書き込む列のヘッダー名",
    )
    parser.add_argument(
        "--evidence-column",
        default="判定根拠",
        help="判定根拠（該当したリード文の抜粋など）を書き込む列のヘッダー名",
    )
    parser.add_argument(
        "--matched-title-column",
        default="参照タイトル",
        help="判定に使った記事/作品ページ上のタイトルを書き込む列のヘッダー名",
    )
    parser.add_argument("--url-column", default="参照URL", help="判定に使ったページのURLを書き込む列のヘッダー名")
    parser.add_argument(
        "--skip-filled",
        action="store_true",
        default=True,
        help="判定結果が既に入っている行はスキップする（デフォルト:有効）",
    )
    parser.add_argument("--no-skip-filled", dest="skip_filled", action="store_false")
    parser.add_argument(
        "--fallback-to-manba",
        action="store_true",
        default=False,
        help=(
            "Wikipediaで判定できなかった行（判定不能/記事なし）をmanba.co.jp経由で"
            "判定し直す（デフォルト:無効）。有効にした場合のみ、以下のPlaywright関連"
            "オプションとMANBA_SEARCH_API_KEY環境変数が必要になる"
        ),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="（--fallback-to-manba有効時のみ使用）ヘッドレスブラウザで実行する",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="（--fallback-to-manba有効時のみ使用）ブラウザを表示して実行する（動作確認に便利）",
    )
    parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_FILE,
        help="（--fallback-to-manba有効時のみ使用）Cloudflare通過後のセッション情報(Cookie)の保存先",
    )
    parser.add_argument(
        "--min-delay", type=float, default=3.0, help="（--fallback-to-manba有効時のみ使用）リクエスト間の最小待機秒数"
    )
    parser.add_argument(
        "--max-delay", type=float, default=6.0, help="（--fallback-to-manba有効時のみ使用）リクエスト間の最大待機秒数"
    )
    parser.add_argument("--save-every", type=int, default=5, help="何件ごとにExcelを保存するか")
    return parser.parse_args(argv)


class RowCounts(NamedTuple):
    """判定を行わずに数えた、処理対象行の内訳（Issue #32）。

    pending: 判定結果が未記入で、これから処理される行数
    filled:  判定結果が既に入っており、skip_filled=True ならスキップされる行数
    """

    pending: int
    filled: int

    @property
    def total(self):
        return self.pending + self.filled


def count_rows(
    excel_path,
    sheet=None,
    header_row=1,
    title_column="タイトル",
    status_column="連載状況",
):
    """処理対象になる行数と、判定済みでスキップされる行数を数える。

    Issue #32: GUIが実行前に「N行は判定済みのためスキップされます」と警告するための
    事前スキャン。Wikipedia等への問い合わせは一切行わず、Excelを読むだけで完結する。

    status_column がまだ存在しないファイル（初回実行）では、判定済みの行はありえない
    ため filled=0 を返す。run() と違い、列を作る副作用は持たせない（数えるだけの
    関数がファイルを書き換えるのは驚きが大きいため）。
    """
    wb = open_workbook(Path(excel_path))
    ws = wb[sheet] if sheet else wb.active

    title_col = find_column(ws, title_column, header_row)
    try:
        status_col = find_column(ws, status_column, header_row)
    except ValueError:
        status_col = None

    all_rows = _collect_rows(ws, title_col, status_col, header_row, skip_filled=False)
    if status_col is None:
        return RowCounts(pending=len(all_rows), filled=0)

    pending_rows = _collect_rows(ws, title_col, status_col, header_row, skip_filled=True)
    return RowCounts(pending=len(pending_rows), filled=len(all_rows) - len(pending_rows))


def _collect_rows(ws, title_col, status_col, header_row, skip_filled):
    """処理対象の行を (行番号, タイトル) のリストで返す。

    タイトルが空欄の行は常に除外する。skip_filled が真なら、判定結果が既に
    入っている行も除外する。

    Issue #32: run() とcount_rows()の両方から使う。実行前に「何件がスキップされるか」を
    GUIに出すには、判定を伴わずに同じ条件で行を数える必要があるが、両者の条件が
    食い違うと警告の件数と実際の処理件数がずれてしまうため、1か所に集約している。
    """
    rows = []
    for row in range(header_row + 1, ws.max_row + 1):
        title = ws.cell(row=row, column=title_col).value
        if title is None or str(title).strip() == "":
            continue
        if skip_filled and ws.cell(row=row, column=status_col).value:
            continue
        rows.append((row, str(title).strip()))
    return rows


def _judge_row(title, fallback_to_manba, get_manba_client):
    """1件分の判定を行い、(status, source, matched_title, url, evidence) を返す。

    Wikipediaで完結/連載中が判定できればそれを採用する。判定不能/記事なしの場合、
    fallback_to_manba が真であれば get_manba_client() 経由でmanba.co.jpにフォールバック
    する。get_manba_client() はManbaClientを遅延生成し、以降の呼び出しでは使い回す。
    """
    wiki_result = wikipedia_client.judge(title)
    wiki_row = (
        wiki_result.status,
        WIKIPEDIA_SOURCE,
        wiki_result.matched_title or "",
        wiki_result.url or "",
        wiki_result.evidence or "",
    )

    if wiki_result.status in ("完結", "連載中") or not fallback_to_manba:
        return wiki_row

    manba_client = get_manba_client()
    manba_result = manba_client.lookup(title)
    return (
        manba_result.status,
        MANBA_SOURCE,
        manba_result.matched_title or "",
        manba_result.url or "",
        "",
    )


def run(
    excel_path,
    sheet=None,
    header_row=1,
    title_column="タイトル",
    status_column="連載状況",
    source_column="判定方法",
    evidence_column="判定根拠",
    matched_title_column="参照タイトル",
    url_column="参照URL",
    skip_filled=True,
    fallback_to_manba=False,
    headless=True,
    state_file=DEFAULT_STATE_FILE,
    min_delay=3.0,
    max_delay=6.0,
    save_every=5,
    on_progress=None,
    cancel_event=None,
):
    """Excelを読み込み、Wikipedia（必要に応じてmanba.co.jp）を検索して連載状況を書き戻す。

    1行処理するごとに on_progress(index, total, title, status, matched_title, error=None)
    を呼び出す。成功時は error=None、行単位で例外が起きた場合は捕捉した例外を渡す。
    on_progress が None の場合は何もしない。戻り値は実際に処理した行数で、中断しなければ
    処理対象の行数と一致する。

    cancel_event に `is_set()` を持つオブジェクトを渡すと、**行の切れ目ごと**に中断要求を
    見て処理を打ち切る（Issue #61）。`threading.Event` を想定しているが、型は要求しない
    （テストから偽物を渡せるようにするため、main.py は threading を import しない）。
    行の途中では止まらないので、中断してから実際に止まるまで1行分（実測4.5秒/行・
    上限見積り約7秒/行）かかる。`wikipedia_client._api_get` の待機は割り込まないため、
    429のリトライ中はさらに待つ。

    **中断してもそこまでの結果は保存する。** 判定結果の5セルは1行ぶんまとめて書くので、
    中断地点に半端な行は残らない。skip_filled=True の次回実行が続きから再開できる。

    fallback_to_manba が真の場合のみ、Wikipediaで判定不能だった行についてManbaClientを
    （最初に必要になった時点で一度だけ）起動し、以降の該当行で使い回す。
    """
    if on_progress is None:
        on_progress = lambda *args, **kwargs: None

    excel_path = Path(excel_path)
    wb = open_workbook(excel_path)
    ws = wb[sheet] if sheet else wb.active

    title_col = find_column(ws, title_column, header_row)
    status_col = ensure_column(ws, status_column, header_row)
    source_col = ensure_column(ws, source_column, header_row)
    evidence_col = ensure_column(ws, evidence_column, header_row)
    matched_col = ensure_column(ws, matched_title_column, header_row)
    url_col = ensure_column(ws, url_column, header_row)

    rows = _collect_rows(ws, title_col, status_col, header_row, skip_filled)

    if not rows:
        print("処理対象の行がありません（タイトル未入力、または既に判定済み）")
        return 0

    total = len(rows)
    print(f"{total}件を処理します")

    # fallback_to_manba時のみ、ここでimportを試みて即座に失敗させる（行処理中に
    # 初めて発覚するのではなく、playwright未同梱ならこの時点でRuntimeErrorにする）。
    manba_client_cls = _import_manba_client() if fallback_to_manba else None

    manba_client_holder = {"client": None}

    def get_manba_client():
        if manba_client_holder["client"] is None:
            client = manba_client_cls(
                headless=headless,
                state_path=state_file,
                min_delay=min_delay,
                max_delay=max_delay,
            )
            client.__enter__()
            manba_client_holder["client"] = client
        return manba_client_holder["client"]

    processed = 0
    try:
        for i, (row, title) in enumerate(rows, start=1):
            # 中断要求は行の切れ目でだけ見る。判定の途中で抜けると、書き込み済みの
            # セルと未書き込みのセルが同じ行に混在しうるため。
            if cancel_event is not None and cancel_event.is_set():
                print(f"中断しました（{processed}件処理）")
                break

            error = None
            try:
                status, source, matched_title, url, evidence = _judge_row(
                    title, fallback_to_manba, get_manba_client
                )
            except Exception as exc:
                status, source, matched_title, url, evidence = "エラー", "", "", "", ""
                error = exc

            ws.cell(row=row, column=status_col, value=status)
            ws.cell(row=row, column=source_col, value=source)
            ws.cell(row=row, column=evidence_col, value=evidence)
            ws.cell(row=row, column=matched_col, value=matched_title)
            ws.cell(row=row, column=url_col, value=url)
            processed = i
            on_progress(i, total, title, status, matched_title, error=error)

            if i % save_every == 0:
                wb.save(excel_path)
    finally:
        if manba_client_holder["client"] is not None:
            manba_client_holder["client"].__exit__(None, None, None)

    # 中断した場合もここへ落として保存する（そこまでの結果を捨てない・Issue #61）。
    wb.save(excel_path)
    if processed == total:
        print("完了しました")
    return processed


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
        source_column=args.source_column,
        evidence_column=args.evidence_column,
        matched_title_column=args.matched_title_column,
        url_column=args.url_column,
        skip_filled=args.skip_filled,
        fallback_to_manba=args.fallback_to_manba,
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
