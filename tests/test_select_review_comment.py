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


def test_finds_comment_by_run_id_match():
    """(a) run_idを含むコメントがあれば、それを採用する。"""
    comments = [
        _comment("someone", "無関係なコメント"),
        _comment("other-bot[bot]", f"**Claude finished** —— [View job](https://github.com/o/r/actions/runs/{RUN_ID})\n\n---\n本文"),
    ]
    result = _run(comments)
    assert result.returncode == 0
    assert "本文" in result.stdout
    assert "一致でコメントを特定しました" in result.stderr


def test_fails_closed_when_no_run_id_match():
    """(c) run_id一致が無ければ exit 2 で落ちる。"""
    comments = [
        _comment("someone", "無関係なコメント"),
        _comment("other-bot[bot]", "別のワークフローのコメント"),
    ]
    result = _run(comments)
    assert result.returncode == 2
    assert "特定できませんでした" in result.stderr
    assert result.stdout == ""


def test_selects_run_id_matching_comment_among_candidates():
    """(d) 複数のコメント候補があっても、run_id一致するものが選ばれる。

    bot名が一致するだけのコメントは別のrunの残骸である可能性があるため、
    このrun固有のrun_id一致を優先する設計を固定する。
    """
    comments = [
        _comment("github-actions[bot]", "別のrunのプレースホルダ残骸"),
        _comment("github-actions[bot]", f"今回のrunの本文 [View job](https://.../actions/runs/{RUN_ID})"),
    ]
    result = _run(comments)
    assert result.returncode == 0
    assert "今回のrunの本文" in result.stdout
    assert "一致でコメントを特定しました" in result.stderr


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


# --- ネガティブコントロール（ADR-019、2次経路削除の固定） -------------------
#
# 2次経路削除前は、これらの入力（run_id不一致＋"github-actions[bot]"または
# "github-actions"名のコメント）は2次経路のbot名一致により exit 0 で終了して
# いた。削除後は run_id一致のみが経路として残るため、いずれも exit 2 に
# なることをここで固定する。


def test_bot_suffix_author_without_run_id_match_fails_closed():
    """author.loginが"github-actions[bot]"でrun_id不一致の場合、exit 2になる。
    削除前は2次経路により0で終了していたが、削除後は2になることを固定する。
    """
    comments = [_comment("github-actions[bot]", "プレースホルダのまま")]
    result = _run(comments)
    assert result.returncode == 2
    assert result.stdout == ""


def test_no_suffix_author_without_run_id_match_fails_closed():
    """author.loginが"github-actions"（サフィックス無し、実運用のgh pr viewの
    形式）でrun_id不一致の場合も、exit 2になる。削除前は2次経路により0で
    終了していたが、削除後は2になることを固定する。
    """
    comments = [_comment("github-actions", "プレースホルダのまま")]
    result = _run(comments)
    assert result.returncode == 2
    assert result.stdout == ""


# --- ここから実データによる検証（Issue #93） -------------------------------
#
# 出所: ~/comic_checker-agent-notes/pr90_comments.json・pr92_comments.json
# （過去の claude-review.yml 実測時に `gh pr view --json comments` で取得した
# 実データ。リポジトリ外の作業ディレクトリにあり、このリポジトリの
# バージョン管理対象ではない）。
#
# 個人名（GitHubアカウント名）除去について: 元データの body にはアカウント名への
# メンションと、URLパス中のアカウント名が含まれていたため、それぞれ
# `@USERNAME` / `github.com/OWNER/REPO` のプレースホルダに置換した。
# author.login の値（"github-actions"）は GitHub Actionsの投稿者名であり
# 個人名ではないため、そのまま使用している。
#
# 事前登録: 手順1の実測（19件の実データ pr*_comments.json 全件、および
# 現行の `gh pr view <n> --json comments` の出力）で、author.login の値は
# 例外なく "github-actions"（末尾に "[bot]" が付かない）だった。
# 当時（ADR-019で削除される前）の `scripts/select_review_comment.sh` の
# 2次経路は `.author.login == "github-actions[bot]"` という完全一致条件
# だったため、実データはこの条件に一致しないと予測した
# （予測テキストのmd5: 7ca0ca59a2027b1de4952acdc7119b2e、
# 記録時HEAD: 531fb53d566108122b0654e3ddb4b926a5f73477）。

_REAL_BODY_PR90 = (
    "**Claude finished @USERNAME's task in 4m 39s** —— "
    "[View job](https://github.com/OWNER/REPO/actions/runs/31155912534)\n\n"
    "---\n### レビュー完了\n\n"
    "- [x] PR差分の取得（`.github/workflows/claude-review.yml` +143/-115）"
)


def test_real_data_run_id_mismatch_fails_closed():
    """実運用の`gh pr view --json comments`出力（author.loginにサフィックスが
    付かない形式）を含む実データ(pr90由来)で、run_id不一致時にfail-closedする
    ことを固定する。2次経路の不発を示す目的はADR-019の削除により失効したが、
    実データ入力に対する被覆としてこのテストを残す。
    """
    comments = [_comment("github-actions", _REAL_BODY_PR90)]
    result = _run(comments)  # RUN_ID="123456789" は実データに含まれない
    assert result.returncode == 2
    assert result.stdout == ""
    assert "特定できませんでした" in result.stderr
