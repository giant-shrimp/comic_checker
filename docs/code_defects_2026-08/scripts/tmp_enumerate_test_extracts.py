"""導出スクリプト（リポジトリ化）。

参照元: docs/code_defects_2026-08/prereg_lineage3_serialized_conjugation.md
4節「フィクスチャ範囲の確定」（旧: `~/comic_checker-agent-notes/
tmp_enumerate_test_extracts.py`という agent-notes 側のパスで参照していたが、
リポジトリ管理外のため将来の再現が不能になるリスクがあった——ERRORS.md
「実測結果の値だけを記録し、導出コマンドを残さないと、同じ手順の再現が不能に
なる」と同種の欠陥。このコミットでリポジトリへ移設して解消する）。

導出内容: `tests/test_wikipedia_client.py` 内の実データ相当の文字列
フィクスチャを ast モジュールで構文解析して列挙する（grepではなく、複数行
文字列・代入形式の揺れを取りこぼさないため）。事前登録4節が採用した
「カテゴリA48件＋カテゴリB11件＋カテゴリC4件＝63件（閾値10）」はこの
スクリプトの出力に基づく。

実行方法（リポジトリルートから）:
    python3 docs/code_defects_2026-08/scripts/tmp_enumerate_test_extracts.py

以下、機能コードは元のスクリプトから無変更。唯一の変更点は、対象ファイルの
参照方法を環境依存の絶対パス（元は `/home/<user>/maehata_ws/comic_checker/
tests/test_wikipedia_client.py` のようなハードコード値）から、このスクリプト
自身の配置場所を起点とした相対解決に変更したことのみ（解決先のファイルは
元のスクリプトと完全に同一）。

列挙の定義（この定義自体が成果物。再現可能であることが要件）:

カテゴリA: モジュールレベルの ast.Assign で、代入先名が "_EXTRACT" で終わり、
値が文字列リテラル（ast.literal_eval で str に評価できるもの。暗黙の隣接
文字列連結・明示的な "+" 連結を含む）であるもの。

カテゴリB: 関数内（ast.FunctionDef 配下、ネスト不問）の ast.Assign で、
値が文字列リテラルであり、かつ次のいずれかを満たすもの:
  - 代入先名が "extract" を含む（大文字小文字問わず）
  - 文字列リテラルが日本語文字（CJK統合漢字・ひらがな・カタカナ）を含み、
    かつ長さが閾値以上（既定20文字。10/20/30の3閾値を併記）

カテゴリC: 関数呼び出しの引数に直接与えられた文字列リテラルで、
呼び出し先名が judge / _judge_extract / _judge_via_infobox のいずれかであり、
日本語文字を含み長さが閾値以上のもの。
"""
import ast
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET = str(_REPO_ROOT / "tests" / "test_wikipedia_client.py")

CJK_RANGES = [
    (0x4E00, 0x9FFF),   # CJK統合漢字
    (0x3040, 0x309F),   # ひらがな
    (0x30A0, 0x30FF),   # カタカナ
]


def has_cjk(s):
    return any(any(lo <= ord(ch) <= hi for lo, hi in CJK_RANGES) for ch in s)


def literal_str_value(node):
    """node が文字列リテラル（連結含む）に評価できれば str を返す。できなければ None。"""
    try:
        val = ast.literal_eval(node)
    except Exception:
        return None
    return val if isinstance(val, str) else None


def target_name(target):
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def call_func_name(call_node):
    f = call_node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def main():
    with open(TARGET, encoding="utf-8") as f:
        source = f.read()
    try:
        tree = ast.parse(source, filename=TARGET)
    except SyntaxError as e:
        print("PARSE ERROR:", e)
        sys.exit(1)

    # 親子関係を構築し、各ノードが「関数内」かどうかを判定できるようにする
    parent_of = {}
    func_ancestor = {}

    def walk(node, parent, in_func):
        parent_of[node] = parent
        func_ancestor[node] = in_func
        next_in_func = in_func or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for child in ast.iter_child_nodes(node):
            walk(child, node, next_in_func)

    walk(tree, None, False)

    category_a = []  # (lineno, name, snippet, full_len)
    category_b = {10: [], 20: [], 30: []}
    category_c = {10: [], 20: [], 30: []}

    module_level_assign_lines = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            module_level_assign_lines.add(id(node))

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            is_module_level = id(node) in module_level_assign_lines
            is_in_func = func_ancestor.get(node, False)
            val = literal_str_value(node.value)
            if val is None:
                continue
            for tgt in node.targets:
                name = target_name(tgt)
                if name is None:
                    continue
                if is_module_level and name.endswith("_EXTRACT"):
                    category_a.append((node.lineno, name, val[:40], len(val)))
                elif is_in_func:
                    name_hit = "extract" in name.lower()
                    for th in (10, 20, 30):
                        cjk_hit = has_cjk(val) and len(val) >= th
                        if name_hit or cjk_hit:
                            category_b[th].append(
                                (node.lineno, name, val[:40], len(val),
                                 "name" if name_hit else "cjk_len")
                            )
        elif isinstance(node, ast.Call):
            fname = call_func_name(node)
            if fname not in ("judge", "_judge_extract", "_judge_via_infobox"):
                continue
            for arg in node.args:
                val = literal_str_value(arg)
                if val is None:
                    continue
                for th in (10, 20, 30):
                    if has_cjk(val) and len(val) >= th:
                        category_c[th].append(
                            (node.lineno, fname, val[:40], len(val))
                        )

    print("=" * 70)
    print("カテゴリA（モジュールレベルの *_EXTRACT 定数、文字列リテラルのみ）")
    print("=" * 70)
    for lineno, name, snippet, length in category_a:
        print(f"L{lineno}\t{name}\t(len={length})\t{snippet!r}")
    print(f"カテゴリA件数: {len(category_a)}")

    for th in (10, 20, 30):
        print()
        print("=" * 70)
        print(f"カテゴリB（関数内ローカル、閾値={th}文字）")
        print("=" * 70)
        # 重複排除（同一行・同一値が name_hit と cjk_hit の両方で入る場合がある）
        seen = set()
        deduped = []
        for row in category_b[th]:
            key = (row[0], row[1], row[3])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        for lineno, name, snippet, length, reason in deduped:
            print(f"L{lineno}\t{name}\t(len={length}, reason={reason})\t{snippet!r}")
        print(f"カテゴリB件数（閾値{th}）: {len(deduped)}")

    for th in (10, 20, 30):
        print()
        print("=" * 70)
        print(f"カテゴリC（judge系関数への直接引数、閾値={th}文字）")
        print("=" * 70)
        for lineno, fname, snippet, length in category_c[th]:
            print(f"L{lineno}\t{fname}\t(len={length})\t{snippet!r}")
        print(f"カテゴリC件数（閾値{th}）: {len(category_c[th])}")

    print()
    print("=" * 70)
    print("合計（閾値20を採用した場合）")
    print("=" * 70)
    seen_b20 = {(r[0], r[1], r[3]) for r in category_b[20]}
    total_20 = len(category_a) + len(seen_b20) + len(category_c[20])
    print(f"A={len(category_a)} + B(20)={len(seen_b20)} + C(20)={len(category_c[20])} = {total_20}")


if __name__ == "__main__":
    main()
