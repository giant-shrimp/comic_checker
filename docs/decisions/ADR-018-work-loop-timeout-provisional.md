# ADR-018: work_loop.sh の CLAUDE_TIMEOUT 既定値は暫定のまま維持する

- 日付：2026-09-05
- 状態：採用

## 背景

Issue #261（`CLAUDE_TIMEOUT`の既定値が4スクリプトで不一致）のうち、PR #265は
`review_loop.sh`が子スクリプト（`review_proposer.sh`・`review_audit.sh`）へ
`CLAUDE_TIMEOUT`をexportしていなかった伝播問題を解消した（Refs #261）。
残件として、`scripts/work_loop.sh:43`の既定値600秒（他3スクリプトは
300／300／900）をどう扱うかが残っていた。

## 測定

- 600秒の由来は`git log -S 'CLAUDE_TIMEOUT' --oneline -- scripts/work_loop.sh`
  で特定したコミット`6d7ef64`（2026-07-24）。コミットメッセージ・diffの
  いずれにも実測への言及はなく、コード上のコメントは「claude呼び出し自体が
  ハングした場合の保険（秒）」のみ（`git show 6d7ef64 -- scripts/work_loop.sh`
  で確認）。
- work_loop.sh単独の実行アーカイブは`ls logs/run_*.json | wc -l`で1件のみと
  確認。その`duration_ms`は`jq '.duration_ms' logs/run_1.json`で153169
  （約153秒）、`terminal_reason`は`jq '.terminal_reason' logs/run_1.json`で
  `max_turns`。600秒の境界に到達する前に、ターン数上限
  （`MAX_TURNS`既定20、`num_turns`は`jq '.num_turns' logs/run_1.json`で21）
  で打ち切られており、600秒という値の妥当性を検証する材料にはならない。
- `grep -n 'CLAUDE_TIMEOUT' scripts/loop_git.sh scripts/verify.sh`はいずれも
  0件。work_loop.shが呼ぶ子スクリプトは`loop_git.sh`・`verify.sh`のみ
  （`grep -n '\./scripts/' scripts/work_loop.sh`で確認）で、どちらも
  `CLAUDE_TIMEOUT`を使わない。work_loop.shが起動する`claude`はバイナリ
  呼び出しであり、シェルスクリプトの子への再継承という構造自体が無いため、
  `review_loop.sh`で生じたのと同種の伝播問題はwork_loop.shには存在しない。

## 決定

1. **`scripts/work_loop.sh`のCLAUDE_TIMEOUT既定値600秒は変更しない。**
2. **同スクリプトへのコメント追記も行わない。** 暫定値である旨の記録は
   本ADRに置く。
3. Issue #261はPR #265（review_loop.shの伝播解消）と本ADR（work_loop.shの
   残件記録）をもって解決とする。

## 検討した案と棄却理由

- **work_loop.sh:43にコメントを直接追記する**: 棄却。同ファイルは
  `.claude/settings.json`で`Edit`/`Write`がdeny対象になっている
  （`grep -n 'work_loop' .claude/settings.json`で確認、該当は
  `Edit(scripts/work_loop.sh)`・`Write(scripts/work_loop.sh)`の2行）。
  設定ファイル冒頭の`_note_deny_scope`は「work_loop.sh経由では
  `--allowedTools`に任意Bashが無いため実害はなく、対話セッションでは
  許可プロンプトが出るので人間が気づける。したがってdenyは最終防御では
  なく、その手前の速度制限として位置づける」と説明しているが、これは
  Issue #14の教訓（採点者・ガードレール自体をAIが書き換える事故）を
  踏まえた意図的な保護である。シェル経由での回避やユーザへの代理実行
  依頼は、この保護の趣旨に反するため行わない。
- **既定値を他3スクリプトに合わせて変更する**: 棄却。実測アーカイブが
  1件（153秒、タイムアウト非到達）のみでは、600秒を300秒や900秒に
  変更する根拠にならない。

## 決定の理由

- 実測で得られている最大所要時間は153秒であり、600秒はこれに対し
  十分な余裕を持つ「保険」として機能する範囲にある
- 値を変更するに足る実測データが無い以上、暫定値のまま維持し、
  その事実だけを記録することが最も正直な扱いである
- 記録先をコード内コメントではなくADRとすることで、ガードレール
  ファイル自体には触れずに同じ目的（暫定値であることの明記）を
  達成できる

## 帰結

- `scripts/work_loop.sh`は本PRで無変更のまま維持される
- 将来、実測に基づく既定値の調整を行う場合は、work_loop.shの実運用
  ログ（`logs/run_N.json`）の蓄積が前提条件となる。現状は1件のみで、
  かつその1件はタイムアウト境界に到達していないため、複数回・かつ
  タイムアウトに近い所要時間を含む実行データが必要
- 4スクリプト間の既定値不一致（300／300／600／900）自体は本ADRでは
  解消しない。解消する場合は改めて検討する

## 関連

- Refs #261
- Refs #265（review_loop.shのexport方式によるCLAUDE_TIMEOUT伝播修正）
