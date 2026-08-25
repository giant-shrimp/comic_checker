# ADR-009: Phase 5-3（依存更新ループ）・Phase 5-4（夜間トリアージ）は現時点で見送る

- 日付：2026-08-24
- 状態：採用

## 背景

`ai-loop-implementation-plan_v8.md`（AI Loop実装計画書）Phase 5-3・5-4は、
Phase 5-2（PRレビュー、ADR-006で再設計済み・稼働中）に続く常時稼働ワークフロー
として位置づけられている。計画書は5-3を単なる機能追加ではなく、

> このループが1か月安定して回るなら、土台（検証・権限・停止条件）は正しく
> 組めています。**そこまで確認してから、コードを書かせるループへ進んで
> ください。**

という「被害の小さい題材でループ基盤の安全性を確認する踏み台」として明示的に
位置づけている。5-3・5-4がいずれも未着手のまま放置されると、この対応関係が
宙に浮き、`ai-loop-implementation-plan_v8.md`との対応表（本ADR作成の前段で
行った比較作業）を見直すたびに「未着手」の理由をゼロから再調査することになる。
本ADRは、着手可否を実測で判定し、結論を記録する。

## 実測結果

### 1-a. Phase 5-3が要求する権限とGitHub側の現在値

計画書 Phase 5-3 のサンプルワークフロー（`ai-loop-implementation-plan_v8.md`
1256-1258行）が要求する権限：

```yaml
permissions:
  contents: write
  pull-requests: write
```

GitHub側の現在値（実測）：

```
$ gh api repos/giant-shrimp/comic_checker/actions/permissions/workflow
{"default_workflow_permissions":"read","can_approve_pull_request_reviews":false}

$ gh api repos/giant-shrimp/comic_checker/branches/main/protection
{"message":"Upgrade to GitHub Pro or make this repository public to enable this feature.",
 "documentation_url":"https://docs.github.com/rest/branches/branch-protection#get-branch-protection",
 "status":"403"}

$ gh api repos/giant-shrimp/comic_checker --jq '{private: .private, visibility: .visibility}'
{"private":true,"visibility":"private"}
```

- ワークフロー既定権限は `read`（Phase 5-3が要求する `write` ではない）
- `can_approve_pull_request_reviews: false`。このフィールドはGitHubの
  「Allow GitHub Actions to create and approve pull requests」チェックボックスに
  対応する単一のAPIフィールドである（GitHub REST APIドキュメントの記述に基づく
  対応関係。本セッションでは値の変更を行っていないため、GUI側の表示との
  完全な一致は未確認 — 手順1のGUI確認項目として後述）
- ブランチ保護は403で取得不可（GitHub Free + privateリポジトリの制約。
  ADR-001・ADR-004で確認済みの制約が、本ADR作成時点でも変化していないことを
  再実測で確認した）
- リポジトリは `private: true`（プラン変更・可視性変更は行っていない）

**上記がGitHub Free + privateリポジトリで変更可能かどうか**: `default_workflow_
permissions`・`can_approve_pull_request_reviews` の2フィールドは、
ブランチ保護のような403（課金プラン起因の明示的ブロック）を伴わずに読み取れて
いる。ただしこれは「現在read/falseである」という事実を示すのみで、write/true
へ変更する操作自体がGitHub Free + privateリポジトリで許可されるかどうかを
証明するものではない。本ADRの制約（GitHubのリポジトリ設定を変更しない）に
従い、実際にPATCHを試みる検証は行っていない。**この点はGUI確認が必要な
未確認事項として扱う**（後述「GUI確認が必要な項目」参照）。

**ブランチ保護が使えない状態で`contents: write`を与えた場合にmainが守られない
構造になるか**: なる。`contents: write`を持つワークフローの実装にバグがあった
場合（例: 誤って`main`へのpushコマンドが発行される）、これを止める手段は
サーバサイドのブランチ保護以外に存在しない。`.githooks/pre-push`は
クライアントサイドフックであり、CI実行には効かない（ADR-001「受け入れた
リスク」3）。これはADR-004決定2が「Step 2」として既に定義した状況と同一の
構造である。

### 1-b. 5-3のブロッカーはADR-004の壁と同一か

**同一である。** 根拠：

- ADR-004決定2は、`contents: write`を与えてActionsからブランチを切りPRを
  作る構成を「Step 2」と呼び、その時点でADR-001の受け入れ済みリスク3
  （CI pushは`.githooks/pre-push`では止められない）が「実際に露出する対象を
  持つ状態に変わる」と記録している。
- Phase 5-3のサンプルワークフローは、まさに「`contents: write`を与えて
  ブランチを切りPRを作る」構成そのものであり、ADR-004が定義した「Step 2」に
  該当する。
- ADR-004は同時に、Phase 5-5（Issue→PR自動化）についても
  「Allow GitHub Actions to create and approve pull requests」が無効のままで
  あることを着手前提条件の未達として記録しており、この制約は5-3にも同様に
  適用される（5-3も最終的にPRを作成する）。
- 本ADR作成時点の再実測（上記1-a）で、ADR-004が記録した制約
  （`default_workflow_permissions: read`・ブランチ保護403・
  `can_approve_pull_request_reviews: false`）はいずれも**変化していない**
  ことを確認した。

したがって、本ADRはADR-004が既に記録した壁を再度別の言葉で記述するのではなく、
**ADR-004を参照する形**で足りると判断する。

### 1-c. Dependabot / Renovateとの重複評価

```
$ ls .github/dependabot.yml
ls: '.github/dependabot.yml' にアクセスできません: そのようなファイルやディレクトリはありません

$ find . -iname "dependabot*" -not -path "./.git/*"
（出力なし）

$ gh api repos/giant-shrimp/comic_checker/vulnerability-alerts
{"message":"Vulnerability alerts are disabled.",
 "documentation_url":"https://docs.github.com/rest/repos/repos#check-if-vulnerability-alerts-are-enabled-for-a-repository",
 "status":"404"}
```

`.github/dependabot.yml`は存在せず、Dependabotのバージョン更新は設定されて
いない。脆弱性アラート（Dependabot alerts）もAPI経由で「disabled」と明示的に
返っており、無効であることを確認した（この項目はAPIで判定が完結しており、
GUI確認は不要）。Dependabot version updatesのGUIトグル自体（Settings →
Code security）の目視は行っていない（詳細は後述のGUI確認項目）。

依存の実態：

```
$ cat requirements.txt
openpyxl
requests
tkinterdnd2

$ cat requirements-fallback.txt
-r requirements.txt
playwright

$ cat requirements-dev.txt
-r requirements-fallback.txt
pytest
```

直接指定の依存は5パッケージ（openpyxl, requests, tkinterdnd2, playwright,
pytest）。

```
$ git log --oneline -- requirements.txt
b2f2bc0 GUIの見た目をポップにし、ドラッグ＆ドロップを追加
cd598cf Prepare M3 light PyInstaller build (Wikipedia-only EXE)
6ce2d19 Switch primary lookup source from manba.co.jp to Wikipedia (Issue #3)
ffa6925 Initial project structure: manba.co.jp comic status checker

$ git log --oneline -- requirements-fallback.txt
cd598cf Prepare M3 light PyInstaller build (Wikipedia-only EXE)

$ git log --oneline -- requirements-dev.txt
cd598cf Prepare M3 light PyInstaller build (Wikipedia-only EXE)
ffa6925 Initial project structure: manba.co.jp comic status checker

$ git log --reverse --format="%cI" | head -1
2026-07-23T01:52:24+09:00
```

リポジトリ開始（2026-07-23）から本ADR作成日（2026-08-24）まで約32日間で、
`requirements*.txt`への変更は4コミットのみ。しかもいずれも既存パッケージの
バージョン更新（patch/minorのbump）ではなく、機能追加に伴う**新規パッケージの
追加**（Wikipedia経路への切替、PyInstaller軽量ビルド対応、GUIドラッグ&ドロップ
対応）である。既存パッケージのバージョン更新それ自体は、本ADR作成時点まで
一度も発生していない。

**計画書0節の条件1「少なくとも週1回は繰り返す作業である」を満たすか**:
満たさない。32日間で依存更新（バージョンbump）が0件である実測に対し、
週1回という頻度の条件には遠く及ばない。計画書自身も「依存更新そのものは
Dependabot や Renovate でもできる。それで足りるならそちらを使ってください」
と明記しており、本プロジェクトの依存更新の頻度・規模（5パッケージ、
更新0件/32日）では、そもそもDependabot導入すら過剰である可能性が高い
（Dependabotが検知するようなバージョンbump自体がまだ一度も必要になって
いない）。

### 1-d. Phase 5-4（夜間トリアージ）の要否

計画書 Phase 5-4 のサンプルワークフロー（`ai-loop-implementation-plan_v8.md`
1304-1306行）が要求する権限：

```yaml
permissions:
  contents: read
  issues: write
```

`contents: write`を要求しない点で5-3・5-5とは異なる。既存の`claude-review.yml`
（`contents: read`・`pull-requests: write`を明示的に宣言し、実測で正常に
コメント投稿まで到達している。ADR-006参照）と同様の構成であるため、
`issues: write`も同じ経路（ワークフローYAML内の明示的`permissions:`宣言）で
機能する可能性が高いと考えられる。**ただしこれは既存ワークフローからの類推
であり、`gh issue create`をActions経由で実際に試した実測は無い。断定しない。**

open issueの実態（実測、2026-08-24時点）：

```
$ gh issue list --state open --limit 200 --json number --jq 'length'
12

$ gh issue list --state open --limit 100 --json number,title,updatedAt
（12件、number: 193,180,171,159,157,156,138,134,121,93,91,41）
```

各issueの`updatedAt`と本ADR作成時刻（2026-08-24T16:10:51+09:00 相当）との
差分を算出したところ、**最も更新が古いもの（#91・#93、2026-08-07更新）でも
16日前**であり、**30日以上更新の無いissueは0件**だった（12件全件が30日以内に
更新されている）。

**トリアージ対象の母数が自動化に見合うか**: 見合わない。計画書のnightly-
triageは「30日以上更新のないIssue」「依存関係でブロックされているIssue」
「次の1週間で着手すべき上位3件」を毎日集計する設計だが、対象となる停滞
Issueが現状0件であり、母集団（open 12件）自体も1人で日次把握するのに十分
小さい規模である。自動化しても「該当なし」を報告するだけの実行が続く
可能性が高く、計画書0節の条件1（週1回以上の繰り返し作業）は形式的には
「毎日」なので満たすが、**産出される情報量が自動化コストに見合わない**。

## GUI確認が必要な項目（APIでは判定を完結できなかった項目）

以下は、5-3・5-4を**現時点で見送る**という結論そのものには影響しないが、
将来この決定を見直す際の判断材料として、GUI目視での確認をユーザに依頼する。

1. Settings → Actions → General → Workflow permissions の現在の表示。
   `default_workflow_permissions: read`をwriteへ変更する操作自体が
   GitHub Free + privateリポジトリで実際に許可されるか（グレーアウトされて
   いないか）。API実測では403のような明示的な課金プラン起因のブロックは
   確認できなかったが、変更操作そのものは試みていない。
2. 同画面の「Allow GitHub Actions to create and approve pull requests」
   チェックボックスの現在の状態とグレーアウトの有無
   （`can_approve_pull_request_reviews: false`との対応関係の視覚的確認）。
3. Settings → Code security → Dependabot の
   「Dependabot version updates」トグルの現在値
   （`.github/dependabot.yml`が存在しないことは確認済みだが、GUIトグル自体の
   状態は未確認）。

## 決定

### 決定1: Phase 5-3（依存更新ループ）は現時点で見送る

**理由（複合）**:

1. 着手にはADR-004が既に記録した壁（ブランチ保護不可、
   `can_approve_pull_request_reviews: false`、`default_workflow_permissions:
   read`）を越える必要があり、これは新たな壁ではなくADR-004決定2の
   「Step 2」そのものである。
2. 仮に壁が解消されたとしても、本プロジェクトの依存更新頻度（32日間で
   バージョンbump0件）は計画書0節の条件1（週1回以上の繰り返し作業）を
   満たさない。ループ化の前提条件そのものが成立していない。

**見直し条件**（次のいずれかが起きたら再検討する）:

- ADR-004の壁が解消される（GitHub Proへの移行、リポジトリのpublic化、または
  GitHubが private + Free でもブランチ保護 / PR自動作成を許可するようになる
  等）
- 依存パッケージのバージョン更新が実際に必要になる頻度が上がる
  （目安: 直近1か月で複数回のバージョンbumpが発生する）
- Dependabotのアラートが実際に有効化され、対応すべき指摘が継続的に出るように
  なる

### 決定2: Phase 5-4（夜間トリアージ）は現時点で見送る

**理由**: 5-3とは異なり、`issues: write`の権限面での壁は5-3ほど強くない
可能性が高い（`contents: write`を要求せず、既存の`claude-review.yml`と
同型の権限宣言で機能すると推測される。ただし未実測）。**見送りの主因は
権限ではなく対象母数である**: open issue 12件のうち30日以上更新の無いものが
0件であり、トリアージが検出すべき「停滞」自体が現状存在しない。

**見直し条件**（次のいずれかが起きたら再検討する）:

- open issueの件数が増加し、日次で人手把握するのが負担になる規模
  （目安: open issueが30件を超える、または一人で見渡すのに5分以上かかる）
  になる
- 30日以上更新の無いissueが実際に発生し始める
- `issues: write`によるActions経由のissue作成が実測で機能することを、
  別の小さな検証（本ADRの範囲外）で確認できる

## 却下した案

### 1. Dependabotをまず導入し、その運用実績を見てから5-3の要否を再判断する

却下。1-cの実測が示す通り、本プロジェクトは32日間で依存のバージョン更新が
0件であり、Dependabotを導入しても検知対象がほぼ発生しない可能性が高い。
導入自体のコストは低いが、「導入してから様子を見る」ために着手すると、
計画書0節の条件1（繰り返し作業であること）を確認する前に自動化基盤を
先に作ることになり、本計画が一貫して採ってきた「VERIFY Gateを先に、
自動化は後に」という優先順位（Phase 0の方針）に反する。

### 2. Phase 5-4だけを先に着手する（5-3とは独立に、権限面の壁が無いため）

却下。1-dで検証した通り、5-4の権限面の壁は5-3ほど強くない可能性があるが、
**対象母数（停滞issue 0件）が自動化を正当化しない**。権限が取得できることと、
自動化する価値があることは別の問題であり、後者が満たされていない以上、
先行着手の理由にならない。

### 3. 5-3・5-4を一括で「ADR-004と同一理由により見送り」と記述する

却下。指示自体が要求する通り、5-3と5-4はブロッカーの性質が異なる
（5-3は権限面の壁、5-4は主に母数の問題）。一括記述すると、5-4の
見直し条件が5-3の見直し条件（GitHub Proへの移行等）に誤って従属して
しまい、実際には母数さえ増えれば5-4だけ先に着手できる可能性を
記述から消してしまう。

## 影響

計画書「Phase 5 完了条件」チェックリストのうち、本決定により満たされない
ままになる項目：

- 「依存更新ループが1週分回り、PRが読める粒度で出てきた」（5-3が未着手のため
  不成立のまま）
- 「夜間ワークフローを手動実行して成功した」（5-4が未着手のため不成立のまま）
- 「`claude-work`ラベルで Issue から draft PR が作られた」（Phase 5-5。
  本ADRの対象外だが、5-3と同一の壁を共有するため、この決定は間接的に
  5-5の着手可否にも同じ制約が及ぶことを示している）

ADR-004・ADR-008とは矛盾しない。ADR-004が記録した壁を本ADRが再確認・
参照しただけであり、supersede関係は発生しない。

## 欠点

- **「見送り」が既定化すると、壁が解消されたことに気づかないリスクがある。**
  GitHub側の設定（ブランチ保護の可否、PR自動作成トグル）は本プロジェクトの
  外側の要因（GitHubのプラン変更、機能提供範囲の変更）で変わりうるが、
  本ADRの見直し条件は誰かが能動的に再確認しない限り自動的には検知されない。
- **5-4の権限面の判断が推測に依存している。** `issues: write`が
  `claude-review.yml`と同型に機能するという判断は、既存ワークフローからの
  類推であり実測ではない。将来5-4に着手する際、この推測が誤っていた場合
  （何らかの理由でissue作成もPR作成と同様の追加制約を受ける場合）、
  着手時点で新たな調査が必要になる。
- **依存が5パッケージという小規模な状態を前提にした判断である。** 依存が
  今後増えれば（例: 新しい外部ライブラリの追加）、更新頻度の実態も変わり、
  決定1の前提（週1回条件を満たさない）が崩れる可能性がある。この場合の
  再判定は、本ADRの見直し条件にある「バージョンbump頻度の上昇」で
  カバーされるが、依存が増えたこと自体を能動的に監視する仕組みは
  本プロジェクトには無い。
