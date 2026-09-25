# 既知の制限

`CLAUDE.md` から移動（Issue #18）。挙動を「直す」前に読むこと。

**Dating convention (added Issue #41 follow-up, 作業63):** entries that depend on a live
Wikipedia article's current content or a live `judge()` call's actual output should carry
a `**Measured YYYY-MM-DD**` stamp next to the claim. Wikipedia articles get edited, so an
unstamped claim about "what the live article currently says" can silently go stale —
`大奥`'s entry below is a confirmed instance of exactly this happening. **If a stamp is
more than a few months old and the claim still matters, re-verify it before relying on
it.** Entries below without a stamp were not re-verified when this convention was
introduced — their measurement date is unknown, and their freshness is not guaranteed.

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
- **`_has_ongoing_signal()` also excludes `SPINOFF_MARKERS`-tagged sentences from its
  scan (Issue #154, 案B).** Before this, a sentence about a spin-off/sequel/derivative
  work being ongoing (「続編」「番外編」「スピンオフ」「外伝」「次世代編」) could veto a
  genuinely-completed main work's weak-tier `完結` — that's what happened to バーテンダー
  à Tokyo (`_judge_extract` path) and 陰陽師 (`judge()`'s infobox-fallback path) and,
  discovered only after implementation via the full test-suite run rather than the
  pre-registered prediction, セトギワ花ヨメ (次世代編, Issue #144's own fixture).
  **Real-data confirmation exists for only two of the five `SPINOFF_MARKERS` elements**
  — 続編 (バーテンダー à Tokyo, 陰陽師) and 次世代編 (セトギワ花ヨメ). 番外編・外伝 have
  zero real sentences co-occurring with `ONGOING_RE` in the current corpus
  (holdout99+regression61) and **can't be confirmed on real data from this corpus at
  all** (`docs/code_defects_2026-08/effective_hit_rate_analysis.md`). スピンオフ does
  have 3 real co-occurring rows, but none of them actually flip the outcome (another
  ongoing sentence in the same row already keeps the row's status unchanged either
  way), so its exclusion behavior is verified only via synthetic fixtures
  (`tests/test_wikipedia_client.py::test_has_ongoing_signal_excludes_each_spinoff_
  marker_individually`), not real data. See
  `docs/code_defects_2026-08/planb_criterion3_withdrawal_and_verdict.md` for the full
  accounting (verdict: 条件付き合格) and
  `docs/code_defects_2026-08/planb_prediction_scope_defect.md` for how セトギワ花ヨメ
  surfaced (a test-suite failure, not something the pre-registered prediction caught —
  the prediction's scope was the 160-row snapshot corpus only, and this fixture lives
  only in `tests/`).
- **The `SPINOFF_MARKERS` exclusion check (used both here and at the `_judge_extract()`
  decision-loop level) is a plain substring match (`marker in sentence`) with no word
  boundary.** A sentence containing an unrelated word that happens to contain one of the
  five markers as a substring (e.g. 「継続編成」contains 続編, 「海外伝道師」contains
  外伝, 「次世代編成局」contains 次世代編) gets excluded too, confirmed on synthetic
  fixtures. Zero real occurrences of this were found across the 160-row corpus
  (`docs/code_defects_2026-08/issue_draft_marker_boundary.md`), and the same
  substring-match pattern is used throughout the module for other marker lists
  (`MANGA_MARKERS`, `NOVEL_MARKERS`, `DERIVATIVE_WORK_MARKERS`,
  `ARTICLE_RELEVANCE_MARKERS`, `MERGED_COVERAGE_MARKERS`, `CONTINUATION_MARKER`,
  `ONGOING_FIELD_MARKER`, `HIATUS_MARKER`) — this isn't specific to `SPINOFF_MARKERS`.
  Tracked as Issue #171; decided to keep as-is (zero real-world harm found across the
  160-row corpus plus the 60 test fixtures). **The failure direction is not the same
  for every marker list.** For `SPINOFF_MARKERS`'s exclusion, over-matching drops an
  unrelated sentence from the scan — the fail-safe direction. For other lists (e.g.
  `ONGOING_FIELD_MARKER`), over-matching could instead cause a wrong `連載中`
  assertion — each site needs its own evaluation of which direction an over-match
  would push the verdict. Before changing this, confirm real-world harm on an
  independent sample and pre-register the verification.
- **`ONGOING_RE` deliberately does not include 「掲載されている」.** Adding it was
  considered (Refs #135) but a real-data example showed it misattributing a
  spin-off/derivative one-shot's serialization to the main work, flipping a
  genuinely-completed work to a false `連載中` (Issue #138). Do not add it on the
  strength of that one example alone — confirm the derivative-work wording against
  independent real data and pre-register before changing this.
- **Sporadic new-content mentions after an explicit completion sentence are not
  treated as ongoing.** If the lead text carries an explicit ending statement
  (caught by `COMPLETED_WEAK_RE`/`COMPLETED_STRONG_RE`), a later mention of
  sporadic new content does not flip the result to `連載中` — this matches the
  definition in `README.md` ("### Wikipedia判定（既定の経路）"), not a bug. A
  candidate rule for the opposite behavior (labelling ruleset v3's R5) exists
  but rests on a single uncorroborated real-data example across three rule
  revisions (see ADR-028) — not adopted as an implementation requirement.
- **`COMPLETED_WEAK_RE`/`ONGOING_RE` miss two vocabulary items: 「配信終了」and
  「連載されており」(Issue #305, a #157 leftover).** Neither pattern currently matches
  these forms, so a row carrying only one of them falls back to `判定不能` rather than a
  wrong confident answer — the missed vocabulary fails closed on the safe side, not the
  dangerous one. In the existing 160-row corpus (holdout99+regression61), each item has
  exactly 1 affected row (`docs/holdout_measurement_2026-08/step98_b_compare_result.md`,
  No.64 and No.98) — below `prereg_v2_effective_count_basis.md`'s adoption threshold of 2+
  affected rows. A second occurrence of 「連載されており」was observed in holdout2, but
  holdout2 has already been consumed for evaluation (PR #270) and is kept in reserve as an
  effectiveness-evidence sample rather than spent on adoption decisions (Issue #305), so
  that observation does not count toward the threshold. Changing this requires meeting the
  threshold on independent real data not drawn from holdout2, with pre-registration before
  implementation.
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
- **The mediamix check above false-negatives on disambiguated ("〜 (漫画)") articles whose
  lead names a prior novel.** `judge("陰陽師")` returns `判定不能` (actually `完結`): the
  matched article opens with "夢枕獏の小説『陰陽師』を原作とする岡野玲子の漫画", missing
  the `"日本の<種別>"` clause and falling back to a bare `小説` marker, which wrongly
  treats the work as novel-primary. Relaxing the check for the trusted disambiguation
  route was investigated with real data (Issue #41) but **not implemented**. Measured
  2026-08-10: the `"〜 (漫画)"` population is ~966 (`intitle:漫画`, filtered locally by
  suffix — `hastemplate:"Infobox animanga/Manga"` undercounts real manga articles by
  design and should not be used to build this population; 10/10 random titles from its
  373-title gap were confirmed genuine manga works lacking that template). A random
  30-sample from the 966 had **zero** rows where the check actually engages
  (`_is_novel_primary() == True`) — 陰陽師 is still the only real-data beneficiary found.
  Staying pending: this is a fail-closed relaxation (Issue #8/#9's stance), and at this
  scale the benefit doesn't clearly outweigh the added false-positive risk.
- **A green test suite is not evidence that real data still behaves correctly.** Every
  fixture in `tests/test_wikipedia_client.py` is a *snapshot* of an article taken on the
  day the test was written. Wikipedia articles get rewritten, so a fixture can keep
  passing long after the live article stopped producing that result — the test proves the
  regex still handles *that text*, not that the row is still answered correctly. This
  entry itself is the concrete proof: it used to say `大奥` — the headline case of Issue
  #36 and the only "confident wrong answer" M6-D-2 turned up — "currently returns
  `判定不能` against the live article," undated, found while working Issue #37. **Measured
  2026-08-10 (Issue #41 follow-up, 作業63): that claim is now wrong.**
  `judge("大奥")` returns `status=完結`, `matched_title=大奥 (漫画)`,
  `adoption_path=direct_disambiguation`, `evidence="隔月刊誌『MELODY』（白泉社）にて
  2004年8月号から2021年2月号まで連載された。"` — a correct answer, from a serialization
  sentence that is present in the live scan range today. **Likely explanation (inference,
  not confirmed against the article's edit history): a further Wikipedia edit
  re-introduced a decisive serialization sentence into the lead/first-section scan range**
  after the `判定不能` state this entry originally described — but that is a guess, not a
  verified cause. Two consequences worth internalizing, now doubly demonstrated: a
  fixture-based regression test cannot tell you a fix is *still needed*, and any claim
  about real-data accuracy — including this doc's own claims — has to be re-measured
  against live articles before being trusted (see `ERRORS.md` for a request-cheap way to
  do that, and for the entry recording how this exact staleness was caught).
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
    being complete). The three dateless-`既刊` misses are the deliberate cost of not taking
    the rejected alternative (refusing a dateless `既刊` as evidence, Issue #56's B-6) — see
    the trade-off comment in `comic_checker/wikipedia_client.py`. The other two are a
    consequence of the threshold not being a clean separator, described above.
  - **Measured 2026-08-11: re-ran the threshold against 3/4/5/6/7/8, kept 5.** 3 detects one
    more (55/59) but at 8.1% false-exclusion (3/37) instead of 2.7%; 6–8 match 5's
    false-exclusion rate but detect strictly less (53, 53, 52 vs 54). 5 dominates 4, 6, 7, 8
    and trades detection for safety against 3, consistent with the project's stated
    preference (a false exclusion is the safe-side failure). The origin of `5` — the 2021|2022
    year-gap in Issue #53's original 75-row study — lives in the code comment directly
    above `CONTINUATION_STALE_YEARS` in `comic_checker/wikipedia_client.py`, and the
    independent re-calculation above
    reproduces that comment's numbers exactly, confirming the record is accurate and
    reproducible. **This measurement selects and evaluates on the same 96 rows the threshold
    was already tuned against, so "5 is best" here is an overestimate (the holdout-sample
    lesson in `ERRORS.md` applies directly) — an independent third sample is needed before
    treating this as a real validation, not just a reproduction.** Building one at the scale
    of the existing corpus (`hastemplate:"Infobox animanga/Manga"` census + holdout) is
    estimated at ~1,800–2,300 requests. **Not scheduled.**
- **Coverage tally, 作業67–71 (`comic_checker/wikipedia_client.py`).** Article-selection
  (`_pick_article` and everything under it), the `_judge_extract()`/`_is_person_article()`
  branches, and the response-parsing functions (`_fetch_extract`/`_fetch_wikitext`/
  `_lead_and_first_section`/`_extract_braced_blocks`'s malformed-template handling) all now
  have direct unit tests, each confirmed mutation-sensitive. **Measured 2026-08-11: branch
  coverage 95%→98%; every 作業69-2 分類A item is closed.** All Category-A work is done —
  no line/branch remains that is both testable and un-tested, **with one exception noted
  below (L494), which is an explicit exclusion, not a resolution — the two are not the same
  thing.** Remaining uncovered items, each classified:
  - `L438`, `L455-458` — Category C (unreachable/pure-defensive; `_declares_merged_coverage`/
    `_marker_modifies_mention`, a diagnostic-only parameter never invoked with a non-default
    value anywhere in the repo).
  - `L494` (`_mentions_as_derivative_work`) — leans Category B; 作業69-2 self-assessed its
    real-data recurrence as thin. **Deliberately excluded from 作業70's scope, not fixed or
    tested — this is an exclusion by instruction, not a closed item.**
  - `L818` (`_api_get`'s post-loop `raise_for_status()`) — provably unreachable given the
    current control flow (every loop iteration already returns or raises before falling
    through). Filed as **Issue #121**, tracked there, not fixed.
  - `L920→919` (`_resolve_titles`) — Category C (external-API-dependent defensive branch).
  - `[572, -572]` (`_is_novel_primary`'s `any(...)` generator fully exhausting without a
    NOVEL_MARKERS hit) — newly surfaced by the 作業70 coverage re-measurement, not present
    in 作業69-2's original list. **Classified Category A in 作業71-2**: the outer branch it
    lives in (`_PRIMARY_TYPE_RE` not matching) already has real-data grounding (35/200 work
    articles per `tests/test_wikipedia_client.py`'s own comment), so this is not assessed as
    thin the way L494 is. Not written this turn — reasoning recorded only.
  - **None of the above are planned to be filled going forward** (L494/C-items by design,
    L818 tracked separately via Issue #121, `[572,-572]` deferred as a live Category-A
    candidate for a future round rather than urgent).
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
- **The M6-B-4 gate's actual reach is much narrower than "protects the infobox path"
  sounds — it exercises exactly one function.** **Measured 2026-08-11.** Tracing the real
  call chain (`verify.sh` → `python scripts/survey_m6d4_infobox.py --verify` →
  `verify_against_labels()`): that function calls `_has_continuation_evidence()` directly
  on each label's stored `volumes` string. It never calls `_judge_via_infobox()` — the
  function that owns the end-field loop, the `完結`-on-nonempty-value branch, and the
  `HIATUS_MARKER` check above — nor `_judge_extract()` (prose analysis), nor any part of
  article selection (`_pick_article()` and everything under it). Structurally, this
  couldn't cover more even if the label data wanted it to:
  `scripts/m6d4_labels.py`'s `Label` (`__slots__ = ("group", "no", "title", "volumes",
  "label")`) has no field for a raw end-field string, only the already-parsed `volumes`
  text `_has_continuation_evidence()` consumes. **Consequence: "the M6-B-4 gate is
  unchanged, therefore no regression" is only a valid claim when the change under test
  sits on this one function's path.** A change to `_judge_via_infobox()`'s branching (like
  the `HIATUS_MARKER` fix above), to `_judge_extract()`, or to article selection can pass
  this gate untested every time — see `ERRORS.md` for the instance that prompted this
  entry, and the retrospective audit of prior claims phrased "gate unchanged ⇒ no
  regression" done in that same investigation.

- **Fixed (M-5 category, `HIATUS_MARKER`): the infobox path used to call a hiatus
  "completed" when the end-field carried an annotation instead of being genuinely blank.**
  `日常` was the concrete case: the live article says "2025年2月号から多忙による
  スケジュール調整により長期休載となっている" — on hiatus, correct label `連載中`, not
  `完結` — while `判定根拠` used to read `インフォボックス: 終了号 = 2008年7月号
  〈一時休載〉`, a non-empty value the old code took as `完結` without looking at what it
  said. Different from Issue #38 (closed, prose path) — this was purely infobox-driven.
  **Measured 2026-08-10: fixed.** `_judge_via_infobox()` now skips an end-field value
  containing `休載` rather than treating it as completion evidence, and falls through to
  the existing M6-B-4 continuation-evidence check (`巻数` field) instead of asserting
  anything on its own. For `日常` that check finds `既刊12巻（2024年10月25日現在）`, so
  `judge("日常")` now returns the correct `連載中`.
  **This is not a pure fail-closed strengthening.** Before this fix, a non-empty end-field
  could only ever assert `完結` — never `連載中`. Now, when a `休載`-annotated end-field
  *and* fresh continuation evidence both happen to be present, the function asserts
  `連載中` on its own — a new confident-assertion path that did not exist before. If a
  work's `巻数` field is stale or wrong for a genuinely completed work whose end-field also
  happens to carry a `休載`-shaped annotation, this path could produce a false `連載中`.
  **That false-positive rate is unmeasured — no real-data survey has been run for this
  path.** The detection vocabulary is deliberately narrow: only `休載` is used, backed by
  the one real case above. `中断`/`休止` were considered but **not added — they are
  unverified guesses**, not measured against real infobox data. Widening the vocabulary,
  or measuring the false-positive risk above, needs a real-data survey
  (`hastemplate:"Infobox animanga/Manga" insource:"休載"`-shaped query, one wikitext fetch
  per candidate since `prop=extracts` strips infobox templates — estimated tens to low
  hundreds of requests). **Deferred, not scheduled.**
  **Measured 2026-08-11, corrected:** this fix does not change the gate's
  `検出54/59・副作用1/37` figures, and the primary reason is structural, not a property
  of the label data — the gate's `--verify` path never calls `_judge_via_infobox()` at
  all (see "The M6-B-4 gate's actual reach…" above), so it could not exercise this branch
  regardless of what the labels contain. The data-level fact is also true and worth
  keeping — `日常` sits outside the M6-D-4 census (`scripts/m6d4_labels.py`'s 96 rows),
  and grep confirms zero rows in either labelled corpus carry a `休載` end-field value —
  but stating only that fact (as an earlier version of this entry did) reads as if
  coverage were contingent on the data, when it is not: even a labelled row that did
  carry `休載` would not exercise this branch through `--verify`.
- **`_judge_via_infobox()` only treats an end-field value as an unresolved placeholder
  when it is nothing but `？`/`?` characters (Issue #156,
  `prereg_lineage2_infobox_placeholder.md`).** When that narrow condition matches, the
  function returns `判定不能` immediately and does not fall through to check any later
  end-field name — the fail-safe direction. **A non-empty value that contains no digit
  and is neither `連載中` nor `休載`-flagged is still taken as a real end value and can
  still assert `完結`.** Two such rows exist in the 160-row corpus
  (holdout99+regression61); whether either is a misjudgment has not been evaluated.
  Widening the placeholder check to cover this shape needs its own pre-registration —
  not a mechanical extension of the `？`/`?` condition.
- **Every request to the Wikipedia API waits 1.0 second, so a real run is slow — budget
  about 7 seconds per input row (Issue #40).** `_api_get()` sleeps before each request and
  retries a 429 up to six times with a `5.0 × attempt` backoff. Before #40 there was no
  pacing at all in the production path: `judge()` fires **2–4 requests per row**
  (`_resolve_titles` → `_fetch_extract` → `_fetch_wikitext` when the prose is inconclusive
  → a search when neither resolves) and they went out back to back. That burst is what
  tripped a 429 during the Issue #51 corpus work.
  **Budget from the upper figure, not the average.** Measured 2026-07-30, a 94-row run of
  `scripts/measure_false_negative_rate.py` took 425 s — but 44% of those rows are
  `記事なし` and never fetch an article body, so they are cheap. **A sheet where every
  title resolves costs about 7 s per row.**

  | Input rows | Upper estimate (~7 s/row) | Measured average (4.5 s/row, 55.6% coverage) |
  |---|---|---|
  | 72 (the real-world sheet) | **~8.4 min** | ~5.4 min |
  | 100 | **~12 min** | ~7.5 min |
  | 300 | **~35 min** | ~22 min |
  | 500 | **~58 min** | ~38 min |
  | 1,000 | **~117 min** | ~75 min |

  **The 1.0 s value is deliberately conservative and its basis is thin.** It was chosen in
  #51 because 429s stopped appearing — nothing more. Wikimedia publishes no hard rate limit
  for anonymous read requests; what it asks for is serial access at a sensible rate, and
  this tool is already serial, so the 429 was most likely caused by the burst rather than
  the rate. A shorter interval might well be enough. **That is an untested hypothesis**, and
  the asymmetry favours waiting: erring fast risks a 429 that aborts the whole run, erring
  slow only costs time. Measure before lowering it.
- **A run can be cancelled, but only at row boundaries (Issue #61).** The GUI's stop button
  sets a `cancel_event` that `run()` checks at the top of each row, so pressing it does not
  stop the row already in flight — expect to wait one row (4.5s/row measured, ~7s/row as
  the upper bound). Waits inside `wikipedia_client._api_get` are not interrupted, so a row
  caught in 429 retry backoff takes longer still. Results up to that point are always
  saved, and `skip_filled=True` picks up where it left off on the next run; note that
  cancelling a *rejudge* (`skip_filled=False`) leaves the not-yet-revisited rows holding
  their old values, and those count as judged, so resuming needs "rejudge all" again.
  Immediately after pressing stop, the status line briefly flips back to `処理中… N/M 件`
  when the in-flight row finishes, then settles on `中断しました` — `_on_progress` does not
  know a cancellation was requested. The final message is correct. Removing the flicker
  means handing the cancel state to `_on_progress`, which adds a worker-thread read of that
  state, so it is deliberately left alone. Still a separate problem from #33 (the worker
  thread reading Tk variables directly), though both live in `_run_worker`.

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
