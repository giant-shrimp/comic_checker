# ADR-036: AI ループを別リポジトリ ai-loop の Claude Code プラグインとして独立させる

- 日付：2026-10-07
- 状態：採用

## 背景
- ADR-034・ADR-035 で導入した AI ループ（司令塔・実装役・スキル・検証の手順）は、本リポジトリの .claude/ と scripts/ に置かれており、ほかのリポジトリでは使えない。
- 2026-10-07 の棚卸し（読み取りのみ、HEAD abf22fc）で、.claude/・scripts/・.githooks/・.github/workflows/・CLAUDE.md の37件を分類した。汎用7件、固有10件、混在20件だった。混在のファイルの主な固有箇所は、検証コマンドとゲート値、リポジトリの所有者名とリポジトリ名、作品名の走査、失敗記録・棚卸し文書・ADR のパス、判定ロジックのパス、Xvfb などの環境の前提である。
- 公式ドキュメント（plugins-reference・plugins/components・settings-reference、2026-10-07 に確認）による制約は次のとおり。プラグインの settings.json で効くキーは agent と subagentStatusLine だけで、permissions（deny・ask・allow）は含められない。userConfig の値の保存先（pluginConfigs）はユーザ設定か管理設定だけで、リポジトリごとには持てない。enabledPlugins と extraKnownMarketplaces はプロジェクトの .claude/settings.json に書ける。プラグインのエージェントでは permissionMode・hooks・mcpServers が無視される。bin/ の実行ファイルは Bash の PATH に載る。スキルとエージェントの名前には「プラグイン名:」が付く。
- クラウドのセッションは、ローカルで設定したプラグインを読み込まない。

## 決定
1. AI ループの汎用部分を、別リポジトリ ai-loop（非公開）の Claude Code プラグインにする。プラグイン名は ai-loop とし、スキルは /ai-loop:<スキル名>、エージェントは ai-loop:<名前> で呼ぶ。マーケットプレイスの定義も同じリポジトリに置く。公開するかは、別リポジトリでの試走の後に、中身と履歴を走査してから判断する。
2. 権限（deny・ask）はプラグインに含めず、ai-loop に .claude/settings.json の雛形を置く。各リポジトリはそれを写し、保護するパスを書き換える。フックで止める方式は今は採らない。
3. リポジトリごとの値は、各リポジトリの .claude/ai-loop.json に置き、スキルが読む。対象は、検証コマンドと合否の目印、所有者名とリポジトリ名、既定ブランチ名、追加で実行する走査器、保護するパス、失敗記録・ADR・試走の記録の場所などである。
4. 汎用のスクリプト（check_no_personal_info.py・check_review_comment.sh・select_review_comment.sh・setup_hooks.sh）は、プラグインの bin/ に置く。
5. プラグインは各リポジトリのプロジェクトの範囲で有効にする（.claude/settings.json の enabledPlugins と extraKnownMarketplaces）。本リポジトリでは settings.json が deny 対象なので、ユーザが GitHub の Web で編集する。
6. ai-loop には、作品名と個人情報の走査器を通したコミットだけを積む。
7. 当面はローカル版の Claude Code だけを対象とし、クラウド版は考えない。
8. ADR-034 の決定（工程の分担・人が行う作業・合否の根拠）は変えない。ADR-035 の ask による承認は、本リポジトリの .claude/skills/ と .claude/agents/ に対するもので、プラグインに移したスキルとエージェントには及ばない。プラグインの中身は ai-loop リポジトリで変更し、ai-loop にも決定2の雛形を置いて ask で守る。

## 実装の順序（それぞれ別の Issue とする）
1. ユーザが GitHub の Web で ai-loop（非公開）を作る。
2. 汎用のファイルと、混在のファイルの固有の値を設定に移した版を、ai-loop に置く。
3. 本リポジトリに .claude/ai-loop.json を置き、プラグインの利用に切り替える。移したファイルを本リポジトリから消すかは、切り替えの後に「迷ったら残す」で判断する。
4. 別のリポジトリ1つで試走する。

## 未決定
- 非公開リポジトリのマーケットプレイスを、手元の git の認証で追加・更新できるか（未確認）。
- 混在のファイルごとの、汎用部分と固有部分の境界（移す Issue で決める）。
- .claude/ai-loop.json の項目と形式の詳細（移す Issue で決める）。
- インストール済みのプラグインの複製（ユーザ設定の配下に置かれる）を、Claude Code が書き換えないように守る方法。
- プラグインのエージェントの skills 欄に書いたスキル名が、接頭辞なしで解決されるか（公式ドキュメントに記載がない。移す Issue で、移す前に実機で確かめる）。

## 追記（2026-10-07：移設の完了と未決定の解決）
- 移設：ai-loop に、スキル7件（report-self-check・replace-doc-range・publish-github・pre-push-check・post-merge-cleanup・diagnose-failure・commander）、エージェント3件（investigator・auditor・implementer）、bin/ のスクリプト3本（check_no_personal_info.py・check_review_comment.sh・select_review_comment.sh）を置いた。プラグインの version は 0.4.1 である。setup_hooks.sh は deny 対象で写せないため、bin/ に置くかは保留する。
- 非公開リポジトリのマーケットプレイスは、手元の git（SSH）の認証で追加・更新できた（claude plugin marketplace update と claude plugin update の後、/reload-plugins で反映）。
- プラグインのエージェントの skills 欄に書いたスキル名は、接頭辞なしで解決された（移す前に実機で確認した）。
- .claude/ai-loop.json の項目と形式は、ai-loop の docs/config.md に定めた。本リポジトリの値は .claude/ai-loop.json に置く。
- 汎用部分と固有部分の境界は、各スキル・エージェントが固有の値を .claude/ai-loop.json から読む形にすることで決めた。diagnose-failure は、検証の失敗の分類を「テストの失敗」と「その他」の2つに簡素化した。
- 判定ロジックの事前登録と holdout2 の扱いは本リポジトリに固有なので、プラグインの commander・implementer からは外し、CLAUDE.md の「判定ロジックの変更と holdout2」節に置く。プラグイン側は、使う側のリポジトリの CLAUDE.md の定めに従うとだけ書く。
- インストール済みのプラグインの複製を守る方法は、未決定のまま残す。
- 決定5の有効化（.claude/settings.json の編集）は、別の Issue で行う。

## 追記（2026-10-08：試走の完了と反映）
- 決定5の有効化は PR #505 で行った（ユーザが GitHub の Web で .claude/settings.json を編集した）。
- 順序4の試走を別のリポジトリ1つ（非公開）で行い、完了した。司令塔（/ai-loop:commander）と実装役（ai-loop:implementer）で Issue から PR までを一度で通した。試走の記録はそのリポジトリの records.trials に置いた。
- 試走で得た気づき24件のうち、手順の改善に当たるものを ai-loop の PR #7〜#11 で反映した。報告の自己点検の書式と下書きの分け方（#7）、マージ後の後始末の番号の抽出（#8）、push 前の検証の再実行の条件（#9）、司令塔の照合の方法と CI がないリポジトリの扱い（#10）、設定の説明と README（#11）である。反映後のプラグインの version は 0.4.6 である。
- 試走したリポジトリと ai-loop の Contributors に AI 由来のアカウントは入らなかった。帰属は settings.json の attribution と照合で守った。
- 決定1の公開の判断と、本リポジトリの運用の切り替え（元のスキル・エージェントの扱いを含む）は、別の Issue で行う。

## 追記（2026-10-08：運用の切り替え・段階1）
- 本リポジトリの司令塔は /ai-loop:commander、実装役は ai-loop:implementer を使う。CLAUDE.md の該当の記述を改めた。
- 報告の自己点検は /ai-loop:report-self-check、push 前の確認は /ai-loop:pre-push-check を使う。
- .claude/skills と .claude/agents の元の複製は、プラグイン版で本リポジトリの Issue を1件通すまで残す。複製はプラグインより古い版なので、呼び出しには必ず ai-loop: を付ける。
- 元の複製の削除は段階2として別の Issue で行う。scripts/check_title_leak.py の説明文が元の複製を指す記述（deny 対象）も、そのとき扱う。
