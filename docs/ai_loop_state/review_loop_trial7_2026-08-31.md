# review_loop.sh 7回目試走記録（2026-08-31、ADR-016 の効果実測）

本文書は 7 回目試走の実測記録である。記載する数値はすべて成果物ファイルからの実出力に由来し、導出コマンドを併記する。

---

## 1. 試走の概要

| 項目 | 値 |
|---|---|
| セッション | `20260831-002025` |
| ブランチ | `loop/trial7`（試走後に削除済み） |
| `MAX_ROUNDS` | 3 |
| 実行ラウンド | round_1、round_2 の 2 ラウンド（`round_3` は生成されていない） |
| 停止理由 | `exit 11`（同一 VERDICT 2 連続）による正常停止 |

主目的は 2 点。

1. ADR-016（A-1 / A-2 / 案C）の効果を実測すること
2. ADR-015 の `diff.txt` 2 節構成が実ループで生成されるかを確認すること

導出: `ls -1 ~/comic_checker-agent-notes/review_loop/20260831-002025/`

---

## 2. 題材

Issue #121（`_api_get()` の `for` ループ外にある到達不能な `raise_for_status()` の削除）。

instruction は `~/comic_checker-agent-notes/trial7_instruction.md`（リポジトリ外・コミット対象外）。`docs/ai_loop_state/instruction_template.md` を複製し、冒頭の雛形説明を削除して `## タスク` と `## 完了条件` を書き換えたもの。`## 実行できないコマンドの扱い（ADR-016 案C）` 節は正本 `docs/ai_loop_state/executor_command_constraints.md` と一字一句一致することを `diff` で確認済み。

---

## 3. 実行役のメトリクス（6 回目との比較）

| 指標 | 6 回目 round_1 | 7 回目 round_1 | 7 回目 round_2 |
|---|---|---|---|
| `subtype` | `error_max_turns` | `success` | `success` |
| `is_error` | true | false | false |
| `num_turns` | 21 | 20 | 11 |
| `permission_denials` | 8 件 | 0 件（空配列） | 0 件（空配列） |
| `duration_ms` | 140855 | 98554 | 58760 |
| `total_cost_usd` | 0.4306199999999999 | 0.48709459999999993 | 0.1590256 |

導出:

```
jq '{subtype, num_turns, is_error, duration_ms, total_cost_usd, permission_denials}' \
  ~/comic_checker-agent-notes/review_loop/<session>/round_N/executor_result.json
```

- 6 回目のセッションは `20260830-175335`（`round_1` のみ）
- 7 回目のセッションは `20260831-002025`

6 回目の `permission_denials` 8 件の内訳は、`chmod +x` 2 件、`bash scripts/check_errors_inventory.sh` 系 4 件、`source .venv/bin/activate && python -m pytest ...` 1 件、`git diff ... ; .venv/bin/python -m pytest ...` の複合式 1 件。いずれも実行役が自己検証を試みて拒否されたものである。

---

## 4. 監査役のメトリクスと VERDICT

| ラウンド | `num_turns` | `total_cost_usd` | `is_error` | `terminal_reason` | VERDICT |
|---|---|---|---|---|---|
| round_1 | 4 | 0.28987450000000003 | false | completed | `APPROVE_CONTINUE` |
| round_2 | 6 | 0.27357149999999997 | false | completed | `APPROVE_CONTINUE` |

導出: `cat ~/comic_checker-agent-notes/review_loop/20260831-002025/round_N/metrics.json`、`cat .../round_N/verdict.txt`

同一 VERDICT が 2 連続したため `exit 11` で停止した。

---

## 5. 検証点ごとの結果

| 検証点 | 結果 | 根拠 |
|---|---|---|
| ADR-016 の識別力（`permission_denials` の減少・正常終了） | **確認された** | 8 件 → 0 件、`error_max_turns` → `success` |
| ADR-015 の `=== git status --porcelain ===` 節の生成 | **確認された** | §6 の `diff.txt` 冒頭 |
| 監査役が status 節を参照するか | **確認された** | 両ラウンドの `review.md` が `git status --porcelain` に言及 |
| ADR-015 の `??` 行（未追跡ファイル）経路 | **未検証のまま** | `grep -c '^??'` が両ラウンドとも 0 |
| type-ahead 修正（Issue #232） | 警告出力は観測していない | 端末での `c` 入力は正常に受理された |

監査役の言及箇所（導出: `grep -n 'git status --porcelain' .../round_N/review.md`）:

- round_1 `review.md:9` — git 操作なしという実行役の記述が、当該 2 ファイルの `M` のみである状態と整合すると判断
- round_2 `review.md:11` — commit/push/PR 未実施の主張について、追跡済み 2 ファイルの `M` のみで新規コミットの痕跡なしと判断

`is_error=true` の経路では `write_diff_evidence` が呼ばれないため、ADR-015 の効果は正常終了ラウンドでしか観測できない。7 回目で初めて観測条件が成立した。

---

## 6. `diff.txt` の実際の冒頭

round_1・round_2 とも同形（導出: `head -8 .../round_N/diff.txt`）。

```
=== git status --porcelain ===
 M comic_checker/wikipedia_client.py
 M tests/test_wikipedia_client.py
=== git diff ===
diff --git a/comic_checker/wikipedia_client.py b/comic_checker/wikipedia_client.py
index d985e80..b8790f3 100644
--- a/comic_checker/wikipedia_client.py
+++ b/comic_checker/wikipedia_client.py
```

未追跡ファイルの有無（導出: `grep -c '^??' .../round_*/diff.txt`）:

```
round_1/diff.txt:0
round_2/diff.txt:0
```

両ラウンドとも変更は追跡済み 2 ファイルの `M` のみであり、`??` 行は 1 件も出現しなかった。したがって Issue #231 が本来対象とする経路は、7 回目試走でも検証されていない。

---

## 7. 残る懸念

### 7.1 `num_turns` が上限に一致している

round_1 の `num_turns` は 20 で、`EXECUTOR_MAX_TURNS` の既定値 20 と一致する。`subtype` は `success` であり上限到達による停止ではないが、余裕が無い。タスクがわずかに重ければ 6 回目と同じ `error_max_turns` に至る可能性がある。上限の引き上げ、またはタスク粒度の指針が必要かどうかは未決である。

### 7.2 `??` 経路が未検証

検証には、実行役が新規ファイルを作るタスクが必要である。ただし新規シェルスクリプトを作るタスクは `bash foo.sh` が `EXECUTOR_ALLOWED` で拒否されるため、実行役の自己検証が成立しない。**新規 Python ファイル＋テストを作るタスク**であれば、`??` を出しつつ pytest のみで検証が完結する。

### 7.3 `NO_FURTHER_ACTION` の発火条件が未検証

round_2 のタスクは起案役の判断による堅牢化（`ast.FunctionDef` → `(ast.FunctionDef, ast.AsyncFunctionDef)`）だった。本旨からの逸脱ではないが、起案役が「やることが無い」と判断せず微修正を提案し続ける傾向がある可能性がある。停止は `exit 11`（同一 VERDICT 2 連続）によるものであり、`NO_FURTHER_ACTION` 経由ではない。

---

## 8. 成果物の扱い

試走の成果物は `~/comic_checker-agent-notes/review_loop/20260831-002025/` 配下にあり、リポジトリ外・コミット対象外である。試走で生じたコード変更は作業ツリーのみに存在し、`loop/trial7` ブランチにはコミットされていない。Issue #121 の対処は別途 PR #247 として整理され、マージ済みである。
