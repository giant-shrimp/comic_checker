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
import fcntl
import json
import os
import pty
import re
import subprocess
import time
import tty

from pathlib import Path

# pty を使うテスト（実端末での type-ahead ドレイン挙動の検証）は POSIX 前提。
# このリポジトリの開発・テストは WSL Ubuntu で行い（CLAUDE.md「環境の分離」）、
# verify.sh 自体も .venv/bin/activate を source する POSIX 専用スクリプトなので、
# pty は常に利用できる。他の既存テストが subprocess+bash+od 等を前提にしている
# のと同じ前提。

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




# --- propose_next_instruction() のテスト（ADR-014決定1・3・6・8） -----------
#
# ADR-014決定3により、旧 build_next_instruction()（review.mdをawkで機械抽出
# して次のinstructionにする、ADR-012決定3の実装）は廃止した。その3件のテスト
# も併せて削除し、置き換えとして本節を追加した。
#
# review_loop.shはmain()関数＋ソースガード（BASH_SOURCE比較）を持つため、
# review_audit.shのreview_audit_process_result()と同じ方式で、sourceして
# 個別の関数だけを直接呼び出せる。起案役の実体（scripts/review_proposer.sh、
# 内部でclaudeを呼ぶ）は呼ばない。代わりに SCRIPT_DIR を一時ディレクトリへ
# 差し替え、そこに置いた偽の review_proposer.sh を呼ばせる。

PROPOSER_STUB_HEADER = "#!/usr/bin/env bash\nset -euo pipefail\n"


# Issue #225: propose_next_instruction()は起案役へ実行役の許可ツール一覧も
# 渡す。テスト全体で使う固定値（review_loop.shのEXECUTOR_ALLOWED既定値と
# 同じ文字列である必要はないが、テストの可読性のため揃えてある）。
EXECUTOR_ALLOWED_FOR_TEST = "Read,Edit,Write,Glob,Grep,Bash(./scripts/verify.sh)"


def _install_proposer_stub(script_dir: Path, body: str) -> None:
    """SCRIPT_DIR差し替え用の偽 review_proposer.sh を置く。

    本物と同じ引数（original-instruction / review.md / output-dir /
    executor-allowed-tools）を受け取り、argvを argv.txt に記録する。
    bodyで終了コードや出力を制御する。
    """
    stub = script_dir / "review_proposer.sh"
    stub.write_text(
        PROPOSER_STUB_HEADER
        + 'mkdir -p "$3"\n'
        + 'printf "%s\\n" "$1" "$2" "$3" "$4" > "$3/argv.txt"\n'
        + body,
        encoding="utf-8",
    )
    stub.chmod(0o755)


def _run_propose_next_instruction(script_dir: Path, original: Path, review_md: Path,
                                  round_dir: Path,
                                  executor_allowed: str = EXECUTOR_ALLOWED_FOR_TEST) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c",
         'source "$1"; SCRIPT_DIR="$2"; propose_next_instruction "$3" "$4" "$5" "$6"',
         "_", str(SCRIPT), str(script_dir), str(original), str(review_md), str(round_dir), executor_allowed],
        capture_output=True,
        text=True,
    )


def _setup_round(tmp_path: Path) -> tuple:
    """偽SCRIPT_DIR・元instruction・review.md・round_dirを用意する。"""
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    original = tmp_path / "instruction_round1.md"
    original.write_text("§3-Cの記述を実態に合わせて修正せよ。\n", encoding="utf-8")
    review_md = tmp_path / "review.md"
    review_md.write_text("VERDICT: APPROVE_CONTINUE\n\nCONTRADICTIONS:\n- なし\n", encoding="utf-8")
    round_dir = tmp_path / "round_1"
    round_dir.mkdir()
    return script_dir, original, review_md, round_dir


def test_propose_next_instruction_passes_original_instruction(tmp_path):
    """ADR-014決定1: 起案役へ渡される第1引数は「1ラウンド目のinstruction」で
    あり、直近ラウンドのreview.mdではない（元のタスクの目的を保持する）。"""
    script_dir, original, review_md, round_dir = _setup_round(tmp_path)
    _install_proposer_stub(script_dir, 'echo "次の指示。" > "$3/next_instruction.md"\n')

    result = _run_propose_next_instruction(script_dir, original, review_md, round_dir)

    assert result.returncode == 0
    argv = (round_dir / "proposer" / "argv.txt").read_text(encoding="utf-8").splitlines()
    assert argv[0] == str(original)
    assert argv[1] == str(review_md)


def test_propose_next_instruction_passes_executor_allowed(tmp_path):
    """Issue #225: 起案役へ渡される第4引数は実行役の許可ツール一覧
    （EXECUTOR_ALLOWED）である。"""
    script_dir, original, review_md, round_dir = _setup_round(tmp_path)
    _install_proposer_stub(script_dir, 'echo "次の指示。" > "$3/next_instruction.md"\n')

    result = _run_propose_next_instruction(script_dir, original, review_md, round_dir,
                                            executor_allowed=EXECUTOR_ALLOWED_FOR_TEST)

    assert result.returncode == 0
    argv = (round_dir / "proposer" / "argv.txt").read_text(encoding="utf-8").splitlines()
    assert argv[3] == EXECUTOR_ALLOWED_FOR_TEST


def test_propose_next_instruction_uses_proposer_subdir(tmp_path):
    """起案役の出力先は round_N/proposer/ であり、round_N/ 直下ではない
    （review_audit.shが同名で書く prompt.txt / result.json / metrics.json を
    上書きしないための分離）。"""
    script_dir, original, review_md, round_dir = _setup_round(tmp_path)
    (round_dir / "result.json").write_text('{"auditor": "must survive"}', encoding="utf-8")
    _install_proposer_stub(
        script_dir,
        'echo "次の指示。" > "$3/next_instruction.md"\n'
        'echo "{\\"proposer\\": true}" > "$3/result.json"\n',
    )

    result = _run_propose_next_instruction(script_dir, original, review_md, round_dir)

    assert result.returncode == 0
    assert (round_dir / "proposer" / "next_instruction.md").exists()
    # 監査役側の result.json が起案役に上書きされていない。
    assert "must survive" in (round_dir / "result.json").read_text(encoding="utf-8")


def test_propose_next_instruction_returns_1_on_proposer_failure(tmp_path):
    """ADR-014決定8: 起案役の呼び出しが失敗（exit 2/3）したら戻り値1
    （HALT_NEEDS_HUMAN相当）。"""
    script_dir, original, review_md, round_dir = _setup_round(tmp_path)
    _install_proposer_stub(script_dir, "exit 3\n")

    result = _run_propose_next_instruction(script_dir, original, review_md, round_dir)

    assert result.returncode == 1


def test_propose_next_instruction_returns_2_on_no_further_action(tmp_path):
    """ADR-014決定8: 1行目がNO_FURTHER_ACTIONなら戻り値2（DONE相当）。
    これは失敗ではなく正常な判断であり、戻り値1と区別される。"""
    script_dir, original, review_md, round_dir = _setup_round(tmp_path)
    _install_proposer_stub(
        script_dir,
        'printf "NO_FURTHER_ACTION\\n本来の目的は達成済み。\\n" > "$3/next_instruction.md"\n',
    )

    result = _run_propose_next_instruction(script_dir, original, review_md, round_dir)

    assert result.returncode == 2


def test_propose_next_instruction_no_further_action_must_be_exact_first_line(tmp_path):
    """NO_FURTHER_ACTIONが1行目に完全一致でなければマーカーとみなさない
    （通常のinstructionとして戻り値0）。"""
    script_dir, original, review_md, round_dir = _setup_round(tmp_path)
    _install_proposer_stub(
        script_dir,
        'echo "NO_FURTHER_ACTIONではない。作業を続けよ。" > "$3/next_instruction.md"\n',
    )

    result = _run_propose_next_instruction(script_dir, original, review_md, round_dir)

    assert result.returncode == 0


# --- wait_for_quit_only() のテスト（ADR-011決定8の1キー承認を維持すること） ---
#
# Issue #232 段2: このプロンプトの while ループ先頭で drain_stray_input() を
# 呼ぶようにした。以下のテストはパイプ経由（input=）で入力を渡すため、
# drain_stray_input() の端末判定ガード（[ -t 0 ]）が働いて drain は no-op に
# なる。つまり「段2の組み込み後も、パイプで渡した q／c がそのまま
# wait_for_quit_only() 自身の read に届く」ことをこの2件が担保する
# （端末での type-ahead ドレイン挙動そのものは _run_drain_stray_input_on_tty
# を使う下の節で検証する）。


def _run_wait_for_quit_only(keys: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; wait_for_quit_only "テスト理由"', "_", str(SCRIPT)],
        input=keys,
        capture_output=True,
        text=True,
    )


def test_wait_for_quit_only_accepts_q(tmp_path):
    """q の1キーで正常に抜ける（1キー入力という形式が保たれている）。
    Issue #232 段2の組み込み後も、パイプ入力の q は drain_stray_input() の
    端末判定ガードを素通りして read に届く（rc 0）。"""
    result = _run_wait_for_quit_only("q")
    assert result.returncode == 0


def test_wait_for_quit_only_rejects_c(tmp_path):
    """c は受け付けない。ADR-014決定8が要求する「c を選べない」状態が、
    起案役の失敗時・NO_FURTHER_ACTION時に共通で使われるこの関数で成立する。
    段2でループ先頭に drain_stray_input() を足した後も、c→再表示→q の
    流れが保たれる（パイプ入力なので drain は no-op）。"""
    result = _run_wait_for_quit_only("cq")
    assert result.returncode == 0
    assert "q のみ入力できます" in result.stdout


# --- 停止条件・呼び出し位置の構造テスト -------------------------------------
#
# 以下はスクリプト本文に対する構造（静的）テストである。review_loop.shの
# main()は実行役・監査役の実claude呼び出しを含み、ループ本体を丸ごとpytestで
# 動かすことはできない（本ファイル冒頭のdocstring参照）。そのため「main()内の
# 呼び出し位置・変数の使われ方」については、関数単体テストでは届かない範囲を
# ソース本文の検査で補う。

SCRIPT_TEXT = SCRIPT.read_text(encoding="utf-8")


def test_original_instruction_file_is_never_reassigned_in_loop():
    """ADR-014決定1: ORIGINAL_INSTRUCTION_FILEへの代入はループ開始前の1箇所
    だけであり、ラウンドごとに上書きされない。"""
    assignments = [line for line in SCRIPT_TEXT.splitlines()
                   if line.strip().startswith("ORIGINAL_INSTRUCTION_FILE=")]
    assert len(assignments) == 1


def test_proposer_receives_original_not_current_instruction():
    """ADR-014決定1: 起案役の呼び出しに渡すのはORIGINAL_INSTRUCTION_FILEで
    あって、毎ラウンド上書きされるCURRENT_INSTRUCTION_FILEではない。"""
    call_lines = [line for line in SCRIPT_TEXT.splitlines()
                  if "propose_next_instruction " in line and "$ORIGINAL_INSTRUCTION_FILE" in line]
    assert len(call_lines) == 1
    assert "$CURRENT_INSTRUCTION_FILE" not in call_lines[0]


def test_proposer_call_site_passes_executor_allowed():
    """Issue #225: review_loop.shがpropose_next_instruction()を呼ぶ箇所で、
    実行役の許可ツール一覧（$EXECUTOR_ALLOWED）を渡していること。"""
    call_lines = [line for line in SCRIPT_TEXT.splitlines()
                  if "propose_next_instruction " in line and "$ORIGINAL_INSTRUCTION_FILE" in line]
    assert len(call_lines) == 1
    assert "$EXECUTOR_ALLOWED" in call_lines[0]


def test_proposer_is_not_called_for_done_or_halt_verdicts():
    """ADR-014決定6: VERDICTがDONE／HALT_NEEDS_HUMANのラウンドでは起案役を
    呼ばない。該当分岐がexit 0で終わり、起案役の呼び出しより前に位置する。"""
    lines = SCRIPT_TEXT.splitlines()
    halt_branch = next(i for i, line in enumerate(lines)
                       if '"$VERDICT" = "HALT_NEEDS_HUMAN"' in line and "if " in line)
    propose_call = next(i for i, line in enumerate(lines)
                        if "propose_next_instruction " in line and "$ORIGINAL_INSTRUCTION_FILE" in line)
    assert halt_branch < propose_call
    # 分岐内で exit 0 に到達し、起案役の呼び出しへ流れ落ちない。
    assert any("exit 0" in line for line in lines[halt_branch:propose_call])


def test_stop_condition_order_is_unchanged():
    """ADR-014決定7: 停止条件3つのifの評価順は変更しない（実装は先送り）。
    exit 10 → exit 11 → exit 12 の順のまま。"""
    order = [line.strip() for line in SCRIPT_TEXT.splitlines()
             if line.strip().startswith("exit 1") and line.strip() in ("exit 10", "exit 11", "exit 12")]
    assert order == ["exit 10", "exit 11", "exit 12"]


def test_build_next_instruction_is_fully_removed():
    """ADR-014決定3: build_next_instruction()は廃止した。呼ばれない関数が
    残っていないこと（定義・呼び出しが無く、経緯を説明するコメントのみ）。"""
    assert "build_next_instruction()" not in SCRIPT_TEXT.replace(
        "旧 build_next_instruction()", "").replace(
        "build_next_instruction()による", "").replace(
        "build_next_instruction()へのフォールバック", "")
    code_lines = [line for line in SCRIPT_TEXT.splitlines()
                  if "build_next_instruction" in line and not line.strip().startswith("#")]
    assert code_lines == []


# --- check_executor_result() のテスト（Issue #223） -------------------------
#
# ADR-014決定8と同じ思想で、実行役のis_error=trueもHALT_NEEDS_HUMAN相当として
# 人間の判断待ちにする（強制終了ではなく、wait_for_quit_only()でq限定にする）。
# review_audit.shのreview_audit_process_result()と同じ流儀で、claudeを呼ばず
# 偽のexecutor_result.jsonを直接フィクスチャとして与えて検証する。

def _write_executor_result(round_dir: Path, *, result: str = "", is_error: bool = False,
                            terminal_reason: str = "completed", num_turns: int = 5) -> None:
    (round_dir / "executor_result.json").write_text(
        json.dumps(
            {
                "is_error": is_error,
                "terminal_reason": terminal_reason,
                "num_turns": num_turns,
                "total_cost_usd": 0.1,
                "permission_denials": [],
                "result": result,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _run_check_executor_result(round_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; check_executor_result "$2"',
         "_", str(SCRIPT), str(round_dir)],
        capture_output=True,
        text=True,
    )


def test_check_executor_result_missing_json_returns_2(tmp_path):
    """executor_result.jsonが存在しない（呼び出し自体の失敗を模す）ならexit 2。"""
    result = _run_check_executor_result(tmp_path)
    assert result.returncode == 2


def test_check_executor_result_invalid_json_returns_2(tmp_path):
    """executor_result.jsonが不正なJSONならexit 2。"""
    (tmp_path / "executor_result.json").write_text("not json", encoding="utf-8")
    result = _run_check_executor_result(tmp_path)
    assert result.returncode == 2


def test_check_executor_result_is_error_true_stops(tmp_path):
    """(1) is_error=trueのとき停止する（戻り値1。exit 2でもexit 0でもない）。"""
    _write_executor_result(tmp_path, is_error=True, terminal_reason="max_turns", num_turns=21)
    result = _run_check_executor_result(tmp_path)
    assert result.returncode == 1


def test_check_executor_result_is_error_false_proceeds(tmp_path):
    """(2) is_error=falseのとき従来どおり後続処理（監査役）へ進んでよい
    （戻り値0）。"""
    _write_executor_result(tmp_path, result="作業を完了しました。", is_error=False)
    result = _run_check_executor_result(tmp_path)
    assert result.returncode == 0


def test_check_executor_result_prints_terminal_reason_and_num_turns(tmp_path):
    """(3) terminal_reasonとnum_turnsが画面出力（stdout）に含まれる。"""
    _write_executor_result(tmp_path, is_error=True, terminal_reason="max_turns", num_turns=21)
    result = _run_check_executor_result(tmp_path)
    assert "max_turns" in result.stdout
    assert "21" in result.stdout


def test_check_executor_result_is_error_false_does_not_print_diagnostics(tmp_path):
    """（対照実験）is_error=falseのときは診断表示が出ない
    （上のテストが「常に出力される」だけの弱いテストでないことを示す）。"""
    _write_executor_result(tmp_path, result="ok", is_error=False, terminal_reason="completed")
    result = _run_check_executor_result(tmp_path)
    assert "実行役が正常終了しませんでした" not in result.stdout


# --- main()内のexecutor_check分岐の構造テスト -------------------------------

def test_executor_is_error_branch_uses_wait_for_quit_only_not_hard_exit():
    """Issue #223: is_error=true（executor_check == 1）の分岐は、既存の
    停止条件（exit 10/11/12）のような強制終了ではなく、wait_for_quit_only()
    を経由してexit 0へ合流する（ADR-011決定8の1キー承認を維持する）。"""
    lines = SCRIPT_TEXT.splitlines()
    branch_idx = next(i for i, line in enumerate(lines)
                      if '"$executor_check" -eq 1' in line)
    # 分岐内でwait_for_quit_onlyが呼ばれ、exit 10/11/12のような数値終了
    # コードには到達しない（次の空行またはfiまでの範囲を見る）。
    end_idx = next(i for i in range(branch_idx, len(lines)) if lines[i].strip() == "fi")
    branch_body = lines[branch_idx:end_idx]
    assert any("wait_for_quit_only" in line for line in branch_body)
    assert any("exit 0" in line for line in branch_body)
    assert not any(line.strip() in ("exit 10", "exit 11", "exit 12") for line in branch_body)


def test_executor_check_call_precedes_report_md_extraction():
    """check_executor_result()の呼び出しは、report.mdへの.result抽出より前に
    ある（is_error検出が抜け道にならないよう、抽出の手前で必ず通過する）。"""
    lines = SCRIPT_TEXT.splitlines()
    check_call_idx = next(i for i, line in enumerate(lines) if 'check_executor_result "$ROUND_DIR"' in line)
    report_idx = next(i for i, line in enumerate(lines) if 'report.md"' in line and "jq -r '.result" in line)
    assert check_call_idx < report_idx


# --- preserve_work_tree_state() のテスト（Issue #227） ----------------------
#
# git diff・git status --porcelainという実際のgit副作用を持つ関数のため、
# _init_repo()（ブランチ検査テストで使っている一時ローカルgitリポジトリの
# 前例）に倣い、本物のcomic_checkerリポジトリとは無関係な一時リポジトリを
# 作ってテストする。

def _run_preserve_work_tree_state(repo_dir: Path, round_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; preserve_work_tree_state "$2"',
         "_", str(SCRIPT), str(round_dir)],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )


def test_preserve_work_tree_state_saves_diff_when_dirty(tmp_path):
    """作業ツリーに変更（追跡済みファイルの変更）がある場合、
    preserved_diff.txt・preserved_status.txtに反映され、戻り値0になる。"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo(repo_dir, "fix/some-topic")
    (repo_dir / "placeholder.txt").write_text("changed\n", encoding="utf-8")
    round_dir = tmp_path / "round_1"
    round_dir.mkdir()

    result = _run_preserve_work_tree_state(repo_dir, round_dir)

    assert result.returncode == 0
    diff_content = (round_dir / "preserved_diff.txt").read_text(encoding="utf-8")
    assert "placeholder.txt" in diff_content
    status_content = (round_dir / "preserved_status.txt").read_text(encoding="utf-8")
    assert "placeholder.txt" in status_content


def test_preserve_work_tree_state_reports_clean_tree(tmp_path):
    """作業ツリーに変更が無い場合も、その旨が画面出力から分かる
    （戻り値1、保存されるファイルは両方とも空）。"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo(repo_dir, "fix/some-topic")
    round_dir = tmp_path / "round_1"
    round_dir.mkdir()

    result = _run_preserve_work_tree_state(repo_dir, round_dir)

    assert result.returncode == 1
    assert "変更はありません" in result.stdout
    assert (round_dir / "preserved_diff.txt").read_text(encoding="utf-8") == ""
    assert (round_dir / "preserved_status.txt").read_text(encoding="utf-8") == ""


def test_preserve_work_tree_state_captures_untracked_files(tmp_path):
    """新規（未追跡）ファイルはgit diffには現れないが、preserved_status.txt
    には現れる（未追跡ファイルの成果を見落とさないことの確認）。"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo(repo_dir, "fix/some-topic")
    (repo_dir / "new_file.txt").write_text("new\n", encoding="utf-8")
    round_dir = tmp_path / "round_1"
    round_dir.mkdir()

    result = _run_preserve_work_tree_state(repo_dir, round_dir)

    assert result.returncode == 0
    diff_content = (round_dir / "preserved_diff.txt").read_text(encoding="utf-8")
    assert "new_file.txt" not in diff_content
    status_content = (round_dir / "preserved_status.txt").read_text(encoding="utf-8")
    assert "new_file.txt" in status_content


def test_preserve_work_tree_state_prints_file_paths(tmp_path):
    """保存したファイルのパスが画面出力（stdout）に含まれる。"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo(repo_dir, "fix/some-topic")
    round_dir = tmp_path / "round_1"
    round_dir.mkdir()

    result = _run_preserve_work_tree_state(repo_dir, round_dir)

    assert str(round_dir / "preserved_diff.txt") in result.stdout
    assert str(round_dir / "preserved_status.txt") in result.stdout


# --- main()内の呼び出し位置の構造テスト -------------------------------------

def test_preserve_work_tree_state_called_before_wait_for_quit_only_on_executor_error():
    """Issue #227: is_error=true分岐でpreserve_work_tree_state()が
    wait_for_quit_only()より前に呼ばれる（人間が判断する前に成果を保全する）。"""
    lines = SCRIPT_TEXT.splitlines()
    branch_idx = next(i for i, line in enumerate(lines)
                      if '"$executor_check" -eq 1' in line)
    end_idx = next(i for i in range(branch_idx, len(lines)) if lines[i].strip() == "fi")
    branch_body = lines[branch_idx:end_idx]
    preserve_idx = next(i for i, line in enumerate(branch_body) if "preserve_work_tree_state" in line)
    wait_idx = next(i for i, line in enumerate(branch_body) if "wait_for_quit_only" in line)
    assert preserve_idx < wait_idx


def test_preserve_work_tree_state_only_called_in_executor_error_branch():
    """Issue #227: preserve_work_tree_state()の呼び出しは1箇所のみ。
    is_error=false（executor_check==0、正常系）では呼ばれない。"""
    call_lines = [line for line in SCRIPT_TEXT.splitlines()
                  if "preserve_work_tree_state " in line and not line.strip().startswith("#")]
    assert len(call_lines) == 1


# --- write_diff_evidence() のテスト（Issue #231 / ADR-015 案D） ------------
#
# 監査役へ渡す diff.txt を生成する関数。git diff だけでは未追跡ファイル
# （新規作成物）が証拠から抜け落ちるため、git status --porcelain の出力を
# 冒頭節として連結する。preserve_work_tree_state() と同じく実 git 副作用を
# 持つため、_init_repo() の一時ローカルリポジトリを流用する。
#
# 見出し文字列は scripts/review_loop.sh の DIFF_EVIDENCE_STATUS_HEADING /
# DIFF_EVIDENCE_DIFF_HEADING 定数を本文（SCRIPT_TEXT）から取り出して参照する
# （テスト側にハードコードしない）。

def _diff_evidence_headings() -> tuple:
    """scripts/review_loop.sh の見出し定数の値を (status見出し, diff見出し) で返す。"""
    status = re.search(r'DIFF_EVIDENCE_STATUS_HEADING="([^"]*)"', SCRIPT_TEXT).group(1)
    diff = re.search(r'DIFF_EVIDENCE_DIFF_HEADING="([^"]*)"', SCRIPT_TEXT).group(1)
    return status, diff


def _run_write_diff_evidence(repo_dir: Path, out_file: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; write_diff_evidence "$2"',
         "_", str(SCRIPT), str(out_file)],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )


def test_write_diff_evidence_includes_untracked_file(tmp_path):
    """(a) 未追跡ファイルのみが存在する状態で実行すると、生成物に
    `?? <パス>` 行が含まれる（git diff 単独では抜け落ちる証拠が入る）。"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo(repo_dir, "fix/some-topic")
    (repo_dir / "brand_new.md").write_text("new content\n", encoding="utf-8")
    out_file = tmp_path / "diff.txt"

    result = _run_write_diff_evidence(repo_dir, out_file)

    assert result.returncode == 0
    content = out_file.read_text(encoding="utf-8")
    assert "?? brand_new.md" in content


def test_write_diff_evidence_includes_tracked_change(tmp_path):
    """(b) 追跡済みファイルの変更がある状態で、生成物に `diff --git` 行が
    含まれる（従来の git diff 相当の証拠は失われていない）。"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo(repo_dir, "fix/some-topic")
    (repo_dir / "placeholder.txt").write_text("changed\n", encoding="utf-8")
    out_file = tmp_path / "diff.txt"

    result = _run_write_diff_evidence(repo_dir, out_file)

    assert result.returncode == 0
    content = out_file.read_text(encoding="utf-8")
    assert "diff --git" in content
    assert "placeholder.txt" in content


def test_write_diff_evidence_status_section_precedes_diff_section(tmp_path):
    """(c) 未追跡ファイルと追跡済みファイルの変更が同時にある状態で、
    両方が1ファイル内に含まれ、status 節（`?? ...`）が diff 節
    （`diff --git ...`）より前にある。"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo(repo_dir, "fix/some-topic")
    (repo_dir / "placeholder.txt").write_text("changed\n", encoding="utf-8")
    (repo_dir / "brand_new.md").write_text("new content\n", encoding="utf-8")
    out_file = tmp_path / "diff.txt"

    result = _run_write_diff_evidence(repo_dir, out_file)

    assert result.returncode == 0
    content = out_file.read_text(encoding="utf-8")

    status_heading, diff_heading = _diff_evidence_headings()
    assert status_heading in content
    assert diff_heading in content
    # 2節の順序: status見出し → diff見出し。
    assert content.index(status_heading) < content.index(diff_heading)
    # 未追跡ファイルの証拠は status 節の側（diff見出しより前）に出る。
    assert content.index("?? brand_new.md") < content.index(diff_heading)
    # 追跡済み変更の diff は diff 節の側（diff見出しより後）に出る。
    assert content.index("diff --git") > content.index(diff_heading)


def test_write_diff_evidence_clean_tree_does_not_fail(tmp_path):
    """(d) 変更が皆無の状態でも関数は非ゼロ終了しない（ループを止めない）。
    生成物には2つの見出しだけが残る。"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo(repo_dir, "fix/some-topic")
    out_file = tmp_path / "diff.txt"

    result = _run_write_diff_evidence(repo_dir, out_file)

    assert result.returncode == 0
    content = out_file.read_text(encoding="utf-8")
    status_heading, diff_heading = _diff_evidence_headings()
    assert status_heading in content
    assert diff_heading in content
    assert "??" not in content
    assert "diff --git" not in content


def test_write_diff_evidence_wired_into_main_loop():
    """main() の diff.txt 生成が write_diff_evidence() 呼び出しになっており、
    素の `git diff > "${ROUND_DIR}/diff.txt"` が残っていない。"""
    lines = [line for line in SCRIPT_TEXT.splitlines()
             if not line.strip().startswith("#")]
    assert any('write_diff_evidence "${ROUND_DIR}/diff.txt"' in line for line in lines)
    assert not any('git diff > "${ROUND_DIR}/diff.txt"' in line for line in lines)


# --- EXECUTOR_ALLOWED の許可パターン（ADR-016 A-1 / Issue #241） -----------
#
# ADR-016（docs/decisions/ADR-016-executor-allowed-pytest.md）の A-1 は、
# 実行役が新設スクリプト／テストを実行できず自己検証できないままターンを
# 空費する Issue #241 への対処として、EXECUTOR_ALLOWED に .venv 経由の
# pytest 実行を 1 パターン追加すると決めた。A-2 = 方法2 の決定により、
# 許可するのは .venv/bin/python 経由のみで、Bash(python -m pytest*)
# （.venv/bin/ 前置なし）は加えない。
#
# 許可文字列全体はテスト側にハードコードせず、scripts/review_loop.sh 本文の
# EXECUTOR_ALLOWED 代入行から読み出してカンマ分割した要素集合を検証する
# （_diff_evidence_headings() と同じく、スクリプト本文を単一の情報源とする）。

def _executor_allowed_elements() -> set:
    """scripts/review_loop.sh の EXECUTOR_ALLOWED 既定値をカンマ分割した集合。"""
    m = re.search(r'^EXECUTOR_ALLOWED="([^"]*)"', SCRIPT_TEXT, re.MULTILINE)
    assert m is not None, "EXECUTOR_ALLOWED の代入行が見つからない"
    return set(m.group(1).split(","))


def test_executor_allowed_includes_venv_pytest():
    """ADR-016 A-1 / Issue #241: 実行役の許可に .venv 経由の pytest 実行
    `Bash(.venv/bin/python -m pytest*)` が含まれる（成果物の自己検証を
    可能にする）。"""
    assert "Bash(.venv/bin/python -m pytest*)" in _executor_allowed_elements()


def test_executor_allowed_keeps_verify_sh():
    """ADR-016 A-1: 既存の `Bash(./scripts/verify.sh)` は残す（A-1 は要素の
    追加のみで、既存要素の変更・削除はしないと決めた）。Issue #241。"""
    assert "Bash(./scripts/verify.sh)" in _executor_allowed_elements()


def test_executor_allowed_excludes_bare_python_pytest():
    """ADR-016 A-2 = 方法2 / Issue #241: `.venv/bin/` 前置なしの
    `Bash(python -m pytest*)` は許可しない（システム Python には pytest が
    無く、方法2 は .venv 経由の 1 パターンのみと決めた）。"""
    assert "Bash(python -m pytest*)" not in _executor_allowed_elements()


# --- drain_stray_input() のテスト（Issue #232、段1＋段2） ------------------
#
# docs/ai_loop_state/typeahead_mitigation_options_2026-08-29.md選択肢Bの
# 実装。段2で端末判定ガード（[ -t 0 ]）を追加し、承認プロンプト2箇所へ
# 組み込んだ。
#
# 検証は2系統に分かれる:
#   - 非端末（パイプ）系: subprocess.run(..., input=...)。ガードが働いて
#     drain が no-op になること（＝パイプで渡した正当な入力を捨てないこと）
#     を検証する。CIも非端末なので、この系統が段2の主眼。
#   - 端末（pty）系: _run_drain_stray_input_on_tty。[ -t 0 ] を満たす実 pty を
#     stdin にして、type-ahead の検出・警告・空白保持・制御文字エスケープを
#     検証する。段1でパイプ経由で見ていた挙動は、ガード追加後はこちらでしか
#     再現できない（パイプでは drain が即 return する）。

def _run_drain_stray_input(stdin_text: str) -> subprocess.CompletedProcess:
    """非端末（パイプ）の標準入力で drain_stray_input() を実行する。"""
    return subprocess.run(
        ["bash", "-c", 'source "$1"; drain_stray_input', "_", str(SCRIPT)],
        input=stdin_text,
        capture_output=True,
        text=True,
    )


def _run_drain_stray_input_on_tty(preload: bytes) -> tuple:
    """実 pty を標準入力にして drain_stray_input() を実行する。

    preload を子プロセス起動前に master 側へ書き込み、先行入力（type-ahead）
    が端末バッファに残っている状況を再現する。pty を raw モードにするのは、
    canonical モードだと改行が来るまで read() にバイトが渡らず
    「echo $?」（改行なし）を read -t 0 が readable と判定しないため。
    (returncode, stdout) を返す。
    """
    master, slave = pty.openpty()
    tty.setraw(slave)
    os.write(master, preload)
    try:
        proc = subprocess.run(
            ["bash", "-c", 'source "$1"; drain_stray_input', "_", str(SCRIPT)],
            stdin=slave, capture_output=True, text=True, timeout=15,
        )
    finally:
        os.close(slave)
        os.close(master)
    return proc.returncode, proc.stdout


# --- 非端末（パイプ）系: 段2の端末判定ガード -------------------------------

def test_drain_stray_input_noop_when_stdin_not_a_tty(tmp_path):
    """段2の端末判定ガード: 標準入力が端末でない場合は、そこにバイトが
    あっても（"echo $?" を渡しても）何もせず「破棄していない」（1）を返す。
    これが承認プロンプトへパイプで渡した正当な入力（"q"／"c"）を守る。"""
    result = _run_drain_stray_input("echo $?")

    assert result.returncode == 1
    assert "先行入力" not in result.stdout
    assert "内容:" not in result.stdout


def test_drain_stray_input_no_input_returns_1(tmp_path):
    """先行入力が無い（空のパイプ）場合：警告が現れず、戻り値が
    「破棄していない」（1）を示す。段2以降はまず端末判定ガードで return 1
    するため、read -t 0 には到達しない。"""
    result = _run_drain_stray_input("")

    assert result.returncode == 1
    assert "先行入力" not in result.stdout


def test_drain_stray_input_silent_for_non_tty_eof(tmp_path):
    """空の標準入力（EOF）でも誤って警告が出ない。段1では read -t 0 が
    EOFを readable と誤判定する挙動に対する空ガードの検証だったが、段2で
    端末判定ガードが read -t 0 より前に入ったため、非端末EOFはそこで
    止まる。いずれにせよ「非端末では黙って何もしない」ことの回帰テスト。"""
    result = _run_drain_stray_input("")

    assert "先行入力" not in result.stdout
    assert "内容:" not in result.stdout


# --- 端末（pty）系: type-ahead の検出・整形 ------------------------------

def test_drain_stray_input_detects_and_warns_on_tty(tmp_path):
    """実端末に先行入力がある場合：警告がstdoutに現れ、戻り値が
    「破棄した」（0）を示す。"""
    rc, out = _run_drain_stray_input_on_tty(b"echo $?")

    assert rc == 0
    assert "先行入力" in out
    assert "7バイト" in out


def test_drain_stray_input_preserves_spaces_on_tty(tmp_path):
    """先行入力中の空白がbufから失われない
    （IFS=を指定していないと read -n 1 が空白を読み落とす、という実測
    確認済みの挙動に対する回帰テスト）。空白を含めて7バイト。"""
    rc, out = _run_drain_stray_input_on_tty(b"echo $?")

    assert rc == 0
    assert "7バイト" in out  # IFSの罠で6になっていないか


def test_drain_stray_input_escapes_control_characters_on_tty(tmp_path):
    """制御文字を含む先行入力を渡した場合、そのまま端末へ出力されない
    （raw byteが混入せず、od -c相当の表記に変換されていること）。"""
    rc, out = _run_drain_stray_input_on_tty(b"\x1b\x01")

    assert rc == 0
    assert "\x1b" not in out
    assert "\x01" not in out
    assert "033" in out
    assert "001" in out


def test_drain_stray_input_empty_guard_on_tty(tmp_path):
    """端末でも、読み出せた内容が実質空（改行のみ）なら警告しない
    （空ガード [ -z "$buf" ]）。IFS= かつ read -n 1 は改行1文字を
    空文字列として読むため buf は空のまま。戻り値は「破棄していない」（1）。"""
    rc, out = _run_drain_stray_input_on_tty(b"\n")

    assert rc == 1
    assert "先行入力" not in out


# --- 構造テスト: 段2の組み込みと端末判定ガード ---------------------------

def test_drain_stray_input_is_wired_into_both_prompts():
    """Issue #232 段2: drain_stray_input()の呼び出しが承認プロンプト2箇所
    （wait_for_quit_only内・main内の[c/q]）に入っている。コメント行と
    定義行は除く。"""
    call_lines = [line for line in SCRIPT_TEXT.splitlines()
                  if "drain_stray_input" in line and not line.strip().startswith("#")
                  and "drain_stray_input()" not in line]
    assert len(call_lines) == 2
    assert all("drain_stray_input || true" in line for line in call_lines)


def test_drain_stray_input_wired_before_wait_for_quit_only_read():
    """段2: wait_for_quit_only() の while ループ内で、read -p より前に
    drain_stray_input() を呼ぶ（片方の呼び出しを消すと落ちる）。"""
    lines = SCRIPT_TEXT.splitlines()
    fn_idx = next(i for i, l in enumerate(lines) if l.startswith("wait_for_quit_only()"))
    while_idx = next(i for i in range(fn_idx, len(lines)) if "while true; do" in lines[i])
    read_idx = next(i for i in range(while_idx, len(lines))
                    if 'read -n 1 -r -p "${reason}' in lines[i])
    body = lines[while_idx + 1:read_idx]
    assert any("drain_stray_input" in l for l in body)


def test_drain_stray_input_wired_before_continue_prompt_read():
    """段2: main() の [c=続行 / q=終了] プロンプトでも、read -p より前に
    drain_stray_input() を呼ぶ（片方の呼び出しを消すと落ちる）。"""
    lines = SCRIPT_TEXT.splitlines()
    read_idx = next(i for i, l in enumerate(lines)
                    if 'read -n 1 -r -p "この指示で次ラウンドへ進みますか' in l)
    while_idx = max(i for i in range(read_idx) if "while true; do" in lines[i])
    body = lines[while_idx + 1:read_idx]
    assert any("drain_stray_input" in l for l in body)


def test_drain_stray_input_has_tty_guard():
    """段2: drain_stray_input() は read -t 0 より前に「標準入力が端末で
    なければ return 1」する端末判定ガードを持つ（このガードを外すと
    パイプ入力系のテストが落ちる）。"""
    lines = SCRIPT_TEXT.splitlines()
    fn_start = next(i for i, l in enumerate(lines) if l.startswith("drain_stray_input()"))
    guard_idxs = [i for i in range(fn_start, len(lines)) if "! -t 0" in lines[i]]
    read_t0_idxs = [i for i in range(fn_start, len(lines)) if "read -t 0" in lines[i]]
    assert guard_idxs, "drain_stray_input() に端末判定ガード（[ ! -t 0 ]）が無い"
    assert read_t0_idxs
    guard_idx, read_t0_idx = guard_idxs[0], read_t0_idxs[0]
    assert guard_idx < read_t0_idx
    # ガード直下が return 1 であること。
    assert any("return 1" in lines[i] for i in range(guard_idx, guard_idx + 3))


def test_continue_prompt_still_accepts_c_and_q():
    """段2の組み込み後も、[c=続行 / q=終了] の case が c) と q) の両方を
    引き続き解釈する（drain_stray_input を足しただけで分岐は不変）。

    ※ この分岐は main() 内にあり、main() は実行役・監査役の実 claude 呼び出し
    を含むため、c/q の受理を pytest で動的に実行して確認することはできない
    （本ファイル冒頭 docstring）。ここでは case 分岐が壊れていないことの
    静的確認に留める。動的検証が可能なのは wait_for_quit_only()（下記
    pty テスト）まで。"""
    lines = SCRIPT_TEXT.splitlines()
    case_idx = next(i for i, l in enumerate(lines) if 'case "$KEY" in' in l)
    esac_idx = next(i for i in range(case_idx, len(lines)) if lines[i].strip() == "esac")
    body = "\n".join(lines[case_idx:esac_idx])
    assert "\n      c)" in "\n" + body
    assert "\n      q)" in "\n" + body


# --- pty 統合テスト: 段2の組み込みが type-ahead を実際に処理する ----------

def test_wait_for_quit_only_drains_typeahead_then_accepts_q_on_tty(tmp_path):
    """Issue #232 の再現シナリオ: ループ起動直後に人間が `echo $?`+Enter を
    打ち込んで先行入力として残った状態で wait_for_quit_only() に入る。
    段2の組み込みにより、先行入力は承認として受理されず破棄・警告され、
    あらためて表示されたプロンプトで人間が押した q が受理される（rc 0）。"""
    master, slave = pty.openpty()
    tty.setraw(slave)
    os.write(master, b"echo $?\n")  # 起動直後に残った type-ahead
    proc = subprocess.Popen(
        ["bash", "-c", 'source "$1"; wait_for_quit_only "テスト理由"', "_", str(SCRIPT)],
        stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    os.close(slave)
    try:
        # 子の stdout を非ブロッキングにして、プロンプト再表示を待ってから q を
        # 送る（固定 sleep に頼らず、drain が先行入力を食べ終えたことを出力で
        # 確認する）。
        flags = fcntl.fcntl(proc.stdout, fcntl.F_GETFL)
        fcntl.fcntl(proc.stdout, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        acc = b""
        deadline = time.time() + 10
        while b"[q]: " not in acc and time.time() < deadline:
            try:
                chunk = proc.stdout.read()
            except (BlockingIOError, TypeError):
                chunk = None
            if chunk:
                acc += chunk
            else:
                time.sleep(0.02)
        os.write(master, b"q")
        fcntl.fcntl(proc.stdout, fcntl.F_SETFL, flags)
        rest = proc.stdout.read()
        if rest:
            acc += rest
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        os.close(master)

    out = acc.decode()
    assert "先行入力" in out          # 先行入力を破棄・警告した
    assert "7バイト" in out           # echo $? の7バイト（改行は空文字として消費）
    assert proc.returncode == 0       # 再表示後の q が受理された


# --- 実行不能コマンドの扱いの常設（ADR-016 案C / Issue #241） --------------
#
# ADR-016（docs/decisions/ADR-016-executor-allowed-pytest.md）の案C は、
# 実行役が実行できないコマンド（シェルスクリプトの直接実行・python -c 等）を
# 試みず報告に記載するだけにとどめるよう instruction 側で明示すると決めた。
# 6 回目試走で停止したのは round_1 のため、round_1 用の instruction 雛形
# （docs/ai_loop_state/instruction_template.md）と round_2 以降の起案役
# プロンプト（scripts/review_proposer_prompt.md）の両方に常設する。
#
# 文面の正本は docs/ai_loop_state/executor_command_constraints.md に置き、
# 転記先 2 ファイルに正本全文が含まれることをここで固定する（正本ファイルを
# 単一の情報源とし、テスト側に文面をハードコードしない）。SCRIPT の解決に
# 使っているリポジトリルート（Path(__file__).resolve().parent.parent）を流用する。

_REPO_ROOT = SCRIPT.parent.parent
_CONSTRAINTS_CANON = _REPO_ROOT / "docs" / "ai_loop_state" / "executor_command_constraints.md"
_PROPOSER_PROMPT = _REPO_ROOT / "scripts" / "review_proposer_prompt.md"
_INSTRUCTION_TEMPLATE = _REPO_ROOT / "docs" / "ai_loop_state" / "instruction_template.md"


def _constraints_canon_text() -> str:
    """正本ファイルの全文から前後の空白を除いた文字列。"""
    return _CONSTRAINTS_CANON.read_text(encoding="utf-8").strip()


def test_proposer_prompt_embeds_command_constraints():
    """ADR-016 案C / Issue #241: 起案役プロンプト（round_2 以降）に、実行
    不能コマンドの扱いの正本文面が全文そのまま部分文字列として含まれる。"""
    assert _constraints_canon_text() in _PROPOSER_PROMPT.read_text(encoding="utf-8")


def test_instruction_template_embeds_command_constraints():
    """ADR-016 案C / Issue #241: round_1 用 instruction 雛形に、実行不能
    コマンドの扱いの正本文面が全文そのまま部分文字列として含まれる。"""
    assert _constraints_canon_text() in _INSTRUCTION_TEMPLATE.read_text(encoding="utf-8")
