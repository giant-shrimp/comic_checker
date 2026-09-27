---
name: replace-doc-range
description: 既存文書の一部（行範囲）を，指示で確定した新本文に置き換えるときに使う．現行部分が一字一句一致することを確かめてから置き換え，範囲外が変わっていないことを確認する．
---

# 文書の行範囲の置き換え

## 前提

- 置き換える文書・開始行・終了行・現行部分・新本文は，指示で確定して渡される．
  このスキルは本文を作らない．書き足し・言い換えをしない．
- 現行部分を指示で受け取っていない場合は，編集せずに対象範囲を `cat -n`
  （行頭の空白を含めて）で取得して報告し，停止する．
- 以下の `<文書>`・`<開始>`・`<終了>` は指示の値，`<N>` は新本文の行数，
  `<E2>` は `<開始> + <N> - 1` を表す．

## 手順1: 現行部分の一致確認

1. 指示の現行部分を `/tmp/replace_old.txt` に書く（行頭の空白を保つ．末尾は改行1つ）．
2. 次を実行する．

```bash
diff /tmp/replace_old.txt <(sed -n '<開始>,<終了>p' <文書>); echo "exit=$?"
```

3. exit が 0 でなければ，編集せずに停止して報告する．

## 手順2: 新本文の書き出し

1. 指示の新本文を `/tmp/replace_new.txt` に書く（行頭の空白を保つ．末尾は改行1つ）．
2. `wc -l /tmp/replace_new.txt` と `grep -c '^$' /tmp/replace_new.txt` を実行し，
   指示の行数・空行数と一致することを確認する．違えば停止して報告する．
3. 箇条書きの中を置き換えるときは，空行を入れない（箇条書きが分断される）．
   入れ子のリストの後に，同じ項目の地の文を続けない（最後の入れ子の項目に
   取り込まれる）．新本文がこれに反していれば，直さずに停止して報告する．

## 手順3: 置き換え

python3 で行範囲だけを置き換える．他の行は触らない．

```bash
python3 - <文書> <開始> <終了> /tmp/replace_new.txt <<'EOF'
import sys
path, s, e, new = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
with open(path, encoding="utf-8") as f:
    lines = f.read().splitlines(keepends=True)
with open(new, encoding="utf-8") as f:
    repl = f.read().splitlines(keepends=True)
lines[s - 1:e] = repl
with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)
EOF
```

## 手順4: 範囲外の確認

比較の基準は，編集前の文書と同じ内容の参照（通常は `origin/main`）とする．
`<開始>` が 1 のときは1行目の比較を省く．

```bash
diff <(git show origin/main:<文書> | sed -n '1,<開始-1>p') <(sed -n '1,<開始-1>p' <文書>); echo "head_exit=$?"
diff <(git show origin/main:<文書> | sed -n '<終了+1>,$p') <(sed -n '<E2+1>,$p' <文書>); echo "tail_exit=$?"
diff /tmp/replace_new.txt <(sed -n '<開始>,<E2>p' <文書>); echo "new_exit=$?"
git diff -U0 -- <文書> | grep '^@@' | sed 's/ @@.*/ @@/'
git diff --stat
```

3つの exit がすべて 0 で，`<文書>` 以外が変わっていないことを確認する．
違えば停止して報告する．

## 手順5: 追加本文の作品名照合

```bash
python3 scripts/check_title_leak.py /tmp/replace_new.txt; echo "exit=$?"
```

文書全体には使わない（追加した本文だけを照合する．ADR-031）．

## しないこと

- 現行部分が一致しないまま置き換えない．
- 指示にない行を足さない・消さない．
- 結果を取得して確認する前に「置き換えた」「一致した」と報告しない．
