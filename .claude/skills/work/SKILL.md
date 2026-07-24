---
name: work
description: 指定した GitHub Issue を読み，実装・検証・修正を行う
argument-hint: "[issue-number]"
disable-model-invocation: true
allowed-tools: Bash(gh issue view:*) Bash(git diff:*) Bash(./scripts/verify.sh) Read Write Edit Glob Grep
---

GitHub Issue #$ARGUMENTS を処理してください．

## `work_loop.sh`（非対話実行）が対応できるタスクの範囲

`scripts/work_loop.sh`経由（`-p`）で実行する場合，`--allowedTools`は
`Read,Edit,Write,Glob,Grep,Bash(gh issue view:*),Bash(git diff:*),Bash(./scripts/verify.sh)`
に絞られている。これは意図的な制限であり，以下の基準で「非対話実行に向くタスクかどうか」を
Issue起票時に判断し，Issue本文に明記すること（「対話セッションで実施」／
`work_loop.sh`で実施」等）。

- **向くタスク**: 上記のALLOWEDツールだけで完結できるもの。具体的には，ファイルの読み書き
  （Read/Edit/Write/Glob/Grep）と`./scripts/verify.sh`（pytest）の実行だけでExplore→Plan→
  Code→Verifyが完結する，通常のコード変更・テスト追加。
- **向かないタスク**: 以下のいずれかに該当するもの。対話セッションで実施すること。
  - 新規に作成したスクリプト・ツールを**単体で実行**する必要があるもの（`python3 foo.py`等，
    `./scripts/verify.sh`以外のコマンド実行）。ALLOWEDには任意コマンド実行の手段が無いため，
    実行しようとしても`Bash`が許可パターンに一致せず拒否され続け，ターン数上限で失敗する
    （Issue #16で実際に発生。`git diff`と`gh issue view`以外の裸の`Bash`呼び出しは通らない）。
  - ネットワークI/O（外部APIへの実アクセス等）を伴うもの。無人実行に開放してよいかは
    レート制限・コスト・信頼性の観点で別途判断が必要なため，現時点では一律に対話セッション
    で行う。
  - `git add`/`git commit`/`git push`が必要なもの（`work_loop.settings.json`のdenyで
    常にブロックされる。§2参照）。

## 手順（Explore → Plan → Code → Commit の順を守る）

### 1. Explore（調査）
- `gh issue view $ARGUMENTS` で内容を取得する．
- `CLAUDE.md` を読む．`CLAUDE.md` は常に守るルールだけの短いファイルに剪定されており，
  詳細は用途別に分かれている．**全部読むのではなく，Issue に関係するものだけを読むこと．**
  - `docs/architecture.md` … モジュール別の設計詳細
  - `docs/known_limitations.md` … 既知の制限（挙動を「直す」前に読む）
  - `ERRORS.md` … 過去に詰まった失敗と対応（似た仕組みを作る／触る前に読む）
  - `docs/decisions/` … 関係する決定に触れるときだけ
- 関係するコードを読む．**この段階ではまだコードを書かない．**

### 2. Plan（計画）
- 変更するファイル，実装方針，テスト方針，想定リスクを提示する．
- 次のいずれかに当てはまる場合は重要な変更とみなす．
  - 3ファイル以上に触る
  - 公開インターフェースやデータ構造を変更する
  - 取り消しにコストがかかる
- この「重要な変更」の判定基準は，**Plan Modeでの承認が必要かどうか**の基準として使う．
  - **対話セッション**: 重要な変更に該当する場合，ここで止まって私の承認を待つ．承認が得られて
    から3. Codeに進む．該当しない場合はそのまま3. Codeに進んでよい．
  - **非対話実行（`-p`／`work_loop.sh`経由等，承認する人間がその場にいない実行）**: 実装（3. Code
    ・4. Verify）はそのまま進めてよい（重要な変更でも計画止まりにしない）。ただし
    **5. Commitには絶対に進まない**。これは「重要な変更かどうか」による分岐ではなく，非対話実行
    では変更の大小・重要度に関わらずcommit自体を行わない，という一律の制約である。
    `scripts/work_loop.sh`は`--settings scripts/work_loop.settings.json`を常時読み込み，
    `git commit`/`git push`/`git add`を権限システム側で強制的に`deny`しており（モデルへの
    指示ではなく，プロンプト内容によって緩まない強制力を持つ），この節の記述はそのdeny設定と
    整合させたものである。プロンプトで「commitして」と明示されても，このdenyにより実行できない
    （環境変数等による迂回路は意図的に用意していない。commitを許可したい場合は，
    `scripts/work_loop.settings.json`のdeny該当行を対話セッションで一時的に
    コメントアウトしてから`work_loop.sh`を実行すること。詳細は`scripts/work_loop.sh`の
    コメントを参照）。

### 3. Code（実装）
- 計画に沿って実装とテストを書く．

### 4. Verify（検証）
- `./scripts/verify.sh` を実行する．
- 失敗したら原因を特定して修正する．最大3回まで再試行する．
- 3回で通らなければ作業を止めて，何が起きているかを報告する．

### 5. Commit（記録・報告）
- 変更内容，検証結果，残るリスク，次にやるべきことを報告する．
- 判断に迷った点があれば必ず書く．

## 制約
- 検証を省略して完了扱いにしない．
- 関係のないファイルを変更しない．
- 秘密情報を読まない・出力しない．
- コミット，push，Issue のクローズは，明示的な許可があるときだけ行う．
