# アーキテクチャ

モジュール別の設計詳細。`CLAUDE.md` から移動（Issue #18）。必要なときだけ読むこと。

## Architecture

Modules under `comic_checker/`, each with one job:

- **`wikipedia_client.py`** — the default, first-tried information source. No bot
  protection to work around, so it's a thin `requests`-based wrapper around the MediaWiki
  action API (`ja.wikipedia.org/w/api.php`), not a browser.
  - `judge(title)` is the public entry point. It calls `_pick_article(title)` to resolve
    a page, then `_judge_extract(extract)` to classify the lead text, and returns a
    `WikipediaJudgment(query, status, matched_title, url, evidence)`. `status` is one of
    `完結` / `連載中` / `判定不能` / `記事なし` (article not found).
  - **Title variants (M6-E-1, Issue #30)**: the Excel input is a hand-written shopping
    list, so it diverges from Wikipedia article names in three systematic ways, all
    observed across a real 73-row sheet. `_title_variants()` expands one input into an
    ordered, highest-confidence-first list covering them:
    1. **Character width.** Users type `私の百合はお仕事です！` / `ヤンキーＪＫクズハナちゃん`;
       Wikipedia titles those `私の百合はお仕事です!` / `ヤンキーJKクズハナちゃん`. The API's
       `titles=` parameter does *not* NFKC-normalize, so `_normalize()` (NFKC) variants must
       be probed explicitly. This alone accounted for 8 of the 48 `記事なし` rows.
    2. **Purchase notes in brackets.** `カッコウの許嫁　(特装版ない場合通常版)`,
       `触手魔術師の成り上がり（電子版のみ【最終巻】5巻が発売済）`. `_strip_annotations()`
       removes them by repeatedly deleting the innermost bracket pair — brackets nest, and
       full/half-width open and close brackets get mixed within a single pair
       (`(特装版がない場合通常版）` is real input), so one non-nesting regex pass is not enough.
    3. **Trailing edition/series notes.** `月曜日のたわわ　青版`,
       `姫騎士がクラスメート！　ＴＨＥ　ＣＯＭＩＣ`. `_strip_trailing_note()` cuts at a
       full-width space or wave dash. A bare half-width space is deliberately *not* a cut
       point — `お隣の天使様…　after the rain` shows real titles containing one.
  - `_pick_article()` runs two tiers: `_pick_via_direct_lookup()` then `_pick_via_search()`.
    - **Direct lookup** probes `"{variant} (漫画)"` for every variant, then every variant
      bare, and resolves them all in **one** `action=query&titles=A|B|…&redirects=1` call.
      Batching is what makes the variant expansion affordable: probes are checked for
      existence in a single lightweight call (no `prop=`, so response size barely grows
      with variant count), and only the one winning page then costs a second call for its
      extract. Typical cost is 2 API calls per row — the same order as the pre-M6-E-1
      single-probe flow. `_resolve_titles()` walks the response's `normalized` and
      `redirects` chains to map each requested string back to a real page title, which is
      also how editor-curated redirects (`彼女、人見知ります` → `彼女、お借りします`,
      `こち亀` → `こちら葛飾区亀有公園前派出所`) get followed.
    - **Search** (`list=search`) only runs when direct lookup found nothing. It scans **all**
      hits, not just the top one: real data had `釣って食べたいギャル澤さん`'s own article
      sitting at rank 3 behind an unrelated `ギャル`, so a top-hit-only rule dropped an
      exact match that existed. Candidates already probed by the direct-lookup tier are
      skipped (their status is settled). Queries are capped at `MAX_SEARCH_QUERIES` (2);
      NFKC-only variants are not re-queried because Wikipedia's full-text search already
      folds character width itself.
  - **Match-confidence check (M6-A-1, Issue #9; extended in M6-E-1)**: a
    `"{variant} (漫画)"` hit is always trusted unconditionally — whether it resolves via an
    exact page or via a Wikipedia redirect, that's editors' own curated disambiguation
    convention, not a guess. Everything else must clear two bars:
    - **Name backing.** A search candidate is accepted only if it equals a variant (or
      `"{variant} (漫画)"`) after NFKC normalization, or if `_subtitle_prefix_match()` says
      it's a variant followed by a `SUBTITLE_SEPARATORS` character and a subtitle (users
      write the main title only; Wikipedia often titles the article with the subtitle
      attached). Requiring the separator is what keeps `ギャルせん` from matching
      `ギャル文字`. Redirect backing is no longer re-checked here — the direct-lookup tier
      already resolved redirects for every variant.
    - **Topic backing (`_is_about_manga()`).** Any article accepted outside the `(漫画)`
      path must mention one of `ARTICLE_RELEVANCE_MARKERS` in its lead. This is what
      replaces the old "never look up the bare title at all" rule: probing bare titles is
      what recovers articles like `真夜中ハートチューン` (exists at its exact name, but
      Wikipedia's search ranks it off the list entirely), and the marker check is what
      still keeps bare `ワンピース` — an article about *clothing* — from being answered
      confidently.
    If neither bar is cleared, `_pick_article()` returns `None` (→ `記事なし`) rather than
    risk a confident wrong answer — same "fail closed" philosophy as the
    `COMPLETED_WEAK_RE` veto in Issue #8.
    Do **not** replace this with fuzzy string similarity (edit distance, normalized
    substring, etc.) as the primary mechanism — it was tried in design discussion and
    rejected: `ワンピース`→`ONE PIECE`, `ハンターハンター`→`HUNTER×HUNTER`, and
    `幽遊白書`→`幽☆遊☆白書` are near-zero string similarity by any generic measure (katakana
    reading vs. English title, abbreviation vs. full title with decorative symbols) and
    would all be rejected by a naive similarity threshold, while genuinely being correct
    matches — verified empirically that all three (plus `こち亀`→`こちら葛飾区亀有公園前
    派出所`, found during M6-D-1) resolve via a real Wikipedia redirect from the exact query
    string, which is a strictly stronger and more precise signal than any string-distance
    heuristic. If a future case needs *neither* an exact match *nor* a query-redirect and
    still needs accepting, that's a sign the risk calculus needs revisiting, not a reason to
    quietly loosen this check.
  - `_judge_extract()` splits the lead text into sentences on `。` and applies regexes per
    sentence: `ONGOING_RE` (`連載中` / `連載されている`, present tense) vs completion, which
    is itself split into two tiers, not one flat regex:
    - `COMPLETED_STRONG_RE` (`完結(した)?`) is trusted unconditionally — in Japanese this
      essentially only means "the work itself concluded."
    - `COMPLETED_WEAK_RE` (`連載(が|を)?終了(した)?` / `連載された` / `まで連載(された)?` /
      `打ち切(り|られ)`) is *not* trusted unconditionally: it's vetoed by
      `CONTINUATION_VETO_RE` (`継続` / `再開` / `引き続き` / `連載を?続け` / `掲載を?続け`)
      appearing in the same sentence. `打ち切り` (M6-B-1, Issue #10) is deliberately mapped
      to the same `完結` status as a natural ending, per explicit product decision — users
      care whether more is coming, not whether the ending was amicable — with no new status
      value added; the `打ち切り` nuance survives only via the matched sentence landing in
      the `判定根拠` column verbatim. It's in the weak tier for the same reason as
      `連載終了`: articles frequently narrate a *survived* cancellation threat ("打ち切りの
      危機に瀕したが連載は継続した", "打ち切りが検討された") that must not be misread as
      an actual ending.
      **Caveat, flagged deliberately (Issue #10)**: the regression test for this survived-
      threat case (`test_near_cancellation_that_was_avoided_is_not_completed`) uses a
      *synthetic* fixture, not a real Wikipedia excerpt — a real example of "打ち切りを
      回避した" phrasing wasn't found despite searching. The test passing only proves the
      veto mechanism works for vocabulary already in `CONTINUATION_VETO_RE`; it says
      nothing about whether real articles actually phrase a survived-cancellation the same
      way. This distinction matters concretely: HUNTER×HUNTER's false-完結 bug (Issue #8)
      existed specifically *because* the real phrasing ("週刊連載ではない掲載形態での
      継続") happened to use vocabulary the veto already covered, and the discovery process
      was "read a real article," not "trust that the synthetic test's wording generalizes."
      If you find a real "打ち切りを回避した"-shaped article and its phrasing *isn't*
      caught by the current veto list, that's a real bug to fix (same fail-closed
      response as always) — the synthetic test passing is not evidence that this scenario
      is actually covered in practice, only that the mechanism is wired correctly for the
      words already in the list.
      This exists because of a real production false-positive: HUNTER×HUNTER's article
      says "…週刊連載を終了し…「週刊連載ではない掲載形態での継続」を発表した" — ending
      *weekly-cadence* serialization while explicitly continuing in another format, which
      `連載(を)?終了` alone can't distinguish from the series actually ending. Do not
      merge these two tiers back into one regex — `tests/test_wikipedia_client.py`'s
      HUNTER×HUNTER case is a direct regression test for this, and its 幽☆遊★白書
      companion test guards against over-correcting (a legitimate `連載された`-based
      completion with no continuation language nearby must still resolve to `完結`, not
      get swept into caution by a blanket veto). This tiering is also the general answer
      if a similar false-`完結` shows up elsewhere: prefer moving the risky pattern into
      the vetoed weak tier (or adding a narrower veto) over loosening/removing it outright
      — a wrongly-`完結` row is worse than a `判定不能` row, so bias new fixes the same
      way. This split matters concretely for tense too: 「アオのハコ」's lead says "…まで
      連載された" (past tense, completed) — a naive `連載` substring check would misread
      that as ongoing.
    - **Cross-sentence continuation veto (M6-B-3, Issue #30)**: `CONTINUATION_VETO_RE`
      only looks *within* one sentence, which left the same false-`完結` class as #8 alive
      across a sentence boundary. Magazine transfers are routinely written as two
      sentences — 「『月刊A』にて…2023年11月号まで連載。その後『週刊B』に移籍し、
      2023年23号から連載されている。」 — and `_judge_extract()` returns on the first
      decisive sentence, so it answered `完結` before ever reading the second. Two real
      rows hit this (`一緒に暮らしていいですか?` answered a confident wrong `完結`;
      `サタノファニ` had its own ambiguous sentence skipped and then picked up a
      *different work*'s 連載終了 sentence from the 概要 section — a subject
      `SPINOFF_MARKERS` cannot catch, since 『DEATHTOPIA』 is neither 番外編 nor 外伝).
      The fix: `_has_ongoing_signal()` scans the whole range once up front, and a
      weak-tier completion in a sentence that itself has no ongoing signal is discarded
      when one exists elsewhere in range. Scope discipline is the same as ever — the veto
      applies to the weak tier only, so 「本編は完結した。スピンオフは連載中。」 still
      resolves to `完結`.
    - **The same veto gates the infobox fallback.** `_judge_via_infobox()` reads "終了系
      field is non-empty ⇒ 完結", which does not hold for transferred works:
      サタノファニ's `終了日` is `2023年34号<br />[[ヤンマガWeb]]：2023年9月6日 -`, where
      the trailing `-` means the new run is still going. So `judge()` refuses an
      infobox-sourced `完結` whenever the prose has an ongoing signal, and stays
      `判定不能`. The opposite direction (infobox says ongoing) is not gated — it agrees
      with the prose rather than contradicting it. Without this gate the text-level fix
      alone does not change サタノファニ's answer; verified end-to-end, not just on
      `_judge_extract()`.
    - **Guideline for adding any new completion pattern**: default it to the vetoed weak
      tier, not the strong tier. Only put a pattern in `COMPLETED_STRONG_RE` if you can't
      construct a plausible sentence where it's true but the work isn't actually over
      (that's the bar `完結` clears and `連載終了` doesn't). The veto is intentionally
      scoped to the weak tier only — it never suppresses `COMPLETED_STRONG_RE` — so a
      sentence like "〜は完結した。アニメは継続する。" still resolves correctly even
      though it contains `継続`; only weak-tier patterns sharing a sentence with
      continuation language get suppressed. That asymmetry was checked deliberately (not
      just assumed) after this fix: grepped all 7 titles verified so far for weak/strong
      completion patterns co-occurring with `CONTINUATION_VETO_RE` in the same sentence —
      HUNTER×HUNTER's is the only hit, and it's the correct one. If a future title turns
      up a real "weak signal + unrelated continuation language" false-判定不能 (the
      inverse failure — safe but annoying), the fix is a narrower veto condition (e.g.
      requiring the continuation word be about the same subject), not widening the veto's
      scope to the strong tier — that direction trades a rare annoyance for reintroducing
      the dangerous failure mode this fix exists to prevent.
    - **Deliberately NOT vetoed: 「元の連載終了後、不定期に新作が作られ続けている」**
      (こち亀 / *Kochikame*, investigated under M6-D-1, Issue #11). Its lead says "…2016
      年42号まで連載され、その後も約年1回のペースで新作が作られている。" — matches
      `COMPLETED_WEAK_RE` via `まで連載`, and superficially resembles the HUNTER×HUNTER
      shape (weekly run ended, something continues afterward). It was *not* added to
      `CONTINUATION_VETO_RE` — explicit judgment call, not an oversight. The distinction:
      HUNTER×HUNTER's `継続` describes the *same ongoing story* continuing in a different
      publication cadence (the work was never finished); こち亀's weekly serialization
      genuinely concluded as a complete story, and what continues afterward is occasional
      new one-off/anniversary content, not a continuation of an unfinished narrative. 完結
      is the correct call here, and the "その後も新作が作られている" nuance is preserved
      for the user via the `判定根拠` column rather than by changing the status. The
      rejected alternative (vetoing on generic words like `その後も`/`新作`) was judged too
      broad: it would misfire on genuinely-completed works that merely got one anniversary
      one-shot years later. If this exact shape ("元の連載は完結したが、不定期に新作が
      作られ続けている") turns up again on another title, apply this same reasoning rather
      than reopening the veto-list question from scratch — the answer isn't "add a keyword
      veto for it," it's "leave it as `完結`, since the underlying story concluded."
  - **Mediamix disambiguation** (the reason this isn't just "find a status word"): if the
    lead text mentions `小説` or `ライトノベル` anywhere, the article is treated as
    covering a franchise where the manga's status could differ from the original novel's
    (「転生したらスライムだった件」is the motivating case — light novel completed, manga
    ongoing). In that case, only a status-bearing sentence that also contains a manga
    marker (`漫画`/`コミカライズ`/`コミック版`/`漫画版`) and *not* a novel marker is
    adopted; novel-only or ambiguous sentences are skipped in favor of continuing to scan.
    If no adoptable sentence is found, the result is `判定不能` rather than a guess — this
    is a deliberate keyword-level heuristic, not real subject parsing, so it's tuned to
    fail closed (判定不能) rather than risk a wrong answer. If the article never mentions
    `小説`/`ライトノベル` at all, there's no competing media to disambiguate against, so
    the first status-bearing sentence found is trusted directly.
  - **Infobox supplementary judgment (Issue #12)**: when `_judge_extract()` returns
    `判定不能`, `judge()` makes one more attempt via `{{Infobox animanga/Manga}}` raw
    wikitext (`action=parse&prop=wikitext`, fetched by `_fetch_wikitext()` for the
    already-resolved `matched_title` — no separate title resolution). This is
    supplementary only: it's never consulted when the text path already resolved
    `完結`/`連載中`, and never for `記事なし`. The motivating gap: 「転生したらスライム
    だった件」has no sentence in its lead+first-section that states the *main manga's*
    own serialization status at all (verified: zero matches for 連載中/完結 language
    about the main work in the full ~140KB article — see the `_fetch_extract()` bullet
    above), so text analysis alone is structurally unable to resolve it, no matter how
    the regexes are tuned.
    - **Main-block identification is the dangerous part, not the field-reading.** A
      mediamix article can contain multiple independent `{{Infobox animanga/Manga}}`
      blocks — one per work (main series + each spinoff/one-shot). Picking the wrong
      block and reading its `終了号`/`終了日` is structurally the same risk shape as the
      HUNTER×HUNTER bug (Issue #8): a *confident* wrong answer, and specifically the
      dangerous direction (an ongoing main series read as completed via a finished
      spinoff's block). Verified empirically across 3 independent real franchises before
      implementing (転生したらスライムだった件・呪術廻戦・NARUTO -ナルト-, 11 infobox
      blocks total): the main work's block never has an explicit `タイトル` field (it's
      implicit — same as the article's own title), while every spinoff block does.
      `_find_main_manga_block()` uses this as the sole signal, and — same fail-closed
      posture as Issue #8/#9 — only trusts it when it's unambiguous: exactly one
      title-less block among all `{{Infobox animanga/Manga}}` blocks in the article. Zero
      or two-or-more title-less blocks means "can't tell", and the function returns
      `None` rather than guessing; `judge()` leaves the result at `判定不能` in that case,
      never falls back to a different block.
    - **Field-name variation**: `終了号`/`終了日`/`終了` (`END_FIELD_NAMES`) are checked in
      that order for a non-empty value → `完結`; all present-but-empty (or entirely
      absent, provided *some* end-field key exists on the block) → `連載中`. Only
      `終了号`/`終了日` are backed by real examples (HUNTER×HUNTER, こち亀); `終了` was
      added defensively for naming variance seen even within the 3-title sample and has
      not itself been observed populated in a real article — this asymmetry is called out
      in the source comment deliberately, same spirit as the Issue #10 synthetic-test
      caveat (a passing check for an untested-in-the-wild code path isn't proof the
      real-world shape is covered). If *none* of `END_FIELD_NAMES` exists on the
      identified main block at all (a schema unlike anything in the verified sample),
      `_judge_via_infobox()` also returns `(None, None)` rather than defaulting to
      `連載中` from ignorance — treating "no end-field concept present" the same as "can't
      tell", not as "must mean ongoing".
    - **Regex pitfall hit during implementation, worth remembering**: `_infobox_field()`'s
      first version used `\s*` around `=` to skip whitespace — but `\s` matches `\n` too,
      so on a field with an *empty* value immediately followed by a newline (e.g.
      `|終了号 = \n|終了日 = \n`), the trailing `\s*` before the capture group silently
      consumed the newline and jumped onto the *next* field's line, returning that line's
      text as if it were the first field's value. A synthetic-fixture unit test (not
      live-API-dependent — this is exactly the kind of bug that's cheap to catch with a
      pure-function test on hand-built wikitext) caught this immediately. Fixed by using
      `[ \t]*` (explicitly excludes `\n`) for all intra-line whitespace in both
      `_infobox_field()` and `_infobox_has_field()`, keeping `^`/`\$` (with
      `re.MULTILINE`) as the only place line boundaries are meant to matter. If you touch
      these regexes again, keep that distinction — same-line-only whitespace is `[ \t]*`,
      not `\s*`, in this file's infobox-parsing code.
    - **Brace balancing, not template-name string matching**: `{{Infobox animanga/Manga
      ...}}` blocks can contain nested templates in field values (e.g.
      `{{small|...}}`). `_extract_braced_blocks()` locates each `{{Infobox
      animanga/Manga` occurrence and then counts `{`/`}` one character at a time back to
      depth 0, rather than matching a fixed-shape `{{...}}` pattern, specifically so a
      nested template inside a field doesn't truncate the block early.
  - Fully offline-testable: `tests/test_wikipedia_client.py` mocks `requests.get`
    (mirrors how `test_manba_client.py` mocks `sync_playwright`) and fixes the 5
    feasibility-check titles as regression fixtures, including an explicit assertion that
    「転生したらスライムだった件」resolves to `連載中` (the manga's status), not the
    light novel's `完結`. Issue #12's infobox path adds its own two-layer test structure
    mirroring the text-judgment tests: `_judge_via_infobox()` and
    `_extract_braced_blocks()` are tested directly on hand-built wikitext (no network
    mocking, same rationale as testing `_judge_extract()` directly on extract text), and
    a handful of `judge()`-level tests mock `requests.get` to confirm the *integration*
    contract — notably that the infobox path adds zero extra API calls when the text
    path already resolved a status, and that an `action=parse` error response degrades
    to `判定不能` (not an exception) rather than crashing the row.

- **`manba_client.py`** — `ManbaClient`, a context-managed Playwright wrapper. Only
  reached when `main.py`'s `run()` is called with `fallback_to_manba=True` and a row's
  Wikipedia judgment came back `判定不能` or `記事なし`. This is the part that matters
  most to understand before touching anything network-related:
  - manba.co.jp sits behind Cloudflare bot protection, so plain `requests` calls get
    blocked; everything goes through a real (headless-by-default) Chromium page.
  - `search()` calls the site's own public Meilisearch endpoint
    (`search.manba.co.jp/multi-search`, index `Board_production`) via
    `page.evaluate(fetch(...))` from inside the already-challenge-passed browser context
    — this is the same request the site's own autocomplete box makes. This fetch is only
    permitted (CSP-wise, as far as observed) from the top page, so `search()` always runs
    against a dedicated `self._search_page` that is opened once in `__enter__` and pinned
    to the top page forever — it is never navigated elsewhere. Navigating to board detail
    pages (`fetch_status()`) uses a separate `self._page` so it can't disturb the search
    page's origin/CSP state. (Added after issue: reusing one page for both caused
    `Failed to fetch` on every search after the first `fetch_status()` navigation.)
  - `fetch_status()` determines 完結 vs 連載中 by checking whether the board page's
    `<title>` tag starts with `[完結]`. This was chosen over parsing the
    `board-label-tag` badge divs because those repeat for unrelated recommendation
    widgets elsewhere on the page and are unreliable to scope correctly; the `<title>`
    tag is a single, authoritative source.
  - `_goto_with_retry(page, url)` detects the Cloudflare challenge page (`page.title() ==
    "Just a moment..."`) and retries up to 3 times with backoff (8s/16s/24s), reloading
    (`page.goto()`) on every attempt, before giving up and returning `False`.
    `fetch_status()` treats `False` as `不明` and moves on.
  - `__enter__()` bootstraps both pages via `_bootstrap_top_page(page)`, not
    `_goto_with_retry()` directly. In headless mode it just delegates to
    `_goto_with_retry()` (nobody's there to click anything, so reload-retry is fine). In
    `--no-headless` mode it does exactly one `goto()`, then — if still challenged — hands
    off to `_wait_for_manual_challenge(page)`, which polls `page.title()` every
    `MANUAL_CHALLENGE_POLL_INTERVAL`s for up to `MANUAL_CHALLENGE_TIMEOUT`s (90s)
    *without ever reloading the page*. This split exists because `_goto_with_retry()`'s
    reload-every-attempt behavior actively destroys a human's in-progress click on an
    interactive "Verify you are human" checkbox — observed in practice: the checkbox
    challenge never has a real chance to be solved through the reload loop, since each
    retry wipes whatever the human was doing. `__enter__()` treats a `False` result (from
    either path, for either page) as fatal: it raises `RuntimeError` and tears down the
    browser/context/playwright itself (since `__exit__` is never called when `__enter__`
    raises) — see "Known limitations" below for the two challenge types this is about.
  - `_sleep()` inserts a random delay (`min_delay`–`max_delay`, default 3–6s) before
    every request — rapid sequential requests re-trigger the Cloudflare challenge even
    mid-session, so this pacing is load-bearing, not cosmetic.
  - Browser storage state (Cloudflare clearance cookies) persists to `state_path`
    (default `.manba_state.json`, gitignored) across runs, independent of Excel-level
    progress tracking.

- **`excel_io.py`** — thin openpyxl helpers: `find_column` (error if header missing),
  `ensure_column` (create at the end if missing). No I/O side effects beyond direct cell
  reads/writes; this is the only module covered by unit tests since it has no network
  dependency.

- **`main.py`** — orchestration: resolves title/status/source/evidence/matched-title/URL
  columns (by header name, not fixed index — `--matched-title-column` and `--url-column`
  now default to the source-agnostic `参照タイトル`/`参照URL`, not manba-specific names),
  builds the row worklist (skipping rows that already have a status value unless
  `--no-skip-filled`), then for each row calls `wikipedia_client.judge(title)` first via
  `_judge_row()`. A `完結`/`連載中` result is taken as-is (`判定方法=Wikipedia`). A
  `判定不能`/`記事なし` result is written through unchanged unless `--fallback-to-manba`
  is set, in which case `_judge_row()` calls `get_manba_client()` — a closure that
  lazily `__enter__()`s a single `ManbaClient` the *first* time a fallback is actually
  needed and hands back that same instance on subsequent calls, so the Cloudflare-fronted
  browser is never started at all for a run where every row resolves via Wikipedia, and
  is started at most once per run otherwise. The `ManbaClient` (if one was created) is
  torn down via `__exit__()` in a `finally` block around the row loop — deliberately not
  a `with` statement, since construction is conditional and lazy. Each row's judgment is
  wrapped in its own try/except so one failure records `エラー` for that row and moves on
  rather than aborting the run; the workbook is saved every `--save-every` rows (default
  5) plus once at the end, so an interrupted run doesn't lose prior progress.

  `from comic_checker.manba_client import ManbaClient` is **not** a top-level import —
  it lives inside `_import_manba_client()`, called from `run()` only when
  `fallback_to_manba` is true, and only once (eagerly, before the row loop, so a missing
  `playwright` install fails fast with a clear `RuntimeError` instead of surfacing as a
  generic per-row `エラー` deep in the loop). This is load-bearing for the M3 light
  PyInstaller build (`comic_checker.spec`, see `docs/build_windows.md`), which excludes
  `playwright`/`comic_checker.manba_client` from the bundle — if this import moves back to
  module level, the light build stops starting up at all (crashes on `import
  comic_checker.main`) even for users who never touch `--fallback-to-manba`, not just
  loses the fallback feature. Confirmed empirically: PyInstaller's own dependency-graph
  warnings log the exclusion as `excluded module named comic_checker.manba_client -
  imported by comic_checker.main (delayed, optional)` — "delayed" is exactly what depends
  on this import staying inside a function. `tests/test_main_run.py` patches
  `comic_checker.manba_client.ManbaClient` (the source module), not
  `comic_checker.main.ManbaClient` — there's no such module-level attribute anymore.
