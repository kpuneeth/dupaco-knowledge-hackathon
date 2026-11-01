# Approach

**No API keys required.** The system is rules-based, uses only the Python standard library (3.9+, tested on 3.11), and makes no network calls. Ingesting all five snapshots takes about 3 seconds, and each answer takes well under 0.1 seconds. The same question always gets the same answer.

## How snapshots are stored and what "current" means

Each snapshot is the whole website as of its `taken_on` date. Snapshots are indexed separately and their pages are never merged. All indexing happens in `ingest()`, so `answer()` only does lookups.

- `as_of=None`: answer from the newest snapshot (28 Sep 2026).
- `as_of=<date>`: answer from the newest snapshot taken on or before that date. If the date is before every snapshot, the earliest snapshot is used.
- Snapshots are chosen by `taken_on`, not by a page's `fetched_at`, because a page can be weeks older than the crawl it appears in.

Within a snapshot, pages are ranked by how much they can be trusted:

| Trust | Pages |
|---|---|
| 5 | The rate sheets: `/rates`, `/business-rates` |
| 4 | Product pages under `/personal/` and `/business/` |
| 3 | Home, contact, about, join and membership pages |
| 2 | Other pages, e.g. promo pages like `/switch-and-earn` or `/earn-more` |
| 1 | `-lp` landing pages and `/learn/` guides |
| 0.5 | Other hosts |
| 0.3 | Calculators, blog, newsroom, business resources, PDFs and dated URLs |

When two pages give different values for the same product and tier, the more trusted page wins. Among dated pages such as press releases, the newest one wins. For example, the vehicle-affordability calculator and `/switch-and-earn` still show 5.34% for a 60-month auto loan, but the rate sheet says 5.39%, so the answer is 5.39%.

## Answering

`answer()` tries the following, in order:

1. **Refuse unknown names.** If the question names something (a branch, a product, a person) that appears on no page of the chosen snapshot, the answer is "I don't know".
2. **Special extractors:**
   - Branch lobby and drive-up hours, which appear only in branch press releases. A named branch with no hours on record gets a refusal.
   - Branch addresses.
   - "How many branches": the majority among the most recent dated statements. This gives 22 after the Hy-Vee branch closed, ignoring older pages that still say 23.
   - Fees, read from the fee schedule.
3. **Rate questions.** Every table row with a percentage becomes a fact. A fact records:
   - its heading and row label
   - the labelled values (rate, APY, APR or dividend)
   - the term in months
   - the model-year range
   - the balance or loan-amount range

   The question is parsed for the same qualifiers, and a row is used only when they agree:
   - **Term:** 60-month equals 5-year.
   - **Model year:** a 2025 car matches the "2024–27" row.
   - **Amount:** "$15,000" matches the "$10,000 – $24,999.99" tier.
   - **Product type:** must match exactly for IRA vs regular, purchase vs refinance, intro rate and home equity. Jumbo, special and business are preferences.

   Only the matching rows are returned, never every number on the page.
4. **Everything else:** BM25 passage search, reranked by:
   - page trust
   - question words in the page title
   - the expected answer type (a time, address, number or phone number)
   - phrase matches from the question

   Among near-equal results, the newest dated page wins, or, for undated pages, the more trusted one. A blog post loses to a Dupaco product page that scores almost as well.

## Saying "I don't know"

The answer is `confident=False`, says the information isn't listed, and contains no numbers when:

- the question names a product no rate table contains (ARM, construction, FHA or land loans)
- a fee or price question finds no price anywhere relevant
- a named branch has no hours on record
- nothing relevant is found at all

## Conflicts

`conflicts()` reports two kinds of contradiction.

**Rate rows.** Each rate-table row is mapped to a product family and a tier (term, model years, balance range) on every page in every snapshot. A conflict is the same family, tier and metric showing different values, across pages or across snapshots.

- **Winner:** the newest value on a trusted page (rate sheet or product page). If a tier was renamed on the rate sheet ("2023–26 Model Year" became "2024–27"), its successor row decides.
- **Not reported:** a row that is gone from the current site, with no page still showing an old value, is a past rate change and not a live contradiction.
- **One stale page, one conflict:** when a stale page (calculator, promo, guide) contradicts many balance or model-year tiers of the same product and term, only the headline tier is reported, i.e. the first row of the current rate sheet.
- **Merged repeats:** tables repeated for business or IRA accounts with identical values are merged into one entry.

**Facts stated in prose.** These are the branch count (22 vs older 23/20/19…) and the number of times Forbes has recognised Dupaco ("fifth time" in the newest release vs "fourth time").
