"""Issue #47 (M6-D-3): #36・#37・#45 投入後の偽陰性率・誤答率・判定不能率を再測定する。

Issue #35（M6-D-2）で測定した各指標を測り直す。2つの群を**別々に**集計する。

  - **回帰群（22行）**: #35 のカテゴリ1（12）＋対照群（10）。#35 が failure mode を炙り出す
    ために**意図的に偏らせて構成した**サンプル。置いている目的は #35 のベースライン
    （偽陰性率 35.0% / 判定不能率 36.4% / 誤答率 9.1%）との**同一母集団での直接比較**のみ。
    ラベルは #35 当時の**旧定義**（本文のみ・インフォボックスを見ない）のまま据え置く。
  - **拡張群（72行）**: 実運用 Excel から #35 との重複1件を除いた**全数**。実分布そのもの。
    ラベルは**新定義**（本文＋インフォボックス）。

**2群を混ぜた率は出さない。** 混ぜると「偏ったサンプルの率」と「実分布の率」が区別できなく
なる（#47 の設計）。結果表には回帰群に「旧定義」、拡張群に「新定義」を必ず併記する。

期待値ラベルは `scripts/m6d3_labels.py` が正。本スクリプトは comic_checker/本体の判定条件を
一切変更せず、judge() の出力をラベルと突き合わせるだけである。

出力する指標:
  - 偽陰性率（分母＝期待が `連載中`/`完結` の行、分子＝#35 の分類 B＋E）
  - 誤答率（C＋D。期待と異なるステータスを断定した割合）
  - 判定不能率（分母＝全行。#35 §8-5 と同じ計算。参考値として「判定を試みた行のみ」も出す）
  - Wikipedia 記事被覆率（拡張群のみ。実装が記事に着地した件数）
加えて次を自動で出す。
  - 偽陰性・誤答の行の判定経路マーク（M-1〜M-9）別内訳。マークなしの行で失敗が出た場合は
    「新規の失敗パターン」として別枠に出す
  - **#45（`_is_person_article()`）由来の偽陰性が何件か**を明示
  - **回帰群のインフォボックス終了系フィールドの機械取得**。旧定義のまま据え置いたラベルが、
    新定義なら変わりうるかを確認する（#47 で (a) を採る際に約束した「代償を潰す義務」）

**分母が小さい。** 回帰群 20 では1件が 5.00 ポイント、拡張群 39 では 2.56 ポイント動く。
数ポイント差の比較には意味がなく、読み取れるのは10ポイント単位の傾向に限られる。

実ネットワーク呼び出しを伴う計測スクリプトのため、pytestの対象にはしていない。

使い方:
    source .venv/bin/activate
    python3 scripts/measure_false_negative_rate.py
"""
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from comic_checker.wikipedia_client import (
    END_FIELD_NAMES, MANGA_INFOBOX_MARKER, STATUS_NOT_FOUND, STATUS_UNKNOWN,
    _extract_braced_blocks, _fetch_wikitext, _find_main_manga_block, _infobox_field,
    _infobox_has_field, judge,
)
from m6d3_labels import (
    BASELINE_REGRESSION, CAT_AUTHOR, DEFINITION_NEW, DEFINITION_OLD, DENOMINATOR,
    LABELS, M35_STAGE1_RESULTS, NOT_FOUND, REGRESSION_DENOMINATOR, REGRESSION_LABELS,
    UNKNOWN,
)

# Issue #40: リクエスト間隔とリトライは `wikipedia_client._api_get` が持つように
# なった。ここで待つと二重待ちになるので落とした。以前はこの定数で2.5秒/行
# 待っていたが、1行が出す2〜4リクエストは間隔ゼロで連射されたままだった。

# 拡張群向けの参考値（#35 の全体57行に対する値）。**母集団もラベル定義も異なるので
# 同一条件の比較ではない。** 同一母集団での直接比較は回帰群 × BASELINE_REGRESSION で行う。
# 誤答率だけは #35 に指標名も数値も存在せず、#47 が §2-1 の A〜E 集計表から (C＋D)/件数 と
# して算出した値である（#35 §4 の期待値訂正2件を適用すると 36.8% になるため両方を併記する）。
BASELINE_EXPANSION_REFERENCE = (
    ("偽陰性率", "fn", 23.3),
    ("誤答率（登録どおり・主指標）", "wa", 40.4),
    ("誤答率（訂正適用・参考）", "wa", 36.8),
    ("判定不能率", "ur", 21.1),
)


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


def _run(labels, group_name):
    print(f"\n-- {group_name}（{len(labels)}件）を計測中 --", flush=True)
    rows = []
    for index, label in enumerate(labels, 1):
        result = judge(label.title)
        rows.append((label, result, _classify(label, result)))
        print(f"  [{index}/{len(labels)}] {label.title} -> {result.status}", flush=True)
    return rows


def _rate(numerator, denominator):
    return numerator / denominator * 100 if denominator else 0.0


def _infobox_end_fields(page_title):
    """本編インフォボックスの終了系フィールドを (判定材料あり, 表示用文字列) で返す。"""
    wikitext = _fetch_wikitext(page_title)
    if wikitext is None:
        return False, "（wikitext を取得できず）"
    blocks = _extract_braced_blocks(wikitext, MANGA_INFOBOX_MARKER)
    if not blocks:
        return False, "（漫画インフォボックスなし）"
    main_block = _find_main_manga_block(blocks)
    if main_block is None:
        return False, f"（本編ブロックを特定できず: {len(blocks)} 個）"
    parts = []
    for name in END_FIELD_NAMES:
        if _infobox_has_field(main_block, name):
            value = _infobox_field(main_block, name)
            parts.append(f"{name} = {value if value else '（空欄）'}")
    if not parts:
        return False, "（終了系フィールドが存在しない）"
    return True, " / ".join(parts)


def _print_rows(rows, group_name, definition):
    print("\n" + "=" * 78)
    print(f"{group_name}: 各行の結果（#35 の A〜E 分類）／ラベルは{definition}")
    print("=" * 78)
    print(f"{'':2s}{'#':>4} {'分類':4s} {'期待':6s} {'出力':6s} タイトル / 着地先")
    for label, result, klass in rows:
        flag = "  " if klass == "A" else "**"
        print(f"{flag}{label.no:4d} {klass:4s} {label.expected:6s} {result.status:6s} "
              f"{label.title} / {result.matched_title or '（着地なし）'}")


def _metrics(rows, denominator, group_name):
    classes = Counter(klass for _, _, klass in rows)
    total = len(rows)
    denominator_numbers = {label.no for label in denominator}
    false_negatives = [
        (label, result, klass) for label, result, klass in rows
        if label.no in denominator_numbers and klass in ("B", "E-a", "E-b")
    ]
    wrong_answers = [(l, r, k) for l, r, k in rows if k in ("C", "D")]
    unknown_returned = [r for r in rows if r[1].status == STATUS_UNKNOWN]
    not_found_returned = [r for r in rows if r[1].status == STATUS_NOT_FOUND]
    landed = [r for r in rows if r[1].matched_title is not None]

    fn = _rate(len(false_negatives), len(denominator))
    wa = _rate(len(wrong_answers), total)
    # 判定不能率の分母は**全行**とする（#35 §8-5 の計算そのもの。同節の「記事なしは含めない」は
    # *分子*の話で、#35 は実際に 8/22 と 12/57 ＝全行を分母として算出している）。
    # #47 の完了条件は「#35 との差分を出す」ことなので、#35 と同じ計算でなければ差分の意味が
    # 無い。**主指標はこちら。**
    ur = _rate(len(unknown_returned), total)
    # 参考値: 記事に着地した行のみを分母にしたもの。両者は意味が違う。
    #   主指標 = 入力全体のうち判定不能だった割合
    #   参考値 = 判定を試みた行のうち判定不能だった割合
    landed_denominator = total - len(not_found_returned)
    ur_landed = _rate(len(unknown_returned), landed_denominator)

    print(f"\n{group_name}")
    print(f"  分類内訳: {dict(classes)}")
    print(f"  偽陰性率   = (B＋E) / 分母 = {len(false_negatives)}/{len(denominator)} = {fn:.1f}%")
    print(f"  誤答率     = (C＋D) / 全行 = {len(wrong_answers)}/{total} = {wa:.1f}%")
    print(f"  判定不能率 = 判定不能 / 全行 = "
          f"{len(unknown_returned)}/{total} = {ur:.1f}%  ← 主指標（#35 と同じ計算）")
    print(f"    参考: 判定を試みた行のみを分母 = "
          f"{len(unknown_returned)}/{landed_denominator} = {ur_landed:.1f}%")
    print(f"  1件あたりの変動幅（分母 {len(denominator)}）: {100 / len(denominator):.2f} ポイント")

    # 判定ロジックの実力（記事に着地した行のみ）。A の件数をそのまま精度にしないための分解。
    landed_ok = sum(1 for _, _, k in landed if k == "A")
    trivial = total - len(landed)
    print(f"  ── 内訳: 記事に着地 {len(landed)} 件 / 着地せず {trivial} 件"
          f"（判定ロジックを通っていない）")
    print(f"     判定ロジックの正答率 = {landed_ok}/{len(landed)} = "
          f"{_rate(landed_ok, len(landed)):.1f}%")
    return {"fn": fn, "wa": wa, "ur": ur, "ur_landed": ur_landed,
            "false_negatives": false_negatives, "wrong_answers": wrong_answers,
            "landed": landed, "rows": rows}


def _print_m35_comparison(title, entries):
    """回帰群の失敗を #35 の記載と照合する。

    回帰群にはマーク体系が無い（#35 由来のラベルなので M-1〜M-9 を付けていない）ため、
    拡張群向けの「マークなしの失敗＝新規の失敗パターン」判定は当てはめない。当てはめると
    既知の失敗が全件「新規」に見えてしまう。代わりに #35 段階1 の生データと突き合わせ、
    **#35 に記載のある既知の失敗かどうか**を判定する。#35 に無い失敗が本当の新規パターン。
    """
    print("\n" + "-" * 78)
    print(f"{title}（#35 段階1 の記載との照合）")
    print("-" * 78)
    print("  ※ 回帰群はマーク未付与のため、マーク別内訳および「新規の失敗パターン」の")
    print("     該当判定は行わない（拡張群向けの判定基準であるため）。\n")
    if not entries:
        print("  該当なし")
        return
    novel = []
    for label, result, klass in entries:
        m35_status, m35_class = M35_STAGE1_RESULTS[label.no]
        known = (result.status == m35_status)
        tag = "既知（#35 と同一）" if known else "★#35 に無い＝新規の失敗パターン"
        print(f"  [{label.no}] {label.title}: 期待={label.expected} 出力={result.status}({klass}) "
              f"／ #35: {m35_status}({m35_class}) → {tag}")
        if not known:
            novel.append((label, result, klass, m35_status, m35_class))
    print(f"\n  既知の失敗 {len(entries) - len(novel)} 件 / **新規の失敗パターン {len(novel)} 件**")
    for label, result, klass, m35_status, m35_class in novel:
        print(f"    [{label.no}] {label.title}: #35 は {m35_status}({m35_class}) だったが "
              f"今回は {result.status}({klass})")
        print(f"        判定根拠: {(result.evidence or '（なし）')[:90]}")


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


def _print_regression_row_diff(regression_rows):
    """回帰群を #35 段階1 と行単位で突き合わせ、出力が変化した行だけを出す。

    指標の差分が「どの行が動いたか」に還元できることを示すため。分母が20と小さいので、
    数ポイントの差は数行の変化に対応する。
    """
    print("\n" + "=" * 78)
    print("回帰群: #35 段階1 からの行単位の変化")
    print("=" * 78)
    changed = []
    for label, result, klass in regression_rows:
        m35_status, m35_class = M35_STAGE1_RESULTS[label.no]
        if result.status != m35_status:
            changed.append((label, result, klass, m35_status, m35_class))
    for label, result, klass, m35_status, m35_class in changed:
        print(f"  ★ [{label.no}] {label.title}: "
              f"{m35_status}({m35_class}) → {result.status}({klass})")
        print(f"        判定根拠: {(result.evidence or '（なし）')[:100]}")
    print(f"\n  出力が変化した行: {len(changed)} / {len(regression_rows)}")
    if not changed:
        print("  （#35 から一切変化なし）")


def _print_person_article_effect(expansion, regression):
    """#45（`_is_person_article()`）由来の偽陰性が何件かを明示する（#47 の完了条件）。"""
    print("\n" + "=" * 78)
    print("#45（_is_person_article）由来の偽陰性")
    print("=" * 78)
    author_rows = [(l, r, k) for l, r, k in expansion["rows"] if l.category == CAT_AUTHOR]
    print(f"  拡張群でカテゴリ2（作者記事）に該当した行: {len(author_rows)} 件")
    for label, result, klass in author_rows:
        verdict = "正答（A）" if klass == "A" else f"失敗（{klass}）"
        print(f"    [{label.no}] {label.title}: 期待={label.expected} 出力={result.status} → {verdict}")
    caused = [x for x in expansion["false_negatives"] if x[0].category == CAT_AUTHOR]
    print(f"  → **#45 由来の偽陰性: {len(caused)} 件**")

    # 回帰群側: #35 のカテゴリ1 は同名・別ジャンル記事なので、人物記事チェックが正当な記事を
    # 誤って弾いていないか（＝取りこぼし E-a が出ていないか）を確認する。
    dropped = [(l, r, k) for l, r, k in regression["rows"] if k == "E-a"]
    print(f"\n  回帰群で `記事なし` に落ちた行（取りこぼし E-a）: {len(dropped)} 件")
    for label, result, klass in dropped:
        print(f"    [{label.no}] {label.title}: 期待={label.expected} → 記事なし")
    if not dropped:
        print("    → 人物記事チェックが正当な記事を誤って弾いた形跡はない")


def _print_definition_debt(regression_rows):
    """回帰群を旧定義のまま据え置いた代償を確認する（#47 で約束した3項目）。"""
    print("\n" + "=" * 78)
    print("回帰群のラベル定義の確認（旧定義のまま据え置いた代償）")
    print("=" * 78)
    print("  回帰群22行のインフォボックス終了系フィールドを機械取得し、")
    print("  新定義（本文＋インフォボックス）ならラベルが変わりうる行を洗い出す。")
    print("  ※ 人手のラベル付けは行わない。ラベルは旧定義のまま据え置く。\n")
    candidates = []
    for label, _result, _klass in regression_rows:
        found, desc = _infobox_end_fields(label.expected_page)
        # 旧定義で `判定不能` としている行にインフォボックスの判定材料があれば、
        # 新定義ならラベルが変わりうる。
        changeable = found and label.expected == UNKNOWN
        flag = "★変わりうる" if changeable else ""
        print(f"  [{label.no}] {label.title:14s} 期待={label.expected:5s} / {desc} {flag}")
        if changeable:
            candidates.append((label, desc))
    print(f"\n  → 新定義ならラベルが変わりうる行: **{len(candidates)} 件**")
    for label, desc in candidates:
        print(f"     [{label.no}] {label.title}: 期待={label.expected} / {desc}")
    if not candidates:
        print("     （なし。旧定義のまま据え置いても新定義との差は生じない）")


def main():
    total = len(REGRESSION_LABELS) + len(LABELS)
    print(f"回帰群 {len(REGRESSION_LABELS)}件 ＋ 拡張群 {len(LABELS)}件 = {total}件 を計測します")

    regression_rows = _run(REGRESSION_LABELS, "回帰群（#35 のカテゴリ1＋対照群・旧定義）")
    expansion_rows = _run(LABELS, "拡張群（実運用 Excel 全数・新定義）")

    _print_rows(regression_rows, "回帰群", DEFINITION_OLD)
    _print_rows(expansion_rows, "拡張群", DEFINITION_NEW)

    print("\n" + "=" * 78)
    print("指標（2群を別々に集計。混ぜた率は出さない）")
    print("=" * 78)
    regression = _metrics(regression_rows, REGRESSION_DENOMINATOR,
                          f"【回帰群】{DEFINITION_OLD}")
    print("\n  --- #35 ベースラインとの直接比較（同一母集団・同一ラベル定義） ---")
    for name, key in (("偽陰性率", "fn"), ("誤答率", "wa"), ("判定不能率", "ur")):
        num, den, base = BASELINE_REGRESSION[name]
        value = regression[key]
        print(f"    {name:6s} #35: {base:5.1f}% ({num}/{den})  →  今回: {value:5.1f}%  "
              f"差分 {value - base:+.1f} ポイント")

    expansion = _metrics(expansion_rows, DENOMINATOR, f"【拡張群】{DEFINITION_NEW}")
    print("\n  --- #35 全体（57行）との参考比較 ---")
    print("    ※ 母集団もラベル定義も異なる。同一条件の比較ではない。")
    for name, key, base in BASELINE_EXPANSION_REFERENCE:
        print(f"    {name:22s} #35: {base:5.1f}%  →  今回: {expansion[key]:5.1f}%  "
              f"差分 {expansion[key] - base:+.1f} ポイント")

    covered = len(expansion["landed"])
    expected_covered = sum(1 for label in LABELS if label.expected_page is not None)
    print(f"\n  拡張群の Wikipedia 記事被覆率（実装ベース）= {covered}/{len(LABELS)} = "
          f"{_rate(covered, len(LABELS)):.1f}%")
    print(f"  同（期待値ベース・人手ラベル）              = "
          f"{_rate(expected_covered, len(LABELS)):.1f}%")

    _print_mark_breakdown("拡張群の偽陰性（B＋E、分母の行のみ）", expansion["false_negatives"])
    _print_mark_breakdown("拡張群の誤答（C＋D）", expansion["wrong_answers"])
    _print_m35_comparison("回帰群の偽陰性（B＋E）", regression["false_negatives"])
    _print_m35_comparison("回帰群の誤答（C＋D）", regression["wrong_answers"])
    _print_regression_row_diff(regression["rows"])
    _print_person_article_effect(expansion, regression)
    _print_definition_debt(regression_rows)

    print("\n" + "=" * 78)
    print("⚠ 結果を報告する際の必須の但し書き")
    print("=" * 78)
    print(f"  回帰群の分母 {len(REGRESSION_DENOMINATOR)} では1件の変動が "
          f"{100 / len(REGRESSION_DENOMINATOR):.2f} ポイント動く。")
    print(f"  拡張群の分母 {len(DENOMINATOR)} では1件の変動が "
          f"{100 / len(DENOMINATOR):.2f} ポイント動く。")
    print("  数ポイント差の比較には意味がなく、読み取れるのは10ポイント単位の傾向に限られる。")
    print("  2群は母集団もラベル定義も異なる。混ぜた率を出してはならない。")
    print("  偽陰性の増減を単独で評価しないこと（誤答率とセットで読む）。")
    print("  A の件数をそのまま精度として引用しないこと（記事に着地しなかった行は")
    print("  判定ロジックを一度も通っていない）。")


if __name__ == "__main__":
    main()
