# ERRORS.md

過去に詰まった失敗の記録。`CLAUDE.md`（これから守るべきルール）と違い、ここは
「過去に何が起きたか」を積み上げる場所。同じ失敗を繰り返しそうなときに読む。
新しくハマった事例は、原因と対応をこのファイルに追記する。

## AI Loop（`scripts/work_loop.sh`）の検証で分かったこと（Issue #14〜#16）

`/work`スキルを`claude -p`で非対話ループ実行するための`scripts/work_loop.sh`を試験導入し、
3段階の失敗を経て現在の設計（`scripts/work_loop.settings.json`によるdeny強制、`/work`の
リテラル呼び出し、no-op検出）に至った。将来また似た仕組みを作る／触るときのために経緯を残す。

1. **Issue #14（未追跡ファイルのgit管理化）で発覚: 許可の"加算"問題**。
   `--allowedTools`に`git add`/`git commit`を含めずに絞ったつもりだったが、実際には
   対話セッション用の`.claude/settings.local.json`（`permissions.allow`に
   `Bash(git add *)`/`Bash(git commit -m ' *)`を保持）がこの非対話実行にも素通しで効き、
   明示的な許可なくcommitが実行された（コミット内容自体は正しかったが、仕組みとして
   「絞ったつもりが絞れていない」状態だった）。Claude Codeの`permissions.allow`は
   発生源（CLIフラグ／プロジェクト設定／ローカル設定）を問わず**加算**される、という
   公式ドキュメント（`permissions.md`）の記載を確認して原因を特定した。
2. **対応: allowを絞るのではなくdenyで塞ぐ**。`permissions.md`には「denyは発生源を問わず
   常にallowより優先される」と明記されている。この性質を使い、`work_loop.sh`専用の
   `scripts/work_loop.settings.json`（`git commit`/`git push`/`git add`を常にdeny）を
   `--settings`で追加読み込みさせる方式に変更した。**プロンプト文面で「commitして」と
   明示してもdenyは緩まないことを実測で確認済み**（denyは権限システム側の強制であり、
   モデルへの指示ではないため）。commitを許可したい場合は、`work_loop.sh`の呼び出し元が
   環境変数`ALLOW_COMMIT=1`を明示的に設定する必要がある（プロンプト文言ではなく、
   スクリプト起動時の帯域外の手段で許可する設計）。この過程で、`disable-model-invocation:
   true`のスキルは`-p`のプロンプト文字列にリテラルな`/skill-name`呼び出しが無い限り
   自動発火せず、SKILL.mdの内容が一度もコンテキストに読み込まれないことも判明したため、
   `work_loop.sh`のPROMPTを`/work ${ISSUE}`のリテラル呼び出しに修正した。
3. **Issue #16（判定不能率の計測）で発覚: `verify.sh`通過は成功の証拠にならない**。
   `scripts/measure_unknown_rate.py`の新規作成・実行を`work_loop.sh`に任せたところ、
   `ALLOWED`に任意の`python3`実行手段が無いため（`Bash(./scripts/verify.sh)`以外の
   コマンド実行が許可パターンに一致せず拒否され続け）、ターン数上限（`num_turns`が
   `MAX_TURNS`に到達）で何も実装できないまま終了した。ところが**何も変更していないのに
   既存テストは当然通るため、`work_loop.sh`は「verified — 停止します」と成功扱いで
   終了していた**。`is_error: true`・`stop_reason: "tool_use"`という`logs/run_N.json`の
   中身を見て初めて気づける状態で、放置していれば「何も進んでいないのに成功ログが残る」
   という誤検知になっていた。対応として、`verify.sh`通過後に`git status --porcelain`で
   実際に変更が発生したかを確認し、無変化なら`no-op`として明確に区別する
   （終了コード2、`logs/outcome_N.txt`に記録）よう`work_loop.sh`を修正した。
   合わせて、ネットワークI/Oや新規スクリプトの単体実行を要するタスクは`work_loop.sh`の
   対象外とし対話セッションで行う、という適用範囲を`.claude/skills/work/SKILL.md`に
   明文化した。
4. **教訓（一般化）**: 非対話ループの安全性は「プロンプトで何を指示したか」ではなく
   「権限システムが実際に何を許可・拒否するか」で決まる。同様に、ループの成否は
   「検証コマンドが通ったか」ではなく「意図した変更が実際に生じたか」で判定する必要が
   ある。どちらも、モデルへの指示（プロンプト・SKILL.md記載）だけでは強制力を持たず、
   実行環境側（`permissions.deny`・`git status`によるdiff確認）で裏付けを取って初めて
   信頼できる、という同じ構造の教訓である。

## 開発環境をUbuntu(20.04/Python3.8)へ移植したらGUIテストが1件失敗

Windows(WSL)から Ubuntu PC へ開発環境を移した際、`verify.sh`で
`test_summary_chips_are_colour_coded_per_status`だけが失敗した
（`assert 'black' == '#b3261e'`：サマリのチップに色が付かない）。WSLでは通っていた。

1. **真因はPythonバージョン差**。Ubuntu機は Python 3.8.10、旧WSLは3.10以降だった。
   `gui.py`の`_apply_theme()`が`tkfont.nametofont(name, root=root)`を呼んでいたが、
   `nametofont`の`root=`引数は**Python 3.10で追加**されたもので、3.8では`TypeError`。
   さらに内側の`try`が`except tk.TclError`しか捕まえないため、`TypeError`が
   `_apply_theme`末尾の`except Exception: pass`まで伝播し、**STATUS_COLORSの色設定
   ループが走る前に関数全体が中断**。結果テーマ(clam)だけ適用され、チップの
   foregroundが未設定→`style.lookup()`がclam既定の`black`を返してテスト失敗、という
   流れだった。「ttkテーマ差」に見えるが原因はテーマではなくバージョン差。
2. **対応**：`root=`の有無を吸収する`_named_font(name, root)`ヘルパーを追加し、
   `TypeError`時は引数なしで`nametofont`を取得するようにした（3.8/3.10両対応、かつ
   例外でテーマ設定が中断しなくなる）。CLAUDE.mdの「Windows/Linux両方で動くように
   書く」方針の一環。
3. **3.10化を試みたが上流都合で不可**。バージョン合わせのため`python3.10`(deadsnakes
   PPA導入済み)でvenvを作り直そうとしたが、Tk GUIに必須の`python3.10-tk`がaptで
   入らなかった。調べると **deadsnakesがfocal(20.04)向けの提供を停止しており、
   `dists/focal/main/binary-amd64/Packages`が空(0バイト、2025-10更新)** だった
   （20.04が標準サポート終了したため）。何度`apt-get update`しても入らない。
   途中、ROSリポジトリの鍵期限切れ(`EXPKEYSIG`)が`apt-get update`のトランザクションを
   巻き添えにする現象や、InReleaseが「ヒット(304)」だとPackagesを取り直さない挙動にも
   はまったが、いずれも本質ではなく上流の空インデックスが結論。
4. **結論**：コード修正で3.8でも`verify.sh`は132 passedになったため、**3.8のまま**運用と
   した。最終目的のEXEはWindows側でPyInstallerが独自Pythonを同梱するので、開発機の
   Pythonバージョン差はビルド成果物に影響しない。3.10+が本当に必要になったら、
   deadsnakesに依存しないMiniconda/pyenv経由が現実的（apt経路はfocalでは詰む）。
5. **教訓**：「ttkテーマ差」等の表層に見える環境依存バグでも、まず`python --version`と
   当該APIの追加バージョンを疑う。また、広い`except Exception: pass`は原因を隠すので、
   バージョン差で飛びうる例外は発生箇所で個別に処理する。
