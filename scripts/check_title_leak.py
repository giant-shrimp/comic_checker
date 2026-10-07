#!/usr/bin/env python3
"""報告の下書きに実在作品名が紛れていないかを走査する CLI。

ERRORS.md の漏洩系記録（作品名を報告に書いてしまった一連の再発、
`docs/errors_md_inventory.md` の No.50・51・54・60・63・65〜73）の再発防止として、
ai-loop プラグインの report-self-check（`/ai-loop:report-self-check`）から呼ばれることを想定している。

辞書は、Issue #331 の起票前の調査で特定した JSON 29ファイル
（`TITLE_KEY_FILES` の27ファイル＋`TITLE_ARRAY_FILES` の2ファイル）から実行時に
読み込む。辞書の実体（作品名そのもの）はファイルとして保存しない。スクリプトが
持つのは「どのファイルのどのキーを読むか」という定数表だけであり、作品名は
このスクリプトのソースにも書かない。`tests/test.xlsx` は辞書の対象外
（xlsxであり対象キーを持つJSONではないため、そもそも対象外）。

`TITLE_KEY_FILES` の各ファイルは、指定したキー名と同名のキーが、ネストした
位置に複数回現れることがある（例: 集計用の件数（int）と実際の一覧（list）が
同じキー名で別の階層に存在する）。走査は再帰的に同名キーをすべて集め、値が
文字列または文字列のリストであるものだけを辞書に加える（int・None 等は無視）。

--dict-file PATH を指定すると、上記の定数表を使わず、PATH（文字列の JSON 配列）
だけを辞書として使う（テスト用）。

判定: 各行に対する部分一致。一致した辞書エントリの文字数（`len()`）で分類する。

    4文字以上の一致 → 検出
    2〜3文字の一致  → 警告
    1文字の一致    → 照合しない（辞書に1文字のエントリがあっても対象外）

1行の中に複数の一致がある場合、検出側の一致があればその中の最長の文字数を、
無ければ警告側の一致の中の最長の文字数を、その行の判定として1件だけ報告する。

出力（標準エラー）: `入力名:行番号: 検出（N文字）` または `入力名:行番号: 警告（N文字）`
だけ。作品名・行の本文・前後の文字列は出力しない。

使い方:
    scripts/check_title_leak.py PATH [PATH ...]
        引数のファイルを走査する。
    ... | scripts/check_title_leak.py
    scripts/check_title_leak.py -
        引数が無い、または引数が `-` であれば標準入力を読む（ラベルは `<stdin>`）。
    scripts/check_title_leak.py --dict-file DICT.json PATH [PATH ...]
        DICT.json（文字列の JSON 配列）を辞書として使う。

終了コード:
    0   検出0件（警告のみ・ヒット無しを含む）
    1   検出1件以上
    2   利用者側の誤り（存在しないパス・読み取り不可等）
    3   辞書の読み込みに失敗した（定数表のファイルが1つでも無い・読めない・
        JSON として不正、または辞書が0件、あるいは --dict-file が同様の状態）。
        照合を実施せずに終了する（fail-closed）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_HIT = 1
EXIT_USAGE_ERROR = 2
EXIT_DICT_LOAD_ERROR = 3

DETECTION_MIN_LEN = 4
WARNING_MIN_LEN = 2

# --- 辞書の定数表（ファイルパス→ネストして探すキー名） -----------------------
# 実体（作品名）はここには書かない。実行時に各ファイルを読み込んで抽出する。

TITLE_KEY_FILES = {
    "docs/code_defects_2026-08/holdout_pool_consumption_ledger.json": {"titles"},
    "docs/holdout2_measurement_2026-08/existing160_mutation_impact_result.json": {"title"},
    "docs/holdout2_measurement_2026-08/holdout2_judge_comparison_result.json": {"title"},
    "docs/holdout2_measurement_2026-08/holdout2_labels_auto.json": {"title"},
    "docs/holdout2_measurement_2026-08/holdout2_labels_v4.json": {"title"},
    "docs/holdout2_measurement_2026-08/holdout2_labels_v4_partial_1-30.json": {"title"},
    "docs/holdout2_measurement_2026-08/holdout2_labels_v4_partial_31-60.json": {"title"},
    "docs/holdout2_measurement_2026-08/holdout2_labels_v4_partial_61-90.json": {"title"},
    "docs/holdout2_measurement_2026-08/holdout2_labels_v4_partial_91-119.json": {"title"},
    "docs/holdout2_measurement_2026-08/holdout2_mutation_impact_result.json": {
        "changed_titles",
        "title",
    },
    "docs/holdout2_measurement_2026-08/holdout2_sample_titles.json": {"sample_titles"},
    "docs/holdout2_measurement_2026-08/holdout2_wikitext.json": {
        "input_title",
        "matched_title",
    },
    "docs/holdout2_measurement_2026-08/spotcheck20_human_labels.json": {"title"},
    "docs/holdout2_measurement_2026-08/spotcheck20_presentation.json": {"title"},
    "docs/holdout2_measurement_2026-08/spotcheck20_v4_keymap.json": {"title"},
    "docs/holdout2_measurement_2026-08/spotcheck20_v4_presentation.json": {"title"},
    "docs/holdout2_measurement_2026-08/spotcheck20_v4_sample.json": {
        "confused_true_titles",
        "sample_titles",
    },
    "docs/holdout_measurement_2026-08/holdout_wikitext.json": {
        "input_title",
        "matched_title",
    },
    "docs/holdout_measurement_2026-08/step98_a3_labels.json": {
        "input_title",
        "matched_title",
    },
    "docs/holdout_measurement_2026-08/step98_a3_raw_material.json": {
        "input_title",
        "matched_title",
    },
    "docs/holdout_measurement_2026-08/step98_a_labeling_rules_v3.json": {
        "title",
        "titles",
    },
    "docs/holdout_measurement_2026-08/step98_b_compare_result.json": {
        "input_title",
        "judge_matched_title",
    },
    "docs/holdout_measurement_2026-08/step98_b_judge_raw.json": {
        "input_title",
        "matched_title",
    },
    "docs/holdout_pool_2026-08/step90_1_used_titles.json": {
        "test_fixture_titles",
        "unique_used_titles",
    },
    "docs/holdout_pool_2026-08/step93_2_holdout_pool.json": {"holdout_pool_titles"},
    "docs/regression_corpus_2026-08/regression_corpus_raw.json": {
        "input_title",
        "matched_title",
    },
    "docs/regression_corpus_2026-08/regression_corpus_wikitext.json": {
        "input_title",
        "matched_title",
    },
}

# トップレベルが配列の2ファイル。要素（文字列）をすべて辞書に加える。
TITLE_ARRAY_FILES = [
    "docs/holdout_measurement_2026-08/step98_a2_sample100_titles.json",
    "docs/holdout_pool_2026-08/step98_a2_sample100_titles.json",
]


def _collect_key_values(obj, keys, out):
    """`obj` を再帰的に走査し、`keys` と同名のキーの値（文字列・文字列のリスト）を集める。"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys:
                if isinstance(value, str):
                    if value:
                        out.add(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item:
                            out.add(item)
            _collect_key_values(value, keys, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_key_values(item, keys, out)


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_builtin_dictionary():
    """定数表（`TITLE_KEY_FILES`・`TITLE_ARRAY_FILES`）から辞書を組み立てる。

    定数表のファイルが1つでも読めない・JSONとして不正であれば `None` を返す
    （fail-closed）。辞書が0件になった場合も `None` を返す。
    """
    repo_root = Path(__file__).resolve().parent.parent
    titles = set()

    for rel_path, keys in TITLE_KEY_FILES.items():
        try:
            data = _load_json(repo_root / rel_path)
        except (OSError, json.JSONDecodeError):
            return None
        _collect_key_values(data, keys, titles)

    for rel_path in TITLE_ARRAY_FILES:
        try:
            data = _load_json(repo_root / rel_path)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, list):
            return None
        for item in data:
            if isinstance(item, str) and item:
                titles.add(item)

    return titles or None


def load_dict_file(path):
    """`--dict-file` で指定された、文字列の JSON 配列を辞書として読み込む。

    ファイルが読めない・JSONとして不正・配列でない・文字列以外の要素を含む・
    辞書が0件のいずれかであれば `None` を返す（fail-closed）。
    """
    try:
        data = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        return None
    titles = {x for x in data if x}
    return titles or None


def classify_line(line, titles):
    """`line` に対する辞書の部分一致を判定する。

    一致が無ければ `None`。あれば `(区分, 文字数)` を返す（区分は "検出" か "警告"）。
    検出側の一致があれば検出側の最長一致を、無ければ警告側の最長一致を返す。
    """
    detection_len = 0
    warning_len = 0
    for title in titles:
        length = len(title)
        if length < WARNING_MIN_LEN:
            continue
        if title not in line:
            continue
        if length >= DETECTION_MIN_LEN:
            detection_len = max(detection_len, length)
        else:
            warning_len = max(warning_len, length)
    if detection_len:
        return "検出", detection_len
    if warning_len:
        return "警告", warning_len
    return None


def scan_lines(label, lines, titles):
    hits = []
    for lineno, raw in enumerate(lines, start=1):
        result = classify_line(raw.rstrip("\n"), titles)
        if result is not None:
            category, length = result
            hits.append((label, lineno, category, length))
    return hits


def scan_path(path, titles):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return scan_lines(path, text.splitlines(), titles)


def scan_stdin(titles, stream=None):
    stream = sys.stdin if stream is None else stream
    return scan_lines("<stdin>", stream.read().splitlines(), titles)


def _error_reason(exc):
    """`str(exc)` はファイル名（パス）を含むため使わず、`strerror` だけを使う。"""
    return exc.strerror if getattr(exc, "strerror", None) else exc.__class__.__name__


def _build_parser():
    parser = argparse.ArgumentParser(
        description="報告の下書きに実在作品名が紛れていないかを走査する CLI。",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="走査するファイル。省略時、または '-' 単体で指定時は標準入力を読む。",
    )
    parser.add_argument(
        "--dict-file",
        metavar="PATH",
        default=None,
        help="組み込みの定数表の代わりに使う、文字列の JSON 配列ファイル（テスト用）。",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.dict_file is not None:
        titles = load_dict_file(args.dict_file)
    else:
        titles = load_builtin_dictionary()

    if titles is None:
        print(
            "辞書の読み込みに失敗しました。照合を実施していません。",
            file=sys.stderr,
        )
        return EXIT_DICT_LOAD_ERROR

    hits = []
    if args.paths and args.paths != ["-"]:
        for path in args.paths:
            if path == "-":
                hits.extend(scan_stdin(titles))
                continue
            try:
                hits.extend(scan_path(path, titles))
            except OSError as exc:
                print(
                    f"{os.path.basename(path)}: 読み込めませんでした（{_error_reason(exc)}）",
                    file=sys.stderr,
                )
                return EXIT_USAGE_ERROR
    else:
        hits.extend(scan_stdin(titles))

    for label, lineno, category, length in hits:
        print(f"{label}:{lineno}: {category}（{length}文字）", file=sys.stderr)

    has_detection = any(category == "検出" for _, _, category, _ in hits)
    return EXIT_HIT if has_detection else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
