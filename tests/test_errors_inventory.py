"""scripts/check_errors_inventory.sh のテスト。

このスクリプトは docs/errors_md_inventory.md（ERRORS.md の棚卸し分析文書、
作成 2026-08-23）の記載値が、現行の ERRORS.md の実測値と乖離して
いないかを機械的に検出する（Issue #193 の前提整備）。Issue #193 作業内容1
（No.3 の見出し分割）に伴い、棚卸し文書の統計値（総行数・見出し数）を実測へ
更新済みのため、現時点では引数なし実行は「終了コード0で一致するのが正常」。
以後、この一致が崩れたら落ちる常設のゲートとして機能する。

検査項目は6つ。検査1（総行数）・検査2（見出し数）に加え、Issue #286 決定1・2
および Issue #292 を受けて次の3検査が追加され、さらに Issue #281・ADR-025を
受けて検査6が追加された。

- 検査3: 分類表の各行の行範囲が ERRORS.md の実測と一致するか
- 検査4: 分類表を集計した A/B/C と合計が「分類の内訳件数」節の記載値と一致するか
- 検査5: 分類表に対応する行を持たない見出しが、除外一覧に載っているもの以外に
  存在しないか
- 検査6: 分類表の見出し列が ERRORS.md の見出し実体（`## ` を除いた文字列）と
  完全一致するか（行範囲を持たない行は対象外）

乖離時の挙動（標準エラーへの記載値・実測値の出力）はフィクスチャ（tmp_path
に書き出すダミーの ERRORS.md / inventory）で検証し、実リポジトリの値には
依存しない。フィクスチャの見出し文字列は実在の記録を引用せず架空のものを使う。

負の対照は検査ごとに1つずつ用意し、その検査だけが鳴り他の検査は鳴らないことを
標準エラーの内容で確認する（どの検査が落ちたかが観測可能に異なる）。

テスト方式は tests/test_check_review_comment.py と同じく pytest から
subprocess でシェルスクリプトを呼ぶ形。bats 等は requirements-dev.txt に無く、
tests/ 配下に置けば ./scripts/verify.sh に追加配線なしで含まれる。
"""
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_errors_inventory.sh"
ERRORS_MD = REPO_ROOT / "ERRORS.md"
INVENTORY_MD = REPO_ROOT / "docs" / "errors_md_inventory.md"

EXCLUDE_SECTION = "### 本表の対象外とする見出し"
RANGE_RE = re.compile(r"^(\d+)-(\d+)$")

# 実測すると 5 行・見出し 2 件、行範囲は 1-2 と 3-5 になるダミー ERRORS.md。
DUMMY_ERRORS_TEXT = (
    "## first heading\n"
    "body line\n"
    "## second heading\n"
    "another line\n"
    "last line\n"
)
# 上のダミーと整合する分類表の行と内訳件数。
DUMMY_ROWS = (
    ("1", "1-2", "first heading", "A"),
    ("2", "3-5", "second heading", "B"),
)
DUMMY_COUNTS = {"A": "1", "B": "1", "C": "0", "total": "2"}

# 検査5の負の対照・除外機構の確認で使う、見出しを1件足したダミー。
# 実測すると 7 行・見出し 3 件になり、3 件目（6 行目）は分類表に行が無い。
DUMMY_ERRORS_TEXT_EXTRA_HEADING = DUMMY_ERRORS_TEXT + "## third heading\ntail line\n"


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


def _build_inventory(total_lines_value, headings_value, rows, counts, excluded):
    """統計表・分類表・内訳件数・除外一覧を備えたダミー inventory を組み立てる。

    検査3〜5は分類表・内訳件数・除外一覧を読むため、統計表だけのダミーでは
    それらの検査が入力を持たない。整合した一式を作り、テストごとに崩したい
    箇所だけを引数で崩す。
    """
    lines = [
        "# dummy inventory",
        "",
        "| 項目 | 値 |",
        "|---|---|",
        "| 総行数 | {}行 |".format(total_lines_value),
        "| 見出し数（`## `） | {}件 |".format(headings_value),
        "",
        "## 手順2: 各項目の分類",
        "",
        "| No | 行範囲 | 見出し | 分類 | 根拠 |",
        "|---|---|---|---|---|",
    ]
    for no, cell, heading, cls in rows:
        lines.append(
            "| {} | {} | {} | {} | dummy rationale |".format(no, cell, heading, cls)
        )
    lines += [
        "",
        "### 分類の内訳件数",
        "",
        "| 分類 | 件数 |",
        "|---|---|",
        "| A（dummy） | {} |".format(counts["A"]),
        "| B（dummy） | {} |".format(counts["B"]),
        "| C（dummy） | {} |".format(counts["C"]),
        "| 判定不能 | 0 |",
        "| **合計** | **{}** |".format(counts["total"]),
        "",
        EXCLUDE_SECTION,
        "",
    ]
    for heading_line in excluded:
        lines.append("- `{}`".format(heading_line))
    lines.append("")
    return "\n".join(lines)


def _write_fixture(
    tmp_path,
    total_lines_value,
    headings_value,
    errors_text=DUMMY_ERRORS_TEXT,
    rows=DUMMY_ROWS,
    counts=None,
    excluded=(),
):
    errors = tmp_path / "ERRORS.md"
    errors.write_text(errors_text, encoding="utf-8")
    inventory = tmp_path / "inventory.md"
    inventory.write_text(
        _build_inventory(
            total_lines_value,
            headings_value,
            rows,
            dict(DUMMY_COUNTS) if counts is None else counts,
            excluded,
        ),
        encoding="utf-8",
    )
    return {"ERRORS_MD": str(errors), "INVENTORY_MD": str(inventory)}


def _write_dummy(tmp_path, total_lines_value, headings_value):
    """統計値だけを引数で崩す、内部的に整合したダミー一式。"""
    return _write_fixture(tmp_path, total_lines_value, headings_value)


def _real_heading_spans():
    """実リポジトリの ERRORS.md から、見出し開始行 -> 終了行の対応を独立に算出する。"""
    lines = ERRORS_MD.read_text(encoding="utf-8").splitlines()
    starts = [i + 1 for i, line in enumerate(lines) if line.startswith("## ")]
    ends = starts[1:] + [len(lines) + 1]
    return {s: e - 1 for s, e in zip(starts, ends)}, lines


def _real_table_rows():
    """実リポジトリの棚卸し文書から、分類表の行（No/行範囲/分類）を独立に取り出す。"""
    rows = []
    for line in INVENTORY_MD.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        if len(parts) < 6:
            continue
        no = parts[1].strip()
        if not no[:1].isdigit():
            continue
        rows.append((no, parts[2].strip(), parts[4].strip()))
    return rows


def _real_table_rows_with_heading():
    """実リポジトリの棚卸し文書から、分類表の行（No/行範囲/見出し/分類）を独立に取り出す。

    検査6のテスト専用。既存の _real_table_rows（No/行範囲/分類の3要素）を
    使う既存テストのアンパック数を変えないため、別関数として用意する。
    """
    rows = []
    for line in INVENTORY_MD.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        if len(parts) < 6:
            continue
        no = parts[1].strip()
        if not no[:1].isdigit():
            continue
        rows.append((no, parts[2].strip(), parts[3].strip(), parts[4].strip()))
    return rows


def _real_excluded_headings():
    """実リポジトリの棚卸し文書の除外一覧を独立に読み取る（行番号は使わない）。"""
    excluded = set()
    in_section = False
    for line in INVENTORY_MD.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            in_section = line.strip() == EXCLUDE_SECTION
            continue
        if in_section:
            entry = re.match(r"^- `(.+)`$", line.strip())
            if entry:
                excluded.add(entry.group(1))
    return excluded


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


def test_repo_line_ranges_match_measurement():
    """検査3の正の対照。実リポジトリで終了コード0になり、かつ分類表の行範囲が
    ERRORS.md の実測と一致する（テスト側でも独立に算出して突き合わせる）。
    """
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    spans, _lines = _real_heading_spans()
    checked = 0
    for no, cell, _cls in _real_table_rows():
        matched = RANGE_RE.match(cell)
        if matched is None:
            # 退避先を書いた行は行範囲を持たないため検査3の対象外。
            continue
        start, end = int(matched.group(1)), int(matched.group(2))
        assert start in spans, no
        assert spans[start] == end, no
        checked += 1
    assert checked > 0, "行範囲を持つ行が1件も無いなら検査3が空振りしている"


def test_repo_classification_counts_match_table():
    """検査4の正の対照。実リポジトリで終了コード0になり、かつ分類表を集計した
    A/B/C と合計が「分類の内訳件数」節の記載値と一致する。
    """
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = _real_table_rows()
    assert rows, "分類表の行が1件も無いなら検査4が空振りしている"
    actual = {"A": 0, "B": 0, "C": 0}
    for _no, _cell, cls in rows:
        key = cls.replace("*", "").strip()
        if key in actual:
            actual[key] += 1
    inventory_lines = INVENTORY_MD.read_text(encoding="utf-8").splitlines()
    for key in ("A", "B", "C"):
        doc_count = None
        label = re.compile(r"^\|\s*%s（" % key)
        for line in inventory_lines:
            if label.match(line):
                doc_count = int(re.search(r"\d+", line.split("|")[2]).group(0))
                break
        assert doc_count == actual[key], key
    doc_total = None
    for line in inventory_lines:
        if re.match(r"^\|\s*\*\*合計\*\*", line):
            doc_total = int(re.search(r"\d+", line.split("|")[2]).group(0))
            break
    assert doc_total == len(rows)


def test_repo_headings_without_table_row_are_all_excluded():
    """検査5の正の対照。実リポジトリで終了コード0になり、かつ分類表に対応する
    行を持たない見出しがすべて除外一覧に載っている。

    突き合わせに失敗した場合も見出し文字列は出さず行番号だけを示す
    （ADR-022 の運用規約）。
    """
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    spans, errors_lines = _real_heading_spans()
    covered = set()
    for _no, cell, _cls in _real_table_rows():
        matched = RANGE_RE.match(cell)
        if matched:
            covered.add(int(matched.group(1)))
    excluded = _real_excluded_headings()
    uncovered = sorted(s for s in spans if s not in covered)
    assert uncovered, "対応する行を持たない見出しが無いなら除外一覧の検査が空振り"
    missing = [s for s in uncovered if errors_lines[s - 1] not in excluded]
    assert missing == [], missing


def test_repo_heading_column_matches_measurement():
    """検査6の正の対照。実リポジトリで終了コード0になり、かつ行範囲を持つ行の
    見出し列が ERRORS.md の見出し実体（`## ` を除いた文字列）と完全一致する
    （テスト側でも独立に算出して突き合わせる）。
    """
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    spans, errors_lines = _real_heading_spans()
    checked = 0
    for no, cell, heading, _cls in _real_table_rows_with_heading():
        matched = RANGE_RE.match(cell)
        if matched is None:
            # 退避先を書いた行は行範囲を持たないため検査6の対象外。
            continue
        start = int(matched.group(1))
        assert start in spans, no
        actual_heading = errors_lines[start - 1][3:]
        assert heading == actual_heading, no
        checked += 1
    assert checked > 0, "行範囲を持つ行が1件も無いなら検査6が空振りしている"


def test_line_range_mismatch_dummy_exits_nonzero(tmp_path):
    """検査3の負の対照。行範囲だけを実測からずらすと、その検査だけが鳴る。"""
    rows = (
        ("1", "1-2", "first heading", "A"),
        ("2", "3-4", "second heading", "B"),  # 実測は 3-5
    )
    env = _write_fixture(tmp_path, "5", "2", rows=rows)
    proc = _run(env)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "行範囲(No.2)" in proc.stderr, proc.stderr
    assert "3-4" in proc.stderr and "3-5" in proc.stderr, proc.stderr
    # 他の検査は鳴っていない（落ち方が観測可能に異なる）。
    assert "分類内訳" not in proc.stderr, proc.stderr
    assert "未対応見出し" not in proc.stderr, proc.stderr
    assert "総行数" not in proc.stderr, proc.stderr
    assert "見出し数" not in proc.stderr, proc.stderr


def test_classification_count_mismatch_dummy_exits_nonzero(tmp_path):
    """検査4の負の対照（A/B/C）。内訳件数だけをずらすと、その検査だけが鳴る。"""
    counts = {"A": "9", "B": "1", "C": "0", "total": "2"}
    env = _write_fixture(tmp_path, "5", "2", counts=counts)
    proc = _run(env)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "分類内訳(A)" in proc.stderr, proc.stderr
    assert "9" in proc.stderr, proc.stderr
    assert "行範囲" not in proc.stderr, proc.stderr
    assert "未対応見出し" not in proc.stderr, proc.stderr
    assert "総行数" not in proc.stderr, proc.stderr
    assert "見出し数" not in proc.stderr, proc.stderr


def test_classification_total_mismatch_dummy_exits_nonzero(tmp_path):
    """検査4の負の対照（合計）。合計だけをずらすと、その検査だけが鳴る。"""
    counts = {"A": "1", "B": "1", "C": "0", "total": "9"}
    env = _write_fixture(tmp_path, "5", "2", counts=counts)
    proc = _run(env)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "分類内訳(合計)" in proc.stderr, proc.stderr
    assert "9" in proc.stderr, proc.stderr
    assert "分類内訳(A)" not in proc.stderr, proc.stderr
    assert "行範囲" not in proc.stderr, proc.stderr
    assert "未対応見出し" not in proc.stderr, proc.stderr


def test_heading_without_table_row_dummy_exits_nonzero(tmp_path):
    """検査5の負の対照。分類表に行が無く除外一覧にも無い見出しを足すと鳴る。"""
    env = _write_fixture(
        tmp_path, "7", "3", errors_text=DUMMY_ERRORS_TEXT_EXTRA_HEADING
    )
    proc = _run(env)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "未対応見出し(ERRORS.md 6行目)" in proc.stderr, proc.stderr
    assert "行範囲" not in proc.stderr, proc.stderr
    assert "分類内訳" not in proc.stderr, proc.stderr
    assert "総行数" not in proc.stderr, proc.stderr
    assert "見出し数" not in proc.stderr, proc.stderr


def test_heading_mismatch_dummy_exits_nonzero(tmp_path):
    """検査6の負の対照。見出し列だけを実測から食い違わせると、その検査だけが鳴る。

    フィクスチャの見出し文字列は架空のもの（"wrong heading"）を使う。
    """
    rows = (
        ("1", "1-2", "first heading", "A"),
        ("2", "3-5", "wrong heading", "B"),  # 実測は "## second heading"
    )
    env = _write_fixture(tmp_path, "5", "2", rows=rows)
    proc = _run(env)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "見出し一致(No.2)" in proc.stderr, proc.stderr
    # 見出し文字列そのものは出さず、文字数のみを出す（ADR-022 の運用規約）。
    assert "wrong heading" not in proc.stderr, proc.stderr
    assert "second heading" not in proc.stderr, proc.stderr
    assert "13文字" in proc.stderr and "14文字" in proc.stderr, proc.stderr
    # 他の検査は鳴っていない（落ち方が観測可能に異なる）。
    assert "行範囲" not in proc.stderr, proc.stderr
    assert "分類内訳" not in proc.stderr, proc.stderr
    assert "未対応見出し" not in proc.stderr, proc.stderr
    assert "総行数" not in proc.stderr, proc.stderr
    assert "見出し数" not in proc.stderr, proc.stderr


def test_excluded_heading_without_table_row_exits_zero(tmp_path):
    """除外一覧に見出し文字列を載せれば、分類表に行が無くても通る。

    除外の判定が行番号ではなく見出し文字列で行われていることの確認でもある。
    """
    env = _write_fixture(
        tmp_path,
        "7",
        "3",
        errors_text=DUMMY_ERRORS_TEXT_EXTRA_HEADING,
        excluded=("## third heading",),
    )
    proc = _run(env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "OK"


def test_does_not_modify_repo_files(tmp_path):
    """引数なし実行後もリポジトリ本体の ERRORS.md / inventory は不変。"""
    before_errors = ERRORS_MD.read_bytes()
    before_inventory = INVENTORY_MD.read_bytes()
    _run()
    assert ERRORS_MD.read_bytes() == before_errors
    assert INVENTORY_MD.read_bytes() == before_inventory
