"""scripts/review_proposer.sh のテスト。

ADR-014（docs/decisions/ADR-014-proposer-design.md）決定2・4・5に基づく起案役
1回分の呼び出しスクリプト。review_audit.shのreview_audit_process_result()と
同じ流儀で、claudeを実際に呼ばずシェル関数単位でpytestから検証する
（tests/test_review_audit.pyの前例に揃える）。

review_loop.shへの組み込み（ADR-014決定6）は別タスクであり、本テストは
render_prompt()・review_proposer_process_result()・ソースガードのみを対象と
する。
"""
import json
import subprocess

from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "review_proposer.sh"
PROMPT_TEMPLATE = Path(__file__).resolve().parent.parent / "scripts" / "review_proposer_prompt.md"


def _write_result_json(output_dir: Path, *, result: str, is_error: bool = False,
                        terminal_reason: str = "completed") -> None:
    (output_dir / "result.json").write_text(
        json.dumps(
            {
                "is_error": is_error,
                "terminal_reason": terminal_reason,
                "num_turns": 1,
                "total_cost_usd": 0.01,
                "permission_denials": [],
                "result": result,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _run_process_result(output_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; review_proposer_process_result "$2"',
         "_", str(SCRIPT), str(output_dir)],
        capture_output=True,
        text=True,
    )


def _run_render_prompt(template: Path, original: Path, review: Path, executor_allowed: str,
                        out_file: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; render_prompt "$2" "$3" "$4" "$5" "$6"',
         "_", str(SCRIPT), str(template), str(original), str(review), executor_allowed, str(out_file)],
        capture_output=True,
        text=True,
    )


# --- render_prompt() のテスト ----------------------------------------------

def test_render_prompt_substitutes_all_three_placeholders(tmp_path):
    """{{ORIGINAL_INSTRUCTION}}・{{REVIEW}}・{{EXECUTOR_ALLOWED}}の3つすべてが
    対応する値に置換される（Issue #225）。"""
    template = tmp_path / "template.md"
    template.write_text(
        "元の指示:\n{{ORIGINAL_INSTRUCTION}}\n\n監査結果:\n{{REVIEW}}\n\nツール:\n{{EXECUTOR_ALLOWED}}\n",
        encoding="utf-8",
    )
    original = tmp_path / "original.md"
    original.write_text("§3-Cの記述を更新せよ。\n", encoding="utf-8")
    review = tmp_path / "review.md"
    review.write_text("VERDICT: APPROVE_CONTINUE\n\nCONTRADICTIONS:\n- なし\n", encoding="utf-8")
    out_file = tmp_path / "prompt.txt"

    result = _run_render_prompt(template, original, review,
                                 "Read,Edit,Write,Glob,Grep,Bash(./scripts/verify.sh)", out_file)

    assert result.returncode == 0
    content = out_file.read_text(encoding="utf-8")
    assert "{{ORIGINAL_INSTRUCTION}}" not in content
    assert "{{REVIEW}}" not in content
    assert "{{EXECUTOR_ALLOWED}}" not in content
    assert "§3-Cの記述を更新せよ。" in content
    assert "VERDICT: APPROVE_CONTINUE" in content
    assert "Read,Edit,Write,Glob,Grep,Bash(./scripts/verify.sh)" in content


def test_render_prompt_does_not_cross_contaminate_placeholders(tmp_path):
    """ORIGINAL_INSTRUCTION・REVIEW・EXECUTOR_ALLOWEDの中身が互いに混入
    しない（置換の対応関係が正しいこと。Issue #225で3つに拡張）。"""
    template = tmp_path / "template.md"
    template.write_text("A:{{ORIGINAL_INSTRUCTION}}/B:{{REVIEW}}/C:{{EXECUTOR_ALLOWED}}", encoding="utf-8")
    original = tmp_path / "original.md"
    original.write_text("ORIGINAL_MARKER", encoding="utf-8")
    review = tmp_path / "review.md"
    review.write_text("REVIEW_MARKER", encoding="utf-8")
    out_file = tmp_path / "prompt.txt"

    result = _run_render_prompt(template, original, review, "EXECUTOR_ALLOWED_MARKER", out_file)

    assert result.returncode == 0
    content = out_file.read_text(encoding="utf-8")
    assert content == "A:ORIGINAL_MARKER/B:REVIEW_MARKER/C:EXECUTOR_ALLOWED_MARKER"


def test_real_prompt_template_has_all_placeholders():
    """実際にscripts/review_proposer_prompt.mdを使う場合の回帰確認:
    3つのプレースホルダが実ファイルにリテラルで存在すること（Issue #225で
    {{EXECUTOR_ALLOWED}}を追加）。"""
    content = PROMPT_TEMPLATE.read_text(encoding="utf-8")
    assert "{{ORIGINAL_INSTRUCTION}}" in content
    assert "{{REVIEW}}" in content
    assert "{{EXECUTOR_ALLOWED}}" in content
    assert "NO_FURTHER_ACTION" in content


# --- review_proposer_process_result() のテスト ------------------------------

def test_result_json_missing_returns_exit_2(tmp_path):
    """result.jsonが存在しない（claude呼び出し自体の失敗を模す）ならexit 2。"""
    result = _run_process_result(tmp_path)
    assert result.returncode == 2
    assert not (tmp_path / "next_instruction.md").exists()


def test_is_error_true_returns_exit_2(tmp_path):
    """is_errorがtrueならexit 2、next_instruction.mdは作られない。"""
    _write_result_json(
        tmp_path,
        result="実行役への指示文。",
        is_error=True,
        terminal_reason="max_turns",
    )
    result = _run_process_result(tmp_path)
    assert result.returncode == 2
    assert not (tmp_path / "next_instruction.md").exists()
    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["is_error"] is True


def test_empty_result_field_does_not_exit_normally(tmp_path):
    """resultフィールドが空文字列のときはexit 0にならない（出力形式不正として
    扱われる）。jq の `//` は空文字列("")をnull/falseと区別せず真値として扱う
    ため、単純な `.result // empty` とファイルサイズだけの判定ではこのケースを
    検出できない、という具体的な回帰を防ぐためのテスト。"""
    _write_result_json(tmp_path, result="")
    result = _run_process_result(tmp_path)
    assert result.returncode == 3
    assert result.returncode != 0
    assert not (tmp_path / "next_instruction.md").exists()


def test_normal_instruction_returns_exit_0(tmp_path):
    """具体的な指示文が返ってきた通常ケースはexit 0で、次のinstructionとして
    書き出される。"""
    _write_result_json(tmp_path, result="docs/foo.mdのXX節を実態に合わせて修正せよ。")
    result = _run_process_result(tmp_path)
    assert result.returncode == 0
    content = (tmp_path / "next_instruction.md").read_text(encoding="utf-8")
    assert content.strip() == "docs/foo.mdのXX節を実態に合わせて修正せよ。"
    assert "NO_FURTHER_ACTION" not in result.stderr


def test_no_further_action_marker_returns_exit_0_and_is_logged(tmp_path):
    """1行目がNO_FURTHER_ACTIONのときもexit 0（正常な出力の一種）で、
    その旨がstderrに出る。"""
    _write_result_json(
        tmp_path,
        result="NO_FURTHER_ACTION\n本来の目的（§3-Cの更新）は既に達成されている。",
    )
    result = _run_process_result(tmp_path)
    assert result.returncode == 0
    content = (tmp_path / "next_instruction.md").read_text(encoding="utf-8")
    assert content.splitlines()[0] == "NO_FURTHER_ACTION"
    assert "NO_FURTHER_ACTION" in result.stderr


def test_no_further_action_marker_must_be_exact_first_line(tmp_path):
    """NO_FURTHER_ACTIONが1行目に完全一致でない（前後に文字が付く）場合は
    マーカーとして認識されない（通常の指示文として扱われる）。"""
    _write_result_json(
        tmp_path,
        result="NO_FURTHER_ACTIONです。次にやることはありません。",
    )
    result = _run_process_result(tmp_path)
    assert result.returncode == 0
    assert "起案役は追加の作業が無い" not in result.stderr


# --- ソースガードのテスト ----------------------------------------------------

def test_source_guard_does_not_run_main(tmp_path):
    """スクリプトをsourceしただけではmain()が実行されない（usageエラー等の
    副作用が起きない）。"""
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; echo SOURCED_OK', "_", str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "SOURCED_OK" in result.stdout
    assert "usage:" not in result.stderr
    assert "review_proposer.sh:" not in result.stderr


def test_running_as_script_with_no_args_shows_usage(tmp_path):
    """（対照実験）直接実行した場合は引数不足でusageが表示されexit 64になる
    ことを確認し、上のソースガードテストが「何もしていないだけ」でないこと
    を示す。"""
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 64
    assert "usage:" in result.stderr


def test_running_as_script_with_five_args_shows_usage(tmp_path):
    """引数が5個（4個の上限を超える）ならusageが表示されexit 64になる
    （Issue #225で3個必須から3個または4個へ変わったことの確認）。"""
    result = subprocess.run(
        ["bash", str(SCRIPT), "a", "b", "c", "d", "e"], capture_output=True, text=True
    )
    assert result.returncode == 64
    assert "usage:" in result.stderr


def test_running_as_script_with_four_args_passes_arg_count_check(tmp_path):
    """引数4個（executor-allowed-tools込み）はusageエラーにならない
    （実在しないoriginal-instruction-fileで止まるため、64ではなく1になる。
    Issue #225）。"""
    result = subprocess.run(
        ["bash", str(SCRIPT), "/no/such/original.md", "/no/such/review.md",
         str(tmp_path), "Read,Edit,Write,Glob,Grep,Bash(./scripts/verify.sh)"],
        capture_output=True, text=True,
    )
    assert result.returncode != 64
    assert "usage:" not in result.stderr
