# -*- coding: utf-8 -*-
"""Issue #367（候補A4 案b）: 「本文（_judge_extract）が完結を返し、かつ
_judge_via_infobox が連載中を返すとき、最終statusを判定不能にする」という変更を
適用した場合に、before→afterでstatusが変わる行を数える。

comic_checker本体は変更しない。現行judge()の出力（before）と、その内訳
（ext・ibx）から、変更後の出力（after）をこのスクリプト側で計算して比較する
（実装の先取りではなく、変化の見積もり）。ネットワークは遮断し、通信を試みた
回数を末尾に出す（/tmp/a4_path.pyと同じ方法）。

各行について:
  before = docs/regression_corpus_2026-08/step98_judge_harness.py の
           run_judge_with_snapshot()（todayを固定して渡す）が返す最終status
           （現行judge()のまま）。
  ext    = _judge_extract(extract) のstatus。
  ibx    = wikitextがあれば _judge_via_infobox(wikitext, today=固定値) のstatus、
           なければNone。
  after  = before=="完結" かつ ext=="完結" かつ ibx=="連載中" のとき "判定不能"、
           それ以外はbeforeのまま（案bの変更を模擬。完結→判定不能の方向にしか
           動かない）。

today は datetime.date(2026, 8, 15) に固定する（scripts/gen_labeled_snapshot.py の
TODAYと同じ値であることをassertで確かめる）。

--dataset saved:
  scripts/gen_labeled_snapshot.py の build_cases() が返す保存データ160行を使う。
  識別子は "<データ名> no=<no>"。

--dataset holdout2:
  docs/holdout2_measurement_2026-08/holdout2_wikitext.json の rows を入力とし、
  期待ラベルは holdout2_labels_v4.json の expected_status を使う。
  行とラベルの対応づけは docs/holdout2_measurement_2026-08/
  step99_holdout2_judge_comparison.py と同じ方法：rowsの各行のmatched_titleを
  キーにして、labelsの title と突き合わせる（input_titleではなくmatched_title
  を使う。理由はstep99のモジュールdocstringに記載: matched_titleは記事解決後の
  実際の記事名であり、judge()の出力・v4ラベル付与時に参照された記事名と同じ
  識別子であるため）。matched_titleがNoneの行はstep99と同様に対応づけ不能として
  除外する。識別子は rows の通し番号（1始まり、rows全体に対する位置）。

出力には記事名・本文・evidence文字列は含めない（識別子・ラベル・statusのみ）。

リポジトリルートで実行する:
    .venv/bin/python docs/code_defects_2026-08/a4b_measure.py --dataset saved
"""
import argparse
import datetime
import json
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
sys.path.insert(0, str(_REPO_ROOT / "docs/regression_corpus_2026-08"))

import requests  # noqa: E402
import comic_checker.wikipedia_client as wc  # noqa: E402
import gen_labeled_snapshot as g  # noqa: E402
from step98_judge_harness import run_judge_with_snapshot  # noqa: E402

TODAY = datetime.date(2026, 8, 15)
assert TODAY == g.TODAY, "TODAYがgen_labeled_snapshot.TODAYと一致しない"

HOLDOUT2_WIKITEXT_FILE = _REPO_ROOT / "docs/holdout2_measurement_2026-08/holdout2_wikitext.json"
HOLDOUT2_LABELS_FILE = _REPO_ROOT / "docs/holdout2_measurement_2026-08/holdout2_labels_v4.json"

STATUS_COMPLETE = "完結"
STATUS_ONGOING = "連載中"
STATUS_UNKNOWN = wc.STATUS_UNKNOWN

# --- ネットワーク遮断（/tmp/a4_path.pyと同じ方法）-------------------------------------
network_attempts = []


class NetworkBlocked(Exception):
    pass


def _blocked(*_args, **_kwargs):
    network_attempts.append(1)
    raise NetworkBlocked()


requests.get = _blocked
requests.post = _blocked
requests.sessions.Session.request = _blocked


def compute_after(before, ext, ibx):
    """案bの変更を模擬したafter statusを返す（単調：完結→判定不能の方向のみ）。"""
    if before == STATUS_COMPLETE and ext == STATUS_COMPLETE and ibx == STATUS_ONGOING:
        return STATUS_UNKNOWN
    return before


def process_row(row):
    """1行から (before, ext, ibx, after) を計算する。rowはinput_title・matched_title・
    extract・url・wikitextを持つ辞書（保存データ・holdout2共通のスキーマ）。
    """
    extract = row["extract"]
    wikitext = row.get("wikitext")

    before_result = run_judge_with_snapshot(
        row["input_title"], row["matched_title"], extract, row["url"], wikitext, today=TODAY)
    before = before_result.status

    try:
        ext_status, _ext_evidence = wc._judge_extract(extract)
    except Exception as exc:
        ext_status = "例外(%s)" % type(exc).__name__

    if wikitext:
        try:
            ibx_status, _ibx_evidence = wc._judge_via_infobox(wikitext, today=TODAY)
        except Exception as exc:
            ibx_status = "例外(%s)" % type(exc).__name__
    else:
        ibx_status = None

    after = compute_after(before, ext_status, ibx_status)
    return before, ext_status, ibx_status, after


def load_saved_entries():
    """保存データ160行を (識別子, 期待ラベル, row辞書) のリストで返す。"""
    entries = []
    for case in g.build_cases():
        identifier = "%s no=%d" % (case.dataset, case.no)
        entries.append((identifier, case.expected, case.row))
    return entries


def load_holdout2_entries():
    """holdout2のrowsを (識別子, 期待ラベル, row辞書) のリストで返す。

    対応づけの方法（step99_holdout2_judge_comparison.pyと同じ）:
    rowsを通し番号1始まりで走査し、matched_titleがNoneの行は対応づけ不能として
    除外する（step99の「matched_titleがNoneのため集計から除外」と同じ扱い）。
    残った行はmatched_titleをキーに、labelsのtitleと一致するexpected_statusを
    引く。labelsに見つからない行（expectedがNone）は除外せず対象に残し、件数だけ
    数えて返す。識別子はrows全体に対する通し番号（1始まり）。
    """
    wikitext_rows = json.load(open(HOLDOUT2_WIKITEXT_FILE, encoding="utf-8"))["rows"]
    labels = json.load(open(HOLDOUT2_LABELS_FILE, encoding="utf-8"))["labels"]
    label_by_title = {x["title"]: x["expected_status"] for x in labels}

    entries = []
    excluded_no_match = 0
    label_not_found = 0
    for i, row in enumerate(wikitext_rows, 1):
        identifier = str(i)
        if row.get("matched_title") is None:
            excluded_no_match += 1
            continue
        expected = label_by_title.get(row["matched_title"])
        if expected is None:
            label_not_found += 1
        entries.append((identifier, expected, row))
    return entries, excluded_no_match, label_not_found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=["saved", "holdout2"], required=True)
    args = parser.parse_args()

    excluded_no_match = 0
    label_not_found = 0
    if args.dataset == "saved":
        entries = load_saved_entries()
    else:
        entries, excluded_no_match, label_not_found = load_holdout2_entries()

    total_before_extract_filter = len(entries)
    excluded_empty_extract = [identifier for identifier, _expected, row in entries
                               if not row.get("extract")]
    entries = [(identifier, expected, row) for identifier, expected, row in entries
               if row.get("extract")]

    print("=== (1) 対象行数・除外行数 ===")
    print("読み込んだ行数（matched_title対応づけ後）: %d" % total_before_extract_filter)
    if args.dataset == "holdout2":
        print("除外（matched_titleがNone）: %d件" % excluded_no_match)
        print("期待ラベルが見つからない行: %d件" % label_not_found)
    print("除外（extractが空）: %d件" % len(excluded_empty_extract))
    print("対象行数: %d件" % len(entries))

    changed = []
    combo_counter = Counter()

    for identifier, expected, row in entries:
        before, ext, ibx, after = process_row(row)
        combo_counter[(ext, ibx)] += 1
        if before != after:
            changed.append((identifier, expected, before, after))

    print()
    print("=== (2) beforeが変わった行の明細 ===")
    print("識別子\t期待ラベル\tbefore→after")
    for identifier, expected, before, after in changed:
        print("%s\t%s\t%s→%s" % (identifier, expected, before, after))

    print()
    print("=== (3) 変わった行の件数（期待ラベル別） ===")
    expected_counter = Counter(expected for _identifier, expected, _before, _after in changed)
    for expected, count in sorted(expected_counter.items(), key=lambda kv: str(kv[0])):
        print("%s: %d件" % (expected, count))
    if not changed:
        print("（変わった行なし）")

    print()
    print("=== (4) before→afterの向きの集計 ===")
    direction_counter = Counter((before, after) for _identifier, _expected, before, after in changed)
    for (before, after), count in sorted(direction_counter.items(), key=lambda kv: str(kv[0])):
        print("%s→%s: %d件" % (before, after, count))
    violation = any(before != STATUS_COMPLETE or after != STATUS_UNKNOWN
                    for before, after in direction_counter)
    if changed and violation:
        print("単調性違反")
    elif not changed:
        print("（変わった行がないため向きの判定対象なし）")

    print()
    print("=== (5) ext×ibxの組み合わせ別の行数 ===")
    for (ext, ibx), count in sorted(combo_counter.items(), key=lambda kv: str(kv[0])):
        print("ext=%s\tibx=%s\t%d件" % (ext, ibx, count))

    print()
    print("=== (6) 通信 ===")
    print("通信を試みた回数（遮断済み）=%d" % len(network_attempts))


if __name__ == "__main__":
    main()
