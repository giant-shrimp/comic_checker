"""Issue #16 (M6-D-2): インフォボックス補助judge()経路（Issue #12）の前後で、
判定不能（STATUS_UNKNOWN）率がどう変化したかを計測する。

Issue #11・#13で実際に投入した実データ24件に対して、judge()のuse_infoboxフラグを
On/Off切り替えて実行し、判定不能件数を比較する。comic_checker/本体の判定条件
（正規表現・マーカー判定ロジックそのもの）は一切変更していない。唯一の差分は、この比較の
ためだけにjudge()へ追加したuse_infoboxフラグ（wikipedia_client.py参照）。

実ネットワーク呼び出しを伴う一回限りの計測スクリプトのため、pytestの対象にはしていない。

使い方:
    source .venv/bin/activate
    python3 scripts/measure_unknown_rate.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from comic_checker.wikipedia_client import STATUS_UNKNOWN, judge

# Issue #11（M6-D-1）で実際に投入した10件
ISSUE_11_TITLES = [
    "ワンピース",
    "進撃の巨人",
    "ダンダダン",
    "アオのハコ",
    "転生したらスライムだった件",
    "HUNTER×HUNTER",
    "ジョジョの奇妙な冒険",
    "ベルセルク",
    "こち亀",
    "DEATH NOTE",
]

# Issue #13で実際に投入し、記事が見つかった14件
# （記事なしだった3件: このすばらしい世界に祝福を！・蜘蛛ですが、なにか？・
#   陰の実力者になりたくて！ は「既存の実データ」の対象外として除外）
ISSUE_13_TITLES = [
    "Re:ゼロから始める異世界生活",
    "オーバーロード",
    "ダンジョンに出会いを求めるのは間違っているだろうか",
    "魔法科高校の劣等生",
    "賢者の孫",
    "幼女戦記",
    "盾の勇者の成り上がり",
    "本好きの下剋上",
    "薬屋のひとりごと",
    "無職転生",
    "ダンジョン飯",
    "ハイキュー!!",
    "とんかつDJアゲ太郎",
    "スパイファミリー",
]

TITLES = ISSUE_11_TITLES + ISSUE_13_TITLES

# Issue #40: リクエスト間隔とリトライは `wikipedia_client._api_get` が持つように
# なった。ここで待つと二重待ちになるので落とした。以前はこの定数で1.0秒/行
# 待っていたが、1行が出す2〜4リクエストは間隔ゼロで連射されたままだった。


def _run(use_infobox):
    results = []
    for title in TITLES:
        result = judge(title, use_infobox=use_infobox)
        results.append((title, result.status))
    return results


def main():
    print(f"{len(TITLES)}件を計測します（インフォボックス補助 Before/After）")

    print("\n-- Before（インフォボックス補助 Off）を計測中 --")
    off_results = _run(use_infobox=False)

    print("-- After（インフォボックス補助 On）を計測中 --")
    on_results = _run(use_infobox=True)

    off_unknown = sum(1 for _, status in off_results if status == STATUS_UNKNOWN)
    on_unknown = sum(1 for _, status in on_results if status == STATUS_UNKNOWN)

    print()
    print(f"{'タイトル':30s} {'Before(Off)':14s} {'After(On)':14s}")
    for (title, off_status), (_, on_status) in zip(off_results, on_results):
        mark = "  <-- 変化" if off_status != on_status else ""
        print(f"{title:30s} {off_status:14s} {on_status:14s}{mark}")

    print()
    print(f"判定不能件数: Before={off_unknown}/{len(TITLES)}  After={on_unknown}/{len(TITLES)}")


if __name__ == "__main__":
    main()
