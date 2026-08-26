"""scripts/review_audit.sh の review_audit_process_result() のテスト。

このスクリプトはADR-011（docs/decisions/ADR-011-review-loop-design.md）の
監査役1回分の呼び出しを行うもので、`review_audit_process_result()` は
claude実行後のresult.jsonからVERDICTを抽出する部分をシェル関数として
切り出してある（.github/workflows/内はClaude Codeへdenyされておりテストが
書けないため、test_check_review_comment.py・test_select_review_comment.pyと
同じ理由でpytestからsubprocessでシェルスクリプトを呼ぶ形にしている）。

claudeは実際には呼ばない。偽のresult.jsonをfixtureとして用意し、関数へ直接
食わせる。`bash -c 'source "$1"; review_audit_process_result "$2"' _ <script> <dir>`
という形で呼ぶことで、review_audit.shのソースガード（BASH_SOURCE比較）に
より`main`は実行されず、関数だけが呼ばれる。
"""
import json
import subprocess

from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "review_audit.sh"


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
        ["bash", "-c", 'source "$1"; review_audit_process_result "$2"',
         "_", str(SCRIPT), str(output_dir)],
        capture_output=True,
        text=True,
    )


def test_verdict_not_in_four_values_returns_exit_3(tmp_path):
    """(1) VERDICT行が4値以外（FOOBAR）ならexit 3、verdict.txtは作られない。"""
    _write_result_json(tmp_path, result="VERDICT: FOOBAR\n\nCONTRADICTIONS:\n- なし\n")
    result = _run_process_result(tmp_path)
    assert result.returncode == 3
    assert not (tmp_path / "verdict.txt").exists()


def test_verdict_line_missing_returns_exit_3(tmp_path):
    """(2) VERDICT行が存在しないならexit 3、verdict.txtは作られない。"""
    _write_result_json(tmp_path, result="CONTRADICTIONS:\n- なし\n\nFOLLOWUPS:\n- なし\n")
    result = _run_process_result(tmp_path)
    assert result.returncode == 3
    assert not (tmp_path / "verdict.txt").exists()


def test_verdict_keyword_in_body_but_not_first_line_returns_exit_3(tmp_path):
    """(3) 本文中にAPPROVE_CONTINUEを含むが1行目には無いならexit 3（誤検出しない）。"""
    _write_result_json(
        tmp_path,
        result=(
            "CONTRADICTIONS:\n- なし\n\n"
            "FOLLOWUPS:\n- 本来はAPPROVE_CONTINUEにすべきだが1行目には書かない\n"
        ),
    )
    result = _run_process_result(tmp_path)
    assert result.returncode == 3
    assert not (tmp_path / "verdict.txt").exists()


def test_is_error_true_returns_exit_2(tmp_path):
    """(4) is_errorがtrueならexit 2、verdict.txtは作られない。"""
    _write_result_json(
        tmp_path,
        result="VERDICT: APPROVE_CONTINUE\n\nCONTRADICTIONS:\n- なし\n",
        is_error=True,
        terminal_reason="max_turns",
    )
    result = _run_process_result(tmp_path)
    assert result.returncode == 2
    assert not (tmp_path / "verdict.txt").exists()


def test_verdict_approve_continue_returns_exit_0(tmp_path):
    """(5) 1行目がVERDICT: APPROVE_CONTINUEならexit 0、verdict.txtにその値。"""
    _write_result_json(tmp_path, result="VERDICT: APPROVE_CONTINUE\n\nCONTRADICTIONS:\n- なし\n")
    result = _run_process_result(tmp_path)
    assert result.returncode == 0
    assert (tmp_path / "verdict.txt").read_text(encoding="utf-8").strip() == "APPROVE_CONTINUE"


def test_verdict_revise_returns_exit_0(tmp_path):
    """(6) 1行目がVERDICT: REVISEならexit 0、verdict.txtにその値。"""
    _write_result_json(tmp_path, result="VERDICT: REVISE\n\nCONTRADICTIONS:\n- 何か\n")
    result = _run_process_result(tmp_path)
    assert result.returncode == 0
    assert (tmp_path / "verdict.txt").read_text(encoding="utf-8").strip() == "REVISE"


def test_verdict_halt_needs_human_returns_exit_0(tmp_path):
    """(7) 1行目がVERDICT: HALT_NEEDS_HUMANならexit 0、verdict.txtにその値。"""
    _write_result_json(tmp_path, result="VERDICT: HALT_NEEDS_HUMAN\n\nCONTRADICTIONS:\n- なし\n")
    result = _run_process_result(tmp_path)
    assert result.returncode == 0
    assert (tmp_path / "verdict.txt").read_text(encoding="utf-8").strip() == "HALT_NEEDS_HUMAN"


def test_verdict_done_returns_exit_0(tmp_path):
    """(8) 1行目がVERDICT: DONEならexit 0、verdict.txtにその値。"""
    _write_result_json(tmp_path, result="VERDICT: DONE\n\nCONTRADICTIONS:\n- なし\n")
    result = _run_process_result(tmp_path)
    assert result.returncode == 0
    assert (tmp_path / "verdict.txt").read_text(encoding="utf-8").strip() == "DONE"
