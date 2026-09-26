# ADR-030: クラウド実行への移行と、役割分離の方針

- 日付：2026-09-26
- 状態：採用

## 背景

実装計画書v8と現状を比較した。3役のレビューループ（`review_loop.sh`）は実装済みだが
実行記録が無い。`work_loop.sh`の最終実行は2026-08-04。実作業は、人間が指示と報告を
中継する対話ループで行われている。

Claude Codeの実行場所を`claude.ai/code`のクラウドセッションへ移す。

## 決定

1. 中継方式（指示ブロックの作成 → ユーザが中継 → Claude Codeが実行・報告）は維持し、
   変更するのは実行場所だけとする。変える変数を1つに絞り、問題の原因を切り分けられる
   ようにする。
2. 役割分離は、エージェントの人格ではなく権限の差で行う。調査役と監査役は読み取り
   専用のサブエージェント（`.claude/agents/`）として定義する（別途。`.claude/`は
   deny対象のためユーザが作成する）。監査役には、根拠を必須とする指摘形式を課す。
3. マネジメント役のエージェントは置かない。優先順位・採否の判断はユーザが行う。
   エージェントに任せるのは集計のみとする。
4. クラウドの対話セッションには`--max-turns`・`--max-budget-usd`に相当する上限が
   無いため、「1セッション1Issue」「上限を超えたら報告して終了」を運用規則とする。
   機械的な上限が必要な作業は、上限フラグを持つ経路（ローカルのスクリプト、Actions）
   で行う。
5. PRのAuto-fixは使わない（人間がレビューとマージを行う運用と衝突するため）。
6. クラウド環境の構成は次のとおり。環境の設定は`claude.ai/code`側（リポジトリ外）に
   あるため、ここに内容を記録する。
   - 環境変数：`DISPLAY=:99`
   - セットアップスクリプト：（下の「付録」をそのまま収録する）
   - リポジトリ側：`scripts/cloud_setup.sh`（SessionStartフックから呼ぶ。`.venv`を
     `/opt/comic_venv`へのリンクとして作り、Xvfbを起動する）。`.claude/settings.json`の
     `attribution.sessionUrl=false`。

## 却下した案

- **マネジメント役のエージェントが他のエージェントを監視する構成**: 却下。
  理由：(1) 監視役もLLMであり、判定が確率的になる（自己採点の問題が1段ずれる
  だけ）。(2) 判断をエージェントに移すことになり、「判断はユーザが行う」原則に
  反する。(3) 費用と、受け渡しでの情報の欠落（静かな失敗）がエージェントの数
  だけ増える。

## 付録（セットアップスクリプト）

```bash
#!/bin/bash
set -e
apt-get update || true
apt-get install -y gh python3.12 python3.12-venv python3-tk xvfb
if [ ! -x /opt/comic_venv/bin/python ]; then
  /usr/bin/python3.12 -m venv /opt/comic_venv
fi
/opt/comic_venv/bin/pip install -q openpyxl requests tkinterdnd2 playwright pytest
```

## 関連

- Refs #325
