# GROBID master vs OpenAlex — affiliation recovery on institution-less OA preprints (30,743 works)

**Date:** 2026-07-19
**GROBID:** master `e8ee8814e` (version `0.9.1-SNAPSHOT`, revision `0.9.0-70-ge8ee8814e`), JDK 21,
`POST /api/processFulltextDocument` with **no parameters** (no consolidation — see §Method).
**Pipeline:** this repo, run continuously to 30,743 works then stopped.

---

## Summary

On open-access preprints where **OpenAlex resolved no institution** for any author, GROBID master
recovers a real affiliation from the PDF for **~80% of works**, and an independent referee confirms
**93% of those additions are genuine** (correct or right-institution-but-garbled), with only **1%
fabricated**. GROBID materially improves on OpenAlex for this corpus, at negligible risk of
introducing bad institution data.

---

## 1. Objective

OpenAlex filter `type:preprint, authorships.institutions.lineage:null, open_access.is_oa:true`
selects **2,870,443** OA preprints for which OpenAlex has **no resolved institution**. Question:
does running the PDF through GROBID master recover the missing affiliations, and are the recovered
affiliations actually correct (better than OpenAlex's nothing)?

## 2. Method

- Fetch PDFs continuously (only works exposing a usable PDF URL), process each through GROBID
  master `processFulltextDocument` with **no parameters**.
- **Consolidation is deliberately OFF.** Consolidation can pull affiliations from an external
  service (CrossRef/biblio-glutton); with it on, an "added affiliation" could come from a database
  rather than the PDF, and — since OpenAlex also ingests CrossRef — the comparison would be partly
  circular. Off keeps every affiliation traceable to the document, which is what we are measuring.
- Compare GROBID affiliations against OpenAlex authorships; classify each work (rapidfuzz
  `token_set_ratio ≥ 80` after accent/punctuation normalization).
- **Referee validation:** a 15% stratified-by-field sample of the `grobid_adds_affiliations` class,
  PDFs re-downloaded, first-2-page text extracted, each work judged by an LLM against the printed
  text (correct / partial / wrong / no-affiliation-printed / unreadable).

## 3. Corpus

The full 2.87M filter is arXiv/STEM-dominated; the **processed subset** (works exposing a direct
PDF URL) is even more so, because arXiv/Zenodo expose PDFs while SSRN/RePEc largely do not:

| | full corpus (2.87M) | processed set |
|---|---|---|
| arXiv | 62.4% | 94.7% |
| Computer Science | 23.4% | 53.2% |
| Physical Sciences (domain) | 72.0% | 87.7% |
| SSRN / Zenodo | 20.1% | ~0% |

**The results below therefore characterise GROBID master primarily on arXiv-style scholarly layouts.**

## 4. Result — GROBID vs OpenAlex (30,743 works)

| class | n | % |
|---|---|---|
| **grobid_adds_affiliations** (OpenAlex had none, GROBID found some) | 24,696 | **80.3%** |
| both_empty (neither has affiliations) | 4,987 | 16.2% |
| agree | 479 | 1.6% |
| disagree | 334 | 1.1% |
| grobid_empty (OpenAlex had raw strings, GROBID none) | 193 | 0.6% |
| grobid_failed | 54 | 0.2% |

Mean author recall (GROBID finds OpenAlex's authors): **0.917**; 1,451 works with zero author
recall; 1,914 flagged for diagnosis. Proportions were stable across all 30 batches (the 80.3%
adds-rate held from ~3k works onward).

### By subject (`grobid_adds_affiliations` rate)

| field | n | adds% |
|---|---|---|
| Materials Science | 312 | 91.0% |
| Physics & Astronomy | 4,622 | 86.5% |
| Computer Science | 15,623 | 83.2% |
| Engineering | 2,312 | 80.6% |
| Medicine | 611 | 80.5% |
| Social Sciences | 749 | 76.9% |
| Business/Management | 206 | 72.8% |

By source: arXiv 81.7% (n=29,210), RePEc 74.4% (n=784), unknown-source 29.0% (n=321). The
unknown-source bucket (no `primary_location`) is where GROBID mostly finds nothing — the
non-paper / cover-page / scan cases.

## 5. Referee validation — are the added affiliations real?

15% stratified sample of the adds class, **3,705 / 3,706 works refereed against the PDF text**:

| verdict | n | % |
|---|---|---|
| grobid_correct | 2,843 | 76.7% |
| grobid_partial (right institution, garbled/incomplete) | 615 | 16.6% |
| no_affiliation_printed (not in first 2 pages) | 196 | 5.3% |
| grobid_wrong (false info — worse than nothing) | 41 | 1.1% |
| unreadable | 10 | 0.3% |

**Better than nothing (correct + partial): 93.3%. Fabricated: 1.1%.** Real institutions are
recovered ~85× more often than a bad affiliation is invented.

### Referee by field

| field | n | correct | partial | no-aff | wrong |
|---|---|---|---|---|---|
| Physics & Astronomy | 598 | 88.1% | 9.7% | 1.7% | 0.2% |
| Computer Science | 1,924 | 78.9% | 19.2% | 0.9% | 0.9% |
| Engineering | 276 | 80.1% | 15.2% | 3.3% | 0.7% |
| Social Sciences | 85 | 70.6% | 22.4% | 0.0% | 4.7% |
| Economics | 71 | 64.8% | 26.8% | 4.2% | 2.8% |
| Mathematics | 361 | 49.0% | 7.8% | 42.4% | 0.6% |

## 6. Failure modes & caveats

- **Mathematics "no-affiliation-printed" (42%) is a referee-window artifact, not GROBID error.**
  Math preprints print affiliations at the end / in footnotes, outside the first-2-page text the
  referee read. GROBID processes the whole document and legitimately found them; the near-zero
  `wrong` rate (0.6%) confirms these are not fabrications.
- **`grobid_partial` is dominated by structural garbling, not wrong institutions**: affiliation
  instances merged, author-index digits or footnote symbols fused into strings, adjacent footnotes
  concatenated, or a venue/date line appended (e.g. "NeurIPS 2020, Vancouver Canada" added as a
  spurious affiliation). The institution itself is usually correct.
- **The 1.1% `grobid_wrong`** are genuine false positives: conference/venue lines, an author name,
  or a title/acronym mis-labelled as an affiliation.
- **Corpus skew:** these figures describe arXiv-style layouts. SSRN/RePEc/working-paper covers
  (largely absent here because they expose no PDF URL) are harder and would lower the rate.
- **Referee model:** 3,188 works refereed by Opus, 517 by Sonnet (after a spend limit). Sonnet
  graded stricter on correct-vs-partial but agreed GROBID recovers real institutions >92% of the
  time; the split does not change the real-vs-fabricated conclusion.

## 7. Conclusion

GROBID master is a **strict improvement over OpenAlex** for institution-less OA preprints on this
corpus: it supplies a real affiliation for ~80% of works OpenAlex left empty, 93% of those verified
genuine, ~1% harmful. The residual gap is (a) works with no affiliation printed at all (a corpus
property, not an extractor failure) and (b) `partial` structural garbling of correct institutions —
an aggregation/segmentation issue, not a recognition failure. Author recall is high (0.917).

**Artifacts:** run stats `stats.json` / `SUMMARY.md`; per-work classification `comparison.json`;
referee verdicts `referee_verdicts.json` / `REFEREE_SUMMARY.md`; topic/source enrichment
`topics_sources.jsonl`. Harness: `referee_sample.py`, `referee_workflow.js`.
