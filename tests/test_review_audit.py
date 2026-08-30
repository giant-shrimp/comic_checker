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
import re
import subprocess

from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "review_audit.sh"
PROMPT = Path(__file__).resolve().parent.parent / "scripts" / "review_audit_prompt.md"
REVIEW_LOOP = Path(__file__).resolve().parent.parent / "scripts" / "review_loop.sh"


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


def test_empty_result_field_returns_exit_3(tmp_path):
    """(10) resultフィールドが空文字列("")のときはexit 0にならず、
    「VERDICTを抽出できない」分岐（exit 3）へ入り、verdict.txtも作られない。

    jqの `//` は空文字列をnull/falseと区別せず真値として扱うため、
    `jq -r '.result // empty' > review.md` は .result="" のとき review.md を
    1バイト（改行のみ）にする。review_audit.sh はこの review.md を
    `[ ! -s ]` のようなファイルサイズ判定ではなく、`head -n1` で1行目を
    取り出して VERDICT 正規表現に掛ける方式で検査しているため、
    1行目が空文字列 → 正規表現に一致せず → exit 3 という意図した分岐へ入る。
    review_proposer.sh の同名回帰テスト（tests/test_review_proposer.py の
    test_empty_result_field_does_not_exit_normally）と対になる、
    「問題ないと判定した箇所」を実行で裏付けるためのテスト。"""
    _write_result_json(tmp_path, result="")
    result = _run_process_result(tmp_path)
    assert result.returncode == 3
    assert result.returncode != 0
    assert not (tmp_path / "verdict.txt").exists()


def test_verdict_line_present_but_not_on_first_line_returns_exit_3(tmp_path):
    """(9) `VERDICT: APPROVE_CONTINUE`という行自体は存在するが1行目ではなく
    3行目にあるならexit 3（1行目限定が外れていないことを確認する）。

    ケース3（本文中にAPPROVE_CONTINUEという裸の単語を含むだけでVERDICT:
    接頭辞を伴わない）とは違い、これは「VERDICT: <値>」という行自体が
    本文のどこかに実在するケースである。1行目限定を外し本文全体から
    grep等で検索する変異は、ケース3では検出できないことが実測で判明した
    （VERDICT: 接頭辞を伴わない裸の単語には元々ヒットしないため）。
    このケースはその変異を確実に検出するために追加した。
    """
    _write_result_json(
        tmp_path,
        result=(
            "この監査は以下の通りである。\n"
            "本文の続きはこちら。\n"
            "VERDICT: APPROVE_CONTINUE\n"
            "\nCONTRADICTIONS:\n- なし\n"
        ),
    )
    result = _run_process_result(tmp_path)
    assert result.returncode == 3
    assert not (tmp_path / "verdict.txt").exists()


# --- review_audit_prompt.md の diff 節ガイド（Issue #231 / ADR-015 案C＝段2） ---
#
# 段1（案D）で review_loop.sh の write_diff_evidence() が diff.txt を2節構成
# （=== git status --porcelain === / === git diff ===）で書くようになった。
# 段2では、その読み方と照合手順を監査役プロンプト（review_audit_prompt.md）に
# 明記した。以下はプロンプト本文に必要な要素が含まれることの静的な確認である。
#
# 限界: これらは文字列の存在確認に留まる。監査役は opus の LLM であり、
# 追記した手順に実際に従って未追跡ファイルを Read し照合するか、という
# 実挙動は pytest では検証できない（ADR-015「識別力は未検証（宣言）」）。

def _diff_evidence_headings() -> tuple:
    """scripts/review_loop.sh の DIFF_EVIDENCE_*_HEADING 定数の値を
    (status見出し, diff見出し) で返す。見出し文字列をテスト側に
    ハードコードせず、段1のソースと一致していることを保証する。"""
    text = REVIEW_LOOP.read_text(encoding="utf-8")
    status = re.search(r'DIFF_EVIDENCE_STATUS_HEADING="([^"]*)"', text).group(1)
    diff = re.search(r'DIFF_EVIDENCE_DIFF_HEADING="([^"]*)"', text).group(1)
    return status, diff


def test_prompt_references_both_diff_evidence_headings():
    """段2: プロンプト本文に、段1の見出し定数（=== git status --porcelain ===
    と === git diff ===）と一字一句一致する文字列が両方含まれる。

    限界: 見出しが「書かれている」ことしか確認できない。監査役が実際に
    2節を読み分けるかは検証対象外。"""
    prompt = PROMPT.read_text(encoding="utf-8")
    status_heading, diff_heading = _diff_evidence_headings()
    assert status_heading in prompt
    assert diff_heading in prompt


def test_prompt_instructs_reading_untracked_files():
    """段2: プロンプトが「?? 行の未追跡ファイルは Read して報告書と照合せよ」
    という趣旨を含む（`??` と `Read` の両方に言及している）。

    限界: 文字列の存在確認のみ。監査役がこの手順に従うかは pytest では
    検証できない（ADR-015「識別力は未検証」）。"""
    prompt = PROMPT.read_text(encoding="utf-8")
    assert "??" in prompt
    assert "Read" in prompt
    # 「未追跡」への言及もあること（?? が何を指すかの説明がある）。
    assert "未追跡" in prompt


def test_prompt_warns_empty_diff_section_is_not_no_change():
    """段2: プロンプトが「git diff 節が空でも変更が無いとは限らない、
    status 節を先に読め」という趣旨を含む。

    限界: 文字列の存在確認のみ。"""
    prompt = PROMPT.read_text(encoding="utf-8")
    status_heading, _ = _diff_evidence_headings()
    assert "空でも" in prompt or "空であっても" in prompt
    # status 節を先に読む旨の指示。
    assert status_heading in prompt


def test_prompt_notes_auditor_cannot_run_git():
    """段2: プロンプトが「監査役は Bash が deny で git を自分で実行できない」
    旨を明記している（だから diff.txt の内容に頼る必要がある、という前提）。

    限界: 文字列の存在確認のみ。"""
    prompt = PROMPT.read_text(encoding="utf-8")
    assert "Bash" in prompt and "deny" in prompt


def test_prompt_guide_is_addition_not_rewrite():
    """段2: 既存の節（## diff / ## 検証コマンド / ## 作業者の報告書 /
    ## 出力形式）と VERDICT の4値・CONTRADICTIONS・FOLLOWUPS の指示は
    そのまま残っている（追記のみで書き換えていない）。"""
    prompt = PROMPT.read_text(encoding="utf-8")
    for marker in (
        "## diff",
        "## 検証コマンド（./scripts/verify.sh）の実出力",
        "## 作業者の報告書",
        "## 出力形式（必ずこの形式で出力すること）",
        "APPROVE_CONTINUE",
        "REVISE",
        "HALT_NEEDS_HUMAN",
        "DONE",
        "CONTRADICTIONS:",
        "FOLLOWUPS:",
        "{{DIFF}}",
        "{{VERIFY}}",
        "{{REPORT}}",
    ):
        assert marker in prompt
