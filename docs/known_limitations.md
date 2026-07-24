# 既知の制限

`CLAUDE.md` から移動（Issue #18）。挙動を「直す」前に読むこと。

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
