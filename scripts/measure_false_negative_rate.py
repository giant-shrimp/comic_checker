"""Issue #47 (M6-D-3): #36・#37・#45 投入後の偽陰性率・誤答率・判定不能率を再測定する。

Issue #35（M6-D-2）で測定した各指標を、実運用の入力分布に対して測り直す。#35 のサンプルが
failure mode を炙り出すために意図的に構成されたものだったのに対し、こちらは実運用 Excel
（73行）から #35 との重複1件を除いた**全数72件**であり、実分布そのものである。

期待値ラベルは `scripts/m6d3_labels.py` が正（人手で確定済み）。本スクリプトは
comic_checker/本体の判定条件を一切変更せず、judge() の出力をラベルと突き合わせるだけである。

出力する指標（すべて #35 のベースラインとの差分付き）:
  - 偽陰性率（分母38＝期待が `連載中`/`完結` の行、分子＝#35 の分類 B＋E）
  - 誤答率（C＋D。期待と異なるステータスを断定した割合）
  - 判定不能率（`記事なし` を返した行を除く）
  - Wikipedia 記事被覆率（実装が記事に着地した件数。期待値ベースの 55.6% とは別物）
加えて、偽陰性・誤答の行を判定経路マーク（M-1〜M-9）別に自動集計する。#47 の完了条件
「偽陰性がどの判定経路で落ちているか」はこの集計で機械的に出る。マークが付いていない行で
偽陰性・誤答が出た場合は、事前分類で捉えられなかった新規の失敗パターンとして別枠に出す。

**分母38では1件の変動が2.63ポイント動く。** 数ポイント差の比較には意味がなく、読み取れるのは
10ポイント単位の傾向に限られる。結果を報告する際は必ずこの但し書きを付けること。

実ネットワーク呼び出しを伴う計測スクリプトのため、pytestの対象にはしていない。

使い方:
    source .venv/bin/activate
    python3 scripts/measure_false_negative_rate.py
"""
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from comic_checker.wikipedia_client import STATUS_NOT_FOUND, STATUS_UNKNOWN, judge
from m6d3_labels import COMPLETED, DENOMINATOR, LABELS, NOT_FOUND, ONGOING, UNKNOWN

REQUEST_INTERVAL_SECONDS = 2.5

# Issue #35 のベースライン。§2-2〜§2-6 の記載値をそのまま置く。
# 誤答率だけは #35 に指標名も数値も存在せず、#47 が §2-1 の A〜E 集計表から
# (C＋D)/件数 として算出した値である（#35 §4 の期待値訂正2件を適用すると全体が 36.8% に
# 変わるため、主指標は「登録どおり」＝#35 の集計方針に合わせた値とし、訂正値は参考）。
BASELINE_FALSE_NEGATIVE = {"回帰群": (7, 20, 35.0), "全体": (7, 30, 23.3)}
BASELINE_WRONG_ANSWER = {"回帰群": 9.1, "全体（登録どおり・主指標）": 40.4, "全体（訂正適用・参考）": 36.8}
BASELINE_UNKNOWN_RATE = {"回帰群": (8, 22, 36.4), "全体": (12, 57, 21.1)}


def _normalize(text):
    return unicodedata.normalize("NFKC", text)


def _selection_is_correct(label, result):
    """記事選定の正否。出力の参照タイトルが「期待する記事名」と一致するかで判定する（#35 §8-1）。

    期待が「記事なし」の行は、出力が `記事なし` であれば選定は正とする。
    """
    if label.expected == NOT_FOUND:
        return result.status == STATUS_NOT_FOUND
    if result.matched_title is None:
        return False
    return _normalize(result.matched_title) == _normalize(label.expected_page)


def _classify(label, result):
    """#35 §8-1 の5分類（E は E-a／E-b に分割）へ割り当てる。

    A   記事選定 正・判定 正（期待が `判定不能`／`記事なし` で出力も一致した場合を含む）
    B   記事選定 正・判定不能（期待が `連載中`／`完結` なのに `判定不能` を返した）
    C   記事選定 正・判定 誤（偽陽性）
    D   記事選定 誤・判定を出した（最も危険）
    E-a 記事選定 誤・`記事なし` を返した（候補に到達できなかった＝取りこぼし）
    E-b 記事選定 誤・別記事を採用したが `判定不能`（fail-closed が働いた）
    """
    if _selection_is_correct(label, result):
        if result.status == label.expected:
            return "A"
        if result.status == STATUS_UNKNOWN:
            return "B"
        return "C"
    if result.status == STATUS_NOT_FOUND:
        return "E-a"
    if result.status == STATUS_UNKNOWN:
        return "E-b"
    return "D"


def _run():
    rows = []
    total = len(LABELS)
    for index, label in enumerate(LABELS, 1):
        result = judge(label.title)
        rows.append((label, result, _classify(label, result)))
        print(f"  [{index}/{total}] {label.title} -> {result.status}", flush=True)
        time.sleep(REQUEST_INTERVAL_SECONDS)
    return rows


def _rate(numerator, denominator):
    return numerator / denominator * 100 if denominator else 0.0


def _print_diff(label_text, value, baselines):
    """測定値と #35 ベースラインの差分を出す。"""
    print(f"  {label_text}")
    for name, base in baselines.items():
        base_value = base[2] if isinstance(base, tuple) else base
        print(f"    vs #35 {name:22s} {base_value:5.1f}%  →  差分 {value - base_value:+.1f} ポイント")


def _print_per_row(rows):
    print("\n" + "=" * 78)
    print("各行の結果（#35 の A〜E 分類）")
    print("=" * 78)
    print(f"{'#':>3} {'分類':4s} {'期待':6s} {'出力':6s} {'マーク':14s} タイトル / 着地先")
    for label, result, klass in rows:
        marks = ",".join(label.marks) if label.marks else "-"
        print(f"{label.no:3d} {klass:4s} {label.expected:6s} {result.status:6s} {marks:14s} "
              f"{label.title} / {result.matched_title or '（着地なし）'}")


def _print_metrics(rows):
    classes = Counter(klass for _, _, klass in rows)
    total = len(rows)

    denominator_numbers = {label.no for label in DENOMINATOR}
    false_negatives = [
        (label, result, klass) for label, result, klass in rows
        if label.no in denominator_numbers and klass in ("B", "E-a", "E-b")
    ]
    wrong_answers = [
        (label, result, klass) for label, result, klass in rows if klass in ("C", "D")
    ]
    unknown_returned = [r for r in rows if r[1].status == STATUS_UNKNOWN]
    not_found_returned = [r for r in rows if r[1].status == STATUS_NOT_FOUND]
    landed = [r for r in rows if r[1].matched_title is not None]

    print("\n" + "=" * 78)
    print("指標（すべて #35 のベースラインとの差分付き）")
    print("=" * 78)
    print(f"\n分類の内訳: {dict(classes)}")

    fn_rate = _rate(len(false_negatives), len(DENOMINATOR))
    print(f"\n[1] 偽陰性率 = (B＋E) / 分母 = {len(false_negatives)}/{len(DENOMINATOR)} = {fn_rate:.1f}%")
    _print_diff("", fn_rate, BASELINE_FALSE_NEGATIVE)

    wa_rate = _rate(len(wrong_answers), total)
    print(f"\n[2] 誤答率 = (C＋D) / 全行 = {len(wrong_answers)}/{total} = {wa_rate:.1f}%")
    _print_diff("", wa_rate, BASELINE_WRONG_ANSWER)

    unknown_denominator = total - len(not_found_returned)
    ur_rate = _rate(len(unknown_returned), unknown_denominator)
    print(f"\n[3] 判定不能率 = 判定不能 / (全行 - 記事なし) = "
          f"{len(unknown_returned)}/{unknown_denominator} = {ur_rate:.1f}%")
    _print_diff("", ur_rate, BASELINE_UNKNOWN_RATE)

    coverage = _rate(len(landed), total)
    expected_coverage = _rate(sum(1 for label in LABELS if label.expected_page is not None), total)
    print(f"\n[4] Wikipedia 記事被覆率（実装ベース）= {len(landed)}/{total} = {coverage:.1f}%")
    print(f"    期待値ベース（人手ラベル）        = {expected_coverage:.1f}%")
    print(f"    差 {coverage - expected_coverage:+.1f} ポイント")
    print("    ※ 実装ベースは「judge() が記事に着地した件数」、期待値ベースは「入力作品自身の")
    print("       記事が実在する件数」。両者の差は、実装が*別の作品*の記事に着地した分である。")

    return false_negatives, wrong_answers


def _print_mark_breakdown(title, entries):
    print("\n" + "-" * 78)
    print(f"{title}（判定経路マーク別の内訳）")
    print("-" * 78)
    if not entries:
        print("  該当なし")
        return
    marked = [e for e in entries if e[0].marks]
    unmarked = [e for e in entries if not e[0].marks]

    counter = Counter(mark for label, _, _ in marked for mark in label.marks)
    for mark, count in sorted(counter.items()):
        numbers = [label.no for label, _, _ in marked if mark in label.marks]
        print(f"  {mark:6s} {count:2d} 件  行: {numbers}")

    print(f"\n  マークあり計 {len(marked)} 件 / マークなし {len(unmarked)} 件")
    if unmarked:
        print("\n  ** 新規の失敗パターン（事前分類で捉えられなかった型）**")
        for label, result, klass in unmarked:
            print(f"    [{label.no}] {label.title}")
            print(f"        分類={klass} 期待={label.expected} 出力={result.status} "
                  f"着地={result.matched_title or '（着地なし）'}")
            print(f"        判定根拠: {(result.evidence or '（なし）')[:90]}")


def main():
    print(f"{len(LABELS)}件を計測します（M6-D-3 拡張群・全数）")
    print(f"リクエスト間隔 {REQUEST_INTERVAL_SECONDS} 秒、所要 約{len(LABELS) * REQUEST_INTERVAL_SECONDS / 60:.0f}分\n")

    rows = _run()
    _print_per_row(rows)
    false_negatives, wrong_answers = _print_metrics(rows)
    _print_mark_breakdown("偽陰性（B＋E、分母38の行のみ）", false_negatives)
    _print_mark_breakdown("誤答（C＋D）", wrong_answers)

    print("\n" + "=" * 78)
    print("⚠ 結果を報告する際の必須の但し書き")
    print("=" * 78)
    print(f"  分母 {len(DENOMINATOR)} では1件の変動が {100 / len(DENOMINATOR):.2f} ポイント動く。")
    print("  数ポイント差の比較には意味がなく、読み取れるのは10ポイント単位の傾向に限られる。")
    print("  また拡張群は実分布、#35 は failure mode を炙り出すために構成されたサンプルであり、")
    print("  母集団が異なる。上の差分は同一条件の比較ではない。")
    print("  偽陰性の増減を単独で評価しないこと（誤答率とセットで読む）。")


if __name__ == "__main__":
    main()
