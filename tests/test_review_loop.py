"""scripts/review_loop.sh のブランチ検査のテスト。

review_loop.sh はADR-011（docs/decisions/ADR-011-review-loop-design.md）段階0の
オーケストレータで、実行役・監査役の実際のclaude呼び出しを含むため、work_loop.sh
と同様に全体をpytestで自動実行することはできない（実ネットワークI/O・課金を伴う）。

ここでテストするのは、mainブランチ上での実行を拒否するブランチ検査だけである。
review_loop.shはmain()関数やソースガードを持たない線形スクリプトのため、
review_audit.shのようにsourceして関数単体を呼ぶことはできない。代わりに、
一時的なローカルgitリポジトリ（本物のcomic_checkerリポジトリとは無関係）を
作り、そのディレクトリをcwdにしてスクリプトをsubprocessで実際に起動する。
ブランチ検査は最初のgit呼び出し（git rev-parse --abbrev-ref HEAD）を、
スクリプト自身がREPO_ROOTへcdする前に、呼び出し元のcwdに対して行う設計に
なっているため、これが成立する。claudeの呼び出しには到達しない
（main上では検査で止まり、main以外の場合も存在しないinstruction-fileの
チェックで止まるようにテストしている）。
"""
import subprocess

from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "review_loop.sh"


def _init_repo(repo_dir: Path, branch: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo_dir, check=True)
    (repo_dir / "placeholder.txt").write_text("placeholder\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo_dir, check=True)


def _run_review_loop(repo_dir: Path, instruction_file: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), str(instruction_file)],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )


def test_refuses_to_run_on_main_branch(tmp_path):
    """mainブランチ上ではブランチ検査でexit 1になり、instruction-fileの
    存在チェックにすら到達しない（claudeも一切呼ばれない）。"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo(repo_dir, "main")

    result = _run_review_loop(repo_dir, tmp_path / "does-not-exist.md")

    assert result.returncode == 1
    assert "main 上で実行しています" in result.stderr
    assert "instruction-file が存在しません" not in result.stderr


def test_passes_branch_check_on_non_main_branch(tmp_path):
    """main以外のブランチではブランチ検査を通過し、次のチェック
    （instruction-fileの存在確認）まで進む（＝ブランチ検査自体はブロックしない）。"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo(repo_dir, "fix/some-topic")

    result = _run_review_loop(repo_dir, tmp_path / "does-not-exist.md")

    assert result.returncode == 1
    assert "main 上で実行しています" not in result.stderr
    assert "instruction-file が存在しません" in result.stderr
