"""scripts/check_title_leak.py のテスト。

ERRORS.md の漏洩系記録（`docs/errors_md_inventory.md` No.50・51・54・60・63・
65〜73）の再発防止として新設した走査器のテスト。`--dict-file` と架空の作品名
だけを使い、実在の作品名はテストコードに書かない。

`scripts/` を `sys.path` へ差し込むと他のテストの import 解決に影響が残るため、
`importlib` でファイルパスから直接読み込む（test_check_no_personal_info.py と
同じ方式）。
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_title_leak.py"

_SPEC = importlib.util.spec_from_file_location("check_title_leak", SCRIPT)
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)


def run_cli(args, stdin=None, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def write_dict(tmp_path, titles, name="dict.json"):
    path = tmp_path / name
    path.write_text(json.dumps(titles, ensure_ascii=False), encoding="utf-8")
    return path


def write_draft(tmp_path, lines, name="draft.txt"):
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- 4文字以上: 検出、終了コード1 -------------------------------------------

def test_four_char_match_is_detection_and_exit_1(tmp_path):
    dict_path = write_dict(tmp_path, ["架空作品名"])
    draft = write_draft(tmp_path, ["この行には架空作品名が含まれる"])

    result = run_cli(["--dict-file", str(dict_path), str(draft)])

    assert result.returncode == 1
    assert "検出（5文字）" in result.stderr


# --- 2〜3文字: 警告のみ、終了コード0 ----------------------------------------

def test_two_to_three_char_match_is_warning_only_and_exit_0(tmp_path):
    dict_path = write_dict(tmp_path, ["架空作", "架空"])
    draft = write_draft(
        tmp_path, ["架空作を含む行", "架空を含む行", "無関係な行"]
    )

    result = run_cli(["--dict-file", str(dict_path), str(draft)])

    assert result.returncode == 0
    assert "警告（3文字）" in result.stderr
    assert "警告（2文字）" in result.stderr
    assert "検出" not in result.stderr


# --- 1文字: 照合しない --------------------------------------------------------

def test_one_char_entry_is_never_matched(tmp_path):
    dict_path = write_dict(tmp_path, ["架"])
    draft = write_draft(tmp_path, ["架を含む行"])

    result = run_cli(["--dict-file", str(dict_path), str(draft)])

    assert result.returncode == 0
    assert result.stderr == ""


# --- 出力に作品名が含まれない -------------------------------------------------

def test_output_never_contains_the_matched_title(tmp_path):
    dict_path = write_dict(tmp_path, ["架空作品名四文字"])
    draft = write_draft(tmp_path, ["この行には架空作品名四文字が含まれる"])

    result = run_cli(["--dict-file", str(dict_path), str(draft)])

    assert "架空作品名四文字" not in result.stdout
    assert "架空作品名四文字" not in result.stderr


# --- 存在しない入力: 終了コード2 ---------------------------------------------

def test_nonexistent_input_is_usage_error(tmp_path):
    dict_path = write_dict(tmp_path, ["架空作品名"])

    result = run_cli(
        ["--dict-file", str(dict_path), str(tmp_path / "does-not-exist.txt")]
    )

    assert result.returncode == 2


# --- 辞書ファイルが不正・空: 終了コード3（fail-closed） -----------------------

def test_malformed_dict_file_is_dict_load_error(tmp_path):
    dict_path = tmp_path / "bad.json"
    dict_path.write_text("not json", encoding="utf-8")
    draft = write_draft(tmp_path, ["何か"])

    result = run_cli(["--dict-file", str(dict_path), str(draft)])

    assert result.returncode == 3


def test_empty_dict_file_is_dict_load_error(tmp_path):
    dict_path = write_dict(tmp_path, [])
    draft = write_draft(tmp_path, ["何か"])

    result = run_cli(["--dict-file", str(dict_path), str(draft)])

    assert result.returncode == 3


def test_dict_file_with_non_string_element_is_dict_load_error(tmp_path):
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(["架空作品名", 1]), encoding="utf-8")
    draft = write_draft(tmp_path, ["何か"])

    result = run_cli(["--dict-file", str(dict_path), str(draft)])

    assert result.returncode == 3


# --- 標準入力で動く ------------------------------------------------------------

def test_reads_from_stdin_when_no_paths_given(tmp_path):
    dict_path = write_dict(tmp_path, ["架空作品名"])

    result = run_cli(
        ["--dict-file", str(dict_path)],
        stdin="この行には架空作品名が含まれる\n",
    )

    assert result.returncode == 1
    assert "<stdin>:1: 検出（5文字）" in result.stderr


# --- 実際の定数表で辞書を読み込めること -----------------------------------------

def test_builtin_dictionary_loads_a_nonempty_set():
    titles = checker.load_builtin_dictionary()

    assert titles is not None
    assert len(titles) > 0
