---
name: decompose
description: 大きな目標を実行可能なタスクへ分解し，GitHub Issue 案を作る
argument-hint: "[goal]"
disable-model-invocation: true
allowed-tools: Bash(gh issue list:*) Read Glob Grep
---

目標「$ARGUMENTS」を次の3層に分解してください．

1. ゴール（達成された状態）
2. マイルストーン（3〜5個）
3. 実行タスク（1つ半日以内で終わる粒度）

各タスクに次を含めてください．
- タイトル
- 背景と目的
- 作業内容
- 完了条件（`./scripts/verify.sh` で検証できる形にする）
- 依存関係
- 優先度

もしタスクが「Windows側での手動作業が必要」な場合は，その旨を明記してください．

まず一覧を提示してください．
**私が承認するまで `gh issue create` を実行しないでください．**
