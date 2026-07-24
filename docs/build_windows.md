# Windows向けEXEビルド手順（M3: 軽量ビルド）

対象読者: Windows向けEXEを入手する人（開発者本人）。エンドユーザー向けの使い方は
[README.md](../README.md) を参照。

## 前提

- PyInstallerはクロスコンパイル不可のため、Windows向けEXEは**Windows上でビルドする
  必要がある**（WSL/Linux上ではビルドできない）。ただしこれは「**人間が**Windows機を
  操作する必要がある」ことは意味しない。**標準手順はGitHub Actions
  （`windows-latest`）でのビルドである**（[ADR-002](decisions/ADR-002-windows-build-on-ci.md)）。
- この手順は「軽量ビルド」＝Wikipedia経路のみで、Playwright/Chromiumを同梱しない。
  `--fallback-to-manba`はこのビルドのEXEでは使えない（実行時に、起動直後ではなく
  `--fallback-to-manba`を指定した時点で明確なエラーメッセージが出る）。
  Playwright/Chromium同梱版は別途M2で扱う（現時点でv1の必須要件からは外れている）。

## 標準手順: GitHub Actions でビルドして artifact を取得する

`.github/workflows/build-windows.yml` が `windows-latest` ランナー上で
`pyinstaller comic_checker.spec` を実行し、`dist/comic_checker.exe` を artifact として
アップロードする。**Windows機もPython環境も用意する必要はない。**

### 1. ワークフローを実行する

- **手動**: GitHubの Actions タブ → 「Build Windows EXE」 → 「Run workflow」
  （`workflow_dispatch`）
- **タグ経由**: `v` で始まるタグをpushすると自動で走る

```bash
git tag v0.1.0
git push origin v0.1.0
```

CLIから手動実行する場合:

```bash
gh workflow run build-windows.yml
gh run watch                      # 進行を追う
```

### 2. 自動検証の内容を確認する

ジョブ内の「Verify build output」ステップが、M3で人間が目視していた確認項目を
そのままゲートにしている。**満たさなければジョブは失敗する**（＝壊れたEXEが
artifactとして上がることはない）。

| # | 検証内容 |
|---|---|
| (a) | `build\comic_checker\warn-comic_checker.txt` に `excluded module named comic_checker.manba_client` が含まれること |
| (b) | 同ファイルに `playwright` への言及が無いこと |
| (c) | `dist\comic_checker.exe` のサイズが 100MB 未満であること（M3実測は14.1MB） |

いずれかが落ちた場合の読み解き方は、後述の
「[除外できているかの確認（トラブルシューティング）](#除外できているかの確認トラブルシューティング)」
と同じである。

#### CI実測（2026-07-25、run 30109272921 / windows-latest / Python 3.13.14）

```
(a) OK: excluded module named comic_checker.manba_client - imported by comic_checker.main (delayed, optional)
(b) OK: build\comic_checker\warn-comic_checker.txt に playwright への言及なし
(c) OK: dist\comic_checker.exe = 15.06 MB (< 100 MB / M3実測 14.1 MB)
```

ビルド所要時間は約1分（ジョブ全体で1分4秒）。**M3の実機ビルド（14.1MB）より約1MB
大きい**が、これは `comic_checker.spec` の `upx=True` に対して、ランナーにUPXが
入っていないため圧縮が省かれることが原因と考えられる（PyInstallerはUPXが無い場合、
エラーにせず非圧縮のまま続行する）。Chromium同梱なら数百MBになるため、この程度の
差は除外設定の失敗を示すものではない。

### 3. artifact をダウンロードする

Actions の該当runのページ下部「Artifacts」から `comic_checker-exe` をダウンロードする
（zip形式。展開すると `comic_checker.exe`）。CLIからは:

```bash
gh run download <run-id> -n comic_checker-exe
```

保持期間は **14日**（`retention-days: 14`）。それを過ぎたら再実行する。

**このリポジトリはprivateのため、artifactのダウンロードにはリポジトリのアクセス権が
必要である。** 第三者へ配布する場合は開発者が取得して受け渡す
（[ADR-002](decisions/ADR-002-windows-build-on-ci.md)「受け入れたリスク」1）。

### 4. 動作確認

ダウンロードした `comic_checker.exe` を、下記
「[3. 動作確認](#3-動作確認ビルドしたwindows機上)」のチェックリストで確認する。

**ランナー上のビルドはダウンロード経由の配布になるため、SmartScreen警告が出る。**
下記「実機検証記録（M4-2）」で確定済み。

---

## 実機検証記録（M4-2）: 2026-07-25、Windows PC（Python未インストール・別ユーザーアカウント）

Issue #21。**「最終目的」（Pythonをインストールしていないwindows PCで、EXEをダブル
クリックするだけで動作する）を満たすことを確認した最初の記録**である。M3の
「実機確認済み（2026-07-23）」はビルドした当人のマシン（Pythonが入っている）での
確認に過ぎず、この条件を満たしていなかった。

- 実施日: 2026-07-25
- 環境: Windows PC、**Python未インストール**、**別ユーザーアカウント**
- 入手経路: ブラウザで Actions タブ → Artifacts から直接ダウンロード
  （`git`・`gh` CLI とも不使用。エンドユーザーと同じ経路）

| # | 項目 | 結果 |
|---|---|---|
| 1 | SmartScreen警告 | **出た**。「詳細情報」→「実行」で起動できた |
| 2 | ダブルクリックでGUI表示 | OK |
| 3 | Excel実行時のログ進捗表示 | OK（`[1/N] タイトル -> 連載中 (...)` 等） |
| 4 | 完了メッセージ | OK |
| 5 | 完了後の「実行」ボタン再有効化 | OK |
| 6 | `tests\test.xlsx`（5件）の判定 | 連載中／完結／連載中／**連載中**／連載中 ※下記 |
| 7 | ファイルサイズ | 15,170 KB（ダウンロードしたzip）／EXE本体は 15,420 KB＝15.06 MB |

### 項目6の差異について（M3実測との違い）

M3実測（連載中／完結／連載中／完結／**判定不能**）に対し、5件目
「転生したらスライムだった件」が **判定不能 → 連載中** に変化した。

**結論: EXE・CIビルドの不具合ではなく、Issue #12（インフォボックス補助判定）の
実装が入ったことによる意図した改善である。** 切り分けの根拠は次の3点。

1. **Wikipedia記事のテキストは、判定に関わる部分が変化していない。**
   `judge("転生したらスライムだった件", use_infobox=False)` は現在も `判定不能` を
   返す（＝M3当時の挙動をそのまま再現できる）。リード文＋概要節に出てくる完結表現は
   「2025年11月をもって本編が完結した」だけであり、これは**原作ライトノベル**の話で
   ある。`_is_novel_primary()` が `True`（リードが「日本のなろう系ライトノベル」）の
   ため、メディアミックス判定が働いて漫画マーカーの無いこの文は採用されず、
   `_judge_extract()` は正しく `判定不能` を返している。この挙動はM3当時と同一。
2. **変化分は、新設されたインフォボックス経路から来ている。**
   `use_infobox=True`（既定）では `連載中` を返し、判定根拠は
   `インフォボックス: 終了号/終了日等が空欄`。M3のEXEをビルドした時点
   （記録コミット `fb9ec29`、2026-07-23 18:29）の `wikipedia_client.py` には
   `Infobox` の文字列が**1箇所も存在しない**（`git show
   fb9ec29:comic_checker/wikipedia_client.py | grep -c Infobox` → `0`）。
   インフォボックス判定は `2f76bbd`（2026-07-24 02:39、Issue #12）で追加されており、
   **M3のEXEビルドより後**である。つまり両者は同じコードではない。
3. **新しい判定結果のほうが正しい。**
   記事には `{{Infobox animanga/Manga}}` ブロックが9個あり、`タイトル` フィールドを
   持たない唯一のブロック（＝本編漫画）は、作画 川上泰樹・掲載誌 月刊少年シリウスで、
   `終了号 = `／`終了日 = ` がいずれも空欄、`巻数 = 既刊32巻（2026年6月現在）`。
   本編漫画は連載中であり、完結しているのは原作ライトノベルのほうである。
   これはまさに Issue #12 が解消しようとした「原作小説完結 vs 漫画連載中」の
   ケースそのものであり、`tests/test_wikipedia_client.py` も
   「転生したらスライムだった件」が `連載中` になることを回帰テストとして固定して
   いる。

したがって、M3の記録にある「判定不能」は**当時のコードにおける正しい期待値**であり、
現在の「連載中」も**現在のコードにおける正しい期待値**である。今後この5件の期待値は
連載中／完結／連載中／完結／**連載中**とする。

### SmartScreen警告について（確定情報）

**CI（GitHub Actions）でビルドしartifactからダウンロードしたEXEでは、SmartScreen
警告が出る。** 「詳細情報」→「実行」で起動でき、実用上の障害にはならなかった。

M3の「SmartScreen等の警告は発生せず」（2026-07-23）は、**`git clone` したソースから
自分でビルドしたローカルビルド固有の結果**である。ダウンロードしたファイルに付与される
「ゾーン識別子（Mark of the Web）」が付かなかったためであり、**標準手順（CI経由）には
適用できない**。標準手順で配布する限り、SmartScreen警告は出るものとして扱うこと。

対応の選択肢（onedir化 / コード署名 / 許容）は後述の
「SmartScreen / ウイルス対策ソフトの誤検知について」に整理してあるが、今回の検証では
「一度承認すれば起動できる」ため**許容**の判断とした。

### 項目7の数値について

報告値 15,170 KB は**ダウンロードしたzipのサイズ**である（15,533,443 バイト）。
展開後のEXE本体は 15,790,717 バイト＝15,420 KB（15.06 MB）で、CIの検証(c)が
ログに出す値と一致する。どちらも判定閾値100MBに対して十分小さく、`playwright` /
Chromium の混入は無い。

---

## 代替手順: ローカルWindows機で手動ビルドする

**CIが使えない場合の代替**である（Actions障害時、Freeプランの実行時間を使い切った場合、
CI以前の挙動を再現して切り分けたい場合など）。標準手順は上記のCI経由。

### 1. Python環境の準備（Windows PowerShell）

```powershell
git clone <このリポジトリのURL>
cd comic_checker
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller
```

**PowerShellでの仮想環境の有効化について**: `.venv\Scripts\activate`（`.\`なし・拡張子なし）
と入力すると、PowerShellは「`.venv`という名前のモジュールを読み込もうとして失敗する」
（`モジュール '.venv' を読み込むことができませんでした`）。これはPowerShellの実行ファイル
解決規則によるもので、`.venv`が壊れているわけではない。カレントディレクトリ内のスクリプト
を実行するには`.\`を付け、かつPowerShell用のスクリプトは`Activate.ps1`（`.bat`ではなく）
を使う必要がある。

もし`.\.venv\Scripts\Activate.ps1`の実行時に
`このシステムではスクリプトの実行が無効になっているため...`
というエラーが出た場合（PowerShellの実行ポリシーによる制限）、そのPowerShellウィンドウ
限定で許可する:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

それでも解決しない、または仮想環境を有効化せずに進めたい場合は、`.venv\Scripts\`配下の
実行ファイルを毎回フルパスで直接呼び出す方法でも代替できる（有効化不要）:

```powershell
.venv\Scripts\pip.exe install -r requirements.txt
.venv\Scripts\pip.exe install pyinstaller
.venv\Scripts\pyinstaller.exe comic_checker.spec
```

`requirements.txt`には`playwright`を含めていない（軽量ビルド用）。`playwright install
chromium`やOS依存ライブラリのインストールはこのビルドでは**不要**。

### 2. ビルド

```powershell
pyinstaller comic_checker.spec
```

成功すると`dist\comic_checker.exe`が生成される（onefile形式、単一の.exeファイル）。

### 3. 動作確認（ビルドしたWindows機上）

（CI経由で取得したEXEの確認にも、このチェックリストをそのまま使う。）

- `dist\comic_checker.exe`をダブルクリックし、GUIウィンドウが表示されることを確認
- 適当なExcelファイル（`タイトル`列があるもの）を選択し、「実行」を押して、ログ欄に
  進捗（`[1/N] タイトル -> 連載中 (...)`等）が流れ、完了メッセージが出ることを確認
- 完了後、「実行」ボタンが再度押せる状態に戻っていることを確認
- 生成された.exeのファイルサイズを確認（軽量ビルドなので数十MB程度のはず。数百MBに
  なっている場合はplaywright等が意図せず同梱されている可能性があるため、後述の
  「除外できているかの確認」を参照）

### 実機確認済み（2026-07-23、Windows 11 / Python 3.13.14）

- `dist\comic_checker.exe`: 14,450 KB（約14.1MB。軽量ビルドとして妥当なサイズ）
- `warn-comic_checker.txt`に`excluded module named comic_checker.manba_client -
  imported by comic_checker.main (delayed, optional)`を確認（`playwright`への
  言及なし＝そもそも同梱を試みていない）
- SmartScreen等の警告は発生せず
  （**この結果はローカルビルド固有である。** ダウンロード配布になる標準手順
  （CI経由）では警告が出る。上記「実機検証記録（M4-2）」を参照）
- `tests\test.xlsx`（ワンピース／進撃の巨人／ダンダダン／アオのハコ／
  転生したらスライムだった件の5件）で実行し、Wikipedia側の単体検証時と同じ結果
  （連載中／完結／連載中／完結／判定不能）を確認。ログ欄への進捗表示、完了後の
  ボタン再有効化も含めて想定通り
  （**5件目の期待値はその後 `連載中` に変わった。** Issue #12 のインフォボックス
  補助判定が本ビルドより後に入ったため。上記「実機検証記録（M4-2）」の
  「項目6の差異について」を参照）

### 4. 「Pythonをインストールしていないwindows PC」での検証（M4の対象、参考まで）

上記3はビルドした当人のマシン（Pythonが入っている）での確認に過ぎない。
「最終目的」の完全な検証（Pythonが入っていないPCでダブルクリックだけで動くか）は、
別マシン・別ユーザーアカウント・クリーンな仮想環境等で行う必要がある。これはM4
（Windows実機検証）のスコープであり、本手順（M3）はそこまでを含まない。

## 除外できているかの確認（トラブルシューティング）

CI経由の場合は「Verify build output」ステップが以下を自動で判定するため、
手動で確認する必要があるのは代替手順（ローカルビルド）を使った場合と、
CIの検証が落ちた原因を調べる場合である。

`pyinstaller comic_checker.spec`実行時のログ、または`build\comic_checker\
warn-comic_checker.txt`に以下の行があれば、`playwright`/`manba_client`が意図通り
除外されていることを示す（エラーではない）:

```
excluded module named comic_checker.manba_client - imported by comic_checker.main (delayed, optional)
```

もし代わりに`playwright`関連のファイルが大量に`dist`に含まれていたり、.exeのサイズが
異常に大きい場合は、`comic_checker.spec`の`excludes=['playwright',
'comic_checker.manba_client']`が効いていない可能性がある。`comic_checker/main.py`で
`from comic_checker.manba_client import ManbaClient`が**モジュールの先頭**に
戻っていないか確認すること（`_import_manba_client()`関数内での遅延importである
必要がある。先頭に書くと、除外指定があっても起動時に`ModuleNotFoundError`で
アプリ自体が起動しなくなる）。

## SmartScreen / ウイルス対策ソフトの誤検知について

PyInstallerのonefileビルドは、署名されていない実行ファイルであるため、Windows
Defender SmartScreenや一部のウイルス対策ソフトに警告・誤検知されることがある
（PyInstaller自体の既知の傾向で、本プロジェクト固有の問題ではない）。M4の実機検証で
これが実用上の障害になる場合、対応の選択肢:

- `comic_checker.spec`をonefileからonedir形式に変更する（起動が速くなり誤検知も
  減る傾向があるが、配布物が単一.exeではなくフォルダになる）
- コード署名証明書を取得して署名する（費用・手間がかかるため、個人利用ツールでは
  過剰な可能性がある）
- 誤検知の程度を見て、そのまま許容する（社内/個人利用限定であれば、警告を一度承認
  すれば以降は起動できることが多い）

2026-07-23の実機ビルドではSmartScreen警告は出なかった（`git clone`で取得したソース
から自分でビルドしたため、ダウンロードファイルに付与される「ゾーン識別子」が無い
ことが影響している可能性がある）。ただし、他のPCへ`.exe`単体を配布した場合
（ダウンロード・USB経由での受け渡し等）は改めて発生しうるため、楽観視せず
M4（別マシンでの配布・実行確認）で確認すること。

**標準手順（CI経由）ではこの条件が変わる。** artifactのダウンロードで入手する以上、
ゾーン識別子が付いた状態で実行されるため、2026-07-23の「警告が出なかった」という
結果はそのまま適用できない。Issue #21（M4-2）で必ず確認し、結果をこのファイルに
記録すること。

## WSL側で行った事前検証（参考）

このリポジトリのメンテナンスをWSL上のClaude Codeと行っている場合、Windows向けEXEは
生成できないが、`comic_checker.spec`の依存関係グラフが健全かどうかは、WSL上で同じ
specファイルを使ってLinux向けバイナリとしてビルドすることである程度事前確認できる
（生成されるのはLinux実行ファイルであり、Windows向けの成果物ではない点に注意）。

```bash
pip install pyinstaller
pyinstaller comic_checker.spec
./dist/comic_checker &   # DISPLAYが使える環境であればGUIが起動するはず
rm -rf build dist        # 確認用の成果物なのでコミットしない・残さない
```
