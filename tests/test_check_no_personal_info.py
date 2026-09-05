"""scripts/check_no_personal_info.py のテスト（Issue #251）。

走査器そのものをリポジトリにコミットし、pytest だけで検証が完結するようにする。
検出 3 種（ホームディレクトリ絶対パス接頭辞・メールアドレスの形・日本語の敬称）と、
誤検出 2 種（複合語の末尾字への一致、ハンクヘッダの記号への一致）の抑止を固定する。

入力データはすべて架空の値（実在のアカウント名・ホスト名・人物に結びつかない）。

`scripts/` を `sys.path` へ差し込むと他のテストの import 解決に影響が残るため、
`importlib` でファイルパスから直接読み込む。
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_no_personal_info.py"

_SPEC = importlib.util.spec_from_file_location("check_no_personal_info", SCRIPT)
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)


# --- ヘルパ -----------------------------------------------------------------

def run_cli(args, stdin=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
    )


def hits_for(lines):
    """行のリストを走査し、ヒット行の内容だけを返す。"""
    return [line for _p, _n, line in checker.iter_hits("<test>", lines)]


# 手順1 で実測した入力。すべて敬称ではない一般語で、ヒットしないのが正しい。
COMMON_WORD_LINES = [
    "多様なパターン",
    "模様替えの案内",
    "王様のレストラン",
    "一様に分布する",
    "態様が異なる",
    "摂氏20度",
    "諸君の健闘を祈る",
    "宮殿の写真",
]

# 手順1 で実測した入力。いずれも敬称で、ヒットするのが正しい。
HONORIFIC_LINES = [
    "サンプル太郎さんへ",
    "テスト花子様より",
    "架空ノ介氏の発言",
]


# --- 検出 1: ホームディレクトリ絶対パス接頭辞 --------------------------------

def test_home_prefix_posix_detected():
    assert checker.HOME_PREFIX_PATTERN.search("/home/exampleuser/work/x.txt")
    assert hits_for(["cd /home/exampleuser/work"]) == ["cd /home/exampleuser/work"]


def test_home_prefix_macos_detected():
    assert checker.HOME_PREFIX_PATTERN.search("/Users/exampleuser/Desktop")


def test_home_prefix_windows_detected():
    assert checker.HOME_PREFIX_PATTERN.search(r"D:\Users\exampleuser\Documents")


def test_home_prefix_not_matched_on_generic_path():
    assert hits_for(["/usr/local/bin/python", "/var/log/app.log"]) == []


# --- 検出 2: メールアドレスの形 -------------------------------------------

def test_email_shape_detected():
    assert checker.EMAIL_PATTERN.search("contact fake.person@example.invalid please")
    assert hits_for(["author = someone@example.test"]) == [
        "author = someone@example.test"
    ]


def test_email_shape_requires_local_and_domain_parts():
    # 区切り記号だけ・ドメインの点が無い形はメールアドレスの形ではない。
    assert hits_for(["send @ now", "a@b no dot"]) == []


# --- 検出 3: 日本語の敬称 ------------------------------------------------

@pytest.mark.parametrize(
    "line",
    [
        "レビューはサンプル太郎さんが担当した",
        "テスト花子様よりご連絡",
        "架空ノ介氏の発言",
        "担当は仮名くん",
        "案内役の架空先生",
    ],
)
def test_honorific_detected(line):
    assert hits_for([line]) == [line]


@pytest.mark.parametrize("line", HONORIFIC_LINES)
def test_honorific_probe_inputs_are_detected(line):
    # 手順1 で見逃しゼロだった敬称入力を固定する。
    assert hits_for([line]) == [line]


# --- 誤検出の抑止 1: 敬称の一字が複合語の末尾字に一致する ------------------

def test_common_word_with_honorific_char_not_detected():
    lines = [
        "この仕様書は前回と同様に扱う",
        "模様替えのため一時休止",
        "異様な負荷がかかっていた",
    ]
    assert hits_for(lines) == []


@pytest.mark.parametrize("line", COMMON_WORD_LINES)
def test_honorific_probe_common_words_not_detected(line):
    # 手順1 で誤検出 7 件だった一般語を、抑止語彙で 1 件残らず落とすことを固定する。
    assert hits_for([line]) == []


def test_all_probe_common_words_produce_no_hit_in_one_pass():
    assert hits_for(COMMON_WORD_LINES) == []


def test_honorific_still_detected_next_to_common_word():
    # 抑止は複合語だけに効き、直後に本物の敬称が来れば拾う。
    line = "仕様を決めたのはサンプル太郎さんだ"
    assert hits_for([line]) == [line]


# --- 誤検出の抑止 2: ハンクヘッダ（区切り記号 2 つで始まる行）------------

def test_hunk_header_line_not_detected():
    # 抑止が無ければ末尾のメール形・敬称でヒットしてしまう行。
    lines = [
        "@@ -1,4 +1,6 @@ def notify(fake.person@example.invalid):",
        "@@ -10,3 +10,3 @@ class サンプル太郎さん:",
    ]
    assert hits_for(lines) == []


def test_hunk_header_pattern_requires_two_symbols_at_line_start():
    # 記号 1 つで始まる行や行頭以外は抑止対象ではない。
    line = "見積もりは someone@example.test に送る @@ 追記"
    assert hits_for([line]) == [line]


def test_hunk_header_pattern_requires_line_number_ranges_and_closing_symbols():
    # 行頭が記号2つだけで、行番号範囲・閉じの記号を伴わない非ハンクヘッダ行は
    # 抑止対象にならず、末尾の敬称形が検出される（架空データ）。
    line = "@@ 架空次郎様より"
    assert hits_for([line]) == [line]


def test_hunk_header_pattern_still_skips_well_formed_hunk_header():
    # 行番号範囲2組・閉じの記号2つを備えた正規のハンクヘッダ形は、
    # 厳格化後も従来どおり抑止対象のまま（既存の意図の維持確認、架空データ）。
    line = "@@ -3,2 +3,4 @@ def notify(fake.reviewer@example.invalid):"
    assert hits_for([line]) == []


# --- CLI としての振る舞い ---------------------------------------------------

def test_cli_exit_1_and_output_format_on_hit(tmp_path):
    target = tmp_path / "sample.txt"
    target.write_text(
        "clean line\n"
        "path is /home/exampleuser/x\n"
        "another clean line\n",
        encoding="utf-8",
    )
    proc = run_cli([str(target)])
    assert proc.returncode == 1
    assert proc.stdout == f"{target}:2:path is /home/exampleuser/x\n"


def test_cli_exit_0_on_clean_file(tmp_path):
    target = tmp_path / "clean.txt"
    target.write_text("nothing to see here\n/usr/bin/env\n", encoding="utf-8")
    proc = run_cli([str(target)])
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_cli_reads_stdin_when_no_args():
    proc = run_cli([], stdin="ok line\nmail someone@example.test here\n")
    assert proc.returncode == 1
    assert proc.stdout == "<stdin>:2:mail someone@example.test here\n"


def test_cli_scans_multiple_files(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("first\n/home/exampleuser/a\n", encoding="utf-8")
    b.write_text("only clean\nテスト花子様\n", encoding="utf-8")
    proc = run_cli([str(a), str(b)])
    assert proc.returncode == 1
    assert proc.stdout == (
        f"{a}:2:/home/exampleuser/a\n"
        f"{b}:2:テスト花子様\n"
    )


# --- CLI の終了コード体系（Issue #257 観測2の解消） ------------------------

def test_cli_help_exits_zero_and_shows_usage():
    # --help は argparse の既定挙動どおり終了コード0で使用法を表示する。
    proc = run_cli(["--help"])
    assert proc.returncode == 0
    assert "usage" in proc.stdout.lower()


def test_cli_nonexistent_path_exits_two_with_no_stdout_hits():
    # 存在しないパス（架空のファイル名）は利用者側の誤りとして終了コード2。
    # ヒットが無いのと区別するため、標準出力にヒット行を一切出さない。
    proc = run_cli(["no_such_file_for_test.txt"])
    assert proc.returncode == 2
    assert proc.stdout == ""


def test_cli_nonexistent_path_does_not_print_traceback():
    # 無捕捉例外によるトレースバックを出さず、1行のエラーメッセージのみ。
    proc = run_cli(["no_such_file_for_test.txt"])
    assert "Traceback" not in proc.stderr
    assert proc.stderr.count("\n") == 1


def test_cli_hit_still_exits_one(tmp_path):
    # ヒットありは従来どおり終了コード1のまま（既存の意味の維持確認、架空データ）。
    target = tmp_path / "sample.txt"
    target.write_text("clean\nテスト花子様より\n", encoding="utf-8")
    proc = run_cli([str(target)])
    assert proc.returncode == 1


# --- 検出パターン定数の公開 ----------------------------------------------

def test_detection_patterns_tuple_exposes_each_constant():
    named = dict(checker.DETECTION_PATTERNS)
    assert named["home-path"] is checker.HOME_PREFIX_PATTERN
    assert named["email"] is checker.EMAIL_PATTERN
    assert named["honorific"] is checker.HONORIFIC_PATTERN


def test_honorific_exclude_pattern_is_importable_and_covers_probe_words():
    # 抑止語彙は独立した定数で、手順1 の一般語をすべて含む。
    for word in ["多様", "模様", "王様", "一様", "態様", "摂氏", "諸君", "宮殿"]:
        assert checker.HONORIFIC_EXCLUDE_PATTERN.search(word), word
