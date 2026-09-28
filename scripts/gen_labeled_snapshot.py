# -*- coding: utf-8 -*-
"""ラベル付き保存データに対する judge() の最終 status の基準（スナップショット）を作る。

**回帰の検知用であり、精度の測定ではない**（Issue #357）。回帰コーパスのラベルは
`docs/m6d3_labeling_rationale.md` の循環測定の制約を受け、holdout のラベルは上界扱いである。
このスナップショットの一致数を精度の指標として報告しないこと。

対象は、ラベルと保存済み wikitext を input_title の完全一致で対応づけられた行
（回帰コーパス: `scripts/m6d3_labels.py` の LABELS・REGRESSION_LABELS と
`regression_corpus_wikitext.json`、holdout: `step98_a3_labels.json` と `holdout_wikitext.json`）。
保存データに行がないラベル（記事なし等）は対象外。holdout2・未消費プールは使わない。

各行を today=2026-08-15（保存データの取得日）に固定し、`docs/regression_corpus_2026-08/
step98_judge_harness.py` の `run_judge_with_snapshot()` で judge() の最終 status を再現する。
ネットワークは遮断し、通信の試行があれば基準を書き出さずに異常終了する。

    python scripts/gen_labeled_snapshot.py     # tests/data/labeled_snapshot.json を書き出す

判定ロジックの変更で status が変わる行が出たら、その PR でこのスクリプトを再実行して基準を
再生成し、PR 本文に変わった行（データ名・no・変更前→変更後・向き）を列挙する。
テスト（`tests/test_labeled_snapshot.py`）はここの関数を import して使う。
基準ファイルには作品名・本文・evidence・input_title を保存しない。
"""
import collections
import datetime
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests  # noqa: E402

TODAY = datetime.date(2026, 8, 15)

# 相対パスはすべてリポジトリルート起点（Windows/Linux 共通に扱うため posix 形式で持つ）
LABELS_MODULE = "scripts/m6d3_labels.py"
CORPUS_WIKITEXT = "docs/regression_corpus_2026-08/regression_corpus_wikitext.json"
HOLDOUT_LABELS = "docs/holdout_measurement_2026-08/step98_a3_labels.json"
HOLDOUT_WIKITEXT = "docs/holdout_measurement_2026-08/holdout_wikitext.json"
HARNESS = "docs/regression_corpus_2026-08/step98_judge_harness.py"
SNAPSHOT = "tests/data/labeled_snapshot.json"
INPUT_FILES = (LABELS_MODULE, CORPUS_WIKITEXT, HOLDOUT_LABELS, HOLDOUT_WIKITEXT)

DATASETS = ("regression:extended", "regression:regression", "holdout:a3")

ERROR_PREFIX = "例外("  # 再現中に例外が出た行の status。基準には書き出さない

Case = collections.namedtuple("Case", "dataset no expected row")


def _load_module(name, rel_path):
    """`sys.path` を汚さずにファイルからモジュールを読み込む（他テストへの影響を避ける）。"""
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HARNESS_MODULE = _load_module("step98_judge_harness", HARNESS)


def _load_json(rel_path):
    with open(REPO_ROOT / rel_path, encoding="utf-8") as f:
        return json.load(f)


def _index_by_title(rows):
    """input_title -> 行。同一タイトルが複数あれば None（曖昧なので対象外）。"""
    index = {}
    for row in rows:
        title = row["input_title"]
        index[title] = None if title in index else row
    return index


def build_cases():
    """保存データに行がある対象行を、DATASETS の順・各 dataset 内は no の昇順で返す。"""
    labels_module = _load_module("m6d3_labels", LABELS_MODULE)
    corpus_index = _index_by_title(_load_json(CORPUS_WIKITEXT)["rows"])
    holdout_index = _index_by_title(_load_json(HOLDOUT_WIKITEXT)["rows"])

    cases = []
    for dataset, labels in (("regression:extended", labels_module.LABELS),
                            ("regression:regression", labels_module.REGRESSION_LABELS)):
        for label in labels:
            cases.append(Case(dataset, label.no, label.expected, corpus_index.get(label.title)))
    for label in _load_json(HOLDOUT_LABELS)["rows"]:
        cases.append(Case("holdout:a3", label["no"], label["expected_status"],
                          holdout_index.get(label["input_title"])))
    cases = [case for case in cases if case.row is not None]
    return sorted(cases, key=lambda case: (DATASETS.index(case.dataset), case.no))


def reproduce(row):
    """保存行 1 行から、today を固定して judge() の最終 status を再現する。"""
    result = HARNESS_MODULE.run_judge_with_snapshot(
        row["input_title"], row["matched_title"], row["extract"], row["url"], row["wikitext"],
        today=TODAY)
    return result.status


def reproduce_all(cases):
    """各行の status を返す。例外が出た行は ERROR_PREFIX で始まる文字列にする（例外クラス名のみ）。"""
    statuses = []
    for case in cases:
        try:
            statuses.append(reproduce(case.row))
        except Exception as exc:
            statuses.append("%s%s)" % (ERROR_PREFIX, type(exc).__name__))
    return statuses


class NetworkAttempt(Exception):
    """遮断中に通信しようとした（試行は attempts に記録される）。"""


NETWORK_TARGETS = (
    (requests, "get"),
    (requests, "post"),
    (requests.sessions.Session, "request"),
)


def make_blocker(attempts):
    """呼ばれたら試行を記録して例外を投げる関数を返す（通信はしない）。"""
    def _blocked(*_args, **_kwargs):
        attempts.append(1)
        raise NetworkAttempt()
    return _blocked


def build_document(cases, statuses):
    return {
        "today": TODAY.isoformat(),
        "inputs": list(INPUT_FILES),
        "rows": [{"dataset": case.dataset, "no": case.no, "expected": case.expected,
                  "status": status} for case, status in zip(cases, statuses)],
    }


def dumps(document):
    """差分が行単位で読めるよう、rows の各要素を 1 行ずつ書き出す。"""
    rows = ",\n".join("    " + json.dumps(row, ensure_ascii=False) for row in document["rows"])
    return ('{\n  "today": %s,\n  "inputs": %s,\n  "rows": [\n%s\n  ]\n}\n'
            % (json.dumps(document["today"]),
               json.dumps(document["inputs"], ensure_ascii=False),
               rows))


def main():
    cases = build_cases()
    attempts = []
    originals = [(owner, name, getattr(owner, name)) for owner, name in NETWORK_TARGETS]
    for owner, name in NETWORK_TARGETS:
        setattr(owner, name, make_blocker(attempts))
    try:
        statuses = reproduce_all(cases)
    finally:
        for owner, name, original in originals:
            setattr(owner, name, original)

    if attempts:
        sys.exit("通信の試行が %d 回あったため基準を書き出さない" % len(attempts))
    errors = [(case.dataset, case.no, status) for case, status in zip(cases, statuses)
              if status.startswith(ERROR_PREFIX)]
    if errors:
        for dataset, no, status in errors:
            print("%s no=%d %s" % (dataset, no, status), file=sys.stderr)
        sys.exit("再現中に例外が出た行があるため基準を書き出さない（%d 行）" % len(errors))

    out_path = REPO_ROOT / SNAPSHOT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(build_document(cases, statuses)))
    counts = collections.Counter(case.dataset for case in cases)
    print("%s に %d 行を書き出した（%s）" % (
        SNAPSHOT, len(cases), "・".join("%s=%d" % (d, counts[d]) for d in DATASETS)))


if __name__ == "__main__":
    main()
