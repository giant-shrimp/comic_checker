# work_loop.sh / pre-push フックの検証手順

`scripts/work_loop.sh` の停止条件と `.githooks/pre-push` を、**API呼び出しゼロ**で
検証する手順。検証用の偽 `claude` は `/tmp` 配下にあり再起動で消えるため、実体は
コミットせず、手順だけをここに残す。

## なぜこの手順書があるか

Issue #16で「`verify.sh` が通ることはタスク完了の証拠にならない」ことが分かって以降、
`work_loop.sh` には「動かないはずのときに動かないこと」を確認すべき経路が増えた。
これらは実際に走らせないと確認できないが、毎回本物の `claude` を呼ぶとAPI費用がかかる。
偽 `claude` を使えば費用ゼロで全経路を通せる。

## 更新すべきタイミング

- `work_loop.sh` の**停止条件を増減したとき**（終了コード・`outcome_N.txt` の値が変わる）
- `.githooks/pre-push` の判定ロジックを変更したとき
- `verify.sh` の出力形式を変えたとき（`no_progress` の比較対象行が変わるため）

---

## 1. 偽 claude の作り方

`session_id` だけを返して何もしないスクリプト。`work_loop.sh` は `jq` で
`.session_id` を読めれば正常に反復を続けるため、これだけで全経路を通せる。

```bash
SP=/tmp/claude-work-loop-test        # 任意の作業ディレクトリ
mkdir -p "$SP/fakebin"
printf '#!/usr/bin/env bash\necho "{\\"session_id\\":\\"fake-session-0001\\"}"\n' \
  > "$SP/fakebin/claude"
chmod +x "$SP/fakebin/claude"
```

### 残置するときは実行権限を落とす

ファイル名が literally `claude` であるため、PATHの前方に入ったまま忘れると
「何もしていないのに正常終了するループ」を作れてしまう（v8が「静かに失敗する
ループ」として警告している状態そのもの）。**使い終わったら `chmod -x` する。**

```bash
chmod -x "$SP/fakebin/claude"     # 残置するとき
chmod +x "$SP/fakebin/claude"     # 再利用するとき（これだけで済む）
```

改名ではなく `chmod -x` を選んでいるのは、ファイル名が `claude` のままの方が
PATHを差し替えるだけで再現でき、かつ実行権限が無い限り事故が起きないため。
`chmod -x` の状態では、PATH前方に置いても `command -v claude` は本物を返す。

## 2. PATHの差し替え方

そのコマンドの間だけ有効にする（シェル全体のPATHを変えない）。

```bash
PATH="$SP/fakebin:$PATH" MAX_ITER=3 ./scripts/work_loop.sh 999
```

`999` は存在しないIssue番号でよい。偽 `claude` は引数を無視するため。

## 3. 一時テストの置き方

| 目的 | 置くファイル | 内容 |
|---|---|---|
| `no_progress` の発火 | `tests/test_zz_tmp_probe.py` | `def test_x(): assert False` |
| `no_progress_unmeasurable` の発火 | `tests/test_zz_tmp_broken.py` | `import nonexistent_module_xyz` |

後者は**collection error** を起こす。pytestは失敗するが `FAILED ` 行を出さないため、
「失敗しているのに失敗行を抽出できない」状態を実際に再現できる（合成ではない）。

## 4. 片付けと確認

```bash
rm -f tests/test_zz_tmp_probe.py tests/test_zz_tmp_broken.py
chmod -x "$SP/fakebin/claude"
git status --porcelain          # 一時ファイルが残っていないことを確認
```

`logs/` は `.gitignore` 対象なので、実行で生成されたログは放置してよい。

---

## 5. 各テストが検出する「壊れ方」と実測結果

実測日：2026-07-24

### work_loop.sh（4経路）

| # | テスト | 検出する壊れ方 | 実測 exit | 実測 `outcome_N.txt` |
|---|---|---|---|---|
| A | 汚れたツリーで偽claude実行 | **実装が何も進んでいないのに success で終わる**（Issue #16の誤検知。旧実装は開始時点でツリーが汚れていると必ずこれを起こした） | `2` | `no-op` |
| B | 同一失敗を2回出す一時テスト | **同じ失敗を繰り返したまま予算を使い切る**（資源側の上限だけでは止まらない） | `3` | `no_progress` |
| C | collection error を起こす一時テスト | **検証自体が成立していないのを「行き詰まり」と誤って記録する**（原因の切り分けができなくなる） | `3` | `no_progress_unmeasurable` |
| D | `.gitignore` から `logs/` を一時除去 | **no-op検出が黙って無効化される**（ループ自身のログでスナップショットが必ず変化するため） | `1` | （中断。記録なし） |

Dの実行例：

```bash
cp .gitignore /tmp/gitignore.bak
grep -v '^logs/$' .gitignore > /tmp/gi.tmp && cp /tmp/gi.tmp .gitignore
PATH="$SP/fakebin:$PATH" ./scripts/work_loop.sh 999    # → exit 1 で中断するはず
cp /tmp/gitignore.bak .gitignore                        # 必ず戻す
git status --porcelain .gitignore                       # 差分が無いことを確認
```

### 5-a. pre-push フック単体テスト（push経路を通らない）

フックは stdin から `<local ref> <local oid> <remote ref> <remote oid>` を1行ずつ
受け取る。この形式を直接投入すれば、`git push` を一切実行せずにロジックを検証できる。
**失敗しても副作用が無いため、ロジックの検証はここで完結させる。**

```bash
Z="0000000000000000000000000000000000000000"   # 全ゼロ = 削除push
S="1111111111111111111111111111111111111111"
printf 'refs/heads/main %s refs/heads/main %s\n' "$S" "$Z" | .githooks/pre-push; echo "exit=$?"
```

| ケース | 期待 | 実測 |
|---|---|---|
| `main` への通常push | exit 1 | **1** |
| フィーチャーブランチのみ | exit 0 | **0** |
| `main` の削除push（local oid が全ゼロ） | exit 1 | **1** |
| 複数ref・1行目のみ `main` | exit 1 | **1** |
| 複数ref・2行目のみ `main` | exit 1 | **1** |
| 複数ref・`main` を含まない | exit 0 | **0** |
| 空入力（pushするrefなし） | exit 0 | **0** |

削除pushがブロックされるのは、フックが `remote ref` だけを見て判定し、
`local oid` の値に依存しない実装になっているため。

### 5-b. 配線テスト（`core.hooksPath` が効いているか）

```bash
git push --dry-run origin HEAD:main
```

`--dry-run` は ref を一切更新しないため、**フックが効いていなくても `main` は
変化しない**。その上で pre-push フックは呼ばれるので、ブロックされれば配線の証拠になる。

| 項目 | 期待 | 実測（git 2.34.1） |
|---|---|---|
| 終了コード | 1 | **1** |
| フックのメッセージ | 出る | **出た** |
| `origin/main` | 変化しない | **6d7ef64 のまま変化なし** |

**ここでブロックされれば配線確認は完了。5-c は不要。**

### 5-c. `--dry-run` でフックが呼ばれなかった場合のみ

gitのバージョンによっては `--dry-run` で pre-push が呼ばれない可能性がある。
5-b でブロックされなかった場合、それが「フック未配線」なのか「`--dry-run` では
呼ばれない」のかを区別する必要がある。

その場合に限り、実際の `git push origin HEAD:main` を実行してよい。
**ただし実行前に必ず人間の確認を取ること。** フックが効いていなかった場合、
現在のコミットが `main` へ fast-forward で入る（破壊的ではないが、PRを通すという
意図は崩れる）。

> 2026-07-24 の検証では 5-b でブロックされたため、5-c は実行していない。

### 5-d. 非常口（`--no-verify`）が機能することの確認

ADR-001は `--no-verify` による迂回を「受け入れたリスク」として明記している。
記載が実態と合っているかを、**副作用なしで**一度確かめておく。

```bash
git push --no-verify --dry-run origin HEAD:main
```

`--no-verify` でフックを呼ばせず、`--dry-run` で ref を更新させない。
5-b（`--no-verify` なし・`--dry-run` あり）がブロックされたことと対にすると、
**「フックは効いている」と「`--no-verify` で越えられる」の両方**が実測で裏付けられる。

| 項目 | 期待 | 実測（git 2.34.1） |
|---|---|---|
| 終了コード | 0 | **0** |
| フックのメッセージ | 出ない | **出なかった** |
| `--dry-run` の表示 | 更新予定が出る | **`6d7ef64..4ae4d1f  HEAD -> main`** |
| `origin/main` | 変化しない | **6d7ef64 のまま変化なし** |

`--dry-run` の表示は「フックが無ければこの更新が起きていた」ことを示している。
すなわち迂回は成立しており、それを止めているのは `--dry-run` だけである。

**この確認は `--dry-run` を付けた形でのみ行うこと。** 実際に `--no-verify` で
`main` へpushする用途ではない。非常口が存在することの確認であって、
使用例ではない（ADR-001「受け入れたリスク」1を参照）。

### 手順6：対照側の確認

`git push origin HEAD`（フィーチャーブランチへのpush）が**通る**ことを確認する。
これは「危険な行き先だけを塞ぐ」という設計意図（ADR-001の却下案3を参照）が
実際に成立していることの確認にあたる。ブロック側だけを見て満足しないこと。

---

## 関連

- `docs/decisions/ADR-001-main保護の方式選定.md` … なぜフック方式を選び、
  ブランチ保護・課金・`deny` を却下したか
- `scripts/work_loop.sh` 冒頭 … 終了コードと `outcome_N.txt` の対応表
