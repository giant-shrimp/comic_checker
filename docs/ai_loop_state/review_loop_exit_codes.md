# review_loop.sh 終了コード一覧

`scripts/review_loop.sh`（ADR-011 段階0のオーケストレータ）が `exit` で
終了するすべての箇所を、現行実装（`b972b57` 時点）から洗い出したもの。
数値・発生条件・到達前提は、いずれも下記に引用したコード行を根拠とする。
推測は含めない。

行番号は `scripts/review_loop.sh` の内容変更で容易にずれる。ずれを疑ったら
`grep -n 'exit [0-9]' scripts/review_loop.sh` 相当（Grep ツールなら
`output_mode: "content"`, `-n: true`, パターン `exit [0-9]`）で一覧を採り直せば
再検証できる。下記「現行実装での exit 一覧」も同じ手段で貼り直すこと。

### 現行実装での exit 一覧（再検証用・`b972b57` 時点）

`grep -n 'exit [0-9]' scripts/review_loop.sh` の結果（`exit` 文のみ。コメント
行の "exit 0" 等は除外済み）:

```
88:  exit 64
93:  exit 1
273:  exit 1
323:    exit 2
339:    exit 0
354:    exit 13
379:    exit 10
383:    exit 11
387:    exit 12
395:    exit 0
415:    exit 0
425:    exit 0
450:        exit 0
```

下の一覧表の各行は、この 13 行のいずれかに対応する（`exit 0` は 339 / 395 /
415 / 425 / 450 の 5 行に分かれる）。

## 一覧

| コード | 意味 | `exit` の行 | トリガ箇所 |
|--------|------|-------------|-----------|
| `0` | 人間が `q` を押して正常終了（複数経路が合流） | 339, 395, 415, 425, 450 | is_error=true / VERDICT=HALT_NEEDS_HUMAN・DONE / 起案役失敗 / NO_FURTHER_ACTION / `[c/q]` で `q` |
| `1` | 前提条件エラー | 93（`die()`）, 273 | jq 不在 / instruction-file 不在 / `main` ブランチ上で実行 |
| `2` | 実行役の呼び出し自体が失敗 | 323 | `executor_result.json` が空／不正JSON（timeout 含む） |
| `10` | 停止条件: ラウンド数上限に到達 | 379 | `round >= MAX_ROUNDS` |
| `11` | 停止条件: 同一 VERDICT が2ラウンド連続 | 383 | `VERDICT == PREV_VERDICT` |
| `12` | 停止条件: no-op ハッシュが前ラウンドと不変 | 387 | `ROUND_SNAPSHOT == PREV_SNAPSHOT` |
| `13` | 監査役の呼び出しが成立しなかった | 354 | `review_audit.sh` が exit 0 以外 |
| `64` | 引数の個数が誤り | 88（`usage()`） | `$# != 1` |

`main()` は明示的な `exit` を経ずに正常復帰することがない（377 行目の条件
`round >= MAX_ROUNDS` により、`round == MAX_ROUNDS` のラウンドで 379 行目の
`exit 10` が必ず発火するため）。詳細は末尾「非明示的な終了」。

---

## コード別の詳細

### `exit 64` — 引数の個数が誤り

- **数値**: 64
- **行**: `usage()` 内の 88 行目。
  ```
  84  usage() {
  85    cat >&2 <<'USAGE'
  86  usage: ./scripts/review_loop.sh <instruction-file>
  87  USAGE
  88    exit 64
  89  }
  ```
- **発生条件**: `main()` 冒頭の 256 行目
  `[ "$#" -eq 1 ] || usage` で、引数が 1 個でないとき `usage` が呼ばれる。
- **到達前提**: `main()` の最初の実行文であり、先に評価される停止条件は無い。
  無条件に最優先で判定される。

### `exit 1` — 前提条件エラー

3 か所からトリガされ、すべて同じ数値 1 で終了する。

- **数値**: 1
- **行**:
  - `die()` 内の 93 行目（`die()` は 91–94 行）。
    ```
    91  die() {
    92    echo "review_loop.sh: $*" >&2
    93    exit 1
    94  }
    ```
  - `main()` 内 273 行目（ブランチ検査、269–274）。
    ```
    269  if [ "$CURRENT_BRANCH" = "main" ]; then
    270    echo "review_loop.sh: エラー: main 上で実行しています。" >&2
    ...
    273    exit 1
    274  fi
    ```
- **発生条件**（`main()` 内での評価順）:
  1. 258 行目 `command -v jq >/dev/null || die "jq が必要です…"` — `jq` が
     PATH に無い。
  2. 269–274 行目 — `git rev-parse --abbrev-ref HEAD` の結果が `main`。
  3. 277 行目 `[ -f "$INSTRUCTION_FILE" ] || die "instruction-file が存在しません…"`
     — 第1引数のパスにファイルが無い。
- **到達前提**:
  - いずれも `exit 64`（引数個数）を通過している（256 行目が先）。
  - jq 検査（258）→ ブランチ検査（269）→ instruction-file 検査（277）の順。
    したがって「instruction-file 不在」に到達するには jq が存在し、かつ
    `main` ブランチ上でないことが前提。
  - すべてループ開始（295 行目の `for`）より前。実行役・監査役・起案役は
    まだ呼ばれていない。
  - 273 行目のトリガ（`exit 1` の 3 条件のうち 2 番目）は、`main` ブランチ上で
    実行していることが前提。review_loop.sh は実行役に既存の作業ブランチ上で
    ファイルを編集させる設計であり、`main` 上で実行すると変更がそのまま
    `main` の作業ツリーに入るため（コメント 260–267 行目）。

> **既知の不整合**: `scripts/review_loop.sh` ヘッダの終了コード表（54 行目）は
> `1` を「前提条件エラー（jq不在・instruction-file不在等）」とだけ説明しており、
> `main` ブランチ上での実行がトリガ条件に含まれることが明示されていない。
> 実装（269–274 行目）には存在する条件なので、本文書側ではトリガとして
> 挙げている。ヘッダ表は `scripts/` 配下のため本タスクでは変更しない。

### `exit 2` — 実行役の呼び出し自体が失敗

- **数値**: 2
- **行**: `main()` 内 320–324 行目。
  ```
  317  executor_check=0
  318  check_executor_result "$ROUND_DIR" || executor_check=$?
  319
  320  if [ "$executor_check" -eq 2 ]; then
  321    echo "review_loop.sh: 実行役の呼び出し自体が失敗しました。" >&2
  322    echo "  ${ROUND_DIR}/executor_result.err を確認してください（timeoutの可能性も含む）。" >&2
  323    exit 2
  324  fi
  ```
- **発生条件**: `check_executor_result()` が `2` を返したとき。同関数
  175–198 行目より、`executor_result.json` が
  「サイズ 0（`! -s`）」または「`jq -e .` でパースできない」場合に `return 2`。
  307–315 行目の `timeout "$CLAUDE_TIMEOUT" claude -p … > executor_result.json … || true`
  が timeout 等で有効な JSON を残さなかったケースがこれにあたる。
- **到達前提**:
  - 前提条件チェック（`exit 1` / `exit 64`）をすべて通過している。
  - ラウンド 1 回目から到達しうる（`round` に依存しない）。
  - `is_error=true`（`check_executor_result` の `return 1`）とは
    **別扱い**。311–315 の JSON が有効なら `return 2` には入らず、
    後述の `exit 0`（339 行目）経路になる（コメント 326–332 行目、
    Issue #223）。

### `exit 10` — 停止条件: ラウンド数上限に到達

- **数値**: 10
- **行**: `main()` 内 377–380 行目。
  ```
  376  # 停止条件（決定9）。ここに該当したら人間の入力を待たず強制終了する。
  377  if [ "$round" -ge "$MAX_ROUNDS" ]; then
  378    echo "review_loop.sh: 強制終了 — ラウンド数上限（${MAX_ROUNDS}）に到達しました。" >&2
  379    exit 10
  380  fi
  ```
- **発生条件**: 現在のラウンド番号 `round` が `MAX_ROUNDS`（既定 10、
  69 行目 `MAX_ROUNDS="${MAX_ROUNDS:-10}"`）以上。
- **到達前提**:
  - 同一ラウンド内で先に評価される停止条件（`exit 2` / `exit 0`(339) /
    `exit 13`）をすべて通過している。特に:
    - `check_executor_result` が `0` を返した（`executor_check` が 1 でも
      2 でもない）。
    - `review_audit.sh` が exit 0（`audit_exit -ne 0` の 351–355 を通過）。
  - 監査結果表示ブロック（360–374）の直後に置かれた **3 つの停止条件の
    先頭**。`exit 11` / `exit 12` より先に評価される。

### `exit 11` — 停止条件: 同一 VERDICT が2ラウンド連続

- **数値**: 11
- **行**: `main()` 内 381–384 行目。
  ```
  381  if [ -n "$PREV_VERDICT" ] && [ "$VERDICT" = "$PREV_VERDICT" ]; then
  382    echo "review_loop.sh: 強制終了 — 同一VERDICT（${VERDICT}）が2ラウンド連続しました。" >&2
  383    exit 11
  384  fi
  ```
- **発生条件**: `PREV_VERDICT` が空でなく、かつ今ラウンドの `VERDICT`
  （357 行目 `VERDICT="$(cat "${ROUND_DIR}/verdict.txt")"`）が前ラウンドの
  ものと一致。
- **到達前提**:
  - `exit 10` を通過している（`round < MAX_ROUNDS`）。
  - `PREV_VERDICT` は `[c=続行]` を選んだときだけ 443 行目
    `PREV_VERDICT="$VERDICT"` で設定される。したがって **最短でも 2 ラウンド目**
    でしか成立しない（1 ラウンド目は `PREV_VERDICT=""`、292 行目の初期化）。
  - `exit 12` より先に評価される。

### `exit 12` — 停止条件: no-op ハッシュが前ラウンドと不変

- **数値**: 12
- **行**: `main()` 内 385–388 行目。
  ```
  385  if [ -n "$PREV_SNAPSHOT" ] && [ "$ROUND_SNAPSHOT" = "$PREV_SNAPSHOT" ]; then
  386    echo "review_loop.sh: 強制終了 — no-opハッシュが前ラウンドと不変です（変更が生じていません）。" >&2
  387    exit 12
  388  fi
  ```
- **発生条件**: `PREV_SNAPSHOT` が空でなく、かつ今ラウンドの
  `ROUND_SNAPSHOT`（358 行目 `ROUND_SNAPSHOT="$(snapshot)"`、`snapshot()` は
  101–108 行目で `git status --porcelain` + `git diff HEAD` + 未追跡ファイルの
  `sha256sum` をまとめて SHA-256 化）が前ラウンドと一致。
- **到達前提**:
  - `exit 10`（`round < MAX_ROUNDS`）と `exit 11`
    （`VERDICT != PREV_VERDICT` もしくは `PREV_VERDICT` 空）を通過している。
  - `PREV_SNAPSHOT` は `[c=続行]` を選んだときだけ 444 行目
    `PREV_SNAPSHOT="$ROUND_SNAPSHOT"` で設定される。**最短でも 2 ラウンド目**。

### `exit 13` — 監査役の呼び出しが成立しなかった

- **数値**: 13
- **行**: `main()` 内 351–355 行目。
  ```
  347  audit_exit=0
  348  "${SCRIPT_DIR}/review_audit.sh" "${ROUND_DIR}/diff.txt" "${ROUND_DIR}/verify.txt" "${ROUND_DIR}/report.md" "$ROUND_DIR" \
  349    || audit_exit=$?
  350
  351  if [ "$audit_exit" -ne 0 ]; then
  352    echo "review_loop.sh: 監査役の呼び出しが成立しませんでした（review_audit.sh exit=${audit_exit}）。" >&2
  353    echo "  ${ROUND_DIR}/result.err ${ROUND_DIR}/result.json を確認してください。" >&2
  354    exit 13
  355  fi
  ```
- **発生条件**: `review_audit.sh` が exit 0 以外を返したとき。
- **到達前提**:
  - `check_executor_result` が `0` を返している（`exit 2` と 339 行目の
    `exit 0` の両方を通過）。すなわち `executor_result.json` は有効な JSON で
    `is_error=false`。
  - 342 行目で `report.md`、344 行目で `verify.txt`、345 行目で `diff.txt` が
    生成済み。
  - 3 つの停止条件（`exit 10/11/12`）より **前**に評価される。

### `exit 0` — 人間が `q` を押して正常終了

`exit 0` は 5 か所にあり、いずれも「人間の 1 キー入力で終了へ合流する」
経路である（ヘッダコメント 36–45 行目）。`wait_for_quit_only()`（241–252）は
`q` が押されたときだけ `return 0` するため、その直後の `exit 0` は
実質「人間が `q` を押した」ことを意味する。

- **数値**: 0
- **行と発生条件**:

  1. **339 行目** — 実行役が `is_error=true` で完了しなかった。
     ```
     333  if [ "$executor_check" -eq 1 ]; then
     334    EXECUTOR_TERMINAL_REASON="$(jq -r '.terminal_reason // "unknown"' "${ROUND_DIR}/executor_result.json")"
     335    # Issue #227: 人間が判断する前に、作業ツリーに残った成果を保全する。
     336    preserve_work_tree_state "$ROUND_DIR" || true
     337    wait_for_quit_only "実行役が正常終了しなかった（is_error=true, terminal_reason=${EXECUTOR_TERMINAL_REASON}）"
     338    echo "review_loop.sh: round ${round} で終了します（実行役 is_error=true）。"
     339    exit 0
     340  fi
     ```
     `check_executor_result()` が `1` を返す（`executor_result.json` は有効な
     JSON だが `.is_error` が `true`。典型例 max_turns 到達）。
     **前提**: `executor_check` が `2` でない（339 は `exit 2` の後）。

  2. **395 行目** — VERDICT が `HALT_NEEDS_HUMAN` または `DONE`。
     ```
     392  if [ "$VERDICT" = "HALT_NEEDS_HUMAN" ] || [ "$VERDICT" = "DONE" ]; then
     393    wait_for_quit_only "VERDICT=${VERDICT}"
     394    echo "review_loop.sh: round ${round} で終了します（VERDICT=${VERDICT}）。"
     395    exit 0
     396  fi
     ```
     **前提**: 3 つの停止条件（`exit 10/11/12`）をすべて通過している
     （`round < MAX_ROUNDS`、VERDICT・snapshot が前ラウンドと不一致）。
     この分岐に入ると起案役は呼ばれない（コメント 390–391）。

  3. **415 行目** — 起案役（`review_proposer.sh`）の呼び出しが失敗
     （ADR-014 決定8: HALT_NEEDS_HUMAN 相当）。
     ```
     410  if [ "$propose_exit" -eq 1 ]; then
     ...
     413    wait_for_quit_only "起案役の呼び出し失敗（HALT_NEEDS_HUMAN相当）"
     414    echo "review_loop.sh: round ${round} で終了します（起案役の呼び出し失敗）。"
     415    exit 0
     416  fi
     ```
     `propose_next_instruction()`（135–156）が `1` を返す
     （145–147: `review_proposer.sh` が exit 0 以外）。
     **前提**: VERDICT が `HALT_NEEDS_HUMAN`/`DONE` でない（395 を通過）、
     3 停止条件を通過。

  4. **425 行目** — 起案役が `NO_FURTHER_ACTION` と判断（DONE 相当）。
     ```
     418  if [ "$propose_exit" -eq 2 ]; then
     419    echo "--- 起案役の判断: 次に実行すべき作業は無い（${NO_FURTHER_ACTION_MARKER}） ---"
     ...
     423    wait_for_quit_only "${NO_FURTHER_ACTION_MARKER}（DONE相当）"
     424    echo "review_loop.sh: round ${round} で終了します（${NO_FURTHER_ACTION_MARKER}）。"
     425    exit 0
     426  fi
     ```
     `propose_next_instruction()` が `2` を返す（149–153:
     `next_instruction.md` の 1 行目が `NO_FURTHER_ACTION`）。
     **前提**: `propose_exit` が `1` でない（424 は `propose_exit==1` 分岐の後）。

  5. **450 行目** — `[c=続行 / q=終了]` プロンプトで人間が `q` を入力。
     ```
     438  while true; do
     439    read -n 1 -r -p "この指示で次ラウンドへ進みますか？ [c=続行 / q=終了]: " KEY
     ...
     448      q)
     449        echo "review_loop.sh: 人間の指示により round ${round} で終了します。"
     450        exit 0
     ```
     **前提**: `propose_exit == 0`（起案役が次 instruction を生成できた）。
     つまり 1〜4 の分岐をすべて通過している。ここで `c` を選ぶと
     `PREV_VERDICT`/`PREV_SNAPSHOT`/`CURRENT_INSTRUCTION_FILE` を更新して
     次ラウンドへ（443–446）。

- **到達前提（共通）**: 前提条件チェック（`exit 1`/`exit 64`）を通過し、
  ループに入っている。ADR-014 は「起案役の失敗に新しい終了コードを新設
  しない」と決めており、これらはすべて既存の `exit 0`（q 限定入力待ち）へ
  合流する（ヘッダコメント 36–45）。

---

## 評価順（1 ラウンド内）

`for` ループ本体（295–457）で `exit` に至りうる分岐を、評価される順に並べると:

1. `exit 2` — `check_executor_result` が 2（320）
2. `exit 0`(339) — `check_executor_result` が 1 / is_error=true（333）
3. `exit 13` — `review_audit.sh` が非 0（351）
4. `exit 10` — `round >= MAX_ROUNDS`（377）
5. `exit 11` — VERDICT が前ラウンドと同一（381）
6. `exit 12` — snapshot が前ラウンドと不変（385）
7. `exit 0`(395) — VERDICT が HALT_NEEDS_HUMAN / DONE（392）
8. `exit 0`(415) — 起案役の呼び出し失敗（410）
9. `exit 0`(425) — 起案役が NO_FURTHER_ACTION（418）
10. `exit 0`(450) — `[c/q]` で `q`（448）／`c` なら次ラウンドへ

前提条件チェックはループより前に:
`exit 64`（256）→ `exit 1`/jq（258）→ `exit 1`/main ブランチ（269）→
`exit 1`/instruction-file（277）。

## 到達不能・非明示的な終了についての判断

- **到達不能と判断した `exit` は無い。** 8 個の数値すべてに、上記のとおり
  具体的な到達経路がある。`exit 11` / `exit 12` は「最短 2 ラウンド目から」
  という制約こそあるが、到達可能である（`[c=続行]` を選べば `PREV_VERDICT`・
  `PREV_SNAPSHOT` が設定される。443–444 行目）。

- **`main()` の正常復帰による暗黙の `exit 0` は事実上到達しない。**
  `for ((round = 1; round <= MAX_ROUNDS; round++))`（295）は
  `round == MAX_ROUNDS` のラウンドで 377 行目の条件 `[ "$round" -ge "$MAX_ROUNDS" ]`
  に必ず該当し、379 行目の `exit 10` が発火する。したがってループカウンタが
  `MAX_ROUNDS` を超えて自然終了する経路は通らない。
  （理論上の例外: `MAX_ROUNDS < 1` を環境変数で与えるとループ本体が一度も
  実行されず `main()` が復帰し、`set -e` 下で最後の文＝ `main "$@"`（465）の
  成功終了として `exit 0` になる。これは `exit` 文ではないため一覧には
  含めない。既定値は 10。）

- **`set -euo pipefail`（64 行目）による打ち切りは `exit` 文ではない。**
  たとえば git リポジトリ外で 268 行目 `git rev-parse --abbrev-ref HEAD` が
  失敗した場合などは、明示的な `exit` を経ずに非 0（git 由来のコード）で
  停止する。本一覧は仕様として管理された `exit` 文のみを対象とする。
