# ADR-015: diff.txt が未追跡ファイルの変更を含まない問題への対処（案D＋案C）

- 日付：2026-08-29
- 状態：採用
- supersede は発生しない（`docs/decisions/ADR-013-stage2-adoption.md`・
  `docs/decisions/ADR-014-proposer-design.md` の決定はいずれも有効なまま。
  詳細は「既存 ADR との関係」節）

## 背景

Issue #231（`review_loop.sh: diff.txtが未追跡ファイルの変更を含まず、監査役へ
渡る証拠が欠落する`）は次の事象を記録している。`scripts/review_loop.sh` が
監査役へ渡す `diff.txt` は `git diff`（`scripts/review_loop.sh:414`
`git diff > "${ROUND_DIR}/diff.txt" || true`）のみで生成され、
`git status --porcelain` を併用していない。そのため新規作成された未追跡
ファイルは `diff.txt` に一切現れず、監査役プロンプトの `{{DIFF}}` 節
（`scripts/review_audit_prompt.md:4-7`）が空行に展開される。

判断材料は `docs/ai_loop_state/issue231_options_2026-08-29.md` にまとめてある。
同文書の実測から、本 ADR が前提とする事実は次のとおり（数値は同文書由来。
新たな推測は加えない）。

- 未追跡ファイルが `diff.txt` から落ちる事象は **4 セッション・6 ラウンド**
  で再現した（`20260829-154741` の round_1・round_2、`20260829-163046` の
  round_1、`20260829-223912` の round_1・round_2、`20260829-225022` の
  round_1。いずれも新規ファイルを作成／更新するタスクで、`diff.txt` が
  0 バイトだった）。
- このうち、本欠陥が監査 VERDICT を誤らせた事例は **0 件**。観測された全
  ラウンドで、監査役は `diff.txt` が空であることに自ら気づき、報告書
  （`{{REPORT}}`）が挙げたパスを `Read` して実ファイルと照合している
  （`20260829-154741` round_1 では、その照合の結果、報告書の行番号誤りを
  検出して VERDICT: REVISE を出している）。
- この補償は「監査役が報告書からファイルパスを読み取り、自発的に `Read`
  する」という LLM（opus）の裁量に依存しており、コード上の保証は無い。
  監査役は `scripts/review_audit.settings.json` で `Bash` を deny されて
  いるため、自力で `git status` を実行して未追跡ファイルを発見することは
  できない（`Read` / `Grep` / `Glob` は使える）。

つまり現状は「証拠としての `diff.txt` が役割を果たしておらず、監査役の
自発的な行動だけが穴を塞いでいる」状態である。監査役がその行動を採らなければ
未追跡ファイルの変更は無検証で通過しうる。

## 決定

Issue #231 への対処として、**案D と案C を併用する**
（`docs/ai_loop_state/issue231_options_2026-08-29.md` §3 の記号）。

### 案D：`diff.txt` の生成を関数化し、`git status --porcelain` を冒頭に連結する

- 変更対象: `scripts/review_loop.sh`。
- 変更内容の要点:
  - 現在 `main()` 内にインラインで置かれている `diff.txt` 生成
    （`scripts/review_loop.sh:414`）を独立した関数へ切り出す
    （`preserve_work_tree_state()` と同じ流儀で `source` して単体テスト
    できるようにするため）。
  - その関数は `git status --porcelain` の出力と `git diff` の出力の
    両方を `diff.txt` へ書き、status を冒頭に置く。監査役から見ると
    `## diff` 節の先頭に `?? path` 形式の行が並び、その下に通常の
    `git diff` が続く。
  - `scripts/review_audit.sh` の引数・プレースホルダは変更しない
    （署名不変）。

### 案C：監査役プロンプトに status 節の読み方と照合手順を明記する

- 変更対象: `scripts/review_audit_prompt.md`。
- 変更内容の要点:
  - `## diff` 節の冒頭に `git status --porcelain` の出力が含まれること、
    `??` で始まる行は未追跡ファイル（新規作成物）であり `git diff` 本体
    には現れないことを説明する。
  - `??` 行があれば、そのパスを `Read` して報告書の記述と照合してから
    VERDICT を出す、という手順を明示する。

具体的な関数名・プロンプト文面・テスト内容は本 ADR では決めず、実装
タスクで設計する（「未決定として明示する事項」節）。

## 各決定の根拠

案D を主軸に据えるのは、伝える情報が案A（`{{STATUS}}` の新設）と同等で
ありながら、変更が `scripts/review_loop.sh` 1 ファイルに収まり、
`scripts/review_audit.sh` の位置引数（現在 4 個）を増やさずに済むためである。
`git diff` と `git status --porcelain` の両方を書き出す実装様式は、同じ
`scripts/review_loop.sh` 内の `preserve_work_tree_state()`（Issue #227 /
PR #230、`scripts/review_loop.sh:221-240`。コメント `:214` に
「新規（未追跡）ファイルを捉えるために別途保存する（git diff には
現れないため）」）が既に前例を作っている。

生成箇所を関数へ切り出すのは、現在の `main()` インライン実装のままでは
pytest で実挙動を検証できず（`main()` は実行役・監査役の実 `claude`
呼び出しを含む）、構造テスト止まりになるためである。`preserve_work_tree_state()`
と同型の独立関数にすれば、一時 git リポジトリ（`tests/test_review_loop.py`
の `_init_repo()` の前例）で「未追跡ファイルの `??` 行が `diff.txt` に
入ること」を実挙動として固定できる。

案C を併用するのは、案D が伝えるのは「未追跡ファイルが**存在すること**」
だけで、その**中身**は依然として監査役の `Read` に委ねられるためである。
背景節のとおり監査役は既にこの `Read` を自発的に行っているが、コード上の
保証は無い。プロンプトに手順として書くことで、`diff.txt` 冒頭の `??` 行と
「実ファイルを読んで照合する」という行動を明示的に結び付ける。案D で
`??` 行が必ず供給されるようになるため、案C は「読み方の分からない情報」
ではなく「供給済みの情報の使い方」を指示する形になり、案C 単独よりも
足場がはっきりする。

## 却下した案

### 案A（`git status --porcelain` を新プレースホルダ `{{STATUS}}` として渡す）

案D と監査役に届く情報は同等（どちらも porcelain 出力）。違いは、案A が
`scripts/review_loop.sh`・`scripts/review_audit.sh`・
`scripts/review_audit_prompt.md`・呼び出し箇所の 4 ファイルを変更し、
`scripts/review_audit.sh` の位置引数を 4→5 に増やす署名変更を伴う点にある。
同じ情報を届けるのに変更範囲が広く、他スクリプトからの呼び出し規約
（`<diff-file> <verify-output-file> <report-file> <output-dir>`）と `usage`
文言の同時更新が必要になる。案D なら 1 ファイルで完結し署名も変えずに
済むため、案A を採らない。

### 案B（未追跡ファイルの中身も `diff.txt` に含める。`git add -N` 後に `git diff`）

案B は 4 案で唯一、未追跡ファイルの**中身そのもの**を監査役へ届ける。
しかし、そのために実行役の作業ツリー上で `git add -N`（intent-to-add）を
実行して index を触る必要がある。`git diff` を取った直後に `git reset` で
取り消す前提だが、途中で失敗して `git reset` が漏れると index が汚れ、
後続の `snapshot()`（`git diff HEAD` を含む）や `preserve_work_tree_state()`
の出力の意味が変わる。`set -euo pipefail` 下での失敗時挙動を含め、
「作業ツリーの状態を壊しうる」という本質的なリスクを新たに持ち込む。

中身を届けるコストを正当化するには「監査役が `Read` を怠って未追跡
ファイルの中身を見逃し、VERDICT を誤った」実事例が要るが、背景節のとおり
その事例は現時点で **0 件**である。リスクに見合う根拠が実データに無いため、
案B は採らない（採る条件は「再検討条件」節）。

### 案C 単独

案C だけを入れる場合、監査役は「未追跡ファイルは diff に出ないことがある
ので報告書のパスを `Read` せよ」と指示されるが、これは背景節で述べた
監査役の現在の自発的挙動をプロンプトに書き写すだけで、`diff.txt` 側は
空のまま変わらない。前進が小さく、`??` 行という機械的な手がかりを監査役に
与えられない。案D と併用してこそ「冒頭の `??` 行を見て `Read` する」という
再現性のある手順になる。

## 識別力は未検証（宣言）

**本欠陥が監査 VERDICT を誤らせた実事例は 0 件である。** したがって
「案D＋案C を入れれば誤判定を防げる」ことは、既存データでは実証できない。
比較対象となる「本欠陥が原因の誤判定」が存在しないためである。

実装後に pytest で確認できるのは次の**形式面**に限られる。

- `diff.txt` 生成関数が `git status --porcelain` と `git diff` の両方を
  書き、`??` 行が `diff.txt` に含まれること（一時 git リポジトリでの
  実挙動テスト）。
- 生成関数を切り出したことによる既存挙動の非退行。
- `scripts/review_audit_prompt.md` に status 節の読み方・照合手順の記述が
  含まれること（文言テスト）。

「監査役が実際により正確な VERDICT を出すようになる」ことは、監査役が
opus の LLM である以上 pytest では確認できない。本 ADR の採用は、この
「識別力未検証」を明示的に引き受けたうえでのものである。

## 再検討条件

次が観測された場合、**案B（未追跡ファイルの中身を `diff.txt` に含める）を
再検討する**。

- 監査役が `Read` を怠って未追跡ファイルの内容を見逃し、その結果 VERDICT
  を誤った実事例（`review.md` と実ファイルの突き合わせで確認できるもの）が
  1 件でも観測されたとき。

この場合、「中身を届けるコスト（index 操作のリスク、`diff.txt` の肥大化）」
に見合う実害が確認できたことになり、案B の採否を改めて判断する。

## 既存 ADR との関係

- **ADR-013（`docs/decisions/ADR-013-stage2-adoption.md`）**: 同 ADR は
  `diff.txt` を監査・no-op 判定の中核証拠として扱っている。本 ADR は
  その `diff.txt` に未追跡ファイルの存在情報を補うものであり、ADR-013 の
  方針を強化する方向で整合する。supersede しない。
- **ADR-014（`docs/decisions/ADR-014-proposer-design.md`）**: 同 ADR 決定1
  は**起案役**への入力を「1 ラウンド目の instruction ＋ 直近の `review.md`」
  に絞る方針を定める。本 ADR が変更するのは**監査役**へ渡す `diff.txt` と
  監査役プロンプトであり、起案役の入力・権限・呼び出しには一切触れない。
  ADR-014 決定5（監査役・起案役とも権限は全 deny）も変更しない（案C は
  プロンプト文言の追加のみで、監査役に新たな権限を与えない）。supersede
  しない。
- 本 ADR の位置づけ: 本 ADR は、これを含む PR をユーザがマージした時点で
  確定する（ADR-012・ADR-013・ADR-014 と同じ扱い）。

## 未決定として明示する事項

- `diff.txt` 生成関数の名前・シグネチャ・戻り値。実装タスクで
  `preserve_work_tree_state()` の様式に合わせて設計する。
- `git status --porcelain` と `git diff` を `diff.txt` 内でどう区切るか
  （見出し行を挟むか、空行だけか）。監査役プロンプトの `## diff` fenced
  block の可読性とあわせて実装タスクで決める。
- `scripts/review_audit_prompt.md` に追記する具体的な文面。
- 追加する pytest の具体的なテスト内容（`tests/test_review_loop.py` /
  `tests/test_review_audit.py`）。本 ADR は方針決定のみで、`scripts/`・
  `tests/` の変更は実装タスクで行う。
- porcelain 出力が非常に大きくなるケース（多数のファイルを一度に変更する
  タスク）で `diff.txt` 冒頭が長大化した場合の扱い。現時点の実データ
  （§2）では 1〜2 行程度で、上限対応は不要と判断しているが、実装後に
  肥大化が観測されたら別途検討する。
