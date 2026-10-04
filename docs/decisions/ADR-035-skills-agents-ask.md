# ADR-035: スキルと実装役の定義を deny から ask に移し、AI が反映して人が承認する

- 日付：2026-10-04
- 状態：採用

## 背景
- ADR-034 決定7は、人が行う作業に「deny 対象の編集」を含め、deny 対象の変更は司令塔が全文と sha256 を用意してユーザに依頼するとした。
- この方式では、ユーザが別のターミナルで cp・git add・git commit を行う必要があった。ユーザが PC を離れ、スマートフォンから Claude Code を遠隔操作しているときは、この作業ができない（2026-10-04、Issue #401 の作業中に発生）。
- ADR-008 決定1は、.claude/settings.json に deny のみを置き、allow は置かないとした。
- 権限ルールの評価順は deny → ask → allow である。ask に一致した操作は auto mode でも確認を求め、allow（.claude/settings.local.json を含む）は ask を上書きしない。確認を出せない文脈では承認されない。例外は bypassPermissions で、本プロジェクトでは使っていない（公式ドキュメント permissions で確認）。

## 決定
1. 次のファイルの Edit/Write を、.claude/settings.json の deny から ask に移す（PR #402）。.claude/skills/ 以下のスキル6件（commander・post-merge-cleanup・pre-push-check・publish-github・replace-doc-range・report-self-check）の SKILL.md と、.claude/agents/ 以下。
2. ask 対象の変更は Claude Code が反映する。反映の前に差分と sha256 を示してチャットでユーザの同意を得て、反映時の承認画面でユーザが承認する。
3. 次は deny に残し、人が編集する。.claude/settings.json、scripts/verify.sh・scripts/setup_hooks.sh・scripts/check_title_leak.py、.githooks/ 以下、.github/workflows/ 以下。
4. 本 ADR は次の決定を改める。ADR-034 決定7の「deny 対象の編集」は、決定3のファイルの編集に限る。ask 対象について人が行うのは、同意と承認画面での承認とする。ADR-008 決定1の「deny のみを置く」は「deny と ask を置く」に改める。allow を置かないことは変えない。

## 確認したこと
- Issue #401（PR #403）で、Claude Code が cp でスキルを反映する際に承認画面が1回出て、ユーザの承認後に反映された。ask は Bash の cp にも効いた。
- .claude/settings.json の変更は、実行中のセッションに再起動なしで反映された（PR #402 の取り込み直後から ask が効いた）。

## 残る注意
- ask は承認を求めるだけで、承認する人が内容を確かめなければ防御にならない。
- deny と同じく、別の書き方（シェル経由など）を列挙で塞ぎ切るものではない（.claude/settings.json の _note_deny_scope）。
