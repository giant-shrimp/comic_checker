# リリース手順（半自動運用）

決定の経緯は [ADR-007](decisions/ADR-007-release-automation-scope.md) を参照。
GitHub Releasesへの公開は自動化していない。**タグ付け・Release作成はすべて
人間（遥哉）がこの手順に沿って手で行う。** ビルド自体の詳細（自動検証項目
(a)(b)(c)の中身、トラブルシューティング）は `docs/build_windows.md` を参照し、
本書では重複させない。

---

## 1. リリース前チェックリスト

- [ ] `main`ブランチにいる、かつ`origin/main`と同期している
      （`git status`・`git log -1 origin/main`で確認）
- [ ] `./scripts/verify.sh`が通る（2026-08-11時点の基準値: 256 passed、
      M6-B-4ゲート 検出54/59・副作用1/37）
- [ ] `git status --porcelain`が空（未コミットの変更が無い）
- [ ] リリースに含めたい変更がすべて`main`にマージ済み
      （`gh pr list --state open`でOPENなPRが残っていないことを確認する。
      残っている場合、それが今回のリリースに含めなくてよい変更かを判断する）

## 2. `__version__`の更新 → PR作成 → マージ

`comic_checker/__init__.py`の`__version__`が単一の情報源（作業72-73）。
これを更新するだけでGUI・CLI両方の表示に反映される。

```bash
git switch main
git pull
git switch -c chore/release-v0.1.1   # v0.1.1 は例。実際のリリース番号に置き換える
```

`comic_checker/__init__.py`を編集:

```python
__version__ = "0.1.1"
```

**忘れやすい点**: `tests/test_version.py`の`test_version_is_pinned`ほか、
複数のテストが旧バージョン番号をリテラルで期待値に埋め込んでいる
（このプロジェクトの「値をpinする」慣習どおり）。`__version__`を上げると
`./scripts/verify.sh`がこのテスト群で落ちる。**テスト側の期待値も同じ
コミットで更新すること。**

**`tests/`だけをgrepしても不十分。** `docs/`配下にも旧バージョン番号を
例示コマンドとして書いている箇所が残ることがある（作業76で
`docs/build_windows.md`のタグ例示コマンドが実際に取り残されていたのを
発見した）。**リポジトリ全体をgrepすること**（`docs/decisions/`配下の
ADRのように、旧バージョン番号が実測値として意図的に書かれた記述と、
単なる例示・現在値への追随が必要な記述が混在するため、機械的な
置換ではなく1件ずつ判断すること——ADRの実測記録は変更しない）:

```bash
grep -rn "0\.1\.0" --include="*.py" --include="*.md" --include="*.yml" .
# 該当箇所を確認し、実測記録（ADRの過去の観測値等）以外を新バージョン
# 文字列に置き換えてから
./scripts/verify.sh   # 通ることを確認
```

コミット・push・PR作成:

```bash
git add comic_checker/__init__.py tests/test_version.py
git commit -m "chore: バージョンを0.1.1へ更新する"
git push -u origin chore/release-v0.1.1
gh pr create --title "chore: バージョンを0.1.1へ更新する" --body "..."
```

**PRのマージはGitHub GUIで人間が行う**（ADR-001）。マージ後は
`main`を最新化する:

```bash
git switch main
git pull
```

## 3. タグ付け

**タグ付けは人間のみが行う（ADR-007決定1）。** マージ後の`main`の先頭
（＝バージョン更新コミットを含む最新コミット）に対して打つ。

```bash
git switch main
git pull
git log -1 --oneline   # バージョン更新コミットが先頭にあることを確認

git tag v0.1.1
git push origin v0.1.1
```

`v`で始まるタグのpushは`build-windows.yml`の`on: push: tags: ["v*"]`を
トリガーし、自動でビルドが走る（`docs/build_windows.md`参照）。

## 4. ビルドの確認

タグpushで自動的に走ったビルドを確認する:

```bash
gh run list --workflow=build-windows.yml --limit 1
```

`databaseId`（run-id）を控え、ジョブが成功したことと、`Embed build info`
ステップのログで実際に埋め込まれた値を確認する:

```bash
gh run view <run-id> --log | grep -A 2 "Embedded build info"
```

`BUILD_COMMIT`がタグを打ったコミットの短縮ハッシュ（`git rev-parse --short
HEAD`と一致）であることを確認する。

**このログ確認コマンド自体は、2026-08-11時点でまだ実際のビルドで検証
できていない**（`Embed build info`のログ出力追加(PR #127)・タグ整合性
チェック追加(PR #129)はいずれもこの日にマージされたばかりで、それ以降
`build-windows.yml`が実際に走った実績が無いことを`gh run list`で確認
済み）。ステップの実装（`Write-Host` 1行 + `Get-Content` 2行）を読んで
`grep -A 2`の行数が正しいことは確認したが、**次回の実ビルドで初めて
実地検証されることになる。** もしコマンドの出力が想定と違う場合は、
まずこの手順書側の記述を疑うこと。

**`Embed build info`ステップにログ出力が無い場合**（`~/comic_checker-agent-
notes/0002-embed-build-info-log-output.patch`が未適用の環境）: ログでの
確認はできない。ダウンロードしたEXEを実際に起動し、ウィンドウタイトル・
フッタの表示を目視確認する（作業74で実際に行った実機確認と同じ手順、
`docs/build_windows.md`の「実機検証記録」参照）。

`docs/build_windows.md`の自動検証(a)(b)(c)（manba_client除外・playwright
不在・EXEサイズ100MB未満）も、通常はここで一緒に確認する。

## 5. artifactのダウンロードとReleaseへの添付

```bash
gh run download <run-id> -n comic_checker-exe -D dist_release
ls dist_release/   # comic_checker.exe が入っていることを確認

gh release create v0.1.1 dist_release/comic_checker.exe \
  --verify-tag \
  --title "v0.1.1" \
  --notes "変更内容の概要をここに書く"
```

`gh release create`は手順3で既にpush済みのタグ`v0.1.1`をそのまま使う
（タグを新規作成する必要はない）。**`--verify-tag`は必須。** `gh release
create --help`で実測確認したところ、指定したタグが存在しない場合
`gh release create`はエラーにせず、`main`の最新状態から**新規にタグを
自動作成してしまう**。手順3のタグpushが何らかの理由で失敗していた場合、
このフラグが無いと、意図したコミットとは異なる`main`の最新HEADが
静かにリリースされる事故につながる。`--verify-tag`を付ければ、タグが
存在しない場合にコマンドが中断される。

## 6. リリース後の確認事項

- [ ] `gh release view v0.1.1`でアセット（`comic_checker.exe`）が添付されて
      いることを確認する
- [ ] `gh release list`に新しいリリースが表示されることを確認する
- [ ] Releaseページからダウンロードしたファイルのサイズが、`dist_release/
      comic_checker.exe`と一致することを確認する（取り違え防止）
- [ ] 可能であれば、`docs/user_guide.md`の手順に沿って実機で起動し、
      バージョン表示（ウィンドウタイトル・フッタ）が意図した値になって
      いることを確認する

## 参考: 一時的なテストビルド（タグを打たない）

リリースを伴わない動作確認だけしたい場合は、タグを打たず手動トリガーで
ビルドできる（Release作成はしない）:

```bash
gh workflow run build-windows.yml
gh run watch
```

`docs/build_windows.md`「標準手順」も参照。
