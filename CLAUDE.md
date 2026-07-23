# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A CLI tool that reads a list of manga titles from an Excel file, looks each one up
(primarily on Japanese Wikipedia, falling back to manba.co.jp only when opted in), and
writes back whether the series is completed (完結) or ongoing (連載中). Japanese is the
working language for user-facing strings (README, CLI help, column headers, status
values) — keep new strings consistent with that.

**Pivot history**: this was originally manba.co.jp-only (see git history / Issue #3).
manba.co.jp sits behind a Cloudflare interactive "Verify you are human" challenge that
kept reappearing even with a real human clicking it in `--no-headless` mode — strong
evidence Cloudflare was fingerprinting the Playwright automation itself, not just request
frequency. Rather than reach for stealth/evasion tooling (against the spirit of the
site's bot protections), the design was changed to make Wikipedia's MediaWiki API — which
has no bot protection — the default information source, with manba.co.jp demoted to an
explicit opt-in fallback (`--fallback-to-manba`) for rows Wikipedia can't judge. See
`manba_client.py`'s section below and "Known limitations" for what's still true about the
Cloudflare situation when the fallback path is used.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # includes pytest; use requirements.txt for runtime-only
playwright install chromium
```

Chromium needs OS shared libraries (`libnspr4`, `libnss3`, `libatk1.0-0`, etc.) that are
not installed by pip. Check what's missing without changing the system:

```bash
playwright install-deps --dry-run chromium
```

Installing them (`sudo playwright install-deps chromium`) is a system change — don't run
it without the user's go-ahead.

The search API also requires a key exported as `MANBA_SEARCH_API_KEY` (see README.md
§4 for how to obtain it from the browser's Network tab — it is manba.co.jp's own public
frontend search key, not a secret, but it isn't hardcoded and isn't recorded in this repo).
`ManbaClient` raises `RuntimeError` at construction time if the env var is unset. This is
only needed for `--fallback-to-manba` runs — the default Wikipedia-only path needs
neither Playwright/Chromium nor this env var at all.

## Commands

```bash
python -m pytest                              # run tests
python -m pytest tests/test_excel_io.py -q    # run a single test file
python -m comic_checker.main path/to/file.xlsx           # run the tool
python -m comic_checker.main path/to/file.xlsx --no-headless   # with a visible browser (debugging)
python -m comic_checker.main --help           # full CLI options
```

There is no lint/format tooling configured yet.

## Architecture

Modules under `comic_checker/`, each with one job:

- **`wikipedia_client.py`** — the default, first-tried information source. No bot
  protection to work around, so it's a thin `requests`-based wrapper around the MediaWiki
  action API (`ja.wikipedia.org/w/api.php`), not a browser.
  - `judge(title)` is the public entry point. It calls `_pick_article(title)` to resolve
    a page, then `_judge_extract(extract)` to classify the lead text, and returns a
    `WikipediaJudgment(query, status, matched_title, url, evidence)`. `status` is one of
    `完結` / `連載中` / `判定不能` / `記事なし` (article not found).
  - `_pick_article()` first tries the exact disambiguated title `"{title} (漫画)"`
    directly (one API call); if that page doesn't exist, it falls back to
    `list=search`, preferring a `"(漫画)"`-suffixed candidate among the results if one
    exists, else the top hit, then fetches that page's lead extract
    (`prop=extracts&exintro=true&explaintext=true`). This mirrors the "曖昧さ回避・派生
    記事の優先探索" requirement — a manga-specific article should win over a franchise or
    novel article when one exists.
  - `_judge_extract()` splits the lead text into sentences on `。` and applies two
    regexes per sentence: `ONGOING_RE` (`連載中` / `連載されている`, present tense) vs
    `COMPLETED_RE` (`完結(した)?` / `連載(が|を)?終了(した)?` / `連載された` /
    `まで連載(された)?`, past tense). This split matters concretely: 「アオのハコ」's lead
    says "…まで連載された" (past tense, completed) — a naive `連載` substring check would
    misread that as ongoing.
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
  - Fully offline-testable: `tests/test_wikipedia_client.py` mocks `requests.get`
    (mirrors how `test_manba_client.py` mocks `sync_playwright`) and fixes the 5
    feasibility-check titles as regression fixtures, including an explicit assertion that
    「転生したらスライムだった件」resolves to `連載中` (the manga's status), not the
    light novel's `完結`.

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

## Known limitations worth knowing before "fixing" something

### Wikipedia path (default)

- `_judge_extract()` is a keyword/regex heuristic over the lead text, not real NLP subject
  parsing. It's deliberately tuned to answer `判定不能` rather than guess when it can't
  tell whether a status sentence is about the manga or a same-franchise novel — treat a
  `判定不能` result as "not confident enough to say," not as a bug to silence by loosening
  the regexes. If you're tempted to relax the manga/novel marker check to reduce
  `判定不能` counts, re-run `tests/test_wikipedia_client.py`'s
  「転生したらスライムだった件」regression case first — that's the exact failure mode
  (原作小説完結 vs 漫画連載中) this heuristic exists to catch.
- Article selection only tries the `"{title} (漫画)"` disambiguated title and then the top
  `list=search` hit (preferring a `"(漫画)"`-suffixed candidate if present among results).
  It does not otherwise validate that the resolved article is actually about the title
  being searched — same class of ambiguous-title risk as manba.co.jp search below, just
  one layer removed.
- `_fetch_extract()` does **not** use `exintro=true` (verified against live Wikipedia:
  many articles' true lead paragraph is a single one-line definition sentence, with the
  actual serialization dates in the first `==` section, usually `概要` — e.g. 進撃の巨人's
  completion date lives there, not in the lead). It instead fetches the full
  `explaintext` and truncates to lead + first section only
  (`_lead_and_first_section()`, cut at the second level-2 `== heading ==`). Do not widen
  this to the whole article "to catch more cases" without re-verifying against a
  mediamix work first: scanning deeper sections picks up spin-off/side-series status
  sentences (which also contain manga markers) and can misattribute a spin-off's status
  to the main work. This was checked directly — for 転生したらスライムだった件, full-text
  regex search over the entire ~140KB article finds zero mentions of the *main* manga
  adaptation's own 連載中/完結 status; only side series (4-koma spinoffs etc.) state
  theirs. That title's main manga status is most likely only present in an infobox
  template, which `prop=extracts` strips entirely — a real data-availability gap, not an
  algorithm bug. This is exactly the `判定不能` case `--fallback-to-manba` exists for.
- `_is_novel_primary()` (the mediamix trigger) checks the work's *primary* classification
  — the `<種別>` in the lead's `"日本の<種別>"` clause — rather than whether `小説`/
  `ライトノベル` appears anywhere in the extract. This distinction is load-bearing:
  進撃の巨人's real lead sentence is "…日本の漫画、およびそれを原作としたアニメ、
  小説（ライトノベル）…" — it lists a novelization among several derivative adaptations
  of a manga-primary work, and a naive "does 小説 appear anywhere" check misfires
  `判定不能` on it. Only when the primary type itself is 小説/ライトノベル (as in
  転生したらスライムだった件's "…日本のなろう系ライトノベル。") does the mediamix
  subject-check kick in.

### manba.co.jp fallback path (`--fallback-to-manba` only)

Everything below only applies when a row falls back to manba.co.jp — it never affects a
default (Wikipedia-only) run, and it's why the fallback is opt-in rather than automatic.

- Search returns the top Meilisearch hit only — no fuzzy-match validation. Ambiguous
  titles (e.g. "ONE PIECE" matching a spin-off/reprint edition before the main series)
  are a real, observed failure mode, not hypothetical. This is why the output always
  includes the matched title and reference URL columns — they exist for manual
  verification, not just as nice-to-have metadata.
- There is no rate-limit tuning beyond `--min-delay`/`--max-delay`; if Cloudflare starts
  challenging more aggressively, widening those is the first thing to try before changing
  retry logic.
- Cloudflare presents two different challenge types, and only one of them is
  auto-solvable: the `Just a moment...` interstitial resolves itself after a few seconds
  (what `_goto_with_retry()`'s wait-and-retry loop is built for), but it can also present
  an *interactive* "Verify you are human" checkbox that requires an actual click —
  observed in practice, not hypothetical. No amount of retrying/waiting through
  `_goto_with_retry()` gets past that one — worse, its reload-every-attempt behavior
  actively wipes out a human's in-progress click, so `--no-headless` alone doesn't help
  if the bootstrap navigation is still going through that path. That's why
  `__enter__()`'s bootstrap (`_bootstrap_top_page()`) branches on `headless`: in
  `--no-headless` mode it does a single `goto()` and then polls the title for up to
  `MANUAL_CHALLENGE_TIMEOUT` (90s) without reloading, giving a real window to click. Once
  solved, the resulting Cloudflare clearance cookie gets saved to `state_path`
  (`.manba_state.json` by default) for reuse on subsequent headless runs. If this starts
  happening often, widen `--min-delay`/`--max-delay` or space runs out further apart. Note
  this bootstrap-time handling doesn't extend to `fetch_status()`'s per-row navigation,
  which still only goes through the reload-based `_goto_with_retry()` — an interactive
  challenge appearing mid-run there still just degrades to `不明`, not a manual-solve
  window.
- Even the 90s manual-click window above is not a reliable fix in practice: observed
  behavior is that the click registers, but the same interactive challenge reappears again
  shortly after — not the "temporary suspicion that clears with time" pattern you'd expect
  from pure rate-based bot detection. That's read as Cloudflare fingerprinting the
  Playwright automation itself (not just request cadence), which is exactly why this
  project's default path no longer routes through manba.co.jp at all — see "Pivot
  history" at the top of this file. If you're debugging a `--fallback-to-manba` challenge
  failure, don't assume more retries or a longer manual-click window will fix it; that
  avenue was already tried and is why the fallback exists as a narrow opt-in rather than
  the primary path.

## 最終目的

Pythonをインストールしていないwindows PCで、EXEをダブルクリックするだけで動作する
GUIツールにする。

## 環境の分離

- 開発・テスト：WSL Ubuntu（このリポジトリ）
- EXEビルド・動作確認：Windows側（PyInstallerはクロスコンパイル不可）
- したがって、コードはWindows/Linux両方で動くように書く
  （パス区切りは os.path / pathlib を使い、`/` をハードコードしない）

## 作業ルール

- 変更後は必ず ./scripts/verify.sh を実行してから完了報告する
- コミット・pushは明示的な許可があるときだけ行う
- 秘密情報を読まない・出力しない
