# ADR-011段階1の判断材料（案A / 案C）

ADR-011（`docs/decisions/ADR-011-review-loop-design.md`）決定8は、段階0
（毎ラウンド人間が1キーで承認）の実測を見てから段階1（指示文の生成を
ループに取り込む）以降の要否を決めるとしている。本文書は段階1の2案
（案A・案C）を比較するための材料を、実際のファイル・コマンド出力から
集めたものである。**ADRではない。案A・案Cのどちらを採るかの判断も
行わない。**

- 案A: 起案役を第3のプロセスとして追加する（instructionファイルのみ
  Write可）
- 案C: 役を増やさず、監査役の`review.md`のCONTRADICTIONS節をそのまま
  次ラウンドのinstructionにする

## 1. review_audit_prompt.mdの出力形式は固定文言か

`scripts/review_audit_prompt.md`を確認（全文引用）。

```
## 出力形式（必ずこの形式で出力すること）

出力は以下の形式に厳密に従うこと。

VERDICT: 次の4値のいずれか1つだけを1行目に書く。
  APPROVE_CONTINUE — 報告書の記述と成果物（diff・verify出力）の間に事実の
    矛盾が無く、かつ verify が PASS している場合
  REVISE — 報告書の記述と成果物の間に事実の矛盾がある、または verify が
    FAIL している場合
  HALT_NEEDS_HUMAN — 判断に人間の承認が要る場合（保護パスへの変更、main への
    push、PR の作成・マージ、Issue の作成が関わる場合）
  DONE — 報告された作業が完了しており、以降に実行すべき残作業が無い場合

CONTRADICTIONS: 報告書と成果物の間の事実の矛盾のみを箇条書きにする。
  各項目に成果物の該当箇所を根拠として必ず添える。根拠を示せない指摘は書かない。
  矛盾が無い場合は「なし」と書く。

FOLLOWUPS: 品質上の改善提案。**ここに書いた内容は VERDICT に影響させてはならない。**
  提案が無い場合は「なし」と書く。
```

`VERDICT:`・`CONTRADICTIONS:`・`FOLLOWUPS:`という3つの見出しラベルは
プロンプト内でリテラルに固定されている。

## 2. 初回試走のreview.mdからCONTRADICTIONS節を機械的に抜き出す

対象: `~/comic_checker-agent-notes/review_loop/20260826-235806/round_1/review.md`

使用コマンド:

```bash
awk '/^CONTRADICTIONS:/{flag=1; next} /^FOLLOWUPS:/{flag=0} flag' review.md
```

出力（全文）:

```
- なし

検証した根拠（矛盾なしの裏付け）:
- 報告書が挙げるセクションは実在する（`ERRORS.md:14` = `## AI Loop（\`scripts/work_loop.sh\`）の検証で分かったこと（Issue #14〜#16）`）。報告書はバッククォート無しで引用しているが指示内容は一致。
- 「過去の設計として再構成し、理由と根拠を併記」は diff の追加行（`ERRORS.md:33-40`）と一致。
- 引用された根拠が実在する: `scripts/loop_git.sh:20-23` に「ALLOW_COMMIT=1 …丸ごと止める迂回路を作り、66分後に撤去した経緯もある（3341902 → 6d7ef64）」「オール・オア・ナッシングだったのが問題」があり、diff の「66分後」「3341902 → 6d7ef64」「オール・オア・ナッシング」を裏付ける。
- 「現在の`work_loop.sh`に環境変数等による迂回路は無い」も裏付けあり: `scripts/work_loop.sh` に `ALLOW_COMMIT` の出現は 0 件で、`work_loop.sh:73` は `--settings` を無条件に付与している。
- 「他ファイルは未変更・commit/pushしていない」は git status（`M ERRORS.md` のみ、branch は `fix/errors-md-allow-commit`、直近コミットは 297d670 のまま）と整合。
- verify.sh は `VERIFY PASSED`（pytest 283 passed、証拠ゲート 検出54/59・副作用1/37 一致）。
```

`wc -lc`の実測: 10行・1375バイト。

**重要な観測**: 監査役は`review_audit_prompt.md`の出力形式指定に無い
「検証した根拠（矛盾なしの裏付け）」という見出しを**自発的に追加**して
いる。プロンプトが指定するCONTRADICTIONS節の内容は「矛盾のみを箇条書き
にする」「矛盾が無い場合は『なし』と書く」だけであり、根拠説明の追加は
仕様に含まれていない。`awk`の抽出条件（`FOLLOWUPS:`が現れるまでを
CONTRADICTIONSとみなす）はこの自発的な追加部分もそのまま拾ってしまう。

## 3. この抽出結果は次ラウンドのinstructionとして成立するか

今回の実測ではVERDICT=`APPROVE_CONTINUE`、CONTRADICTIONS=「なし」だった。
上記の抽出結果（10行・1375バイト）をそのまま次ラウンドのinstructionとして
実行役に渡した場合を検討する。

- 冒頭の`- なし`単体は、実行役に対する具体的な行動指示ではない
- 続く「検証した根拠」以下6項目は、監査役が"なぜ矛盾が無いと判断したか"を
  説明する文章であり、"次に何をすべきか"という指示文ではない
- **結論: 今回の実測データに基づく限り、案Cが生成する次ラウンドの
  instructionは、実行役への具体的な作業指示として成立していない**
- **REVISE時（矛盾が実際にある場合）に抽出されるCONTRADICTIONSがどう
  機能するかは、今回のデータからは判定できない。** 今回の試走は
  APPROVE_CONTINUEの1件のみであり、REVISE時のCONTRADICTIONS内容
  （矛盾点の指摘）が「次に何をすべきか」の指示として機能しうるかは別途
  実測が必要

## 4. review_loop.shのラウンド遷移部分・案C実装時の変更範囲

`scripts/review_loop.sh`で`CURRENT_INSTRUCTION_FILE`・`PREV_VERDICT`・
`PREV_SNAPSHOT`を扱っている箇所（`grep -n
"CURRENT_INSTRUCTION_FILE\|PREV_VERDICT\|PREV_SNAPSHOT"
scripts/review_loop.sh`の実測）:

- 初期化: `CURRENT_INSTRUCTION_FILE="$INSTRUCTION_FILE"` ／
  `PREV_VERDICT=""` ／ `PREV_SNAPSHOT=""`（ループ開始前、1箇所）
- 各ラウンド先頭: `cp "$CURRENT_INSTRUCTION_FILE" "${ROUND_DIR}/instruction.md"`
- 停止条件判定: `PREV_VERDICT`・`PREV_SNAPSHOT`との比較（2箇所）
- `c`選択時のcaseブロック内: `PREV_VERDICT="$VERDICT"` ／
  `PREV_SNAPSHOT="$ROUND_SNAPSHOT"` ／
  `CURRENT_INSTRUCTION_FILE="${ROUND_DIR}/review.md"`（3行、1箇所）

現在の実装は、`c`選択時に`review.md`**全体**（VERDICT行・CONTRADICTIONS
節・FOLLOWUPS節すべて）を次のinstructionにしている。これは「監査役の
出力ファイルをそのまま次のinstructionにする」という点で既に案Cに近い
設計だが、案Cが求める「CONTRADICTIONS節だけ」ではない。

案Cを実装する場合、変更が必要な範囲は**`c`選択時のcaseブロック内、
`CURRENT_INSTRUCTION_FILE`代入行1箇所**と読める。そこにCONTRADICTIONS
抽出処理（上記2節で検証したawk相当）を追加し、抽出結果を新しいファイルへ
書き出してから代入先を差し替える、数行規模の変更で収まる。実行役・
監査役の呼び出し部分、停止条件判定部分には変更が及ばない（ERRORS.md
「`review_loop.sh`: 次ラウンドのinstructionに監査役のFOLLOWUPSが混入する」
も参照。この欠陥自体は案Cを実装すれば副作用的に解消される）。

## 5. 案Aのコスト増分見積り（仮定を明示）

実測値（そのまま）:

- 実行役（sonnet、num_turns=12）: `total_cost_usd = 0.2203498`
- 監査役（opus、num_turns=7）: `total_cost_usd = 0.3150445`
- 現状（追加ロール無し）の1ラウンド合計: **0.5353943 USD**

ここから先は**仮定**である。

- 起案役の想定モデル: **opus**（仮定。監査役と同程度の慎重さが必要という
  想定に基づく）
- 起案役の想定ターン数: **5ターン**（仮定。instructionファイルを書くだけの
  軽いタスクという想定。根拠となる実測値は無い）
- **コストがターン数に比例すると仮定**した場合、監査役の実測
  （opus・7ターン・0.3150445ドル）から1ターンあたり単価を按分:
  `0.3150445 / 7 ≈ 0.04501` ドル/ターン
- これに基づく起案役の想定コスト: `0.04501 × 5 ≈ 0.2250` ドル
- 案Aの1ラウンド合計（仮定込み）: `0.5353943 + 0.2250 ≈ 0.7604` ドル
- **増分（仮定）: 約0.225ドル、現状比で約42%増**

**この見積りは2つの未検証の仮定に依存する**（「起案役はopus・5ターン」
「コストはターン数に比例する」）。後者の仮定自体、`docs/ai_loop_state/
audit_experiment_2026-08-26.md`「参考: 手順2（文脈量ごとの実コスト）の
実測」に記録した過去の実測と矛盾する。同じ`--model opus`・**同じ
num_turns=1**でも、新プロンプト×3反復で`total_cost_usd`が**0.0465〜
0.1210ドル**の幅でばらついたことが実測されている（`docs/ai_loop_state/
audit_experiment_2026-08-26.md`の「結果」表、「判定基準の効果」「再現性」
行）。コストは実際には各ターンのトークン量（特にプロンプトキャッシュの
生成・読み込み量）に強く依存しており、ターン数だけからの単純な比例計算は
信頼できない。**したがって「約42%増」という数字は、起案役を実際に実装して
実測しない限り確定できない参考値に過ぎない。**

## 6. 案Cが監査役の権限を変更せずに済むか

ADR-011決定5: 監査役はWrite/Edit/NotebookEdit/Bashをdeny、Read/Glob/Grepは
許可。

前提として引用予定だった「Writeをdenyすると`Bash(touch)`へ自発的に迂回
した」実測は、本文書に未記録だったことが判明したため、
`docs/ai_loop_state/audit_experiment_2026-08-26.md`「追記（2026-08-27）」
節に、原本JSON（`~/comic_checker-agent-notes/audit_experiment/
writeonly_probe_result.json`）に基づいて記録した。要旨: `Write`ツール
拒否後、モデルは`Bash(touch ...)`という別経路を自発的に試み、それも
拒否された。

**この実測を踏まえた考察（推測であることを明示）**: 案Cは監査役自身への
指示内容（診断してVERDICT/CONTRADICTIONS/FOLLOWUPSを出力せよ、という
プロンプト）を変更しない。次のinstructionファイルへの書き込みは監査役
自身ではなく`review_loop.sh`（オーケストレータ側のシェルスクリプト）が
`review.md`を読んで行う設計であり、現状の実装（4節参照）でも既にそう
なっている。したがって案Cを採用しても、監査役に新たな「ファイルを書け」
という動機を与えることはなく、監査役の権限（Write/Edit/NotebookEdit/
Bashのdeny）を変更せずに済むと考えられる。**ただしこれは実測ではなく、
現在の実装から論理的に導いた推論である。** `Bash(touch)`への迂回実測
自体は「denyされた監査役が自発的に迂回を試みることがある」という一般的な
リスクを示しており、案Cの設計（監査役へ書き込み系の指示を一切与えない）
がこのリスクを回避できているかどうかは、案Cを実際に実装して確認する
必要がある。
