# -*- coding: utf-8 -*-
"""既存160件（holdout99+regression61）に対するjudge()ロジックのオフライン再現。

docs/code_defects_2026-08/prereg_holdout2_judge_comparison.md 3(a)が根拠とする
実測分布（完結88・連載中56・判定不能16）の導出スクリプト。

_pick_article・_fetch_wikitext（ネットワークI/O）は呼ばない。保存済みのextract・
wikitextフィールドをそのまま_judge_extract()・_judge_via_infobox()へ注入する
（verification_procedure.md「厳禁」節が指すサブ関数個別呼び出しのシミュレーション
ではなく、judge()本体のveto層（_has_ongoing_signal・_is_novel_primary）を
含めて再現する）。comic_checker/本体は一切変更しない。

本スクリプトはjudge()本体を呼ばず、_judge_extract・_judge_via_infoboxとveto層を
組み合わせて同経路を再現している。この再現がjudge()本体と等価であることを、
docs/regression_corpus_2026-08/step98_judge_harness.pyのrun_judge_with_snapshot()
（_pick_article・_fetch_wikitextのみ差し替えてjudge()本体を呼ぶ）による160件の
再算出と突合して確認した。突合結果: 集計値（完結88・連載中56・判定不能16）が
一致し、記事単位でも不一致0件。確認時点のコミット: 4ef614e。
"""
import json
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from comic_checker.wikipedia_client import (  # noqa: E402
    MANGA_MARKERS,
    STATUS_UNKNOWN,
    _has_ongoing_signal,
    _is_novel_primary,
    _judge_extract,
    _judge_via_infobox,
)

HOLDOUT_FILE = _REPO_ROOT / "docs/holdout_measurement_2026-08/holdout_wikitext.json"
REGRESSION_FILE = _REPO_ROOT / "docs/regression_corpus_2026-08/regression_corpus_wikitext.json"


def judge_offline(extract, wikitext):
    """judge()と同じ経路をオフラインで再現し、最終statusを返す。"""
    status, _evidence = _judge_extract(extract)
    final_status = status
    if status == STATUS_UNKNOWN and wikitext:
        infobox_status, _infobox_evidence = _judge_via_infobox(wikitext)
        if infobox_status == "完結" and _has_ongoing_signal(extract):
            infobox_status = None
        if infobox_status == "完結" and _is_novel_primary(extract):
            if not any(marker in extract for marker in MANGA_MARKERS):
                infobox_status = None
        if infobox_status is not None:
            final_status = infobox_status
    return final_status


def main():
    holdout = json.load(open(HOLDOUT_FILE, encoding="utf-8"))["rows"]
    regression = json.load(open(REGRESSION_FILE, encoding="utf-8"))["rows"]
    rows = holdout + regression
    print(f"combined rows: {len(rows)} (holdout={len(holdout)}, regression={len(regression)})")

    counts = Counter()
    for r in rows:
        extract = r.get("extract") or ""
        wikitext = r.get("wikitext")
        counts[judge_offline(extract, wikitext)] += 1

    total = len(rows)
    for k, v in counts.most_common():
        print(f"{k}: {v} 件 ({v / total * 100:.1f}%)")


if __name__ == "__main__":
    main()
