"""scripts/check_review_comment.sh のテスト。

このスクリプトは Claude PR Review（Phase 5 Step 1）のトラッキング
コメント本文を検査するロジックを .github/workflows/ の外へ切り出した
もの（ADR-006 作業9-1。この領域は Claude Code へ deny されておりテストが
書けないため）。

テスト方式として pytest から subprocess でシェルスクリプトを呼ぶ形を選んだ。
理由: このリポジトリの既存テストはすべて pytest（bats 等の別ツールは
requirements-dev.txt に無く、新規導入するコストに見合わない）。
`./scripts/verify.sh` は `python -m pytest -q` を実行するだけなので、
`tests/` 配下に置けば追加の配線なしで verify.sh に含まれる。
"""
import subprocess

import pytest

from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_review_comment.sh"

# anthropics/claude-code-action の updateCommentBody() を機械的にトレースして
# 確認した、Claudeが update_claude_comment を一度も呼ばなかった場合の
# 実際の最終コメント本文（ADR-006参照）。
UNTOUCHED_BODY = (
    "**Claude finished @someuser's task in 12s** "
    "—— [View job](https://github.com/o/r/actions/runs/456)\n"
    "\n---\n"
    "I'll analyze this and get back to you."
)

PLAUSIBLE_REVIEW_BODY = (
    "**Claude finished @someuser's task in 48s** "
    "—— [View job](https://github.com/o/r/actions/runs/456)\n"
    "\n---\n"
    "## 指摘1\n"
    "- 該当箇所: comic_checker/wikipedia_client.py:120\n"
    "- 期待される挙動: 記事が見つからない場合は判定不能として扱う\n"
    "- 実際に起きること: except節が広すぎて例外を握りつぶし、常に完結扱いになる\n"
    "- 根拠: diffの125行目でexcept Exceptionにしている\n"
    "- 最小の修正案: except HTTPError等の具体的な例外に絞る\n"
)


def _run(body: str, use_file: bool, tmp_path) -> subprocess.CompletedProcess:
    if use_file:
        p = tmp_path / "body.txt"
        p.write_text(body, encoding="utf-8")
        return subprocess.run(
            ["bash", str(SCRIPT), str(p)],
            capture_output=True,
            text=True,
        )
    return subprocess.run(
        ["bash", str(SCRIPT)],
        input=body,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("use_file", [False, True], ids=["stdin", "file_arg"])
def test_untouched_placeholder_is_rejected(use_file, tmp_path):
    """(a) 未更新時の実際の本文 -> exit 1"""
    result = _run(UNTOUCHED_BODY, use_file, tmp_path)
    assert result.returncode == 1
    assert "プレースホルダ" in result.stderr


def test_short_body_is_rejected(tmp_path):
    """(b) 短い本文 -> exit 2"""
    body = "**Claude finished @user's task** —— [View job](url)\n\n---\n問題ありません。"
    result = _run(body, False, tmp_path)
    assert result.returncode == 2
    assert "短すぎます" in result.stderr


def test_plausible_review_is_accepted(tmp_path):
    """(c) 実際のレビュー文を模した十分な長さの本文 -> exit 0"""
    result = _run(PLAUSIBLE_REVIEW_BODY, False, tmp_path)
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_empty_body_is_rejected(tmp_path):
    """完全に空の本文(ghのjqが該当コメントを見つけられず`// \"\"`で
    フォールバックしたケースを想定) -> exit 2。fail-closedで、
    誤ってexit 0(通過)にならないことを固定する(作業10-2)。
    """
    result = _run("", False, tmp_path)
    assert result.returncode == 2
    assert "短すぎます" in result.stderr


def test_missing_separator_is_treated_as_empty_content(tmp_path):
    """(d) 区切り線(---)が無い本文の挙動を定義する。

    区切り線が見つからない場合はCONTENTを空とみなし、fail-closedで
    短すぎる(exit 2)として扱う(スクリプト内コメント参照)。
    """
    body = "**Claude finished @user's task** —— [View job](url)"
    result = _run(body, False, tmp_path)
    assert result.returncode == 2


def test_threshold_boundary_just_below_passes_as_too_short(tmp_path):
    """MIN_LENGTH(50文字)の境界: 49文字はexit 2。

    この定数を書き換えても検出できるように、境界そのものをテストで
    固定する(CLAUDE.mdの「定数を変異させたら落ちることを確認する」の
    対象になる)。
    """
    content = "あ" * 49
    body = f"header —— link\n\n---\n{content}"
    result = _run(body, False, tmp_path)
    assert result.returncode == 2


def test_threshold_boundary_at_exactly_min_length_passes(tmp_path):
    """MIN_LENGTH(50文字)の境界: 50文字はexit 0。"""
    content = "あ" * 50
    body = f"header —— link\n\n---\n{content}"
    result = _run(body, False, tmp_path)
    assert result.returncode == 0


def test_placeholder_check_takes_priority_over_length(tmp_path):
    """プレースホルダ残骸があれば、本文が十分長くてもexit 1が優先される。"""
    body = (
        "header —— link\n\n---\n"
        "I'll analyze this and get back to you."
        + "あ" * 100
    )
    result = _run(body, False, tmp_path)
    assert result.returncode == 1
