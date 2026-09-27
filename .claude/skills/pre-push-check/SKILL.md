---
name: pre-push-check
description: コミットした後，push する前に使う．verify.sh・差分の個人情報走査・追加行の作品名照合・抑制層の走査・（ERRORS.md を変えたときの）棚卸し検査をまとめて実行する．
---

# push 前の検証

## 前提

- 変更はコミット済みであること（`--diff-base` は `origin/main...HEAD` の差分を見る）．
- `git fetch origin` を実行してから始める．

## 手順1: 変更範囲とコミットの確認

```bash
git diff --stat origin/main...HEAD
git log origin/main..HEAD --format=%B | grep -i -E 'co-authored-by|generated with'; echo "trailer_grep_exit=$?"
```

- 変更ファイルが指示の範囲だけであることを確認する．
- `trailer_grep_exit` が 1（一致なし）であることを確認する．0 ならコミットに
  トレーラが付いているので，push せずに報告する．

## 手順2: 追加行の書き出し

```bash
git diff --no-color -U0 origin/main...HEAD | grep '^+' | grep -v '^+++' | cut -c2- > /tmp/prepush_added.txt
wc -l /tmp/prepush_added.txt
```

## 手順3: 検証の実行

```bash
./scripts/verify.sh 2>&1 | tail -n 15
python3 scripts/check_no_personal_info.py --diff-base origin/main; echo "exit=$?"
python3 scripts/check_title_leak.py /tmp/prepush_added.txt; echo "exit=$?"
bash scripts/check_scanner_registry.sh; echo "exit=$?"
```

`ERRORS.md` または `docs/errors_md_inventory.md` を変えたときは，次も実行する．

```bash
bash scripts/check_errors_inventory.sh; echo "exit=$?"
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
