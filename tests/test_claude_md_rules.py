"""CLAUDE.md に明記されているべき運用ルールを固定するテスト。

CLAUDE.md はコミット時の作法（`git add -A` 禁止、`Fixes #N` の付与など）を
「作業ルール」節に列挙している。文言そのものは変わりうるが、ルールとして
言及されている事実は消えないことを検査する。行番号・前後の文脈は
ハードコードせず、キーワードの含有だけを見る。
"""
from pathlib import Path

CLAUDE_MD = Path(__file__).resolve().parents[1] / "CLAUDE.md"
_TEXT = CLAUDE_MD.read_text(encoding="utf-8")


def test_claude_md_forbids_ai_attribution_trailers():
    """契約: CLAUDE.md は「コミットメッセージに AI 帰属のトレーラを付けない」
    ルールを明記しており、除去対象の代表例として `Co-Authored-By` と
    `Claude-Session` の両方を名指ししている。

    このテストが単独で検知できる壊れ方: このルールの箇条書きごと削除される、
    または代表例の名指しが失われて「何を付けてはいけないか」が読み手に
    伝わらなくなるリグレッション（PR #248 でトレーラが自動付加された事例の
    再発を防ぐための明文）。
    """
    assert "Co-Authored-By" in _TEXT
    assert "Claude-Session" in _TEXT
