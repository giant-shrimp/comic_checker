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


def _install_proposer_stub(script_dir: Path, body: str) -> None:
    """SCRIPT_DIR差し替え用の偽 review_proposer.sh を置く。

    本物と同じ引数（original-instruction / review.md / output-dir）を受け取り、
    argvを argv.txt に記録する。bodyで終了コードや出力を制御する。
    """
    stub = script_dir / "review_proposer.sh"
    stub.write_text(
        PROPOSER_STUB_HEADER
        + 'mkdir -p "$3"\n'
        + 'printf "%s\\n" "$1" "$2" "$3" > "$3/argv.txt"\n'
        + body,
        encoding="utf-8",
    )
    stub.chmod(0o755)


def _run_propose_next_instruction(script_dir: Path, original: Path, review_md: Path,
                                  round_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c",
         'source "$1"; SCRIPT_DIR="$2"; propose_next_instruction "$3" "$4" "$5"',
         "_", str(SCRIPT), str(script_dir), str(original), str(review_md), str(round_dir)],
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


def _run_wait_for_quit_only(keys: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; wait_for_quit_only "テスト理由"', "_", str(SCRIPT)],
        input=keys,
        capture_output=True,
        text=True,
    )


def test_wait_for_quit_only_accepts_q(tmp_path):
    """q の1キーで正常に抜ける（1キー入力という形式が保たれている）。"""
    result = _run_wait_for_quit_only("q")
    assert result.returncode == 0


def test_wait_for_quit_only_rejects_c(tmp_path):
    """c は受け付けない。ADR-014決定8が要求する「c を選べない」状態が、
    起案役の失敗時・NO_FURTHER_ACTION時に共通で使われるこの関数で成立する。"""
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
