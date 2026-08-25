"""scripts/select_review_comment.sh のテスト。

このスクリプトは claude-review.yml のトラッキングコメントを、PRの
コメント一覧JSON配列から特定するロジックを .github/workflows/ の外へ
切り出したもの（ADR-006 作業12-2）。test_check_review_comment.py と
同じ理由でpytestからsubprocessで呼ぶ形にしている。
"""
import json
import subprocess

from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "select_review_comment.sh"

RUN_ID = "123456789"


def _run(comments: list, run_id: str = RUN_ID) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), run_id],
        input=json.dumps(comments),
        capture_output=True,
        text=True,
    )


def _comment(login: str, body: str) -> dict:
    return {"author": {"login": login}, "body": body}


def test_finds_by_run_id_primary_path():
    """(a) run_idを含むコメントがあれば、それを1次経路で採用する。"""
    comments = [
        _comment("someone", "無関係なコメント"),
        _comment("other-bot[bot]", f"**Claude finished** —— [View job](https://github.com/o/r/actions/runs/{RUN_ID})\n\n---\n本文"),
    ]
    result = _run(comments)
    assert result.returncode == 0
    assert "本文" in result.stdout
    assert "1次経路" in result.stderr


def test_falls_back_to_bot_name_when_no_run_id_match():
    """(b) run_id一致が無ければ、bot名の最新コメントへフォールバックする。"""
    comments = [
        _comment("someone", "無関係なコメント"),
        _comment("github-actions[bot]", "プレースホルダのまま"),
    ]
    result = _run(comments)
    assert result.returncode == 0
    assert "プレースホルダのまま" in result.stdout
    assert "2次経路" in result.stderr


def test_fails_closed_when_neither_matches():
    """(c) どちらの経路でも見つからなければ exit 2 で落ちる。"""
    comments = [
        _comment("someone", "無関係なコメント"),
        _comment("other-bot[bot]", "別のワークフローのコメント"),
    ]
    result = _run(comments)
    assert result.returncode == 2
    assert "特定できませんでした" in result.stderr
    assert result.stdout == ""


def test_run_id_match_takes_priority_over_bot_name():
    """(d) 両方の経路で候補があっても、1次経路(run_id一致)が優先される。

    bot名一致のコメントは別のrunの残骸である可能性があるため、
    このrun固有のrun_id一致を優先する設計を固定する。
    """
    comments = [
        _comment("github-actions[bot]", "別のrunのプレースホルダ残骸"),
        _comment("github-actions[bot]", f"今回のrunの本文 [View job](https://.../actions/runs/{RUN_ID})"),
    ]
    result = _run(comments)
    assert result.returncode == 0
    assert "今回のrunの本文" in result.stdout
    assert "1次経路" in result.stderr


def test_multiple_run_id_matches_takes_last():
    """(e) run_id一致が複数あれば最後の1件を採る。"""
    comments = [
        _comment("a", f"1件目 actions/runs/{RUN_ID}"),
        _comment("b", f"2件目(最新) actions/runs/{RUN_ID}"),
    ]
    result = _run(comments)
    assert result.returncode == 0
    assert "2件目" in result.stdout


def test_missing_run_id_argument_is_usage_error():
    """(f) run_id引数が無ければ exit 1(使い方の誤り)。"""
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input=json.dumps([_comment("github-actions[bot]", "x")]),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "使い方" in result.stderr


def test_empty_comments_list_fails_closed():
    """コメントが1件も無いPR(実行直後等)でも fail-closed で exit 2。"""
    result = _run([])
    assert result.returncode == 2


# --- ここから実データによる検証（Issue #93） -------------------------------
#
# 出所: ~/comic_checker-agent-notes/pr90_comments.json・pr92_comments.json
# （過去の claude-review.yml 実測時に `gh pr view --json comments` で取得した
# 実データ。リポジトリ外の作業ディレクトリにあり、このリポジトリの
# バージョン管理対象ではない）。
#
# 個人名（GitHubアカウント名）除去について: 元データの body には
# `@giant-shrimp`（アカウント名へのメンション）と
# `github.com/giant-shrimp/comic_checker`（URLパス中のアカウント名）が
# 含まれていたため、いずれも `@USERNAME` / `github.com/OWNER/REPO` の
# プレースホルダに置換した。author.login の値（"github-actions"）は
# GitHub Actionsの投稿者名であり個人名ではないため、そのまま使用している。
#
# 事前登録: 手順1の実測（19件の実データ pr*_comments.json 全件、および
# 現行の `gh pr view <n> --json comments` の出力）で、author.login の値は
# 例外なく "github-actions"（末尾に "[bot]" が付かない）だった。
# `scripts/select_review_comment.sh` の2次経路は
# `.author.login == "github-actions[bot]"` という完全一致条件のため、
# 実データはこの条件に一致しないと予測した
# （予測テキストのmd5: 7ca0ca59a2027b1de4952acdc7119b2e、
# 記録時HEAD: 531fb53d566108122b0654e3ddb4b926a5f73477）。

_REAL_BODY_PR90 = (
    "**Claude finished @USERNAME's task in 4m 39s** —— "
    "[View job](https://github.com/OWNER/REPO/actions/runs/31155912534)\n\n"
    "---\n### レビュー完了\n\n"
    "- [x] PR差分の取得（`.github/workflows/claude-review.yml` +143/-115）"
)


def test_real_data_run_id_mismatch_does_not_fall_back_to_bot_name():
    """実データ(pr90由来)で1次経路を外すと、2次経路も発火せずfail-closedになる。

    実データの author.login は "github-actions"（"[bot]" 無し）であり、
    2次経路の条件 ".author.login == \"github-actions[bot]\"" とは
    完全一致しない。1次経路が拾うはずのrun_id(31155912534)とは異なる
    RUN_ID を渡すことで1次経路を意図的に外し、2次経路の実効性を確認する。
    """
    comments = [_comment("github-actions", _REAL_BODY_PR90)]
    result = _run(comments)  # RUN_ID="123456789" は実データに含まれない
    assert result.returncode == 2
    assert result.stdout == ""
    assert "特定できませんでした" in result.stderr


def test_real_data_multiple_comments_no_bot_suffix_fails_closed():
    """実データ複数件（いずれも author.login="github-actions"）でも、
    "[bot]" サフィックスが無いため2次経路の対象が0件になり、fail-closedになる。
    """
    body_pr92 = (
        "**Claude encountered an error after 1m 39s** —— "
        "[View job](https://github.com/OWNER/REPO/actions/runs/31160930257)\n\n"
        "---\n### レビュー進行中"
    )
    comments = [
        _comment("github-actions", _REAL_BODY_PR90),
        _comment("github-actions", body_pr92),
    ]
    result = _run(comments)  # RUN_ID="123456789" はいずれの実データにも無い
    assert result.returncode == 2
    assert result.stdout == ""
