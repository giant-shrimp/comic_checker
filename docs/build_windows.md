# Windows向けEXEビルド手順（M3: 軽量ビルド）

対象読者: Windows側でEXEをビルドする人（開発者本人）。エンドユーザー向けの使い方は
[README.md](../README.md) を参照。

## 前提

- PyInstallerはクロスコンパイル不可のため、Windows向けEXEは**Windows上でビルドする
  必要がある**（WSL/Linux上ではビルドできない）。
- この手順は「軽量ビルド」＝Wikipedia経路のみで、Playwright/Chromiumを同梱しない。
  `--fallback-to-manba`はこのビルドのEXEでは使えない（実行時に、起動直後ではなく
  `--fallback-to-manba`を指定した時点で明確なエラーメッセージが出る）。
  Playwright/Chromium同梱版は別途M2で扱う（現時点でv1の必須要件からは外れている）。

## 手順

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
- `tests\test.xlsx`（ワンピース／進撃の巨人／ダンダダン／アオのハコ／
  転生したらスライムだった件の5件）で実行し、Wikipedia側の単体検証時と同じ結果
  （連載中／完結／連載中／完結／判定不能）を確認。ログ欄への進捗表示、完了後の
  ボタン再有効化も含めて想定通り

### 4. 「Pythonをインストールしていないwindows PC」での検証（M4の対象、参考まで）

上記3はビルドした当人のマシン（Pythonが入っている）での確認に過ぎない。
「最終目的」の完全な検証（Pythonが入っていないPCでダブルクリックだけで動くか）は、
別マシン・別ユーザーアカウント・クリーンな仮想環境等で行う必要がある。これはM4
（Windows実機検証）のスコープであり、本手順（M3）はそこまでを含まない。

## 除外できているかの確認（トラブルシューティング）

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
