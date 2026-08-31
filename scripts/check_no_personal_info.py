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

    ヒットした行は `パス:行番号:行の内容` の形式で標準出力へ出す。
    ヒットが 1 件以上なら終了コード 1、0 件なら 0。

`scripts/verify.sh` への組み込みは本 Issue の範囲外（Issue #251「スコープ外」参照）。
"""
import re
import sys
from pathlib import Path

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
HUNK_HEADER_PATTERN = re.compile(r"^@@")


def _honorific_hit(line):
    """名前らしい 1 文字＋敬称の一致のうち、除外語の内側でないものが 1 つでもあれば True。"""
    exclude_spans = [m.span() for m in HONORIFIC_EXCLUDE_PATTERN.finditer(line)]
    for m in HONORIFIC_PATTERN.finditer(line):
        token_start = m.start(1)
        if any(start <= token_start < end for start, end in exclude_spans):
            continue
        return True
    return False


def iter_hits(path, lines):
    """`lines` を 1 行ずつ走査し、ヒットした `(path, 行番号, 行の内容)` を返す。"""
    for lineno, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        if HUNK_HEADER_PATTERN.search(line):
            continue
        if (
            HOME_PREFIX_PATTERN.search(line)
            or EMAIL_PATTERN.search(line)
            or _honorific_hit(line)
        ):
            yield path, lineno, line


def scan_path(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return list(iter_hits(path, text.splitlines()))


def scan_stdin(stream=None):
    stream = sys.stdin if stream is None else stream
    return list(iter_hits("<stdin>", stream.read().splitlines()))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    hits = []
    if argv:
        for path in argv:
            hits.extend(scan_path(path))
    else:
        hits.extend(scan_stdin())

    for path, lineno, line in hits:
        print(f"{path}:{lineno}:{line}")

    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
