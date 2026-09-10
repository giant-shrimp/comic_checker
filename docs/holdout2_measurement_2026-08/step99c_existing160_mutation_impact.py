# -*- coding: utf-8 -*-
"""Issue #157 v2基準（影響件数）の累計評価のため、step99b_holdout2_mutation_impact.py
と同一の差し替えパターン（NEW_COMPLETED_WEAK_RE・NEW_ONGOING_RE）を既存160件
（holdout99+regression61）へ適用し、影響件数を再実測する。

comic_checker/本体は変更しない。差し替えパターンは本ディレクトリの
step99b_holdout2_mutation_impact.pyからimportし、文字列を書き直さない。
"""
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "docs/regression_corpus_2026-08"))
sys.path.insert(0, str(_REPO_ROOT / "docs/holdout2_measurement_2026-08"))
from step98_judge_harness import run_judge_with_snapshot  # noqa: E402
from step99b_holdout2_mutation_impact import (  # noqa: E402
    NEW_COMPLETED_WEAK_RE,
    NEW_ONGOING_RE,
)
import comic_checker.wikipedia_client as wc  # noqa: E402

HOLDOUT_FILE = _REPO_ROOT / "docs/holdout_measurement_2026-08/holdout_wikitext.json"
REGRESSION_FILE = _REPO_ROOT / "docs/regression_corpus_2026-08/regression_corpus_wikitext.json"
OUT_FILE = _REPO_ROOT / "docs/holdout2_measurement_2026-08/existing160_mutation_impact_result.json"

_ORIG_COMPLETED_WEAK_RE = wc.COMPLETED_WEAK_RE
_ORIG_ONGOING_RE = wc.ONGOING_RE


def measure_word(word, target_attr, new_pattern, rows):
    print(f"\n===== 「{word}」（{target_attr}） =====")
    orig_pattern = getattr(wc, target_attr)

    changed = []
    try:
        before_results = {}
        for r in rows:
            title = r.get("matched_title") or r.get("input_title")
            result = run_judge_with_snapshot(
                r["input_title"], r["matched_title"], r["extract"], r["url"], r["wikitext"]
            )
            before_results[title] = result.status

        setattr(wc, target_attr, new_pattern)

        for r in rows:
            title = r.get("matched_title") or r.get("input_title")
            result = run_judge_with_snapshot(
                r["input_title"], r["matched_title"], r["extract"], r["url"], r["wikitext"]
            )
            before_status = before_results[title]
            after_status = result.status
            if before_status != after_status:
                changed.append({"title": title, "before": before_status, "after": after_status})
    finally:
        setattr(wc, target_attr, orig_pattern)

    print(f"影響件数: {len(changed)}")
    for c in changed:
        print(f"  {c['title']}: {c['before']} -> {c['after']}")
    return {"word": word, "target_attr": target_attr, "impact_count": len(changed), "changed": changed}


def main():
    holdout = json.load(open(HOLDOUT_FILE, encoding="utf-8"))["rows"]
    regression = json.load(open(REGRESSION_FILE, encoding="utf-8"))["rows"]
    rows = holdout + regression
    print(f"combined rows: {len(rows)} (holdout={len(holdout)}, regression={len(regression)})")

    results = {}
    results["配信終了"] = measure_word("配信終了", "COMPLETED_WEAK_RE", NEW_COMPLETED_WEAK_RE, rows)
    results["連載されており"] = measure_word("連載されており", "ONGOING_RE", NEW_ONGOING_RE, rows)

    assert wc.COMPLETED_WEAK_RE is _ORIG_COMPLETED_WEAK_RE
    assert wc.ONGOING_RE is _ORIG_ONGOING_RE
    print("\n復元確認: wc.COMPLETED_WEAK_RE・wc.ONGOING_REとも元のオブジェクトに復元済み")

    json.dump(results, open(OUT_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n結果を保存: {OUT_FILE.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()
