"""scripts/check_errors_inventory.sh のテスト。

このスクリプトは docs/errors_md_inventory.md（ERRORS.md の棚卸し分析文書、
作成 2026-08-23）の統計表の記載値が、現行の ERRORS.md の実測値と乖離して
いないかを機械的に検出する（Issue #193 の前提整備）。Issue #193 作業内容1
（No.3 の見出し分割）に伴い、棚卸し文書の統計値（総行数・見出し数）を実測へ
更新済みのため、現時点では引数なし実行は「終了コード0で一致するのが正常」。
以後、この一致が崩れたら落ちる常設のゲートとして機能する。

乖離時の挙動（標準エラーへの記載値・実測値の出力）はフィクスチャ（tmp_path
に書き出すダミーの ERRORS.md / inventory）で検証し、実リポジトリの値には
依存しない。

テスト方式は tests/test_check_review_comment.py と同じく pytest から
subprocess でシェルスクリプトを呼ぶ形。bats 等は requirements-dev.txt に無く、
tests/ 配下に置けば ./scripts/verify.sh に追加配線なしで含まれる。
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_errors_inventory.sh"
ERRORS_MD = REPO_ROOT / "ERRORS.md"
INVENTORY_MD = REPO_ROOT / "docs" / "errors_md_inventory.md"


def _run(env_overrides=None):
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
    )


def _write_dummy(tmp_path, total_lines_value, headings_value):
    """実測すると 5 行・見出し 2 件になるダミー ERRORS.md と、
    統計表だけを持つダミー inventory を書き出す。
    引数の *_value は inventory の統計表に書き込む数値。
    """
    errors = tmp_path / "ERRORS.md"
    errors.write_text(
        "## first heading\n"
        "body line\n"
        "## second heading\n"
        "another line\n"
        "last line\n",
        encoding="utf-8",
    )
    inventory = tmp_path / "inventory.md"
    inventory.write_text(
        "# dummy inventory\n"
        "\n"
        "| 項目 | 値 |\n"
        "|---|---|\n"
        f"| 総行数 | {total_lines_value}行 |\n"
        f"| 見出し数（`## `） | {headings_value}件 |\n",
        encoding="utf-8",
    )
    return {"ERRORS_MD": str(errors), "INVENTORY_MD": str(inventory)}


def test_repo_stats_are_in_sync():
    """棚卸し文書の統計値が ERRORS.md の実測からずれたら落ちる常設のゲート。
    引数なし・実リポジトリ入力では、統計値が一致し終了コード0となるべき。
    """
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "OK", proc.stdout + proc.stderr


def test_stderr_contains_doc_and_actual_values_on_mismatch(tmp_path):
    """乖離時の標準エラーに、棚卸し文書の記載値と実測値の両方が出る。

    実リポジトリの値には依存せず、tmp_path に書き出したフィクスチャで
    見出し数を意図的に食い違わせて検証する（期待値はリテラル）。
    """
    env = _write_dummy(tmp_path, total_lines_value="5", headings_value="99")
    proc = _run(env)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "見出し数" in proc.stderr, proc.stderr
    assert "99" in proc.stderr, proc.stderr
    assert "2" in proc.stderr, proc.stderr


def test_matching_dummy_inputs_exit_zero(tmp_path):
    """実測値と記載値が一致するダミー入力では OK / 終了コード 0。"""
    env = _write_dummy(tmp_path, total_lines_value="5", headings_value="2")
    proc = _run(env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "OK"


def test_single_stat_mismatch_dummy_exits_nonzero(tmp_path):
    """ダミーの統計値を 1 項目だけ食い違わせると非ゼロ終了する。"""
    env = _write_dummy(tmp_path, total_lines_value="999", headings_value="2")
    proc = _run(env)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    # 「項目 / 記載値 / 実測値」の形で食い違いが出る。
    assert "総行数" in proc.stderr, proc.stderr
    assert "999" in proc.stderr and "5" in proc.stderr, proc.stderr


def test_does_not_modify_repo_files(tmp_path):
    """引数なし実行後もリポジトリ本体の ERRORS.md / inventory は不変。"""
    before_errors = ERRORS_MD.read_bytes()
    before_inventory = INVENTORY_MD.read_bytes()
    _run()
    assert ERRORS_MD.read_bytes() == before_errors
    assert INVENTORY_MD.read_bytes() == before_inventory
