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

def run_cli(args, stdin=None, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
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
    assert proc.stdout == f"{target.name}:2:path is /home/exampleuser/x\n"


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
        f"{a.name}:2:/home/exampleuser/a\n"
        f"{b.name}:2:テスト花子様\n"
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


# --- CLI の出力パス（Issue #257 観測3の解消） ------------------------------

def test_cli_output_path_has_no_directory_name(tmp_path):
    # 絶対パスを渡しても、出力にはディレクトリ名が含まれずファイル名のみになる。
    target_dir = tmp_path / "架空ディレクトリ"
    target_dir.mkdir()
    target = target_dir / "sample.txt"
    target.write_text("clean\nテスト花子様より\n", encoding="utf-8")
    proc = run_cli([str(target)])
    assert proc.returncode == 1
    assert proc.stdout == "sample.txt:2:テスト花子様より\n"
    assert str(target_dir) not in proc.stdout


def test_cli_same_basename_in_different_dirs_gets_numbered(tmp_path):
    # 異なるディレクトリの同名ファイルは #N（入力順の1始まり）で区別される。
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()
    a = dir1 / "dup.txt"
    b = dir2 / "dup.txt"
    a.write_text("clean\nテスト花子様より（1つ目）\n", encoding="utf-8")
    b.write_text("clean\nテスト花子様より（2つ目）\n", encoding="utf-8")
    proc = run_cli([str(a), str(b)])
    assert proc.returncode == 1
    assert proc.stdout == (
        "dup.txt#1:2:テスト花子様より（1つ目）\n"
        "dup.txt#2:2:テスト花子様より（2つ目）\n"
    )


def test_cli_no_identifier_when_no_collision(tmp_path):
    # basename が衝突しない場合は識別子を付けない（架空データ）。
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()
    a = dir1 / "alpha.txt"
    b = dir2 / "beta.txt"
    a.write_text("clean\nテスト花子様より\n", encoding="utf-8")
    b.write_text("clean\n見積もりは someone@example.test に送る\n", encoding="utf-8")
    proc = run_cli([str(a), str(b)])
    assert proc.returncode == 1
    assert "#" not in proc.stdout
    assert proc.stdout == (
        "alpha.txt:2:テスト花子様より\n"
        "beta.txt:2:見積もりは someone@example.test に送る\n"
    )


def test_cli_read_error_message_has_no_directory_name(tmp_path):
    # 存在しないパスの標準エラーメッセージにもディレクトリ名を含めない。
    target_dir = tmp_path / "架空ディレクトリ"
    target = target_dir / "no_such_file.txt"
    proc = run_cli([str(target)])
    assert proc.returncode == 2
    assert "no_such_file.txt" in proc.stderr
    assert str(target_dir) not in proc.stderr


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


# --- 差分限定モード（Issue #258、--diff-base）--------------------------------

def _init_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    subprocess.run(
        ["git", "config", "user.email", "ci@example.invalid"],
        cwd=str(tmp_path), check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "ci"], cwd=str(tmp_path), check=True,
    )


def _commit_all(tmp_path, message):
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=str(tmp_path), check=True,
    )


def test_diff_hits_report_original_file_line_numbers_across_multiple_hunks():
    # 合成した git diff -U0 出力。2つのハンクにまたがってヒットが元ファイル
    # （新ファイル側）の行番号で報告されることを確認する。
    diff_text = (
        "diff --git a/sample.txt b/sample.txt\n"
        "index 1111111..2222222 100644\n"
        "--- a/sample.txt\n"
        "+++ b/sample.txt\n"
        "@@ -2,0 +3,2 @@\n"
        "+plain context line\n"
        "+/home/exampleuser/project\n"
        "@@ -9,0 +12,1 @@\n"
        "+contact: example@example.invalid\n"
    )
    hits = list(checker.iter_diff_hits(diff_text))
    assert hits == [
        ("sample.txt", 4, "/home/exampleuser/project"),
        ("sample.txt", 12, "contact: example@example.invalid"),
    ]


def test_diff_hits_do_not_false_positive_from_leading_plus_symbol():
    # ストリップ前の生の行（先頭+付き）なら EMAIL_PATTERN の local-part 文字
    # 集合に "+" が含まれるため誤ってヒットしてしまうことを、内部関数で示す。
    assert checker._line_has_hit("+@example.invalid") is True
    # 実際のファイル内容（先頭+を除去した後）には local-part が無く、ヒットしない。
    assert checker._line_has_hit("@example.invalid") is False

    diff_text = (
        "diff --git a/sample.txt b/sample.txt\n"
        "index 1111111..2222222 100644\n"
        "--- a/sample.txt\n"
        "+++ b/sample.txt\n"
        "@@ -1,0 +2,1 @@\n"
        "+@example.invalid\n"
    )
    assert list(checker.iter_diff_hits(diff_text)) == []


def test_diff_hits_skip_deleted_lines():
    # 削除行（- 始まり）に検出パターンが含まれていても走査対象にならない。
    diff_text = (
        "diff --git a/sample.txt b/sample.txt\n"
        "index 1111111..2222222 100644\n"
        "--- a/sample.txt\n"
        "+++ b/sample.txt\n"
        "@@ -3,1 +3,0 @@\n"
        "-/home/exampleuser/old-project\n"
    )
    assert list(checker.iter_diff_hits(diff_text)) == []


def test_cli_diff_base_unresolved_ref_exits_three(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "sample.txt").write_text("plain line\n", encoding="utf-8")
    _commit_all(tmp_path, "base")

    proc = run_cli(["--diff-base", "refs/heads/does-not-exist"], cwd=str(tmp_path))
    assert proc.returncode == 3
    assert proc.stdout == ""
    assert "does-not-exist" in proc.stderr


def test_cli_diff_base_reports_added_hit_with_original_line_number(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "sample.txt").write_text("line one\nline two\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_path), check=True, capture_output=True, text=True,
    ).stdout.strip()

    (tmp_path / "sample.txt").write_text(
        "line one\nline two\ncontact: example@example.invalid\n", encoding="utf-8",
    )
    _commit_all(tmp_path, "add a hit")

    proc = run_cli(["--diff-base", base_sha], cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stdout == "sample.txt:3:contact: example@example.invalid\n"


def test_cli_diff_base_rejects_combination_with_path_args(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "sample.txt").write_text("plain line\n", encoding="utf-8")
    _commit_all(tmp_path, "base")

    proc = run_cli(["--diff-base", "HEAD", "sample.txt"], cwd=str(tmp_path))
    assert proc.returncode == 2
    assert proc.stdout == ""
