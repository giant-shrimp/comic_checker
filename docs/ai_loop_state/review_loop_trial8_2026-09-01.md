# review_loop.sh 8回目試走記録（2026-09-01、`??` 経路の検証）

本文書は 8 回目試走の実測記録である。記載する数値はすべて成果物ファイルからの実出力に由来し、導出コマンドを併記する。観測（ファイルに残っている事実）と推測・伝聞を区別して書く。

---

## 1. 試走の概要

| 項目 | 値 |
|---|---|
| セッション（成功） | `20260901-003928` |
| セッション（1回目・失敗） | `20260901-000314` |
| ブランチ | `loop/trial8` |
| `MAX_ROUNDS` | 3 |
| `EXECUTOR_MAX_TURNS` | 30 |
| `CLAUDE_TIMEOUT` | 900（1回目は既定 300 のまま起動して失敗） |
| 実行ラウンド | `round_1` のみ |
| 停止理由 | 起案役が `NO_FURTHER_ACTION` を返し round 1 で終了（`exit 0`） |

主目的は、ADR-015（Issue #231）が対象とする **`diff.txt` の `??` 行（未追跡ファイル）経路** を実ループで検証すること。7 回目試走ではタスクが既存ファイルの編集のみで `??` 行が 1 件も出ず、この経路は未検証のまま残っていた（`review_loop_trial7_2026-08-31.md` §5・§7.2）。新規 Python ファイル＋テストを作るタスクなら `??` を出しつつ pytest だけで検証が完結する、という 7 回目の宿題を受けている。

導出: `ls -1 ~/comic_checker-agent-notes/review_loop/20260901-003928/`

---

## 2. 題材

Issue #251（個人情報・絶対パスの走査を行う CLI を恒久的な検査として実装する）。

instruction は `~/comic_checker-agent-notes/trial8_instruction.md`（リポジトリ外・コミット対象外）。`docs/ai_loop_state/instruction_template.md` を複製し、冒頭の雛形説明を削除して `## タスク` と `## 完了条件` を書き換えたもの。`## 実行できないコマンドの扱い（ADR-016 案C）` 節は正本 `docs/ai_loop_state/executor_command_constraints.md` と一字一句一致することを `diff` で確認済み。新規に作らせるファイルは `scripts/check_no_personal_info.py` と `tests/test_check_no_personal_info.py` の 2 つのみ、`verify.sh` への組み込みは明示的にスコープ外とした。

---

## 3. 1回目の起動失敗（セッション `20260901-000314`）

### 観測

`round_1/` には `instruction.md`（4023 バイト）・`executor_result.json`（**0 バイト**）・`executor_result.err`（**0 バイト**）の 3 ファイルのみが残り、`report.md` 以降は生成されていない。

| 項目 | 値 | 導出 |
|---|---|---|
| `executor_result.json` の行数 | 0 | `grep -c '' ~/comic_checker-agent-notes/review_loop/20260901-000314/round_1/executor_result.json` |
| `executor_result.err` の行数 | 0 | `grep -c '' ~/comic_checker-agent-notes/review_loop/20260901-000314/round_1/executor_result.err` |
| `round_1/` の中身 | `instruction.md` / `executor_result.json` / `executor_result.err` のみ | `ls -la ~/comic_checker-agent-notes/review_loop/20260901-000314/round_1/` |

このセッションは `CLAUDE_TIMEOUT` を既定の 300 秒のまま起動していた。実行役は起動し、ツールでファイルを作る所まで動いた（作業ツリーに `scripts/check_no_personal_info.py` が残存していた）が、`--output-format json` は全出力を最後に一括 flush する仕様のため、最終 JSON を出す前に打ち切られ、`executor_result.json` が 0 バイトのまま残った。`review_loop.sh` は空 JSON を検出すると `check_executor_result()` が `return 2` を返し、`exit 2` で停止する経路に入る。

### 端末に表示された終了コード 127 について

**観測**: 起動した端末には終了コード **127** が表示された（この数値はセッションディレクトリのファイルには残っていない。端末表示のみ）。

**確認できること**:

- `scripts/review_loop.sh` 本文に文字列 `127` は現れない。
- `trap` は定義されていない（`set -euo pipefail` の 1 行のみ）。
- 空 JSON / 不正 JSON を受けたときの `check_executor_result()` の戻り値は `2` / `1` / `0` の 3 通りだけで、`return 127` も `exit` も無い。呼び出し元がその `2` を受けて出す終了コードは `exit 2`。
- `timeout` も `claude` も「コマンドが見つからない」場合は診断文字列を stderr に出し、`2> executor_result.err` により `executor_result.err` に残るはずだが、同ファイルは 0 バイト。したがって 425 行目の `timeout "$CLAUDE_TIMEOUT" claude ...` が "command not found" で 127 を出したわけではない。

**推測（未特定）**: 127 の出所は特定できていない。候補として「`review_loop.sh` を起動した外側のコマンド／ラッパの終了コードが 127（そのコマンド自体が not found）」「`claude` が子プロセスの不在等で内部的に 127 を返しつつ stdout/stderr を出さなかった」などが残るが、起動時の端末トランスクリプトが手元に無く確定できない。**`review_loop.sh` の内部に 127 を返す経路は無い**、という点のみが確定している。

---

## 4. 2回目（セッション `20260901-003928`）の実行役メトリクス

| 指標 | 7 回目 `round_1` | 8 回目 `round_1` |
|---|---|---|
| `subtype` | `success` | `success` |
| `is_error` | false | false |
| `terminal_reason` | completed | completed |
| `num_turns` | 20 | 27 |
| `permission_denials` | 0 件（空配列） | 0 件（空配列） |
| `duration_ms` | 98554 | **351968** |
| `total_cost_usd` | 0.48709459999999993 | 0.6465812 |

導出:

```
jq '{subtype, is_error, terminal_reason, num_turns, duration_ms, total_cost_usd, permission_denials}' \
  ~/comic_checker-agent-notes/review_loop/20260901-003928/round_1/executor_result.json
```

7 回目のセッションは `20260831-002025`。8 回目は `EXECUTOR_MAX_TURNS=30` に対し `num_turns=27` で、余裕を残して正常完了した。

---

## 5. 監査役のメトリクスと VERDICT

| 指標 | 値 | 導出 |
|---|---|---|
| `subtype` | `success` | `jq '{subtype, is_error, terminal_reason, num_turns, total_cost_usd}' ~/comic_checker-agent-notes/review_loop/20260901-003928/round_1/result.json` |
| `is_error` | false | 同上 |
| `terminal_reason` | completed | 同上 |
| `num_turns` | 3 | 同上 / `cat .../round_1/metrics.json` |
| `total_cost_usd` | 0.32467899999999994 | 同上 |
| VERDICT | `APPROVE_CONTINUE` | `cat ~/comic_checker-agent-notes/review_loop/20260901-003928/round_1/verdict.txt` |

`CONTRADICTIONS` は「なし」（`review.md:3`）。

起案役（proposer）は `round_1/proposer/next_instruction.md` の 1 行目に `NO_FURTHER_ACTION` を出力した（`num_turns=1`、`total_cost_usd≈0.0801`）。監査が `APPROVE_CONTINUE`・矛盾なしで、元 instruction の完了条件がすべて満たされている、というのが根拠。これにより round 2 は起動されず `exit 0` で終了した。7 回目は `exit 11`（同一 VERDICT 2 連続）での停止だったため、**`NO_FURTHER_ACTION` 経由の停止は 8 回目が初の観測**（7 回目 §7.3 の宿題）。

導出: `cat ~/comic_checker-agent-notes/review_loop/20260901-003928/round_1/proposer/*`

---

## 6. 検証点ごとの結果

| 検証点 | 7 回目 | 8 回目 | 判定 |
|---|---|---|---|
| `diff.txt` の `^??` 行数 | 0 | **2** | 8 回目で初めて `??` 経路が踏まれた |
| 監査役が `??` 行を参照したか | （`??` 無し） | 参照した（`review.md:5`） | 確認された |
| 実行役の正常終了 | `success` / completed | `success` / completed | 確認された |
| 停止経路 | `exit 11`（同一 VERDICT 2 連続） | 起案役 `NO_FURTHER_ACTION` → `exit 0` | `NO_FURTHER_ACTION` 経路を初観測 |

導出:

```
grep -c '^??' ~/comic_checker-agent-notes/review_loop/20260901-003928/round_1/diff.txt   # => 2
grep -c '^??' ~/comic_checker-agent-notes/review_loop/20260831-002025/round_1/diff.txt   # => 0
```

8 回目の `diff.txt` 全文（導出: `cat .../20260901-003928/round_1/diff.txt`）:

```
=== git status --porcelain ===
?? scripts/check_no_personal_info.py
?? tests/test_check_no_personal_info.py
=== git diff ===
```

`=== git status --porcelain ===` 節に `??` 行が 2 本入り、`=== git diff ===` 節は空（未追跡ファイルは `git diff` に現れないため）。監査役はこの status 節を根拠に「新規 2 ファイルのみ・既存ファイル未変更」を判定した（`review.md:5`）:

> - 新規2ファイルのみ・既存ファイル未変更: `git status --porcelain` は `?? scripts/check_no_personal_info.py` と `?? tests/test_check_no_personal_info.py` の2行のみ、`git diff` 節は空。報告書と一致。

ADR-015（案D）が意図した「未追跡ファイルの証拠を status 見出し付きで監査役へ渡す」経路が、実ループで初めて機能したことが確認できた。

---

## 7. 新たに得られた知見

### 7.1 `CLAUDE_TIMEOUT` の既定 300 秒はタスクの重さに対して不足しうる

2 回目の実行役 `duration_ms` は **351968 ms（約 352 秒）**。1 回目は `CLAUDE_TIMEOUT` を既定の 300 秒のまま起動しており、300 秒では最終 JSON 出力に届かず 0 バイトの `executor_result.json` を生んで失敗した（§3）。2 回目は `CLAUDE_TIMEOUT=900` へ引き上げて成功している。

これは Issue #250（`EXECUTOR_MAX_TURNS` の既定値が実測に対して余裕を欠く）と同型の問題である。`num_turns` の余裕（7 回目 §7.1）だけでなく、壁時計時間の上限も既定値が実タスクに対して薄い。新規ファイル作成＋pytest フル実行＋定数ごとのミューテーションを伴うタスクは 300 秒に収まらないことがある、という実測値が 1 つ得られた。

### 7.2 `drain_stray_input()` が実データで初めて発火した（伝聞）

**伝聞（操作者の端末観察）**: 試走コマンドの投入直後に貼り付けられた 14 バイトが、`drain_stray_input()`（Issue #232 / type-ahead 対策）によって先行入力として破棄された、と報告されている。7 回目 §5 では type-ahead の警告出力は観測されておらず、実データでの発火はこれが初めてとされる。

**観測の限界**: セッションディレクトリ `~/comic_checker-agent-notes/review_loop/20260901-003928/` には drain のログ（`review_loop_debug_*.log` に相当するもの）が残っていない。破棄バイト数や発火の事実をファイルから裏付けることはできず、本項は端末観察の記録にとどまる。今後 drain の発火を追跡可能にするなら、セッションディレクトリへログを残す変更が要る。

### 7.3 監査役は「テストが存在すること」は確認したが「テストが十分か」は判定しなかった

**観測**: `VERDICT: APPROVE_CONTINUE` / `CONTRADICTIONS: なし` で承認された `round_1` の成果物に、後日の人間レビューで **誤検出 7 件** が見つかった。原因は round_1 版 `HONORIFIC_PATTERN` の構造欠陥である。除外は否定後読み `(?<![仕同模異])` を敬称トークンの直前に置くだけで、`仕同模異` の 4 字以外を先頭字に持つ複合語をすべて素通ししていた。実測で誤検出したのは「多様」「王様」「一様」「態様」「摂氏」「諸君」「宮殿」の 7 語（「模様」は先頭字が `模` で除外集合に含まれていたため唯一免れていた）。

**監査役の言及範囲**: この点は監査役の `CONTRADICTIONS` には入らず、`FOLLOWUPS` に非ブロッキングの保守性コメントとして 1 項だけ挙がっていた（`review.md:19`）:

> - `HONORIFIC_PATTERN` の誤検出抑止が `仕同模異` の固定4字リストのため、「多様」「異常」等の他の複合語には効かない（「多様」は「多」+「様」で誤検出する）。除外語彙をリスト化して定数に切り出すか、抑止対象の網羅方針をコメントに書き残しておくと保守しやすい。

この FOLLOWUP は根本原因（固定 4 字リスト）と誤検出例 1 件（「多様」）を正しく指摘している。一方で、(a) 挙げた具体例は「多様」1 語のみで、実際の 7 語には触れていない（併記された「異常」は `様/氏/君/殿` を含まず、そもそもこのパターンに一致しない誤った例）、(b) 位置づけは「保守しやすい」という改善提案であってブロッカーではない、(c) VERDICT を動かしていない。

`review.md` の他の FOLLOWUPS（`review.md:17`〜`:21`）も、`verify.sh` 実行主体の運用整合、`HUNK_HEADER_PATTERN` の行全体スキップ、`sys.path` 汚染、`verify.sh` 組み込みの未着手、といった内容で、いずれも「テストが押さえていない検出漏れ／誤検出そのもの」を矛盾として立てる指摘ではない。

**この試走から言えること**: 監査役は「報告書と実成果物の矛盾」を検出する役割であり、テストが 1 件も押さえていない欠陥は原理的に検出できない。round_1 のテストは指示で名指しされた 2 例（「仕様」「同様」）と、除外集合に偶然含まれる「模様」しか固定しておらず、他の複合語の誤検出を 1 件も検査していなかった。`APPROVE_CONTINUE` は完了条件（テストが存在し、pytest が通り、件数が減っていない）の充足を意味するのであって、成果物の品質保証ではない。指示側で「誤検出の抑止」を要求するなら、抑止すべき語の集合そのものをテストに列挙させる完了条件が要る。

---

## 8. 成果物の扱い

試走の成果物は `~/comic_checker-agent-notes/review_loop/20260901-003928/` 配下にあり、リポジトリ外・コミット対象外である。試走で生じたコード変更（新規 2 ファイル）は作業ツリーに未追跡で残り、`loop/trial8` ブランチにはコミットしていない。

Issue #251 の対処は、§7.3 の誤検出 7 件を人間レビューで修正（`HONORIFIC_PATTERN` を除外語彙一覧 `HONORIFIC_EXCLUDE_PATTERN` 方式へ作り直し、`sys.path` 汚染を `importlib` 直接ロードへ置換、誤検出 7 語と敬称 3 例をパラメータ化テストで固定）したうえで、別途 PR #252 として整理し、マージ済みである。`verify.sh` への組み込みは PR #252 でもスコープ外とし、Issue #251 は `Fixes #251` により自動クローズされた。
