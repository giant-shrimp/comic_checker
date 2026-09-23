#!/usr/bin/env python3
"""個人情報・絶対パスの走査を行う CLI（Issue #251）。

`CLAUDE.md` の散文ルール「リポジトリ内のあらゆるファイルに個人名を記載しない」を
機械的に検査するための実行可能なチェック。これまで各作業指示に都度書かれていた
`grep` のワンライナー（ホームディレクトリの絶対パス接頭辞・記号・敬称を対象にした
正規表現）を、リポジトリにコミットされた単一の走査器へ置き換える。

検出対象:
    1. ホームディレクトリを指す絶対パスの接頭辞（`HOME_PREFIX_PATTERN`）
    2. メールアドレスの形（ローカル部・区切り記号・ドメイン部、`EMAIL_PATTERN`）
    3. 日本語の敬称（`HONORIFIC_PATTERN`）

誤検出の抑止:
    1. 敬称を表す一字が複合語（「仕様」「同様」など）の末尾字に一致すること
       → 除外語彙の一覧 `HONORIFIC_EXCLUDE_PATTERN` を持ち、敬称が一致した位置が
         除外語のスパン内にあるときは落とす（`_honorific_hit()`）。
         **この除外は有限の列挙で成り立っており、一覧に無い複合語（例では
         「摂氏」に対する「華氏」を追加したのと同様に、随時手で足す必要がある）は
         取りこぼす。** 網羅性は保証しない。新しい誤検出が見つかるたびに
         `HONORIFIC_EXCLUDE_PATTERN` へ語を追記する運用とする。
    2. 区切り記号を 2 つ並べて始まる行（`git diff` のハンクヘッダ）に一致すること
       → `HUNK_HEADER_PATTERN` に一致する行は走査前にスキップする。

使い方:
    scripts/check_no_personal_info.py PATH [PATH ...]
        引数のファイルを走査する。
    ... | scripts/check_no_personal_info.py
        引数が無ければ標準入力を走査する（ラベルは `<stdin>`）。
    scripts/check_no_personal_info.py --diff-base REF
        REF との差分（`git diff --no-color -U0 REF...HEAD`）で追加された行のみを
        走査する（Issue #258）。リポジトリのルートで実行すること。PATH 引数とは
        併用できない。削除行・文脈行・ハンクヘッダ・ファイルヘッダは走査しない。
        追加行は先頭の `+` を除去してから検出処理に渡し、元ファイル（新ファイル側）
        の行番号で報告する。出力パスは `git diff` が報告する相対パスをそのまま使う
        （basenameへの短縮はこのモードでは行わない）。
    scripts/check_no_personal_info.py --help
        使用法を表示する（終了コード 0）。

    ヒットした行は `ファイル名:行番号:行の内容` の形式で標準出力へ出す（Issue #257
    観測3の解消。ディレクトリ名は含めない）。異なる入力パスが同じファイル名を
    持つ場合に限り、`ファイル名#N`（N は入力順の1始まり番号）で区別する。
    （`--diff-base` モードはこの限りでない。上記参照）

終了コード（Issue #257 観測2の解消。既存の 0/1 の意味は変えていない）:
    0   ヒット 0 件（正常終了）。`--help` もここに含める
    1   ヒット 1 件以上（検出）
    2   利用者側の誤り（存在しないパス・読み取り不可・不正な引数）
    3   `--diff-base` の REF を解決できなかった（Issue #258）。スキップせず停止する

`scripts/verify.sh` への組み込みは本 Issue の範囲外（Issue #251「スコープ外」参照）。
`--diff-base` の CI・フックへの組み込みも本 Issue の範囲外（Issue #258）。
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_HIT = 1
EXIT_USAGE_ERROR = 2
EXIT_DIFF_BASE_UNRESOLVED = 3

# --- 検出パターン（テストからミューテーション対象として import される）-------------

# 1. ホームディレクトリを指す絶対パスの接頭辞。よくある接頭辞（POSIX 系の
#    ユーザディレクトリ、macOS のユーザディレクトリ、Windows のユーザディレクトリ）と、
#    その直後のユーザ名相当の 1 セグメントまでを掴む。
HOME_PREFIX_PATTERN = re.compile(
    r"(?:/home/|/Users/|[A-Za-z]:\\Users\\)[^/\\\s'\"]+"
)

# 2. メールアドレスの形。ローカル部・区切り記号（アットマーク）・ドメイン部。
EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)

# 3. 日本語の敬称。先行する名前らしい 1 文字（ひらがな・カタカナ・漢字）に続く
#    敬称を掴む。敬称トークンは捕捉グループにし、`_honorific_hit()` が一致位置を
#    `HONORIFIC_EXCLUDE_PATTERN` のスパンと突き合わせて誤検出を落とす。
#    パターン自身には否定後読みなどの抑止を持たせない（除外は語彙一覧で行う）。
HONORIFIC_PATTERN = re.compile(
    r"[ぁ-ゖァ-ヺ一-鿿](さん|ちゃん|くん|様|氏|君|殿|先生)"
)

# 敬称を表す一字（様・氏・君・殿）を末尾に含む一般語の一覧（誤検出の抑止 1）。
# HONORIFIC_PATTERN がこれらの語の内側でヒットした位置は数えない。
#
# 【限界】この一覧は有限の列挙であり、網羅性を保証しない。ここに載っていない
# 複合語（新たに見つかった「〇様」「〇氏」「〇君」「〇殿」の類）は誤検出として
# 残る。運用として、誤検出が判明するたびに語を追記する。
HONORIFIC_EXCLUDE_PATTERN = re.compile(
    r"仕様|同様|多様|一様|異様|態様|模様|様々|様子|様式|王様|神様|殿様|皆様|お客様"
    r"|摂氏|華氏|氏名|某氏|両氏|同氏|諸氏"
    r"|諸君|君主|君臨|主君|暴君"
    r"|宮殿|御殿|殿堂|沈殿|神殿|仏殿"
)

# 名前とパターンの対応。走査本体と、テストのミューテーション網羅確認で使う。
# honorific は検出時に HONORIFIC_EXCLUDE_PATTERN も参照する（_honorific_hit）。
DETECTION_PATTERNS = (
    ("home-path", HOME_PREFIX_PATTERN),
    ("email", EMAIL_PATTERN),
    ("honorific", HONORIFIC_PATTERN),
)

# --- 誤検出の抑止パターン（検出ではなく除外に使う）-------------------------------

# 区切り記号（アットマーク）を 2 つ並べて始まる行 = `git diff` のハンクヘッダ。
# ハンクヘッダの末尾にはセクション見出しが付き、そこに敬称やメール形が紛れ得る
# ため、行ごとスキップする（誤検出の抑止 2）。
# 行番号範囲2組と閉じの記号2つまで要求し、単に記号2つで始まるだけの非ハンクヘッダ行を
# 誤ってスキップしないようにする。
HUNK_HEADER_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def _honorific_hit(line):
    """名前らしい 1 文字＋敬称の一致のうち、除外語の内側でないものが 1 つでもあれば True。"""
    exclude_spans = [m.span() for m in HONORIFIC_EXCLUDE_PATTERN.finditer(line)]
    for m in HONORIFIC_PATTERN.finditer(line):
        token_start = m.start(1)
        if any(start <= token_start < end for start, end in exclude_spans):
            continue
        return True
    return False


def _line_has_hit(line):
    """1行に検出パターン（home-path/email/honorific）のいずれかが一致するか。

    `iter_hits`（ファイル・標準入力の走査）と `iter_diff_hits`（Issue #258、
    差分の追加行のみの走査）が共用する。1行判定の挙動はどちらの経路でも
    同一でなければならない（`iter_hits` の判定部分をここへ切り出したもの）。
    """
    return bool(
        HOME_PREFIX_PATTERN.search(line)
        or EMAIL_PATTERN.search(line)
        or _honorific_hit(line)
    )


def iter_hits(path, lines):
    """`lines` を 1 行ずつ走査し、ヒットした `(path, 行番号, 行の内容)` を返す。"""
    for lineno, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        if HUNK_HEADER_PATTERN.search(line):
            continue
        if _line_has_hit(line):
            yield path, lineno, line


def scan_path(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return list(iter_hits(path, text.splitlines()))


def scan_stdin(stream=None):
    stream = sys.stdin if stream is None else stream
    return list(iter_hits("<stdin>", stream.read().splitlines()))


# --- 差分限定モード（Issue #258）--------------------------------------------------

# `git diff --no-color` のファイルヘッダ行。新ファイル側のパス（b/ 以降）を
# 元ファイルの行番号報告に使う（障害1の解決）。
_DIFF_FILE_HEADER_RE = re.compile(r"^diff --git a/(?:.+) b/(.+)$")

# `git diff` のハンクヘッダ行。新ファイル側の開始行番号（+c の c）を取り出す。
# `-U0` 指定時は文脈行が出ないため、以降の `+` 行はこの値から単調増加する。
_DIFF_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def iter_diff_hits(diff_text):
    """`git diff --no-color -U0 REF...HEAD` の出力から、追加行のみを走査する。

    削除行（`-` 始まり）・文脈行・ハンクヘッダ・ファイルヘッダ（`diff --git`・
    `index`・`---`・`+++`）・「`\\ No newline at end of file`」行は走査しない
    （障害3の解決：削除行・非追加行を検出対象から外す）。追加行は先頭の `+` を
    除去してから `_line_has_hit()` に渡す（先頭記号自体が誤検出源にならない
    ようにする）。行番号はハンクヘッダから追跡した新ファイル側の行番号
    （障害1の解決：標準入力経由の走査に伴う行番号のズレを避ける）。
    """
    current_path = None
    new_lineno = None
    for raw_line in diff_text.splitlines():
        header_match = _DIFF_FILE_HEADER_RE.match(raw_line)
        if header_match:
            current_path = header_match.group(1)
            new_lineno = None
            continue
        hunk_match = _DIFF_HUNK_RE.match(raw_line)
        if hunk_match:
            new_lineno = int(hunk_match.group(1))
            continue
        if new_lineno is None and (
            raw_line.startswith("+++") or raw_line.startswith("---")
        ):
            # ファイルヘッダの2行目・1行目。ハンクヘッダ到達前（new_lineno未設定）
            # にしか現れない。ハンクヘッダ到達後の "+++"/"---" は本文の内容
            # （Markdownの水平線・frontmatter区切り等）であり、ファイルヘッダでは
            # ないため、ここでスキップしてはならない。
            continue
        if raw_line.startswith("\\"):
            continue  # "\ No newline at end of file"
        if raw_line.startswith("+"):
            if current_path is None or new_lineno is None:
                continue  # ハンクヘッダより前に追加行相当の行が来ることは無いが安全側
            content = raw_line[1:]
            if _line_has_hit(content):
                yield current_path, new_lineno, content
            new_lineno += 1
        elif raw_line.startswith("-"):
            continue  # 削除行。新ファイル側に存在しないので行番号は進めない
        # それ以外（-U0 では通常出現しない文脈行等）は無視する。


def _ref_exists(ref):
    """`ref` が現在のリポジトリで解決できるか（障害2の解決の前段）。"""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _git_diff_added_lines(ref):
    result = subprocess.run(
        ["git", "diff", "--no-color", "-U0", f"{ref}...HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def scan_diff_base(ref):
    """`--diff-base REF` の実処理。REFが解決できなければ `None` を返す。

    呼び出し側（`main`）が `None` を `EXIT_DIFF_BASE_UNRESOLVED` に対応づける。
    スキップして通過させない（障害2の解決）。
    """
    if not _ref_exists(ref):
        return None
    diff_text = _git_diff_added_lines(ref)
    return list(iter_diff_hits(diff_text))


def _build_parser():
    parser = argparse.ArgumentParser(
        description="個人情報・絶対パスの走査を行う CLI。",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="走査するファイル。省略時は標準入力を読む。",
    )
    parser.add_argument(
        "--diff-base",
        metavar="REF",
        default=None,
        help=(
            "REF との差分（git diff --no-color -U0 REF...HEAD）で追加された行のみを"
            "走査する。PATH 引数とは併用できない。"
        ),
    )
    return parser


def _error_reason(exc):
    """OSError からファイル名を含まない理由文字列だけを取り出す。

    `str(exc)` はエラー発生時に渡した引数（パス）をそのまま含むため、
    絶対パスで渡された場合に観測3と同じ漏洩経路になる。`strerror`
    （OS のエラー文字列。ファイル名を含まない）だけを使う。
    """
    return exc.strerror if getattr(exc, "strerror", None) else exc.__class__.__name__


def main(argv=None):
    # argparse は --help を自前で処理し、使用法を表示して終了コード 0 で
    # 終了する。不正なオプション・引数の場合は使用法をエラーとして標準
    # エラーへ出し、終了コード 2 で終了する（いずれも argparse の既定挙動）。
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.diff_base is not None:
        if args.paths:
            parser.error("--diff-base は PATH 引数と同時に指定できません。")
        hits = scan_diff_base(args.diff_base)
        if hits is None:
            print(
                f"{args.diff_base}: 参照を解決できませんでした"
                "（存在しない参照・浅いクローン等）。走査を実施していません。",
                file=sys.stderr,
            )
            return EXIT_DIFF_BASE_UNRESOLVED
        for path, lineno, line in hits:
            print(f"{path}:{lineno}:{line}")
        return 1 if hits else 0

    hits = []
    if args.paths:
        for path in args.paths:
            try:
                hits.extend(scan_path(path))
            except OSError as exc:
                # Issue #257 観測2: 存在しないパス・読み取り不可を「利用者側の
                # 誤り」として終了コード2に分離し、無捕捉例外のトレースバックは
                # 出さない。ヒットの有無（終了コード1）とは独立した経路にする。
                # メッセージは basename のみ（観測3: ディレクトリ名を含めない）。
                print(
                    f"{os.path.basename(path)}: 読み込めませんでした（{_error_reason(exc)}）",
                    file=sys.stderr,
                )
                return 2
    else:
        hits.extend(scan_stdin())

    # Issue #257 観測3: 出力パスは basename のみにする。ただし2つ以上の
    # 異なる入力パスが同じ basename を持つ場合に限り、該当する行だけへ
    # 入力順（args.paths内の1始まりの位置）の識別子 `#N` を付け、区別
    # できるようにする。ディレクトリ名・パス断片は識別子に含めない。
    # 衝突が無ければ基準どおり basename のみ（識別子は付かない）。
    order_index = {p: i + 1 for i, p in enumerate(args.paths)}
    basename_of = {}
    groups = {}
    for path, _lineno, _line in hits:
        b = path if path == "<stdin>" else os.path.basename(path)
        basename_of[path] = b
        groups.setdefault(b, set()).add(path)
    collided = {b for b, paths in groups.items() if len(paths) > 1}

    for path, lineno, line in hits:
        b = basename_of[path]
        display_path = f"{b}#{order_index.get(path, '?')}" if b in collided else b
        print(f"{display_path}:{lineno}:{line}")

    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
