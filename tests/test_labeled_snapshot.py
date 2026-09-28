"""Issue #357: ラベル付き保存データに対する judge() の最終 status のスナップショット照合。

**回帰の検知用であり、精度の測定ではない。** 一致数を精度の指標として報告しないこと
（回帰コーパスのラベルは循環測定の制約を受け、holdout のラベルは上界扱い。
`docs/m6d3_labeling_rationale.md` 参照）。

基準は `tests/data/labeled_snapshot.json`。判定ロジックの変更で status が変わる行が出たら、
`python scripts/gen_labeled_snapshot.py` で基準を再生成し、PR 本文に変わった行
（データ名・no・変更前→変更後・向き）を列挙する。変化を受け入れるかはマージ前に人が判断する。
ネットワークは requests を遮断して再現し、通信の試行が 1 回でもあれば失敗する。
"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

import comic_checker.wikipedia_client as wc

REPO_ROOT = Path(__file__).resolve().parent.parent

# `scripts/` を `sys.path` へ差し込むと他のテストの import 解決に影響が残るため、ファイルから読む。
_SPEC = importlib.util.spec_from_file_location(
    "gen_labeled_snapshot", REPO_ROOT / "scripts" / "gen_labeled_snapshot.py")
gen = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gen)

BASELINE_PATH = REPO_ROOT / gen.SNAPSHOT


def _watched_attributes():
    """ハーネスとこのテストが差し替える属性（元に戻ったかの確認用）。"""
    return {
        "wikipedia_client._pick_article": wc._pick_article,
        "wikipedia_client._fetch_wikitext": wc._fetch_wikitext,
        "requests.get": requests.get,
        "requests.post": requests.post,
        "requests.sessions.Session.request": requests.sessions.Session.request,
    }


def _load_baseline():
    assert BASELINE_PATH.is_file(), (
        "基準ファイルがない: %s（python scripts/gen_labeled_snapshot.py で生成する）" % gen.SNAPSHOT)
    with open(BASELINE_PATH, encoding="utf-8") as f:
        document = json.load(f)
    return {(row["dataset"], row["no"]): row["status"] for row in document["rows"]}


def _label(key):
    return "%s no=%d" % key


@pytest.fixture(scope="module")
def reproduced():
    """通信を遮断して全対象行を再現する。requests の遮断は終了時に必ず元へ戻る。"""
    before = _watched_attributes()
    attempts = []
    with pytest.MonkeyPatch.context() as mp:
        for owner, name in gen.NETWORK_TARGETS:
            mp.setattr(owner, name, gen.make_blocker(attempts))
        cases = gen.build_cases()
        statuses = gen.reproduce_all(cases)
    after = _watched_attributes()
    return SimpleNamespace(
        current={(case.dataset, case.no): status for case, status in zip(cases, statuses)},
        attempts=attempts, before=before, after=after)


def test_baseline_file_exists():
    assert BASELINE_PATH.is_file(), "基準ファイルがない: %s" % gen.SNAPSHOT


def test_target_rows_match_baseline(reproduced):
    baseline = _load_baseline()
    only_baseline = sorted(set(baseline) - set(reproduced.current))
    only_current = sorted(set(reproduced.current) - set(baseline))
    assert not only_baseline and not only_current, (
        "対象行の集合が基準と異なる。\n  基準にのみある行: %s\n  現在にのみある行: %s"
        % (", ".join(_label(k) for k in only_baseline) or "なし",
           ", ".join(_label(k) for k in only_current) or "なし"))


def test_status_matches_baseline(reproduced):
    baseline = _load_baseline()
    diffs = ["  %s 基準=%s 現在=%s" % (_label(key), baseline[key], reproduced.current[key])
             for key in sorted(baseline) if key in reproduced.current
             and baseline[key] != reproduced.current[key]]
    assert not diffs, (
        "judge() の最終 status が基準と異なる行が %d 行ある。\n%s\n"
        "意図した変更なら python scripts/gen_labeled_snapshot.py で基準を再生成し、"
        "変わった行を PR 本文に列挙する。" % (len(diffs), "\n".join(diffs)))


def test_no_network_attempts(reproduced):
    assert reproduced.attempts == [], "再現中に通信の試行が %d 回あった" % len(reproduced.attempts)


def test_patched_attributes_restored(reproduced):
    changed = sorted(name for name in reproduced.before
                     if reproduced.after[name] is not reproduced.before[name])
    assert not changed, "再現の後に元へ戻っていない属性がある: %s" % ", ".join(changed)
    # ハーネスが保持している元の関数とも一致していること
    assert reproduced.after["wikipedia_client._pick_article"] is (
        gen.HARNESS_MODULE._ORIG_PICK_ARTICLE)
    assert reproduced.after["wikipedia_client._fetch_wikitext"] is (
        gen.HARNESS_MODULE._ORIG_FETCH_WIKITEXT)
