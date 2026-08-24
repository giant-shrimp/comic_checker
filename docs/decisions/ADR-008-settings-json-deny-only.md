# ADR-008: `.claude/settings.json` には `deny` のみを置き、`allow` は置かない

- 日付：2026-08-24
- 状態：採用

## 背景

`ai-loop-implementation-plan_v8.md`（AI Loop実装計画書）Phase 1-3は、
`.claude/settings.json` に `permissions.allow` と `permissions.deny` の両方を
置き、次の目安で `allow` の範囲を段階的に広げる運用を推奨している。

| 時期 | 許可する範囲（計画書の目安） |
|---|---|
| 1週目 | 読み取り・テスト実行・検証のみ |
| 2週目 | ファイル編集・ローカルコミット |
| 3週目以降 | ブランチ push・PR 作成（`main` への直 push は最後まで禁止） |

本プロジェクトの `.claude/settings.json`（実測、本ADR作成時点）は、この形を
採っていない。

```
$ jq '.permissions.deny | length' .claude/settings.json
29
$ jq '.permissions | has("allow")' .claude/settings.json
false
```

`permissions` ブロックには `deny`（29要素）のみが存在し、`allow` キー自体が
無い（実測: 上記コマンドの出力どおり）。対話セッションでは `allow` に無い操作は毎回 `ask`
（許可プロンプト）で判断され、非対話実行（`scripts/work_loop.sh`）では
`work_loop.settings.json`（`--settings` オプションで個別に追加読み込みされる、
`scripts/work_loop.sh` L73）が別途 `deny` のみを定義する形になっている。

計画書どおりの段階的 `allow` を採らなかった直接のきっかけは、Issue #14で
実際に起きた事故である。`ERRORS.md`「AI Loop（`scripts/work_loop.sh`）の
検証で分かったこと（Issue #14〜#16）」（本ADR作成時点で ERRORS.md 本体14〜69行に
現存。剪定〔PR #192〕の対象外〔分類A〕であり、アーカイブへは移動していない）に
経緯が記録されている。

要約すると：`scripts/work_loop.sh`（非対話実行）の `--allowedTools` に
`git add`/`git commit` を含めずに絞ったつもりだったが、実際には対話セッション用の
`.claude/settings.local.json`（`permissions.allow` に `Bash(git add *)`/
`Bash(git commit -m '*)` を保持）がこの非対話実行にも素通しで効き、明示的な許可
なくcommitが実行された。原因は、Claude Codeの `permissions.allow` が
**発生源（CLIフラグ／プロジェクト設定／ローカル設定）を問わず加算される**という
仕様（`ERRORS.md` が引用する公式ドキュメント `permissions.md` の記載）である。

この事故が示したのは、「`settings.json` に狭い `allow` を書けば、それだけで
権限が絞られる」という前提が誤りだということである。`allow` はどこか別の場所
（特に `.gitignore` 対象で対話セッションのたびに蓄積していく
`.claude/settings.local.json`）に広い定義が1つでもあれば、加算されてすり抜ける。

一方、`deny` は**発生源を問わず常に `allow` より優先される**ことも同じ調査で
実測済みである（`ERRORS.md` 該当項、および `.claude/settings.json` の
`_note_deny_scope` 注記）。`scripts/work_loop.sh` はこの非対称性を使い、
`work_loop.settings.json` を非対話実行にだけ追加で読み込ませることで、
プロジェクト側や個人側にどんな `allow` が積み上がっていても、非対話実行の権限は
`deny` によって一律で絞り込まれる設計にしている（`scripts/work_loop.sh`
L51-72のコメント参照。「プロンプト文面で『commitして』等と指示しても、この
denyは緩まない」ことも同コメントに明記されている）。

## 決定

1. **`.claude/settings.json` には `deny` のみを置き、`allow` は置かない。**
2. **対話セッションの権限は、都度 `ask`（許可プロンプト）で判断する。**
   `allow` によって恒常的に許可される操作の集合を、プロジェクト側の設定として
   持たない。
3. **非対話実行（`scripts/work_loop.sh` 等）の権限は `work_loop.settings.json`
   に個別指定し、対話セッション用の設定（`.claude/settings.local.json` の
   `allow` を含む）を継承させない。** `--settings` オプションによる追加読み込み
   （現在の実装）を維持する。

## 却下した案

### 1. 計画書どおり `settings.json` に `allow` を置き、段階的に拡大する

却下。Issue #14の事故は、まさに「`allow` を絞ったつもりが、別の場所
（`settings.local.json`）の `allow` が加算されてすり抜けた」という形で起きた。
`permissions.allow` が発生源を問わず加算される仕様である以上、
`settings.json` 側だけ `allow` を狭く保っても、`settings.local.json` 側
（対話セッションで許可プロンプトに「はい」と答えるたびに自動的に蓄積される、
gitignore対象のためレビューもされないファイル）に広い `allow` が積み上がって
いけば、`settings.json` の `allow` は歯止めとして機能しない。計画書の
「時期で `allow` を広げる」運用は、`settings.json` という単一ファイルの中で
段階を管理できることを前提にしているが、本プロジェクトの実測では
`allow` の実効範囲は複数ファイルの合算でしか決まらないため、この前提が
成立しなかった。

### 2. `settings.local.json` に `allow` を集約する運用を、正式な決定として明文化する

**これは現状の運用そのものである**（対話セッションで許可プロンプトに答える
たびに `settings.local.json` の `allow` が実際に増えている）。それでも本ADRは
これを「決定」ではなく「`ask` 運用の既定の副作用」として扱い、`allow` を
`settings.local.json` に**意図的に集約する**方針としては採用しない。

理由：`settings.local.json` は個人のローカル環境ごとに異なり、gitignore対象で
あるためコミットもレビューもされない。ここに `allow` を積極的に集約する方針を
取ると、「このプロジェクトでAIに何を許可しているか」がリポジトリのどこにも
記録されない状態を追認することになる。決定2・3（`ask` 運用と
`work_loop.settings.json` の分離）は、`settings.local.json` に何が積み上がって
いてもプロジェクトの意図した権限境界（特に非対話実行）が保たれる設計であり、
`settings.local.json` の中身自体を設計の一部として当てにしない。つまり
`settings.local.json` へのallowの蓄積は黙認された副作用であり、そこへ意図を
込めた運用（例えば「よく使うコマンドはここに書いておく」といった積極的な
運用手順化）はしない。

## 影響

この決定が縛るもの：

- 新しいツール・コマンドを対話セッションで恒常的に許可したい場合、
  `.claude/settings.json` に `allow` を追加する経路は取らない。都度の
  許可プロンプトで対応するか、非対話実行にだけ関わる場合は
  `work_loop.settings.json` 側の `deny` を見直す（`work_loop.settings.json`
  自体も `.claude/settings.json` の `deny` によりAIからは編集できない。
  Phase1-3の3層防御と同じ構造）。
- 計画書「Phase 1 完了条件」の「`.claude/settings.json` に allow / deny が
  ある」というチェック項目は、本プロジェクトでは**意図的に満たさない**。
  計画書のチェックリストをそのまま適合確認に使う場合は、この項目を
  「`deny` のみで意図的に運用（ADR-008参照）」と読み替える必要がある。
- ADR-003（`.github/workflows/**` の `deny` 維持）・ADR-004決定3と矛盾しない。
  いずれも「検査される側〔AI〕が検査・権限の定義そのものを書き換えられない
  状態を保つ」という同じ非対称性の論理に立っており、本ADRは
  その対象を `settings.json` の `allow` の扱いに広げたものである。
  supersede関係は発生しない。

## 欠点

- **都度 `ask` による摩擦が増える。** 計画書の段階的 `allow` 拡大は、
  信頼が積み上がった操作について許可プロンプトを省略し、対話の速度を
  上げることを狙っている。本プロジェクトはこれを採らないため、同じ
  コマンドであっても対話セッションのたびに `settings.local.json` に
  蓄積された `allow` の範囲外であれば毎回プロンプトが出る（ただし
  `settings.local.json` は実際には`allow`が蓄積し続けるため、実務上は
  同一コマンドの再確認頻度は徐々に下がる。これは意図した設計ではなく、
  上記「却下した案2」で述べた黙認された副作用である）。
- **権限の実効範囲が可視化されない。** `settings.json` を見るだけでは
  「対話セッションで実際に何が許可されているか」は分からず、
  `settings.local.json`（個人ごとに異なり、コミットもレビューもされない）を
  別途確認しない限り全体像を把握できない。計画書が目指す「`allow`/`deny`を
  見れば権限が分かる」という単純さを、本プロジェクトは手放している。
- **新規参加者・別環境での再現性が下がる。** `settings.local.json` は
  gitignore対象のため、別のマシン・別のユーザーで作業を始める場合、
  同じ利便性（過去に許可した操作の再確認省略）を得るには、そのマシン上で
  同じ許可プロンプトを一から積み上げ直す必要がある。
