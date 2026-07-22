# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A CLI tool that reads a list of manga titles from an Excel file, looks each one up on
manba.co.jp, and writes back whether the series is completed (完結) or ongoing
(連載中). Japanese is the working language for user-facing strings (README, CLI help,
column headers, status values) — keep new strings consistent with that.

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
`ManbaClient` raises `RuntimeError` at construction time if the env var is unset.

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

Three modules under `comic_checker/`, each with one job:

- **`manba_client.py`** — `ManbaClient`, a context-managed Playwright wrapper. This is
  the part that matters most to understand before touching anything network-related:
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
    "Just a moment..."`) and retries up to 3 times with backoff (8s/16s/24s) before
    giving up and returning `False`. `fetch_status()` treats `False` as `不明` and moves
    on. `__enter__()` treats `False` (for either of the two pages above) as fatal: it
    raises `RuntimeError` and tears down the browser/context/playwright itself (since
    `__exit__` is never called when `__enter__` raises) — see "Known limitations" below
    for why this can't just retry harder.
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

- **`main.py`** — orchestration: resolves title/status/matched-title/URL columns (by
  header name, not fixed index), builds the row worklist (skipping rows that already
  have a status value unless `--no-skip-filled`), then drives one `ManbaClient` for the
  whole run inside a `with` block. Each row's `lookup()` call is wrapped in its own
  try/except so one failure records `エラー` for that row and moves on rather than
  aborting the run; the workbook is saved every `--save-every` rows (default 5) plus
  once at the end, so an interrupted run doesn't lose prior progress.

## Known limitations worth knowing before "fixing" something

- Search returns the top Meilisearch hit only — no fuzzy-match validation. Ambiguous
  titles (e.g. "ONE PIECE" matching a spin-off/reprint edition before the main series)
  are a real, observed failure mode, not hypothetical. This is why the output always
  includes the matched title and board URL columns — they exist for manual verification,
  not just as nice-to-have metadata.
- There is no rate-limit tuning beyond `--min-delay`/`--max-delay`; if Cloudflare starts
  challenging more aggressively, widening those is the first thing to try before changing
  retry logic.
- Cloudflare presents two different challenge types, and only one of them is
  auto-solvable: the `Just a moment...` interstitial resolves itself after a few seconds
  (what `_goto_with_retry()`'s wait-and-retry loop is built for), but it can also present
  an *interactive* "Verify you are human" checkbox that requires an actual click —
  observed in practice, not hypothetical. No amount of retrying/waiting gets past that
  one. The only real fix is a human: run with `--no-headless`, click the checkbox once,
  and the resulting Cloudflare clearance cookie gets saved to `state_path`
  (`.manba_state.json` by default) for reuse on subsequent headless runs. If this starts
  happening often, widen `--min-delay`/`--max-delay` or space runs out further apart.

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
