# ADR-016: review_loop.sh の実行役が成果物を自己検証できない問題への対処（案A＋案C）

- 日付：2026-08-30
- 状態：採用（ただし「決定」節 A-2 の実現方法は要決定。「未決定として明示する事項」節）
- supersede は発生しない（`docs/decisions/ADR-011-review-loop-design.md`・
  `docs/decisions/ADR-014-proposer-design.md` の決定はいずれも有効なまま。
  詳細は「既存 ADR との関係」節）

## 背景

Issue #241（`review_loop.sh: EXECUTOR_ALLOWED が新設スクリプト/テストの実行を
許可せず、実行役がターンを空費する`）は次の事象を記録している。

- `scripts/review_loop.sh` の 6 回目試走（セッション `20260830-175335` の
  `round_1`）で、実行役セッションが `executor_result.json` に
  `subtype=error_max_turns`・`num_turns=21`（上限 20）・`is_error=true`・
  `terminal_reason=max_turns` を残して停止した。
- `permission_denials` は 8 件。すべて新設スクリプトの直接実行
  （`bash scripts/check_errors_inventory.sh` ほか）・pytest 実行
  （`python -m pytest ...` / `.venv/bin/python -m pytest ...`）・`chmod`・
  `git diff` で、同じコマンドを表現だけ変えて再試行しては 1 ターンずつ
  消費していた。
- 原因は `scripts/review_loop.sh:79`

  ```
  EXECUTOR_ALLOWED="Read,Edit,Write,Glob,Grep,Bash(./scripts/verify.sh)"
  ```

  が実行役の `--allowedTools`（`scripts/review_loop.sh:428`）に渡され、
  `Bash` で許可されるのが `./scripts/verify.sh` に完全一致するものだけで
  ある点。実行役は Write/Edit で成果物を書けるが、書いたスクリプトや
  テストを一度も実行できず、自己検証が原理的にできない。
- この試走の成果物（`scripts/check_errors_inventory.sh` と
  `tests/test_errors_inventory.py`）自体は完成しており、後日の人間側
  セッションで `pytest` 5 件緑・スクリプトは仕様どおり非ゼロ終了することを
  確認して PR #242 としてマージ済みである。欠陥は成果物の品質ではなく、
  実行役が検証手段を持たず、検証できないまま再試行でターンを浪費する点に
  ある。

Issue #241 の対処方針は「案A（`EXECUTOR_ALLOWED` に pytest 実行を追加）と
案C（instruction 側での明示）の併用」で合意済みである。本 ADR に先立ち、
案A の許可パターンが実際に何を通し何を拒否するかを実測した。

## 実測

### 導出条件

作業用の一時ディレクトリで、`scripts/review_loop.sh:425-431` の実行役
呼び出しを踏襲して測定した。

- `claude -p --model sonnet --max-turns 3 --allowedTools "<下記>"
  --settings scripts/work_loop.settings.json --output-format json`
- 許可文字列:
  `Read,Edit,Write,Glob,Grep,Bash(./scripts/verify.sh),Bash(python -m pytest*)`
- 各コマンドは別プロセス・別プロンプトで 1 件だけ実行させ、
  `executor_result.json` の `permission_denials` の有無で「許可／拒否」を
  判定した（判定は実データに基づく。推測を加えていない）。

### 結果

| コマンド | 結果 |
|---|---|
| `python -m pytest tests/... -q` | 許可 |
| `python -m pytest --version` | 許可 |
| `python -m pytest ... && echo done` | 許可 |
| `python -m pytest ... ; echo done` | 許可 |
| `python -c "print(1)"` | 拒否 |
| `bash scripts/check_errors_inventory.sh` | 拒否 |
| `.venv/bin/python -m pytest ... -q` | 拒否 |
| `python -m pytest --version ; python -c "print(2)"` | 式全体を拒否 |
| `python -m pytest --version && ./scripts/verify.sh` | 許可 |

### 実測から言えること

- `Bash(python -m pytest*)` の `*` はワイルドカードで、`python -m pytest` に
  前方一致すれば引数・オプションを問わず許可される。
- `python -c ...` や `.venv/bin/python -m pytest ...` は `python -m pytest*`
  に一致せず、`work_loop.settings.json` の deny にも無いが、`-p` 非対話
  モードでは「許可リストに無い ＝ 拒否」となる。
- **allow 側でも複合シェル式は個別評価される**ことが実測で確認された。
  `python -m pytest --version ; python -c "print(2)"` は、許可要素と
  非許可要素を `;` で連結しただけで式全体が拒否され、どちらの要素も
  実行されなかった。両要素とも許可リストに個別一致する
  `python -m pytest --version && ./scripts/verify.sh` は許可された。
  これは ERRORS.md「CI（非対話）環境の claude-review で…」項および
  `docs/decisions/ADR-008-settings-json-deny-only.md` が deny 側について
  記した「複合シェル式は個別評価され、いずれかが該当すれば式全体が
  ブロックされる」という性質が、allow 側にも対称に働くことを示す。
  `... && echo done` / `... ; echo done` が許可されたのは、`echo` が
  Claude Code の組み込み安全コマンドとして個別に許可されるためと解釈できる。

### 環境の実測

- `which python` → システムの Python（`/usr/bin/python` 相当）。
- `python -m pytest --version` → `No module named pytest`。
- `.venv/bin/python -m pytest --version` → `pytest 8.3.5`。
  pytest はリポジトリの仮想環境内にのみ存在する。
- `scripts/verify.sh:7` は自分の subshell 内で `source .venv/bin/activate`
  してから `python -m pytest` を呼ぶ（この activate は `verify.sh` の
  子プロセス限定で、親シェルには波及しない）。
- `scripts/review_loop.sh` は仮想環境を activate しない（`grep` で該当なし）。
  したがって `claude -p` 実行役が継承するのは、人間が `review_loop.sh` を
  起動したシェルの環境である。activate 済みで起動すれば `python` は
  仮想環境の Python を指し `python -m pytest` が動く。activate せずに
  起動すると、`python -m pytest` は「許可はされるが実行時に
  `No module named pytest` で失敗する」。

### 未検証

- パイプ `|` を挟んだ複合式（例: `python -m pytest ... | tail -40`）の
  可否は測定していない。`tail` が組み込み安全扱いなら許可、そうでなければ
  式全体拒否と予想されるが、**未検証**。

## 決定

Issue #241 への対処として、**案A と案C を併用する**。ただし上記実測から、
案A は許可パターンの追加だけでは機能しない。

### A-1: `EXECUTOR_ALLOWED` に pytest 実行の許可を追加する

`scripts/review_loop.sh:79` の `EXECUTOR_ALLOWED` に `Bash(python -m pytest*)`
相当を加える。実測のとおり、これにより `python -m pytest ...`（引数・
`&& echo` / `; echo` の付随を含む）が実行役に許可される。
具体的な文字列（`python -m pytest*` のみか、`.venv/bin/python -m pytest*`
も並べるか）は A-2 の結論に依存するため、ここでは確定しない。

### A-2: pytest が実行可能な Python を実行役に届ける（実現方法は要決定）

実測により、`review_loop.sh` を activate なしで起動した場合、実行役の
`python` はシステム Python で pytest 非導入であり、A-1 の許可パターン追加
だけでは実行時に失敗する。pytest を届ける方法として少なくとも次がある。
**どれを採るかは本 ADR では決定しない（「要決定」）。**

- **方法1: `review_loop.sh` 側で仮想環境を activate してから `claude -p`
  を呼ぶ**（`verify.sh:7` と同じ `source .venv/bin/activate`）。
  - 利点: 許可パターンは `Bash(python -m pytest*)` の 1 つで済む。
    実行役・起案役・instruction のいずれも `python -m pytest` という
    単一の書き方に統一できる。`verify.sh` に前例がある。
  - 欠点: `review_loop.sh` の変更が必要。`claude -p` を `timeout` 経由で
    子プロセス起動しているため、activate した環境が確実に継承されるかを
    実装時に確認する必要がある。仮想環境が無い環境では activate が失敗
    するため、その場合の扱い（落とすか、フォールバックか）を決める必要が
    ある。
- **方法2: `EXECUTOR_ALLOWED` に `Bash(.venv/bin/python -m pytest*)` を
  別パターンとして追加する**。
  - 利点: `review_loop.sh` の `claude -p` 起動前後の環境に依存しない。
    activate 忘れ・環境継承の問題が起きない。
  - 欠点: 許可文字列に pytest 起動系が 2 つ並ぶ。instruction や起案役が
    「どちらで書くべきか」を判断する必要が生じ、実行役が activate 済みを
    仮定して `python -m pytest` で書くと環境次第で実行時失敗する余地が
    残る。仮想環境ディレクトリ名がパターンにハードコードされる。
- **方法3: 方法1 と方法2 の両方**。
  - 利点: どちらの書き方でも通る。最も堅牢。
  - 欠点: 対処が二重で保守点が増える。許可範囲が最も広い。

### C: instruction 側で実行不能コマンドの扱いを明示する

instruction に、実行役が実行できないコマンド——シェルスクリプトの直接実行
（`bash foo.sh` / `./foo.sh`。実測 #6 で拒否）、`python -c ...`（実測 #5 で
拒否）、`chmod`、`git diff` など——を**試みず、報告に記載するだけにとどめ、
言い換え再試行をしない**ことを明記する。検証は監査役・人間に委ねる。
テンプレート化（instruction 雛形への常設）の要否は別途判断する。

## 却下した案

### 案B（`EXECUTOR_ALLOWED` を環境変数で上書き可能にし、タスクごとに指定する）

許可範囲がタスクごとに可変になり、試走ログだけでは「そのラウンドで何が
実行可能だったか」を追いにくくなる。指定漏れ時に案A 以前の状態へ静かに
退行する。得られる柔軟性は案C（instruction 側の明示）と重複する。
さらに、ERRORS.md「AI Loop（`scripts/work_loop.sh`）の検証で分かったこと
（Issue #14〜#16）」および `docs/decisions/ADR-008-settings-json-deny-only.md`
が定着させた「権限は実行環境側で固定し、プロンプト文面や帯域外スイッチで
操作しない」という方針に反する（Issue #16 の当時、環境変数
`ALLOW_COMMIT=1` による迂回路がオール・オア・ナッシングの設計問題で
66 分後に撤去された前例がある）。よって案B は採らない。

### 案D（`--allowedTools` を外し、`work_loop.settings.json` の deny のみで縛る）

ERRORS.md の Issue #14 の事故を根拠に却下する。同項の記録によれば、
`scripts/work_loop.sh` の非対話実行で `--allowedTools` を絞ったつもりでも、
対話セッション用の `.claude/settings.local.json` の `permissions.allow` が
発生源を問わず**加算**されて素通しし、明示的な許可なく `git commit` が
実行された。`--allowedTools` を外して deny のみにすると、deny 列挙に無い
任意の操作（対話用 `settings.local.json` の `allow` に載っているものを
含む）が実行役に通りうる状態になり、安全が deny の網羅性に全面依存する。
`review_loop.sh` は非対話ループであり、この加算経路を塞ぐには allow を
明示する現方式のほうが確実である。よって案D は採らない。

### 案E（`review_loop.sh` の対象タスクを絞る）

`work_loop.sh` は「ネットワーク I/O や新規スクリプトの単体実行を要する
タスクは対象外」と `.claude/skills/work/SKILL.md` に明文化して同種の問題
（Issue #16）を回避したが、`review_loop.sh` はレビューループとして
「実行役が作った成果物を監査役が検証する」ことが主目的であり、成果物の
作成・検証を要するタスクを全面的に対象外にすると存在意義が損なわれる。
案A＋案C で補える範囲は補い、タスク種別の全面除外はしない。よって案E は
採らない（案C で補いきれない範囲は「残る制約」節で明示する）。

## 残る制約

案A を入れても、シェルスクリプトの直接実行（`bash foo.sh` / `./foo.sh`）は
依然として拒否される（実測 #6）。したがって**新規シェルスクリプトを作成し、
それを実行して検証させるタスクでは、実行役の自己検証は不可能なまま**で
ある。`./scripts/verify.sh` に組み込まれたスクリプトなら `verify.sh` 経由で
間接的に走るが、新設直後で未配線のものは対象外である。この穴は案C
（「実行できないコマンドは試みず報告に記載のみ」）で運用上補うが、
**根本解決ではない**。実行役が任意のシェルスクリプトを実行できるように
許可を広げることは、非対話ループで実行役ができることを大きく増やし、
案D と同種のリスク（deny の網羅性への依存）を招くため、本 ADR では採らない。

## 識別力は未検証（宣言）

**本 ADR の変更が「実行役のターン空費を実際に減らす」ことは、7 回目以降の
試走で実測するまで未検証である。** 6 回目試走の `round_1` は
`num_turns=21`（上限 20）・`permission_denials` 8 件で停止したが、そのうち
案A で解消されるのは pytest 実行（言い換え再試行を含む）に対応する分だけで
あり、残る分（`bash foo.sh`・`chmod`・`git diff`）は案C の運用でしか
減らせない。案A＋案C の適用後に、同型のタスクで `num_turns` が
`EXECUTOR_MAX_TURNS` 未満で正常終了し、`permission_denials` が減ることを
試走ログで確認して初めて実証される。本 ADR の採用は、この
「識別力未検証」を明示的に引き受けたうえでのものである。

## 既存 ADR との関係

- **ADR-011（`docs/decisions/ADR-011-review-loop-design.md`）**: 決定2 は
  実行役を Sonnet、決定4 は 1 ラウンドの流れを定める。本 ADR は実行役の
  `--allowedTools` の中身（`EXECUTOR_ALLOWED`）と instruction の書き方を
  変えるだけで、実行役・監査役の役割分担、ラウンドの流れ、監査役の権限
  （決定5）には触れない。supersede しない。
- **ADR-014（`docs/decisions/ADR-014-proposer-design.md`）/ Issue #225**:
  `scripts/review_loop.sh:521` は `EXECUTOR_ALLOWED` を起案役へ第4引数で
  渡し、`scripts/review_proposer_prompt.md:17` の `{{EXECUTOR_ALLOWED}}` に
  埋め込む。したがって A-1 で `EXECUTOR_ALLOWED` を変更すれば、起案役が
  参照する許可一覧にも追加の配線なしで反映される。実装タスクでは、
  起案役が新しい許可（pytest 実行可）を踏まえた instruction を生成する
  ことを確認する。ADR-014 の決定そのものは変更しない。supersede しない。
- **ADR-008（`docs/decisions/ADR-008-settings-json-deny-only.md`）**:
  本 ADR は `.claude/settings.json` を変更しない。`review_loop.sh` は
  `--allowedTools`（CLI フラグの許可リスト）＋ `--settings`
  `work_loop.settings.json`（deny 専用）という別系統で、ADR-008 が対象と
  する対話セッション用の `.claude/settings.json` の話とは層が異なる。
  ただし ADR-008 が定着させた「権限は実行環境側で固定する」という思想は
  案B の却下根拠として引用している。
- 本 ADR の位置づけ: 本 ADR は、これを含む PR をユーザがマージした時点で
  確定する（ADR-012・ADR-013・ADR-014・ADR-015 と同じ扱い）。

## 未決定として明示する事項

- **A-2 の実現方法（方法1／方法2／方法3）。要決定。** 本 ADR は
  「案A＋案C の併用」と「案A は許可パターン追加だけでは機能しない」ことを
  決めるにとどめ、pytest を実行役へ届ける具体手段は実装前に別途決める。
- A-1 で `EXECUTOR_ALLOWED` に加える正確な文字列。A-2 の結論に依存する。
- 案C の文面を instruction 雛形に常設するか、タスクごとに書くか。
- パイプ `|` を挟んだ複合式の可否（実測「未検証」）。案C の文面や
  instruction で `| tail` 等を使わせる可能性があるなら、実装前に測定する。
- `scripts/review_loop.sh`・instruction・テストの具体的な変更内容。本 ADR は
  方針決定のみで、`scripts/` の変更は実装タスクで行う。
