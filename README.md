# comic-checker

Excelに入っている漫画タイトル一覧を [manba.co.jp](https://manba.co.jp/) で検索し、
完結しているか連載中かを判定してExcelに書き戻すツールです。

manba.co.jpはCloudflareのボット対策下にあるため、`requests`のような単純なHTTP
アクセスでは弾かれます。そのため本ツールはPlaywright（ヘッドレスブラウザ）で
実際にページを開いてアクセスします。

## セットアップ

### 1. Python仮想環境の作成

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # 開発・テストする場合
# または
pip install -r requirements.txt        # 実行のみの場合
```

### 2. Playwright用Chromiumの取得

```bash
playwright install chromium
```

### 3. OS依存ライブラリ

Chromiumの実行にはOSの共有ライブラリ（`libnspr4`, `libnss3`, `libatk1.0-0` など）が
必要です。以下のコマンドで確認・インストールできます（システムへの変更を伴うため、
実行するかはご自身で判断してください）。

```bash
playwright install-deps --dry-run chromium   # 何が足りないか確認するだけ
sudo playwright install-deps chromium         # 実際にaptでインストールする場合
```

### 4. 検索APIキーの設定

本ツールはmanba.co.jpのキーワード検索ボックス（オートコンプリート）が使っているのと
同じ検索専用キーを使って、Meilisearchの検索APIを呼び出します。これはmanba.co.jpの
フロントエンドで公開されている検索専用キーであり、サイトを訪れた誰のブラウザでも
検索するたびに同じ値が使われている、秘匿情報ではないものです。それでもREADMEに
固定値として書くとサイト側の変更で古い値のまま放置されやすいため、利用者ご自身の
ブラウザで確認して設定する形にしています。

1. ブラウザでmanba.co.jpを開き、開発者ツールのNetworkタブを開く
2. 検索ボックスに何か入力する
3. `search.manba.co.jp/multi-search` へのリクエストを見つける
4. リクエストヘッダーの `authorization: Bearer ` の後ろの文字列をコピーする
5. 環境変数に設定する

```bash
export MANBA_SEARCH_API_KEY=<コピーした値>
```

## 使い方

対象のExcelファイルの1行目にヘッダー行があり、タイトル列に「タイトル」という
列名がある前提です（列名は引数で変更可能）。

```bash
source .venv/bin/activate
python -m comic_checker.main path/to/対象.xlsx
```

実行すると、以下の列が（無ければ）自動的に追加され、判定結果が書き込まれます。

| 列名 | 内容 |
|---|---|
| 連載状況 | `完結` / `連載中` / `ヒットなし` / `不明` / `エラー` |
| マンバ上のタイトル | manba.co.jpでの検索最上位ヒットのタイトル（一致確認用） |
| マンバURL | 判定に使った作品ページのURL |

タイトルの表記ゆれなどで検索結果が別作品にヒットする場合があるため、
「マンバ上のタイトル」列で目視確認することを推奨します。

### 主なオプション

```
--title-column        タイトル列のヘッダー名（デフォルト: タイトル）
--status-column        判定結果を書き込む列名（デフォルト: 連載状況）
--sheet                 対象シート名（省略時はアクティブシート）
--no-skip-filled        判定済みの行も再判定する（デフォルトは既判定行をスキップ）
--no-headless           ブラウザを表示して実行する（動作確認用）
--min-delay / --max-delay  リクエスト間の待機秒数（デフォルト 3〜6秒）
```

`python -m comic_checker.main --help` で全オプションを確認できます。

## 動作の仕組み・制限事項

- **検索**: manba.co.jpの検索ボックスと同じ公開検索API（Meilisearch）を利用し、
  タイトルの最上位ヒットを採用します。
- **完結/連載判定**: 作品ページ（`https://manba.co.jp/boards/<id>`）の`<title>`タグが
  `[完結] `で始まるかどうかで判定します。
- **アクセス間隔**: Cloudflareのボット対策により連続アクセスするとチャレンジページが
  再表示されることがあるため、リクエストごとにランダムな待機（デフォルト3〜6秒）を
  入れています。作品ページ取得中にチャレンジページに当たった場合は最大3回まで
  リトライ（8秒→16秒→24秒の間隔）し、それでも突破できない場合は「不明」として
  記録し、次のタイトルへ処理を続けます。
- **起動時のチャレンジ突破失敗**: 実行開始時（`ManbaClient`の`with`ブロックに入る
  タイミング）にCloudflareチャレンジを自動突破できなかった場合は、その時点で
  `RuntimeError`を送出して処理を中断します。特に「Verify you are human」のような
  チェックボックスをクリックする**インタラクティブなチャレンジ**は、`Just a moment...`
  型と違って待っても自動では解決しません。この場合は`--no-headless`を付けて実行し、
  表示されたブラウザで手動でチェックボックスをクリックしてください。一度突破すれば
  Cookieが`.manba_state.json`（`--state-file`で変更可）に保存され、次回以降の
  ヘッドレス実行で再利用されます。頻発する場合は`--min-delay`/`--max-delay`を
  広げてアクセス頻度を下げる、時間を置いて再実行する、なども有効です。
- **エラー処理**: 1件ごとの処理は`main.py`内でtry/exceptしており、途中で例外が
  発生してもそのタイトルを「エラー」として記録し、処理全体は止めずに次のタイトルへ
  進みます。また `--save-every` 件ごとにExcelを保存するため、途中で処理が
  停止しても、そこまでの結果は保存されています。
- **セッション再利用**: `.manba_state.json`（gitignore対象）にPlaywrightの
  browser context の状態（Cloudflare通過後のCookie等）を保存し、次回実行時に
  再利用することで、毎回チャレンジを解かせずに済むようにしています。

## テスト

ネットワークに依存しない`excel_io.py`部分のみ、簡単なユニットテストを用意しています。

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest
```
