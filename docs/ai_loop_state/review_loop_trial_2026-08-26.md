# review_loop.sh 初回試走記録（2026-08-26）

ADR-011（`docs/decisions/ADR-011-review-loop-design.md`）段階0の初回試走の実測記録。
すべて実際のファイル内容・コマンド出力から転記した値であり、推測・記憶による記述は
含まない。導出コマンドはその都度併記する。

## 1. セッション概要

- セッションID: `20260826-235806`
  （`ls -1 ~/comic_checker-agent-notes/review_loop/` の実測値。
  `review_loop.sh`の`SESSION="$(date +%Y%m%d-%H%M%S)"`による生成）
- 対象ブランチ: `fix/errors-md-allow-commit`
- instruction: `~/comic_checker-agent-notes/review_loop_trial/instruction_round1.md`
  （ERRORS.mdの`ALLOW_COMMIT=1`失効記述の修正を指示）
- ラウンド数: **1回のみ**
  （`ls -1 ~/comic_checker-agent-notes/review_loop/20260826-235806/`で
  `round_1`のみが存在し、`round_2`は生成されていないことを確認済み）
- `review_loop.sh`の終了コード: **0**（人間が`q`を入力しての正常終了。
  この値はスクリプトが生成したファイルには記録されず、実行した人間からの
  報告に基づく）

## 2. round_1に生成されたファイル一覧とサイズ

`ls -la ~/comic_checker-agent-notes/review_loop/20260826-235806/round_1/`の実測値。

| ファイル | サイズ(バイト) |
|---|---:|
| `instruction.md` | 1,439 |
| `executor_result.json` | 2,815 |
| `executor_result.err` | 0 |
| `report.md` | 816 |
| `verify.txt` | 507 |
| `diff.txt` | 2,014 |
| `prompt.txt` | 4,852 |
| `result.json` | 4,313 |
| `result.err` | 0 |
| `review.md` | 2,322 |
| `verdict.txt` | 17 |
| `metrics.json` | 135 |

## 3. 実行役（executor）

`executor_result.json`から実測（コマンド: `python3 -c "import json; d=json.load(open('executor_result.json')); print(d['num_turns'], d['total_cost_usd'], list(d['modelUsage'].keys()))"`）。

- モデル: `modelUsage`のキーに`claude-sonnet-5`が含まれる（`review_loop.sh`が
  `--model sonnet`を渡していることと整合。内部的に`claude-haiku-4-5-20251001`も
  併用されている）
- `num_turns`: **12**
- `total_cost_usd`: **0.2203498**
- `is_error`: `false`
- `terminal_reason`: `completed`
- `permission_denials`: `[]`（空配列）

`report.md`の全文（英語で書かれている。instructionは日本語、言語指定は無し）:

> Fixed the stale description in `ERRORS.md`, section `## AI Loop（scripts/work_loop.sh）の検証で分かったこと（Issue #14〜#16）`
> (retrieve via `grep -n "^## AI Loop" ERRORS.md`; the corrected text is near
> `grep -n "ALLOW_COMMIT" ERRORS.md`).
>
> Change: the sentence claiming `ALLOW_COMMIT=1` is a currently-required opt-in
> was reframed as a past design decision that was later abandoned, with the
> reason (all-or-nothing bypass) and evidence cited (commits 3341902 → 6d7ef64,
> and `scripts/loop_git.sh`'s comment, retrievable via
> `grep -n "ALLOW_COMMIT" scripts/loop_git.sh`). No lines were deleted — the
> original reasoning is preserved, now marked as historical, plus a closing
> note that no such bypass exists in `work_loop.sh` today.
>
> No other files were touched, and nothing was committed or pushed.

## 4. 監査役（auditor）

`metrics.json`から実測（`review_audit.sh`が`result.json`から
`{total_cost_usd, num_turns, is_error, terminal_reason, permission_denials}`を
抽出して書き出したもの）。

```json
{
  "total_cost_usd": 0.3150445,
  "num_turns": 7,
  "is_error": false,
  "terminal_reason": "completed",
  "permission_denials": []
}
```

- モデル: `result.json`の`modelUsage`のキーに`claude-opus-5`が含まれる
  （`review_audit.sh`が`--model opus`を渡していることと整合）

## 5. 1ラウンドあたりの合計コスト

`executor_result.json`の`total_cost_usd`（0.2203498）＋`metrics.json`の
`total_cost_usd`（0.3150445）＝ **0.5353943 USD**（1ラウンドあたり）。

## 6. VERDICTと監査役の判断根拠

`verdict.txt`: **`APPROVE_CONTINUE`**

`review.md`のCONTRADICTIONS節: **「なし」**。以下を裏付けとして提示していた
（`review.md`から要旨転記）。

- 報告書が挙げるセクション見出しが実在すること（`grep -n "^## AI Loop" ERRORS.md`
  で再取得できる見出しと一致）
- diffの追加行が「過去の設計として再構成し、理由と根拠を併記」という報告内容と一致
- 報告書が引用する根拠（`scripts/loop_git.sh`の「66分後」「3341902 → 6d7ef64」
  「オール・オア・ナッシング」という記述）が実在すること
- 「現在の`work_loop.sh`に環境変数等による迂回路は無い」という主張の裏付け
  （`work_loop.sh`内に`ALLOW_COMMIT`の出現が0件であること）
- 「他ファイルは未変更・commit/pushしていない」がgit statusの実際の状態
  （`M ERRORS.md`のみ）と整合すること
- `verify.sh`が`VERIFY PASSED`（283 passed、検出54/59・副作用1/37一致）であること

## 7. FOLLOWUPS（VERDICTには影響していない）

`review.md`のFOLLOWUPS節（3件、要旨）:

1. 報告書の「No lines were deleted」という表現は、diff上は3行削除・8行追加
   （折り返しによる変更）であり、「削除された記述内容は無い」という意味では
   正確だが文言と成果物の見え方が一段ずれている、という指摘
2. 修正の出所である`docs/ai_loop_state/2026-08-26.md`§Cが
   「`ERRORS.md:34`（現在も残存）」という古い記述のまま残っており、
   今回の修正で解消済みである旨を追記しておくと次のループが同じ指摘を
   再検出しない、という指摘
3. 根本原因（「記録が実装に追従しているか確認する仕組みが無い」こと）への
   再発防止は、今回は個別対応に留まっており、別途検討の余地がある、という指摘

いずれも`review.md`の出力形式（`scripts/review_audit_prompt.md`）が定める
「FOLLOWUPSの内容はVERDICTに影響させてはならない」という制約どおり、
CONTRADICTIONS「なし」・VERDICT `APPROVE_CONTINUE`とは独立に記載されている。

## 8. 機構の通過判定

| 項目 | 判定 |
|---|---|
| 実行役が起動しreport.mdが生成されたか | ○ |
| 実行役がERRORS.mdを実際に編集したか | ○ |
| verify.shが実行されverify.txtが残ったか | ○ |
| diff.txtに変更が記録されたか | ○ |
| 監査役が起動しreview.mdが生成されたか | ○ |
| verdict.txtが4値のいずれかになったか | ○ |
| metrics.jsonにtotal_cost_usdが記録されたか | ○ |
| 人間の1キー入力待ちまで到達したか | ○ |

8項目すべて○。×は0件だった。

## 9. 気づいた事実

- `report.md`の本文が英語で書かれていた。instructionは日本語で書いたが、
  出力言語の指定は行っていなかった。

## 10. 既知の欠落（意図的な保留）

`review_loop.sh`には、実行時のブランチが`main`でないことを検査する仕組みが
無い。`scripts/work_loop.sh`は`CURRENT_BRANCH != main`でエラー終了するが、
`review_loop.sh`には同等の検査が実装されていない。この欠落は把握した上で、
今回の初回試走では意図的に修正を保留した（試走前に変更を積むと、試走が
「変更後の未検証な版」に対するものになるため）。

## 11. 限界（明示）

- **試走は1ラウンド1セッションのみ**である。複数ラウンドにわたる継続動作は
  検証していない
- **`c`入力による次ラウンドへの継続は未検証**である（今回は人間が`q`を選び、
  round_1で終了した）
- **停止条件3種（ラウンド数上限／同一VERDICTが2ラウンド連続／no-opハッシュ
  不変）はいずれも発火しておらず、未検証**である
- **exit 2（実行役の呼び出し自体が失敗）・exit 13（監査役の呼び出しが成立
  しなかった）の経路も未検証**である
