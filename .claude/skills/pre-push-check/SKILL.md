---
name: pre-push-check
description: コミットした後，push する前に使う．verify.sh・差分の個人情報走査・追加行の作品名照合・抑制層の走査・（ERRORS.md を変えたときの）棚卸し検査をまとめて実行する．
---

# push 前の検証

## 前提

- 変更はコミット済みであること（`--diff-base` は `origin/main...HEAD` の差分を見る）．
- `git fetch origin` を実行してから始める．

## コマンドの実行と判定

- 下の各コードブロックの1行を，1回の Bash 呼び出しで実行する．`&&`・`;` でつながず，1回の応答で複数のツール呼び出しを出さない．
- パイプは読み取り専用の確認と /tmp への書き出しに限る．
- 合否は，Bash ツールの結果がエラー（`Exit code N`）として返ったかどうかで判断する．`; echo "exit=$?"` は付けない．
- `grep -c` は一致が0件でもエラーとして返らない．件数の値で判断する．

## 手順1: 変更範囲とコミットの確認

```bash
git diff --stat origin/main...HEAD
git log origin/main..HEAD --format=%B | grep -c -i -E 'co-authored-by|claude-session|generated with'
```

- 変更ファイルが指示の範囲だけであることを確認する．
- 2行目の値が 0 であることを確認する．0 でなければコミットに
  トレーラが付いているので，push せずに報告する．

## 手順2: 追加行の書き出し

```bash
git diff --no-color -U0 origin/main...HEAD | grep '^+' | grep -v '^+++' | cut -c2- > /tmp/prepush_added.txt
wc -l < /tmp/prepush_added.txt
```

## 手順3: 検証の実行

```bash
./scripts/verify.sh
python3 scripts/check_no_personal_info.py --diff-base origin/main
python3 scripts/check_title_leak.py /tmp/prepush_added.txt
bash scripts/check_scanner_registry.sh
```

- `verify.sh` は末尾が `VERIFY PASSED` で，エラーとして返らないことを確認する．出力をパイプで `tail` などに渡さない（終了コードが失われる）．
- 同じ HEAD で直前に `verify.sh` が成功している場合は，再実行せずその結果を使ってよい．

`ERRORS.md` または `docs/errors_md_inventory.md` を変えたときは，次も実行する．

```bash
bash scripts/check_errors_inventory.sh
```

- `check_title_leak.py` は既存文書の全文には使わない（追加した行だけを照合する．ADR-031）．
- 警告（2〜3文字の一致）が出た行は，実在作品名の一部として書かれていないかを
  目で確認する．

## 手順4: 判定

- 1つでも失敗したら push しない．
- 指示の範囲で直せるものは直してコミットし，手順1からやり直す．
- 直せないもの，または直すと指示の範囲を超えるものは，停止して事実だけを報告する．

## しないこと

- 失敗を `|| true` 等で隠さない．
- 走査器の検出行の本文・パターン定義を報告に書き写さない．
