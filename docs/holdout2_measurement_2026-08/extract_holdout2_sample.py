# -*- coding: utf-8 -*-
"""事前登録 docs/code_defects_2026-08/prereg_corpus_expansion_holdout2.md
2節の抽出条件に従い、未消費262件から120件を抽出する。

comic_checker/・judge()は一切呼ばない。抽出結果（タイトルのみ）を保存する。
"""
import json
import random
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

POOL_FILE = _REPO_ROOT / "docs/holdout_pool_2026-08/step93_2_holdout_pool.json"
DRAWN100_FILE = _REPO_ROOT / "docs/holdout_pool_2026-08/step98_a2_sample100_titles.json"
OUT_FILE = _REPO_ROOT / "docs/holdout2_measurement_2026-08/holdout2_sample_titles.json"

SEED = 158
N = 120


def main():
    pool = json.load(open(POOL_FILE, encoding="utf-8"))
    pool_titles = pool["holdout_pool_titles"]
    assert len(pool_titles) == 362, f"想定362件のところ{len(pool_titles)}件"

    drawn100 = json.load(open(DRAWN100_FILE, encoding="utf-8"))
    assert len(drawn100) == 100, f"想定100件のところ{len(drawn100)}件"
    drawn100_set = set(drawn100)

    remaining = [t for t in pool_titles if t not in drawn100_set]
    assert len(remaining) == 262, f"想定262件のところ{len(remaining)}件"

    # 再現性のため、抽出前に必ず昇順ソートする（ソート順が異なると再現性が失われる）
    remaining_sorted = sorted(remaining)

    sample = random.Random(SEED).sample(remaining_sorted, N)
    assert len(sample) == N
    assert len(set(sample)) == N, "抽出結果に重複がある"

    out = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "docs/code_defects_2026-08/prereg_corpus_expansion_holdout2.md 2節の"
            "抽出条件に従った未観測評価用標本（holdout2）の抽出結果。"
        ),
        "extraction_conditions": {
            "source_pool": "docs/holdout_pool_2026-08/step93_2_holdout_pool.json",
            "source_pool_size": len(pool_titles),
            "excluded_drawn100_file": "docs/holdout_pool_2026-08/step98_a2_sample100_titles.json",
            "excluded_drawn100_size": len(drawn100),
            "remaining_before_extraction": len(remaining),
            "seed": SEED,
            "n": N,
            "method": (
                "未消費262件を昇順ソートしたうえで "
                "random.Random(158).sample(pool_sorted, 120)"
            ),
        },
        "sample_titles_count": len(sample),
        "sample_titles": sample,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(OUT_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("抽出件数:", len(sample))
    print("保存先:", OUT_FILE.relative_to(_REPO_ROOT))
    print("先頭5件:", sample[:5])
    print("末尾5件:", sample[-5:])


if __name__ == "__main__":
    main()
