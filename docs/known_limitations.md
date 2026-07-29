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
- **The cross-sentence continuation veto (M6-B-3, Issue #30) only sees the scan range,
  not the whole article.** `_has_ongoing_signal()` looks at what `_judge_extract()` sees —
  the lead plus the first `==` section (`_lead_and_first_section()`), typically `概要`.
  A work whose 連載中 statement lives in a *later* section (刊行状況, 書誌情報, etc.) will
  not have its weak-tier `完結` vetoed, and can still be answered `完結` on a magazine-
  transfer sentence. Widening `_has_ongoing_signal()` to the full article is **not** a
  safe unilateral fix: the scan range is narrow for a reason (see the
  `_fetch_extract()` bullet below — deeper sections carry spin-off status sentences), and
  a full-article ongoing scan would let any spin-off's 連載中 veto a genuinely completed
  main work, trading a false `完結` for a false `判定不能` on a much larger set of rows.
  If this shows up in real data, prefer narrowing which sections are scanned over
  widening the veto's reach.
- Article selection (`_pick_article()`, reworked in M6-E-1, Issue #30) probes several
  normalized variants of the input title, then falls back to `list=search`. It validates
  the *name* (exact match after NFKC normalization, a `(漫画)` disambiguation, an
  editor-curated redirect, or a subtitle-extended form) and the *topic*
  (`_is_about_manga()` requires a manga/novel marker in the lead), but nothing more.
  A page that clears both bars is accepted, so an ambiguous title that happens to name a
  *different* manga will still be answered confidently — same class of risk as the
  manba.co.jp search below, just one layer removed. This is why the `参照タイトル` /
  `参照URL` columns exist: they are for manual spot-checking, not decoration.
- `記事なし` is frequently the *correct* answer, not a lookup failure. On the real 73-row
  sheet used to tune M6-E-1, 29 rows still come back `記事なし` after the fix, and
  spot-checking confirmed most are titles Japanese Wikipedia genuinely has no article for
  (short-run seinen/adult series, anthologies). Before adding another fallback tier to
  push that number down, verify against actual article existence — a `記事なし` rate near
  40% on a list like that is a property of the data, not evidence of a bug.
- The variant expansion deliberately does **not** cut titles at a half-width space
  (`お隣の天使様…　after the rain` is a real article name containing one) and does not do
  fuzzy/edit-distance matching (see `docs/architecture.md` for why that was tried and
  rejected). A title whose Wikipedia article name differs by more than case/width,
  bracketed notes, or an appended subtitle will not resolve.
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
- **A green test suite is not evidence that real data still behaves correctly.** Every
  fixture in `tests/test_wikipedia_client.py` is a *snapshot* of an article taken on the
  day the test was written. Wikipedia articles get rewritten, so a fixture can keep
  passing long after the live article stopped producing that result — the test proves the
  regex still handles *that text*, not that the row is still answered correctly.
  Concrete instance, found while working Issue #37: **`大奥` — the headline case of Issue
  #36 and the only "confident wrong answer" M6-D-2 turned up — currently returns
  `判定不能` against the live article**, while `OOOKU_EXTRACT` still asserts `完結` and
  passes. `連載中から多くの漫画賞を受賞し` no longer appears in the live scan range, so
  the fix that test guards is no longer being exercised by the real page. Cause not
  investigated (deliberately out of scope for #37). Two consequences worth internalizing:
  a fixture-based regression test cannot tell you a fix is *still needed*, and any claim
  about real-data accuracy has to be re-measured against live articles (see `ERRORS.md`
  for a request-cheap way to do that).
- **Rows that land on an author's article were fixed in Issue #45 — but only that shape.**
  Category 2 of M6-D-2 (a title with no article of its own whose redirect points at the
  漫画家 article) is now rejected at selection time by `_is_person_article()`, taking all
  10 rows to `記事なし` (D-rate 90.0% → 0%): `こさめちゃん`/`横須賀こずえ` (→ `小田扉`),
  `リングサイドクレイジー` (→ `吾妻ひでお`), `独裁君`/`詩人ケン`/`神様物語`/
  `ガラガラポン!日本政治` (→ `業田良家`), `ジーニアース` (→ `押切蓮介`), `叛意明らか也`
  (→ `松本大洋`), `終わった漫画家` (→ `福満しげゆき`). Note what it took: #36 and #37 each
  removed a specific false signal in these rows and *neither changed the answer* — the
  judge simply grabbed the next legitimate-looking sentence about a different work by the
  same author. If a similar "confidently wrong on an article that isn't about the input
  work" case turns up, reach for article *selection*, not more regex vocabulary.
- **The author-article check can, in principle, reject a real work article.**
  `_is_person_article()` exempts anything whose lead starts with `『`, which is how
  Wikipedia work articles conventionally open — but **5 of 200 sampled work articles do
  not start with `『`** (and the exemption is a literal `『` check, so a lead opening with
  `「` or a bare Latin title is not exempted either). If such an article also has a lead
  whose 「日本の<種別>」 begins with a `家`-suffixed word — the `魔法少女メルル` shape —
  it would be dropped to `記事なし`. Measured false-positive rate is 0/200 today, and the
  failure lands on the fail-closed side (`記事なし`, not a wrong assertion), but this is
  the direction to check first if a title that used to resolve suddenly reports
  `記事なし`.
  The same `『` exemption also lets *non-serialized* work articles through — collected
  editions, anthologies and the like — which can then answer `完結` off a collected work's
  serialization sentence (observed: `長谷川町子全集`, answered `完結` from 『サザエさん』's
  連載 sentence). Left as-is deliberately: dropping the `『` guard to catch these would
  sweep in the `魔法少女メルル` shape above, and no such row appeared in M6-D-2.
- **Category 3 (spin-off / sequel redirecting to the parent work) is handled, but the
  guard that handles it is the one place in the selection path that fails *closed*.**
  A title with no article of its own can redirect onto the *parent work's* article, which
  is a correctly formatted work article — just not the input's work — so
  `_is_person_article()` cannot help. `_lands_on_a_different_work()` (Issue #51) rejects
  those rows: when the landing title differs from the raw input, it looks for a lead
  sentence that names the input inside `『』` with a derivative-work marker
  (`DERIVATIVE_WORK_MARKERS`) modifying that specific mention. Two details are load-bearing
  and were each measured, not guessed:
  - The comparison against `『』` is **NFKC-exact, never a substring**. `[47]`
    `お隣の天使様にいつの間にか駄目人間にされていた件` is a prefix of the spin-off title
    `…件 after the rain`, and the two land on the *same article*; a substring match drops
    the main series. Separately, `精霊の守り人` → `守り人シリーズ` is a substring of
    『ジン～アニメ精霊の守り人外伝～』 and would be dropped even though the gate is open.
  - The marker must **modify that mention** — outside the `『』`, before it, within
    `MARKER_MAX_DISTANCE` characters. Sentences that list several works otherwise fire on
    all of them.
- **The merged-article exemption (condition B, Issue #51) fails toward *over*-rejection,
  not toward safety.** `_mentions_as_derivative_work()` refuses to fire when the landing
  article declares it covers several works at once (`本項では…併せて解説する`, `…の総称`,
  and the other phrases in `MERGED_COVERAGE_MARKERS`, harvested from 150 real articles).
  That exemption is what keeps `バキ` → `グラップラー刃牙` and `カイジ` →
  `賭博黙示録カイジ` from being dropped to `記事なし` — measured, they are rows the tool
  answers correctly today. **Every other guard in the selection path fails open**
  (`_is_person_article()`, the marker proximity check): when the evidence is missing they
  leave the previous behaviour alone. This one does not. If a Wikipedia editor rewrites a
  merge declaration into wording the vocabulary does not match, the article stops being
  recognised as merged, the rule fires, and a row that used to answer correctly starts
  answering `記事なし`. The failure is silent — the row simply reports no article, which is
  indistinguishable from a title Wikipedia has never covered.
  **There is no runtime mitigation. The only check that exists is re-running the Issue #51
  corpus survey — `python scripts/survey_m6a2_corpus.py`**, which reproduces both the
  adversarial group (`hastemplate:"Infobox animanga/Manga"`, 150 articles, all incoming
  redirects) and the normal group, and reports any firing that was not in the recorded
  2026-07-29 set. It exits non-zero on a difference. Budget ~370 API calls / 20-25 minutes;
  results are cached on disk so an interrupted run resumes. A false-exclusion count above zero there is
  the signal that the vocabulary has drifted. Re-run it before trimming
  `MERGED_COVERAGE_MARKERS`, and after any report of a title that used to resolve and now
  returns `記事なし`. Note that a `〜シリーズ` article name is *not* a usable substitute for
  the declaration: `守り人シリーズ` carries no merge declaration at all.
- **Reading a work's status off a *series* article is still accepted — the line is drawn at
  "introduced as a derivative work", not at "is the article about exactly this work".**
  `精霊の守り人` → `守り人シリーズ` is answered `完結` from the series article's sentence
  about that work's manga version, and that is the intended behaviour; a spin-off landing
  on its parent (`彼女、人見知ります` → `彼女、お借りします`) is dropped to `記事なし`.
  Both are "the landing article is not exclusively about the input", so the asymmetry is
  deliberate, not an oversight: Issue #47's labelling settled that a spin-off must not be
  answered from its parent, while M6-D-2 accepted the series article as the right article
  for a constituent work. **Do not "fix" the `守り人シリーズ` case by widening the rule** —
  it would have to reject constituent-work rows, which are correct today.
- **The derivative-work check only catches mentions written the same way as the input.**
  `チンピース` redirects to `ONE PIECE`, whose lead introduces the spin-off as
  『CHIN PIECE』 in Latin script; NFKC does not equate kana with Latin, so the row is not
  rejected and still answers off `ONE PIECE`. This is the fail-open side of requiring an
  exact match and is not a bug to chase with fuzzy matching — see the string-similarity
  warning in `docs/architecture.md`. Recall on the Issue #51 adversarial corpus was low by
  design; that corpus is deliberately enriched with derivative works and is not the real
  input distribution (category 3 was 2/72 rows there).
- **The infobox path's "empty end field ⇒ `連載中`" inference now requires positive
  evidence that the run is continuing (M6-B-4, Issue #56), because the bare inference was
  measured wrong 61.3% of the time.** `_judge_via_infobox()` exists to read "終了系 field is
  non-empty ⇒ `完結`". The opposite reading — empty ⇒ `連載中` — is its contrapositive and is
  much weaker: **an empty field is not a record that serialization is continuing, it is
  equally what you get when nobody filled it in.** The `完結` direction had a gate since #30
  (`judge()` refuses an infobox-sourced `完結` whenever the prose has an ongoing signal); the
  `連載中` direction had none.
  M6-D-4 (Issue #53) measured what that cost. Sampling 1,800 work articles and keeping the
  rows where the prose was inconclusive *and* the infobox said `連載中`, **46 of 75 (61.3%)
  were actually completed**; an independent 500-article holdout gave 13 of 21 (61.9%).
  `_has_continuation_evidence()` therefore requires the `巻数` field to carry `既刊` and,
  when a year is readable, to be newer than `CONTINUATION_STALE_YEARS` (5). Measured over
  the 96 labelled rows: **detection 54/59 = 91.5%, false-exclusion 1/37 = 2.7%**.
  Three things about it are worth knowing before touching it.
  - **`既刊` with no date counts as evidence.** Refusing it looked better on the sample the
    threshold was chosen from (3.4% false-exclusion) but cost 25.0% on the holdout, because
    some editors simply never write the date. See the `ERRORS.md` entry on holdout samples.
  - **The 5-year threshold is not a clean separator.** The failing rows' years were 2012,
    2013, 2015, 2016, 2017, 2019, 2021 and **2023**, the correct ones **2022** onward — the
    two overlap. Re-measure the distribution before changing the constant.
  - **What still gets through**: one false exclusion (`一人之下`, an ongoing work whose
    article has no `巻数` field at all — no date rule can help) and five misses
    (`もし高校野球の…`, `Ef - a fairy tale of the two.`, `ノブナガ・ザ・フール` carry `既刊`
    with no date while being complete; `空の境界` and `俺、つしま` carry recent dates while
    being complete).
- **The `判定根拠` column's wording changed for infobox-decided rows (M6-B-4, Issue #56).**
  It used to read `インフォボックス: 終了号/終了日等が空欄`, which said only that a field was
  blank and never said why that meant the work was running. It now reads
  `インフォボックス: 終了号/終了日等が空欄、巻数 = 既刊12巻（2026年2月現在）` — the volume
  count is the actual basis for the verdict, so it belongs in the column the user reads.
  **This is a user-visible change**: `判定根拠` is written back to the spreadsheet
  (`--evidence-column`). The status itself is unchanged.
- **This path still decides a large share of real rows.** On the M6-D-3 census (72 real
  input rows, 40 of which land on an article after Issue #51), the prose analysis returned
  `判定不能` for 8 rows and the infobox decided **6 of them** — `うしろの正面カムイさん`,
  `てんぷる`, `カッコウの許嫁`, `月曜日のたわわ`, `リコリス・リコイル`, `魔都精兵のスレイブ`
  — **6/40 = 15.0%**. All six carry a 2026 `既刊` date, so the M6-B-4 gate passes every one
  of them and the 94-row regression showed **zero** changed rows. That is the point worth
  remembering: **the regression corpus never exercises this gate's detecting side**, so a
  future regression here will not show up there. `scripts/survey_m6d4_infobox.py --verify`
  is what pins it, against the 96 labelled rows in `scripts/m6d4_labels.py`.

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
