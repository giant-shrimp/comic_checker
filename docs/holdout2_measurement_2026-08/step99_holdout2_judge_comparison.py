# -*- coding: utf-8 -*-
"""Issue #180 項目4・5: holdout2 120件に対しjudge()を実行し、v4ラベルと照合する。

事前登録 docs/code_defects_2026-08/prereg_holdout2_judge_comparison.md 4節の
手順1〜3に対応する。comic_checker/本体は変更しない。Wikipediaへの再取得は
行わない（保存済みのextract・wikitextのみ使用）。

結合キー: matched_title を使う。手順3の被覆確認で input_title・matched_title
いずれも labels（119件）との積集合が119件で一致したが、matched_titleは
Wikipedia記事解決後の実際の記事名であり、judge()の出力（WikipediaJudgment.
matched_title）およびv4ラベル付与時に参照された記事名と同じ識別子であるため、
input_titleより意味的に正確な対応関係を持つ。
"""
import json
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "docs/regression_corpus_2026-08"))
from step98_judge_harness import run_judge_with_snapshot  # noqa: E402

WIKITEXT_FILE = _REPO_ROOT / "docs/holdout2_measurement_2026-08/holdout2_wikitext.json"
LABELS_FILE = _REPO_ROOT / "docs/holdout2_measurement_2026-08/holdout2_labels_v4.json"
OUT_FILE = _REPO_ROOT / "docs/holdout2_measurement_2026-08/holdout2_judge_comparison_result.json"


def main():
    rows = json.load(open(WIKITEXT_FILE, encoding="utf-8"))["rows"]
    labels = json.load(open(LABELS_FILE, encoding="utf-8"))["labels"]
    label_by_title = {x["title"]: x["expected_status"] for x in labels}

    excluded = [r["input_title"] for r in rows if r.get("matched_title") is None]
    print(f"matched_titleがNoneのため集計から除外: {len(excluded)}件 {excluded}")

    records = []
    for r in rows:
        if r.get("matched_title") is None:
            continue
        result = run_judge_with_snapshot(
            r["input_title"], r["matched_title"], r["extract"], r["url"], r["wikitext"]
        )
        title = r["matched_title"]
        expected = label_by_title.get(title)
        records.append(
            {
                "title": title,
                "judge_status": result.status,
                "expected_status": expected,
                "match": result.status == expected,
            }
        )

    total = len(records)
    print(f"集計対象: {total}件")

    print("\n(1) judge()出力のカテゴリ別分布")
    status_counts = Counter(rec["judge_status"] for rec in records)
    for status, count in status_counts.most_common():
        print(f"  {status}: {count}件 ({count / total * 100:.1f}%)")

    print("\n(2) expected_statusとの一致件数・一致率")
    match_count = sum(1 for rec in records if rec["match"])
    print(f"  一致: {match_count}/{total}件 ({match_count / total * 100:.1f}%)")

    print("\n(3) 混同行列（judge_status × expected_status）")
    confusion = Counter((rec["judge_status"], rec["expected_status"]) for rec in records)
    judge_statuses = sorted(status_counts.keys())
    expected_statuses = sorted(set(rec["expected_status"] for rec in records))
    header = "judge\\expected".ljust(12) + "".join(s.ljust(10) for s in expected_statuses)
    print(f"  {header}")
    for js in judge_statuses:
        row_str = js.ljust(12) + "".join(
            str(confusion.get((js, es), 0)).ljust(10) for es in expected_statuses
        )
        print(f"  {row_str}")

    out = {
        "total": total,
        "excluded_matched_title_none": excluded,
        "status_distribution": dict(status_counts),
        "match_count": match_count,
        "match_rate": match_count / total,
        "confusion_matrix": {f"{js}|{es}": c for (js, es), c in confusion.items()},
        "records": records,
    }
    json.dump(out, open(OUT_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n結果を保存: {OUT_FILE.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()
