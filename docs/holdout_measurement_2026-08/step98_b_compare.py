# -*- coding: utf-8 -*-
"""作業98-B 突き合わせスクリプト（作成のみ・未実行）。

step98_b_reporting_plan.md に事前確定した報告項目にそのまま従う。項目は変更しない。

【読み取り専用であることの設計上の保証】
入力3ファイル（凍結ラベル・judge()生出力・凍結生データ）はいずれも `json.load` で
読むだけで、書き戻す処理は無い。本スクリプトが書き込む先は出力2ファイル
（機械可読JSON・人間可読Markdown）のみで、入力ファイルへの `open(..., "w")` は
存在しない（末尾の静的自己点検で確認する）。

【カテゴリ分類の役割分担】
- 事前登録 5_metric_definitions のバケット（A_correct/D_error/E_missed/F_unverifiable）
  は本スクリプトが機械的に確定する（曖昧さの無い定義のため）。
- reporting_plan の4カテゴリ（A=v3の穴由来/B=#141〜#144の修正範囲/C=新種/
  D=記事更新の疑い）のうち、**カテゴリDのみ機械的に判定する**（evidence実在確認）。
  A・B・Cは人間が読んで判断する材料を並べるところまでに留め、最終分類はしない。

【用語の衝突についての注意】
バケット（A_correct等）と不一致カテゴリ（A=v3の穴由来等）はどちらも記号Aを含むが
別の分類軸である。本スクリプト内の変数名は bucket_* / category_* で区別する。
"""
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS_DIR = f"{REPO_ROOT}/docs/holdout_measurement_2026-08"

LABELS_PATH = f"{DOCS_DIR}/step98_a3_labels.json"
JUDGE_RAW_PATH = f"{DOCS_DIR}/step98_b_judge_raw.json"
RAW_MATERIAL_PATH = f"{DOCS_DIR}/step98_a3_raw_material.json"

OUT_JSON_PATH = os.path.expanduser("~/comic_checker-agent-notes/step98_b_compare_result.json")
OUT_MD_PATH = os.path.expanduser("~/comic_checker-agent-notes/step98_b_compare_result.md")

V3_HOLES_KNOWN_EXAMPLES = {
    "キャラ者": "#4（年入りinfobox終了系 vs 本文の曖昧な継続示唆）",
    "天使の裁量": "#5（R2の適用範囲が本文中に限定、巻数フィールドの古い基準時点が未カバー）",
    "空色パンデミック": "#7（具体的終了時期を伴わない過去形のみ）",
    "文豪の食彩": "#7（具体的終了時期を伴わない過去形のみ）",
}

END_FIELD_NAMES = ("終了号", "終了日", "終了")
VOLUME_FIELD_NAME = "巻数"


# --- 事前登録 5_metric_definitions のバケット分類（機械的・曖昧さ無し） ---
def classify_bucket(label, judge_status):
    if label in ("連載中", "完結"):
        if judge_status == label:
            return "A_correct"
        if judge_status in ("連載中", "完結"):
            return "D_error"
        return "E_missed"  # judge_status in (判定不能, 記事なし)
    if label == "判定不能":
        if judge_status == "判定不能":
            return "A_correct"
        return "F_unverifiable"  # judge_status in (連載中, 完結, 記事なし)
    raise ValueError(f"想定外のラベル値: {label!r}")


# --- カテゴリD（記事更新の疑い）判定: evidence実在確認 ---
_INFOBOX_EMPTY_VOLUMES_RE = re.compile(
    r"^インフォボックス: 終了号/終了日等が空欄、巻数 = (.*)$"
)
_INFOBOX_HIATUS_RE = re.compile(
    r"^インフォボックス: (.+?) = (.+?)（休載注記のため終了とみなさず）、巻数 = (.*)$"
)
_INFOBOX_SIMPLE_RE = re.compile(r"^インフォボックス: (.+?) = (.*)$")


def check_evidence_exists(evidence, raw_row):
    """judge()のevidenceが、凍結した生データ中に実在するかを確認する。

    戻り値: (result, detail)
      result: "N/A"（evidenceがNone、記事なし等）/ "confirmed"（実在確認できた）/
               "not_found"（生データ中に見当たらない＝記事更新の疑い）/
               "unparsed"（既知の3形式のいずれにも一致せず、機械判定を放棄）
    """
    if evidence is None:
        return "N/A", "evidence自体がNone（判定不能/記事なし行）"

    if raw_row is None:
        return "not_found", "凍結生データに該当タイトルの行が無い"

    if not evidence.startswith("インフォボックス:"):
        # 本文由来の文。extractへの部分文字列一致で確認する。
        extract = raw_row.get("extract") or ""
        if evidence in extract:
            return "confirmed", "本文（extract）中に該当文が実在する"
        return "not_found", "本文（extract）中に該当文が見当たらない"

    fields = raw_row.get("infobox_fields") or {}
    volumes = raw_row.get("infobox_volumes")

    m = _INFOBOX_EMPTY_VOLUMES_RE.match(evidence)
    if m:
        vol_value = m.group(1)
        all_end_empty = all(not fields.get(f) for f in END_FIELD_NAMES)
        volumes_match = (volumes == vol_value)
        if all_end_empty and volumes_match:
            return "confirmed", "終了系全空欄・巻数一致を確認"
        return "not_found", (
            f"終了系全空欄={all_end_empty}, 巻数一致={volumes_match}"
            f"（生データ巻数={volumes!r} vs evidence={vol_value!r}）"
        )

    m = _INFOBOX_HIATUS_RE.match(evidence)
    if m:
        field_name, value, vol_value = m.group(1), m.group(2), m.group(3)
        field_match = fields.get(field_name) == value
        volumes_match = (volumes == vol_value)
        if field_match and volumes_match:
            return "confirmed", "休載注記フィールド・巻数とも一致を確認"
        return "not_found", (
            f"フィールド一致={field_match}（生データ{field_name}={fields.get(field_name)!r} "
            f"vs evidence={value!r}）, 巻数一致={volumes_match}"
        )

    m = _INFOBOX_SIMPLE_RE.match(evidence)
    if m:
        field_name, value = m.group(1), m.group(2)
        if field_name == VOLUME_FIELD_NAME:
            if volumes == value:
                return "confirmed", "巻数フィールド一致を確認"
            return "not_found", f"生データ巻数={volumes!r} vs evidence={value!r}"
        if field_name in fields:
            if fields.get(field_name) == value:
                return "confirmed", f"{field_name}フィールド一致を確認"
            return "not_found", f"生データ{field_name}={fields.get(field_name)!r} vs evidence={value!r}"
        return "unparsed", f"未知のフィールド名: {field_name!r}"

    return "unparsed", "既知の3形式（空欄+巻数／休載注記+巻数／単純フィールド）に一致しない"


def main():
    labels = json.load(open(LABELS_PATH, encoding="utf-8"))
    judge_raw = json.load(open(JUDGE_RAW_PATH, encoding="utf-8"))
    raw_material = json.load(open(RAW_MATERIAL_PATH, encoding="utf-8"))

    label_by_title = {r["input_title"]: r for r in labels["rows"]}
    judge_by_title = {r["input_title"]: r for r in judge_raw["rows"]}
    raw_by_title = {r["input_title"]: r for r in raw_material["rows"]}

    titles_labels = list(label_by_title.keys())
    titles_judge = list(judge_by_title.keys())
    assert titles_labels == titles_judge, "ラベルとjudge()出力でタイトル順序が一致しない"
    assert len(titles_labels) == 100

    rows_out = []
    bucket_counts = {"A_correct": 0, "D_error": 0, "E_missed": 0, "F_unverifiable": 0}

    for title in titles_labels:
        lrow = label_by_title[title]
        jrow = judge_by_title[title]
        raw_row = raw_by_title.get(title)

        label = lrow["expected_status"]
        judge_status = jrow["status"]
        bucket = classify_bucket(label, judge_status)
        bucket_counts[bucket] += 1

        is_mismatch = bucket in ("D_error", "E_missed", "F_unverifiable")

        entry = {
            "no": lrow["no"],
            "input_title": title,
            "label": label,
            "judge_status": judge_status,
            "bucket": bucket,
            "is_mismatch": is_mismatch,
        }

        if is_mismatch:
            ev_result, ev_detail = check_evidence_exists(jrow.get("evidence"), raw_row)
            entry.update({
                "judge_evidence": jrow.get("evidence"),
                "judge_matched_title": jrow.get("matched_title"),
                "judge_url": jrow.get("url"),
                "label_evidence_summary": lrow.get("evidence_summary"),
                "label_confused": lrow.get("confused"),
                "label_confused_conditions": lrow.get("confused_conditions"),
                "category_D_article_update_check": {
                    "result": ev_result,
                    "detail": ev_detail,
                },
                "category_A_v3_hole_known_example": V3_HOLES_KNOWN_EXAMPLES.get(title),
                # カテゴリB・Cの最終分類は人間判断に委ねるため、材料のみを残す。
                "category_BC_note": (
                    "人間が read して category を B(#141-144の修正範囲) / C(新種) / "
                    "その他 のいずれかに分類する。judge_evidence と "
                    "label_evidence_summary を突き合わせて判断する。"
                ),
            })

        rows_out.append(entry)

    mismatches = [r for r in rows_out if r["is_mismatch"]]
    d_error_rows = [r for r in rows_out if r["bucket"] == "D_error"]

    result = {
        "purpose": "作業98-B 突き合わせ結果（機械分類のみ。カテゴリA/B/Cの最終判断は含まない）",
        "inputs": {
            "labels": LABELS_PATH,
            "judge_raw": JUDGE_RAW_PATH,
            "raw_material": RAW_MATERIAL_PATH,
        },
        "total_rows": len(rows_out),
        "bucket_counts": bucket_counts,
        "mismatch_count": len(mismatches),
        "d_error_count": len(d_error_rows),
        "rows": rows_out,
    }

    with open(OUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # --- 人間可読Markdown（不一致行のみを一覧化） ---
    lines = []
    lines.append("# 作業98-B 突き合わせ結果")
    lines.append("")
    lines.append(f"バケット内訳: {bucket_counts}")
    lines.append(f"不一致合計: {len(mismatches)} 件（うち D_error: {len(d_error_rows)} 件）")
    lines.append("")
    for r in mismatches:
        lines.append(f"## No.{r['no']} {r['input_title']} — bucket={r['bucket']}")
        lines.append(f"- ラベル: {r['label']} / judge()出力: {r['judge_status']}")
        lines.append(f"- judge() evidence: {r['judge_evidence']!r}")
        lines.append(
            f"- カテゴリD判定（記事更新の疑い）: "
            f"{r['category_D_article_update_check']['result']} "
            f"— {r['category_D_article_update_check']['detail']}"
        )
        if r["category_A_v3_hole_known_example"]:
            lines.append(f"- v3の穴の既知実例: {r['category_A_v3_hole_known_example']}")
        lines.append(f"- ラベル根拠: {r['label_evidence_summary']}")
        lines.append(
            f"- ラベル(a)〜(f): confused={r['label_confused']}, "
            f"conditions={r['label_confused_conditions']}"
        )
        lines.append("")

    with open(OUT_MD_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("bucket_counts:", bucket_counts, file=sys.stderr)
    print("mismatch_count:", len(mismatches), file=sys.stderr)
    print("wrote:", OUT_JSON_PATH, file=sys.stderr)
    print("wrote:", OUT_MD_PATH, file=sys.stderr)


if __name__ == "__main__":
    main()
