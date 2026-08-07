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
    フォールバックしたケースを想定) -> exit 1。fail-closedで、
    誤ってexit 0(通過)にならないことを固定する(作業10-2)。

    作業36（Issue #94対応）でヘッダー判定を追加して以降、空文字列は
    "**Claude finished"で始まらないため、長さ判定(exit 2)より先に
    ヘッダー判定(exit 1、想定外の形式)で拒否されるようになった。
    """
    result = _run("", False, tmp_path)
    assert result.returncode == 1
    assert "想定外の形式" in result.stderr


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
    body = f"**Claude finished @user's task** —— [View job](url)\n\n---\n{content}"
    result = _run(body, False, tmp_path)
    assert result.returncode == 2


def test_threshold_boundary_at_exactly_min_length_passes(tmp_path):
    """MIN_LENGTH(50文字)の境界: 50文字はexit 0。"""
    content = "あ" * 50
    body = f"**Claude finished @user's task** —— [View job](url)\n\n---\n{content}"
    result = _run(body, False, tmp_path)
    assert result.returncode == 0


def test_placeholder_check_takes_priority_over_length(tmp_path):
    """プレースホルダ残骸があれば、本文が十分長くてもexit 1が優先される。"""
    body = (
        "**Claude finished @user's task** —— [View job](url)\n\n---\n"
        "I'll analyze this and get back to you."
        + "あ" * 100
    )
    result = _run(body, False, tmp_path)
    assert result.returncode == 1
    assert "プレースホルダ" in result.stderr


# --- 実データによるテスト（作業36、Issue #94対応） ---
#
# 以下の本文は ~/comic_checker-agent-notes/pr9*_comments.json（実際の
# GitHub API出力、gh pr view --json comments）から取得したものをそのまま
# 埋め込んでいる。手で書き起こしたものではない。

# PR #92（run 31160930257）の実際のトラッキングコメント本文。
# error_max_turnsで打ち切られ、tagモードの初期進捗テンプレートの
# まま最終状態になった（Issue #94の実測根拠そのもの）。
REAL_PROGRESS_TEMPLATE_BODY = '**Claude encountered an error after 1m 39s** —— [View job](https://github.com/giant-shrimp/comic_checker/actions/runs/31160930257)\n\n---\n### レビュー進行中 <img src="https://github.com/user-attachments/assets/5ac382c7-e004-429b-8e35-7feb3e8f9c6f" width="14px" height="14px" style="vertical-align: middle; margin-left: 4px;" />\n\n- [ ] コンテキスト収集（CLAUDE.md, ERRORS.md, 差分）\n- [ ] 差分の内容を理解\n- [ ] レビュー観点ごとにチェック\n- [ ] 指摘事項をまとめて投稿'

# PR #90・#95・#96・#97・#98・#99の実際の完了コメント本文
# （いずれも run が success で完走したもの）。
REAL_COMPLETED_BODIES = {
    90: "**Claude finished @giant-shrimp's task in 4m 39s** —— [View job](https://github.com/giant-shrimp/comic_checker/actions/runs/31155912534)\n\n---\n### レビュー完了\n\n- [x] PR差分の取得（`.github/workflows/claude-review.yml` +143/-115）\n- [x] `CLAUDE.md` / `ERRORS.md` / ADR-006 の確認\n- [x] 差分の精読（verify.sh ゲート空洞化・fail-closed崩れ・秘密情報・テスト増減の観点）\n- [x] レビューコメントの投稿\n\n### 指摘事項\n\n**なし。** 根拠を示せる範囲では、ブロッキングな問題は見つかりませんでした。\n\n### 確認した内容\n\n- **`verify.sh` ゲートの空洞化**: 該当なし。このワークフロー自体が `verify.sh` を実行する構成ではなく、差分中にテストや既存チェックの削除・`continue-on-error`追加・`skip`/`xfail`追加は見当たりません。\n- **fail-closedの原則**: `comic_checker/wikipedia_client.py` はこのPRで変更されていません。ワークフロー自体のfail-closed設計（`scripts/select_review_comment.sh`/`scripts/check_review_comment.sh` を使い、見つからない・プレースホルダ残骸・本文短すぎのいずれも非ゼロ終了として扱う、L209-231）は意図通り実装されており、`set -euo pipefail` と `if`文の組み合わせ・`pipefail`下での終了コード伝播も手でトレースして問題ありませんでした。\n- **秘密情報のハードコード**: すべて `secrets.GITHUB_TOKEN` / `secrets.CLAUDE_CODE_OAUTH_TOKEN` 経由で、ハードコードは無し。シェルへ直接埋め込まれる `${{ }}` 展開は `github.event.pull_request.number` / `github.run_id` / `github.repository` のみで、いずれもGitHub管理下の値（攻撃者制御不可）であり、PRタイトルや本文のようなインジェクションリスクのある値は使われていません。\n- **テストの増減**: このPRはワークフローYAMLのみの変更で、テストファイルの追加・削除・スキップ化は含まれません（`scripts/select_review_comment.sh`・`scripts/check_review_comment.sh` はPR #88で既にマージ・単体テスト済みで、このPRの差分には含まれていません）。\n- **`ERRORS.md`への追記漏れ**: 該当なし。今回のコミット（1件、本文なし）は3回の実測失敗（`workflow_dispatch`/agentモードの問題）を踏まえた設計変更の実装ですが、その実測過程は既に `ERRORS.md`「`claude-review.yml`（Phase 5 Step 1）」および `ADR-006` に詳細に記録済みで、このPR自体は決定済みの設計をYAMLに反映しただけです。\n- 参考: `scripts/select_review_comment.sh` / `scripts/check_review_comment.sh` は `git ls-files -s` で実行ビット（100755）が付与されていることを確認し、`./scripts/....sh` の直接実行は問題ありません。\n\n### 補足（ブロッキングではない観察）\n\nコード自体はADR-006で自ら「未検証」と明記した項目（`track_progress`の実際の効き方、`--disallowedTools`の優先順位、`select_review_comment.sh`の2次経路が実際に機能するか等）を多数抱えていますが、これらはコメント内で正直に未検証と記載されており、隠蔽や断定はされていません。実運用での実測結果は今後 `ERRORS.md` へ追記される前提として扱われています。",
    95: '**Claude finished @giant-shrimp\'s task in 2m 28s** —— [View job](https://github.com/giant-shrimp/comic_checker/actions/runs/31164462563)\n\n---\n### レビュー\n\n- [x] コンテキスト取得（CLAUDE.md, ERRORS.md, 差分）\n- [x] リクエスト内容の整理\n- [x] 差分のレビュー\n- [x] 結果を投稿\n\nこのPRは `.github/workflows/claude-review.yml` の `--max-turns` を実測目的で `15` → `40` へ一時的に引き上げるのみ（差分は+9/-1、対象ファイル1つ）。コードは変更しておらず、意図通り「探り実測用の暫定値」であることが冒頭コメントに明記されています。指摘は2件です。\n\n### 1. 新規コメントが参照する ERRORS.md の節が現時点で存在しない（中）\n\n- **該当箇所**: `.github/workflows/claude-review.yml` 6-7行目\n  ```\n  # 戻すこと。詳細は ERRORS.md「claude-review.yml（Phase 5 Step 1）」の\n  # 作業19・作業20該当節を参照。\n  ```\n- **期待される挙動**: 「作業19・作業20該当節」という参照先が、実際に `ERRORS.md` 内の該当セクション見出しとして存在すること。\n- **実際に起きること**: `ERRORS.md` 全体を検索しても「作業19」「作業20」という文字列は1件もヒットしません（既存の類似ラベルは「作業7-2」「作業8-2」「作業11-3」など`ADR-006`側にはありますが、`ERRORS.md`側の該当節にはこの番号付けが未反映です）。現時点でこのコメントの指示に従って参照先を探しても見つかりません。\n- **根拠**: `grep -rn "作業19\\|作業20" --include="*.md" .` が0件。`ERRORS.md`内の直近セクション見出しは `## \\`claude-review.yml\\`（Phase 5 Step 1）: 2回目のsteady-stateケース実測（PR #92 / run 31160930257）で\\`error_max_turns\\`により失敗した`（695行目）であり、「作業19」「作業20」という見出し・タグは付いていません。PR本文も「作業19-2で...確定しなかったため」「詳細はERRORS.md参照」としていますが、対応する記録が今回の差分にもリポジトリ内にも見当たりません。\n- **最小の修正案**: 本PRの目的（実測）を優先するなら影響は小さいですが、後続で結果を`ERRORS.md`に追記する際に「作業19」「作業20」という節見出し・ラベルを実際に使う（過去のPR #92のように別docsPRで追記予定なら、その旨をこのコメントに一言添えるか、番号が確定するまでは節名を明言しない書き方にする）。\n\n[Fix this →](https://claude.ai/code?q=In%20.github%2Fworkflows%2Fclaude-review.yml%20on%20branch%20ci%2Fclaude-review-max-turns-probe%2C%20lines%206-7%20reference%20ERRORS.md%20sections%20labeled%20%E4%BD%9C%E6%A5%AD19%2F%E4%BD%9C%E6%A5%AD20%20under%20%22claude-review.yml%EF%BC%88Phase%205%20Step%201%EF%BC%89%22%20but%20no%20such%20section%20headings%20currently%20exist%20in%20ERRORS.md.%20Either%20add%20ERRORS.md%20sections%20documenting%20the%20%E4%BD%9C%E6%A5%AD19-2%20investigation%20results%20(num_turns%20vs%20--max-turns)%2C%20or%20rephrase%20the%20workflow%20comment%20so%20it%20doesn%27t%20point%20to%20a%20not-yet-existing%20section.&repo=giant-shrimp/comic_checker)\n\n### 2. `timeout-minutes: 15` の根拠が `--max-turns 15` 時代の実測のままで、40への引き上げに合わせて再検討されていない（低〜中）\n\n- **該当箇所**: `.github/workflows/claude-review.yml` 74-76行目\n  ```\n  # 過去の実測はいずれも数分以内に完了しており（例: run 31113307119の\n  # Claude PR Reviewステップは約110秒）、15分の余裕で十分と判断した。\n  timeout-minutes: 15\n  ```\n- **期待される挙動**: このPRの目的は「完走時の実際のnum_turnsを観測する」ことなので、`--max-turns 40`まで消費される可能性のある実行が、途中でjob timeoutにより打ち切られずに完走できること。\n- **実際に起きること**: `timeout-minutes: 15`の根拠コメントは`--max-turns 15`時代の実測（約110秒で完了）に基づいたままで、上限を40へ引き上げたことに伴う所要時間の再見積もりがされていません。ツール呼び出し回数が増えれば実行時間も比例して伸びる可能性があり、最悪の場合15分のjob timeoutが先に発動し、`error_max_turns`ではなく`timeout`で打ち切られて「完走時の実際のnum_turns」という本来の観測目的を達成できないリスクがあります。\n- **根拠**: 同diff内で`--max-turns`は186行目で15→40（2.67倍）に変更されている一方、74-76行目の`timeout-minutes`とその根拠コメントは無変更（今回の差分に含まれていない）。\n- **最小の修正案**: 実測期間中だけ`timeout-minutes`を余裕を持った値（例: 20〜25分）へ一時的に引き上げるか、少なくとも「今回はtimeout側の再検証はしていない」旨をコメントに一言加える。\n\n---\n\n以上2件です。いずれも実験目的の一時変更であることを損なうものではなく、観測結果の信頼性・追跡可能性に関わる指摘です。`verify.sh`のゲート空洞化・fail-closed原則・秘密情報のハードコードに該当する変更は見当たりませんでした（対象が`.github/workflows/claude-review.yml`のコメントと数値変更のみのため）。',
    96: "**Claude finished @giant-shrimp's task in 1m 55s** —— [View job](https://github.com/giant-shrimp/comic_checker/actions/runs/31165668583)\n\n---\n### レビュー結果\n\n- [x] コンテキスト収集（CLAUDE.md / ERRORS.md / 差分の確認）\n- [x] リクエスト内容の把握\n- [x] レビュー実施\n- [x] コメント投稿\n\n**変更内容**: `ERRORS.md`への1セクション・63行の追記のみ（`git diff origin/main...HEAD -- ERRORS.md`で確認、コード変更なし）。\n\n### 観点ごとの確認結果\n\n- **既存の挙動**: 影響なし（docsのみの追記、`.github/workflows/**`・`comic_checker/**`・`tests/**`は無変更）。\n- **テストの追加・更新・削除・スキップ**: 対象範囲外（テストコード変更なし、`skip`/`xfail`/アサーション緩和なし）。\n- **エラー処理・境界値**: 対象範囲外。\n- **秘密情報のハードコード**: なし（記載されているのはPR番号・run ID・GitHub公式ドキュメントの引用・コスト数値のみ）。\n- **`verify.sh`ゲートの空洞化**: 該当なし（`verify.sh`自体・CIワークフローへの変更なし）。\n- **fail-closedの原則**: 該当なし（`wikipedia_client.py`等の判定ロジックへの変更なし）。\n- **数値の整合性**: 追記された2つの表を、同ファイル内の既存記述（790行より前、PR #90・#92の実測値を記録した既存段落）と突き合わせたところ、`実ツール呼び出し数`（PR #90: 19、PR #92: 17）・`num_turns`（PR #90: 20、PR #92: 16）・`total_cost_usd`（PR #90: 1.0537520999999999、PR #92: 0.5830226）はいずれも一致しており、矛盾は見つからなかった（PR #95の値は本追記が初出のため、差分単体からの検証はできず）。\n- **観測と推定の区別**: 「3点中2点が同じ式に一致した」というパターンについて「一次情報の裏付けは無い」「断定しない」と明記しており、`ERRORS.md`末尾の既存セクション（「観測 vs 推定」の区別ルール）と一貫した書き方になっている。\n- **`ERRORS.md`への追記漏れ**: コミットメッセージとPR本文を確認したが、今回の作業過程（このPR自体の作成）で2回以上の試行を要した新たな問題は読み取れなかった。追記されている内容自体が過去の失敗（作業19〜21）の記録であり、その点で漏れは無い。\n\n指摘事項はありませんでした。",
    97: '**Claude finished @giant-shrimp\'s task in 2m 45s** —— [View job](https://github.com/giant-shrimp/comic_checker/actions/runs/31167312663)\n\n---\n### レビュー結果\n\n- [x] コンテキスト収集（CLAUDE.md / ERRORS.md / 差分の確認）\n- [x] リクエスト内容の把握\n- [x] 差分レビュー（既存挙動・テスト・fail-closed原則・verify.sh空洞化・秘密情報・ERRORS.md追記漏れ）\n- [x] レビュー結果の投稿\n\nこのPRはdocsのみ2ファイル（`ERRORS.md`＋`ADR-006`）への追記で、コードは変更していません。`.github/workflows/**`も未変更で、`verify.sh`のゲート（チェック削除・`continue-on-error`追加・対象除外・`skip`/`xfail`追加・アサーション緩和）に該当する変更は見当たりません。`comic_checker/wikipedia_client.py`等の実コードも触っていないため、fail-closed原則の観点でも該当なしです。テストの追加・削除もdocsのみなので不要と判断します（`CLAUDE.md`の「新しい定数」ルールにも該当なし）。コミットメッセージ・PR本文からも2回以上の試行を要した失敗は読み取れず、`ERRORS.md`への追記漏れも見当たりませんでした。ADR-006が追加したポインタ（`ERRORS.md`「`num_turns`探り実測（作業19〜21）で分かったこと・分からなかったこと」）も、`ERRORS.md:790`の見出しと一字一句照合し、リンク切れではないことを確認しました。\n\n以下、1件のみ指摘します（重要度: 低〜中、事実誤りではなく結論の強さに関する指摘です）。\n\n---\n\n**1. `ERRORS.md:863-869` — 「ばらつきが小さく」「$1.10未満」という表現が、実測値に対してやや強すぎる結論になっている**\n\n- **該当箇所**: `ERRORS.md:863-869`（新規追加）\n  ```\n  1. **実測コストは`$0.5830226`〜`$1.0537520999999999`の範囲に収まり、\n     いずれも`$1.10`未満だった。** 値のばらつきが小さく（最大と最小の差は\n     約`$0.47`）...安定した水準にとどまった。\n  ```\n- **期待される挙動**: このドキュメント（`ERRORS.md`）は他の箇所で「実測結果でしか確定しない値を断定として書かない」「閾値を選んだ標本で評価すると実力を過大評価する」（`ERRORS.md:203`, `:330`）といった、まさに"結論を実測データが支える強さ以上に書かない"ことを繰り返し教訓化しているファイルです。同じ基準で見ると、この新規追加も同程度に慎重な書き方であるべきです。\n- **実際に起きること**: 4点の実測値（`1.0537520999999999, 0.5830226, 0.8667735, 0.6153178999999999`）は、最大値が最小値の約1.81倍（`1.0537521 / 0.5830226 ≈ 1.807`）です。平均（約`$0.78`）に対して差の`$0.47`は約60%に相当し、「ばらつきが小さく」「安定した水準」と形容するには相対的にかなり幅があります。また`$1.10`という閾値は、たまたま観測された最大値（`$1.0537521`）のすぐ上に置かれた値であり、この4点のデータのみから導かれた恣意的な基準に見えます（n=4のサンプルで将来のコストが必ず`$1.10`未満に収まる根拠は示されていません）。\n- **そう判断した根拠**: `ERRORS.md:849-852`の実測値テーブルそのものからの計算（上記）。加えて`ERRORS.md`内の既存エントリ（`ERRORS.md:203`「閾値を選んだ標本で評価すると、実力を過大評価する」等）が、まさに同種の「限られた実測点から強い結論を導くこと」への警戒を教訓化しており、本PRの追記がその基準を自身に適用できていません。\n- **最小の修正案**: 「ばらつきが小さく」を「n=4と少数だが、観測された範囲では」等に弱め、「$1.10未満」という具体的閾値を結論の根拠として使うのをやめる（または「n=4時点の観測値としては」等の留保を付ける）。結論2点目（各選択肢のトレードオフ構造はコストの絶対値と独立）はこの弱めた表現でも変わらず成立するため、影響は軽微です。\n\n---\n\nその他、以下は問題なしと判断しました。\n- `ADR-006:494-508`の`ERRORS.md`へのポインタ（見出し文字列）は`ERRORS.md:790`と完全一致しており、リンク切れなし。\n- `PR #90: num_turns 20 / --max-turns 15超過`という記述は`ERRORS.md:675,849`の実測値と整合。\n- 秘密情報のハードコードなし。\n- Markdownの見出し階層（`##`/`###`）も既存構造と整合。\n\nBranch: [`docs/claude-review-num-turns-adr-followup`](https://github.com/giant-shrimp/comic_checker/tree/docs/claude-review-num-turns-adr-followup)',
    98: '**Claude finished @giant-shrimp\'s task in 3m 28s** —— [View job](https://github.com/giant-shrimp/comic_checker/actions/runs/31186534910)\n\n---\n### レビュー完了\n\n- [x] 差分取得（`git diff origin/main...HEAD -- .github/workflows/claude-review.yml`）\n- [x] `CLAUDE.md` / `ERRORS.md` の確認\n- [x] レビュー観点に沿った差分の精査\n- [x] 指摘のまとめ・投稿\n\nこのPRは `.github/workflows/claude-review.yml` のみを変更し、`--max-turns` を暫定値40から本番値35に変更、`git fetch` を避ける誘導をプロンプトに追加するものです。`verify.sh` は実行せず、差分と`CLAUDE.md`・`ERRORS.md`を読んだ範囲での指摘です。\n\n### 指摘（重要度順）\n\n**1. プロンプトに追加された「過去5回すべてでgit fetchが拒否された」という記述が、`ERRORS.md`の実測記録と一致しません**\n- 該当箇所: `.github/workflows/claude-review.yml` 128-132行目（新規追加）\n  ```\n  - 過去5回の実測（run 31155912534・31160930257・31164462563・\n    31165668583・31167312663）すべてで、`git fetch` を含む\n    Bashコマンドが承認待ちで拒否されています。\n  ```\n- 期待される挙動: 本番プロンプトに埋め込まれる事実主張は、`CLAUDE.md`・`ERRORS.md`が求める「観測 vs 推定」の区別（`ERRORS.md` 907-916行目に明記された既存ルール）に沿って、根拠のある範囲でのみ断定されるべきです。\n- 実際に起きること: `ERRORS.md`でgit fetch拒否が記録されているのはPR #90・#92・#95の3runのみです（790-852行目、および840-844行目「git fetch拒否は3/3で再発したが」）。挙げられた5run中、`31165668583`（PR #96）はコスト実測表（852行目）に登場するだけでgit fetch拒否の記述が無く、`31167312663`に至ってはリポジトリ全体を検索しても`ERRORS.md`はおろかこのPRの新規プロンプト文以外どこにも出現しません（`grep -r 31167312663`で該当なし）。この差分自体も`ERRORS.md`を一切変更していません（変更ファイルは`claude-review.yml`のみ）。\n- 根拠: `ERRORS.md` 840-844行目（「git fetch拒否は3/3で再発」と明記）、852行目（PR #96の行にfetch拒否の言及なし）、リポジトリ全体grepで`31167312663`が新規プロンプト文以外に出現しない。\n- 最小の修正案: 5run目の実測ログを基に`ERRORS.md`へ追記してから本文言を「5回すべて」に更新するか、現時点の証拠に合わせて「これまで確認できた3回で」のように記述を実測の裏付け範囲まで弱める。\n\n**2. `--max-turns` を35とした根拠として参照先に指定された`ERRORS.md`の節に、35という値の導出過程が書かれていません**\n- 該当箇所: `.github/workflows/claude-review.yml` 172-174行目（新規追加コメント）\n  ```\n  # --max-turns を代わりの歯止めとして使う。値（35）の根拠は\n  # ERRORS.md「claude-review.yml（Phase 5 Step 1）: num_turns\n  # 探り実測（作業19〜21）で分かったこと・分からなかったこと」を参照。\n  ```\n- 期待される挙動: コメントが指す節を読めば、なぜ35が選ばれたか（実測値へのマージンの取り方など）を追跡できること。\n- 実際に起きること: 参照先の節（`ERRORS.md` 790-852行目）は4run分の`num_turns`実測（最大20、790-852行目の表）と、上限を超えて成功した理由が「未確定のままである」という結論（832-839行目）を記載しているのみで、35という具体的な数値がどう導かれたかの記述はありません。PR本文が言及する「作業27-3」の判断（git fetch誘導との同時適用の理由）や5点目の実測データも同節はもちろん`ERRORS.md`全体のどこにも見当たりません（`grep 作業2[2-9]`で該当なし）。\n- 根拠: `ERRORS.md` 790-852行目の内容確認、`grep -n "作業2[2-9]" ERRORS.md`が1件（作業23-4、無関係な節）のみヒット。\n- 最小の修正案: 35の導出根拠（実測最大値20へのマージンの取り方など）と作業22〜27・5点目の実測を`ERRORS.md`に追記し、コメントの参照節を実際に根拠が読める節に更新する。\n\n### 確認した範囲で問題が見当たらなかった観点\n- 削除された冒頭の暫定値コメントブロック（旧1-8行目）は本番値化に伴う整理として妥当です。\n- `verify.sh`のゲート空洞化、テストの削除・skip化には該当なし（workflowファイルのみの変更で、テストコード・アサーションへの変更はありません）。\n- `comic_checker/wikipedia_client.py`など fail-closed に関わるロジック変更は本PRに含まれていません。\n- 秘密情報のハードコードは見当たりません。',
    99: "**Claude finished @giant-shrimp's task in 1m 23s** —— [View job](https://github.com/giant-shrimp/comic_checker/actions/runs/31187785587)\n\n---\n### レビュー結果\n\n- [x] CLAUDE.md を読み、作業ルールを確認\n- [x] ERRORS.md（既存部分）を読み、過去の失敗パターンと重複がないか確認\n- [x] PR差分（ERRORS.md +53/-0）を読む\n- [x] レビュー観点に沿って確認（挙動破壊・テスト・境界値・秘密情報・verify.sh空洞化・fail-closed・ERRORS.md追記漏れ）\n- [x] コメントを最終更新\n\n**指摘事項：なし**\n\nこのPRは `ERRORS.md` への追記1件のみ（`.github/workflows/**` や `comic_checker/` 配下のコードは無変更）で、以下を確認した結果、指摘すべき問題は見つかりませんでした。\n\n- **挙動への影響**: コード変更が無いため、既存動作への影響はありません。\n- **テスト**: docsのみの変更のためテストの追加・削除は不要で、実際にも変更されていません。\n- **`verify.sh` ゲートの空洞化**: 対象となるコードやCI設定（`.github/workflows/claude-review.yml` 等）が変更されていないため、該当なし。\n- **fail-closedの原則（`wikipedia_client.py` 周辺）**: 当該ファイルは今回のdiffに含まれていません。\n- **秘密情報のハードコード**: 追記された文章・表に、APIキーやトークン等の機密情報は含まれていません（run IDやコスト額、PR番号など、既存のログ・PRコメントから引用された非機密の実測値のみ）。\n- **数値の内部整合性**: 新設された表（`ERRORS.md#L882`以降）の6行（PR #90・#92・#95・#96・#97・#98）は、本文で主張されている「成功時は `num_turns = 実ツール呼び出し数 + 1`、`error_max_turns`時のみ`-1`」というパターンと矛盾なく一致しています（例: PR #98は 実ツール呼び出し数17・`num_turns`18で `+1`、失敗した唯一の例であるPR #92は 17・16で `-1`）。\n- **PR本文で予告されているリンク**: 本文中の `ERRORS.md#L882` （mainブランチ・SHA固定の両方）は、実際に新設された見出し行（`## \\`claude-review.yml\\`: 本番値（\\`--max-turns 35\\`＋\\`git fetch\\`誘導）適用runの結果（6点目）`）の行番号と一致することを確認しました。\n- **ERRORS.md追記漏れ**: PR本文・コミットメッセージから、この追記作業自体で2回以上の試行を要した問題（該当PRのrun自身がそれを裏付ける対象）は読み取れませんでした。むしろこのPR自身が、次回実測（7点目）の材料として記録される設計になっています。\n\n以上より、本PRはドキュメントのみの安全な追記であり、承認可否の判断は行いませんが（本レビューの範囲外）、内容面での懸念はありませんでした。",
}


def test_real_progress_template_is_rejected(tmp_path):
    """PR #92の実際の本文（エラーヘッダー + 未完了チェックボックス）は
    exit 1 で拒否される（Issue #94: 修正前はexit 0だった穴）。
    """
    result = _run(REAL_PROGRESS_TEMPLATE_BODY, False, tmp_path)
    assert result.returncode == 1
    assert "エラー" in result.stderr


@pytest.mark.parametrize("pr_number", sorted(REAL_COMPLETED_BODIES))
def test_real_completed_bodies_are_accepted(pr_number, tmp_path):
    """実際に完走した6件（PR #90・#95・#96・#97・#98・#99）の本文は
    引き続き exit 0 を返す（Issue #94対応による回帰が無いことの確認）。
    """
    body = REAL_COMPLETED_BODIES[pr_number]
    result = _run(body, False, tmp_path)
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_error_header_alone_is_rejected(tmp_path):
    """ヘッダーが"**Claude encountered an error"で始まる場合、
    本文が十分長くてもexit 1で拒否される（ヘッダー判定は全文対象、
    ---以降の文字数とは独立）。
    """
    body = (
        "**Claude encountered an error after 5m** —— [View job](url)\n"
        "\n---\n"
        + "十分な長さのある本文です。" * 10
    )
    result = _run(body, False, tmp_path)
    assert result.returncode == 1
    assert "エラー" in result.stderr


def test_unrecognized_header_is_rejected(tmp_path):
    """先頭行が"**Claude finished"でも"**Claude encountered an error"でも
    ない想定外の形式は、fail-closedでexit 1にする。
    """
    body = "想定外のヘッダー行\n\n---\n" + "十分な長さのある本文です。" * 10
    result = _run(body, False, tmp_path)
    assert result.returncode == 1
    assert "想定外の形式" in result.stderr


def test_incomplete_checkbox_is_rejected_even_with_valid_header(tmp_path):
    """ヘッダーは正常("**Claude finished")でも、本文中に未完了の
    チェックボックス("- [ ] ")が残っていればexit 1にする
    （fail-closed。ヘッダーだけでは救えないケースの補助チェック）。
    """
    body = (
        "**Claude finished @user's task in 1m** —— [View job](url)\n"
        "\n---\n"
        "- [ ] 未完了の項目\n"
        + "十分な長さのある本文です。" * 10
    )
    result = _run(body, False, tmp_path)
    assert result.returncode == 1
    assert "未完了のチェックボックス" in result.stderr
