# -*- coding: utf-8 -*-
"""Issue #180 項目4・5 / Issue #157: holdout2 120件に対する「配信終了」
「連載されており」のミューテーションテスト（影響件数の実測）。

事前登録 docs/code_defects_2026-08/prereg_holdout2_judge_comparison.md 4節の
手順4に対応する。comic_checker/本体は変更しない。プロセス内でwc.COMPLETED_WEAK_RE・
wc.ONGOING_REを一時的に属性差し替えし、測定後に必ず元へ復元する（try/finally）。
差し替えは既存パターンへ対象語を選択肢として追加するだけの最小変更とし、
既存の選択肢は削除・改変しない。2語は独立に測定する（同時差し替えはしない）。
"""
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "docs/regression_corpus_2026-08"))
from step98_judge_harness import run_judge_with_snapshot  # noqa: E402
import comic_checker.wikipedia_client as wc  # noqa: E402

WIKITEXT_FILE = _REPO_ROOT / "docs/holdout2_measurement_2026-08/holdout2_wikitext.json"
LABELS_FILE = _REPO_ROOT / "docs/holdout2_measurement_2026-08/holdout2_labels_v4.json"
OUT_FILE = _REPO_ROOT / "docs/holdout2_measurement_2026-08/holdout2_mutation_impact_result.json"

_ORIG_COMPLETED_WEAK_RE = wc.COMPLETED_WEAK_RE
_ORIG_ONGOING_RE = wc.ONGOING_RE

# 既存パターン（手順2で提示した現行値。この文字列自体は変更しない）に、
# 対象語を選択肢として追加しただけの代替パターン。
NEW_COMPLETED_WEAK_RE = re.compile(
    r"連載(?:が|を)?終了(?:した)?|連載された|連載され、|まで[^。、]{0,20}?連載(?:された)?|打ち切(?:り|られ)"
    r"|配信された|配信終了"
)
NEW_ONGOING_RE = re.compile(
    r"連載中(?!から|は|に|作品|の[0-9０-９]|だっ|であっ|断|、)|連載されている|発行されている|連載されており"
)


def classify_transition(before_status, after_status, expected_status):
    """事前登録5節の4分類。

    D_error（危険な確信誤り、完結/連載中いずれかで正解と逆）・E_missed（判定不能）・
    A_correct（正解）の3値を軸に、before/afterの遷移を分類する。
    """
    def bucket(status):
        if status == expected_status:
            return "A_correct"
        if status == "判定不能":
            return "E_missed"
        return "D_error"

    before_bucket = bucket(before_status)
    after_bucket = bucket(after_status)

    if before_bucket == "D_error" and after_bucket in ("E_missed", "A_correct"):
        return f"D_error→{after_bucket}"
    if before_bucket == "A_correct" and after_bucket == "D_error":
        return "A_correct→D_error"
    if before_bucket == "E_missed" and after_bucket == "A_correct":
        return "E_missed→A_correct"
    if before_bucket == "E_missed":
        return "E_missed→別のE_missed／判定不能のまま"
    return f"{before_bucket}→{after_bucket}（4分類外）"


def measure_word(word, target_attr, new_pattern, sanity_text_before, sanity_text_after, rows, label_by_title):
    print(f"\n===== 「{word}」（{target_attr}） =====")

    orig_pattern = getattr(wc, target_attr)
    print(f"差し替え前パターン: {orig_pattern.pattern!r}")
    print(f"差し替え後パターン: {new_pattern.pattern!r}")

    assert not orig_pattern.search(sanity_text_before), (
        f"健全性チェック失敗: 対象語 {word!r} が差し替え前パターンに一致した"
    )
    assert new_pattern.search(sanity_text_after), (
        f"健全性チェック失敗: 対象語 {word!r} が差し替え後パターンに一致しなかった"
    )
    print(f"健全性チェック: 差し替え前パターン非マッチ=OK、差し替え後パターンマッチ=OK")

    changed = []
    try:
        before_results = {}
        for r in rows:
            if r.get("matched_title") is None:
                continue
            result = run_judge_with_snapshot(
                r["input_title"], r["matched_title"], r["extract"], r["url"], r["wikitext"]
            )
            before_results[r["matched_title"]] = result.status

        setattr(wc, target_attr, new_pattern)

        for r in rows:
            if r.get("matched_title") is None:
                continue
            title = r["matched_title"]
            result = run_judge_with_snapshot(
                r["input_title"], r["matched_title"], r["extract"], r["url"], r["wikitext"]
            )
            before_status = before_results[title]
            after_status = result.status
            if before_status != after_status:
                expected = label_by_title.get(title)
                transition_class = classify_transition(before_status, after_status, expected)
                changed.append(
                    {
                        "title": title,
                        "before_status": before_status,
                        "after_status": after_status,
                        "expected_status": expected,
                        "transition_class": transition_class,
                    }
                )
    finally:
        setattr(wc, target_attr, orig_pattern)

    print(f"影響件数（statusが変化した行数）: {len(changed)}")

    class_counts = {}
    for c in changed:
        class_counts[c["transition_class"]] = class_counts.get(c["transition_class"], 0) + 1
    print("4分類の内訳:")
    for k, v in class_counts.items():
        print(f"  {k}: {v}件")

    print("変化した行のタイトル一覧（全件）:")
    for c in changed:
        print(f"  - {c['title']}: {c['before_status']} -> {c['after_status']} (expected={c['expected_status']}, {c['transition_class']})")

    return {
        "word": word,
        "target_attr": target_attr,
        "pattern_before": orig_pattern.pattern,
        "pattern_after": new_pattern.pattern,
        "sanity_check_before_no_match": not orig_pattern.search(sanity_text_before),
        "sanity_check_after_matches": bool(new_pattern.search(sanity_text_after)),
        "impact_count": len(changed),
        "transition_class_counts": class_counts,
        "changed_titles": changed,
    }


def main():
    rows = json.load(open(WIKITEXT_FILE, encoding="utf-8"))["rows"]
    labels = json.load(open(LABELS_FILE, encoding="utf-8"))["labels"]
    label_by_title = {x["title"]: x["expected_status"] for x in labels}

    excluded = [r["input_title"] for r in rows if r.get("matched_title") is None]
    print(f"matched_titleがNoneのため集計から除外: {len(excluded)}件 {excluded}")

    results = {}

    results["配信終了"] = measure_word(
        word="配信終了",
        target_attr="COMPLETED_WEAK_RE",
        new_pattern=NEW_COMPLETED_WEAK_RE,
        sanity_text_before="2008年8月6日第1シーズン配信終了",
        sanity_text_after="2008年8月6日第1シーズン配信終了",
        rows=rows,
        label_by_title=label_by_title,
    )

    results["連載されており"] = measure_word(
        word="連載されており",
        target_attr="ONGOING_RE",
        new_pattern=NEW_ONGOING_RE,
        sanity_text_before="2012年より不定期連載されており",
        sanity_text_after="2012年より不定期連載されており",
        rows=rows,
        label_by_title=label_by_title,
    )

    assert wc.COMPLETED_WEAK_RE is _ORIG_COMPLETED_WEAK_RE, "COMPLETED_WEAK_REが復元されていない"
    assert wc.ONGOING_RE is _ORIG_ONGOING_RE, "ONGOING_REが復元されていない"
    print("\n復元確認: wc.COMPLETED_WEAK_RE・wc.ONGOING_REとも元のオブジェクトに復元済み")

    out = {
        "excluded_matched_title_none": excluded,
        "results": results,
    }
    json.dump(out, open(OUT_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n結果を保存: {OUT_FILE.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()
