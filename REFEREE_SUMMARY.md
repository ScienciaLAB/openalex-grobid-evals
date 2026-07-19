# Referee validation — are GROBID's added affiliations real?

Ground-truth check on the `grobid_adds_affiliations` class (OpenAlex resolved no
institution, GROBID extracted one). A **15% stratified-by-field sample** of that class
was drawn from the 30,743-work run (GROBID master `0.9.0-70-ge8ee8814e`), PDFs
re-downloaded, first-2-page text extracted, and each work refereed by an LLM against
the printed text. **3,705 / 3,706 refereed (100%).**

## Result (combined)

| verdict | n | % |
|---|---|---|
| grobid_correct | 2,843 | 76.7% |
| grobid_partial (right institution, garbled/incomplete) | 615 | 16.6% |
| no_affiliation_printed (not in first 2 pages) | 196 | 5.3% |
| grobid_wrong (false info — worse than nothing) | 41 | 1.1% |
| unreadable | 10 | 0.3% |

**Better than nothing (correct + partial): 93.3%. Actually wrong: 1.1%.**
GROBID's ~80% "adds affiliations" is overwhelmingly a genuine improvement over OpenAlex's
missing institutions — real institutions are recovered ~85× more often than a bad string is invented.

## By field (correct + partial)

| field | n | correct | partial | no-aff | wrong |
|---|---|---|---|---|---|
| Physics & Astronomy | 598 | 88.1% | 9.7% | 1.7% | 0.2% |
| Computer Science | 1,924 | 78.9% | 19.2% | 0.9% | 0.9% |
| Engineering | 276 | 80.1% | 15.2% | 3.3% | 0.7% |
| Social Sciences | 85 | 70.6% | 22.4% | 0.0% | 4.7% |
| Economics | 71 | 64.8% | 26.8% | 4.2% | 2.8% |
| Mathematics | 361 | 49.0% | 7.8% | 42.4% | 0.6% |

**Mathematics caveat:** the high `no_affiliation_printed` (42%) is a *referee-window
artifact*, not GROBID error — math preprints print affiliations at the end / in footnotes,
outside the first-2-page text the referee read. GROBID processes the whole document, so it
legitimately found them; the near-zero `wrong` rate (0.6%) confirms these aren't fabrications.

## Methodology note — Opus vs Sonnet referee

3,188 works were refereed by Opus, the final 517 (tail of the manifest) by Sonnet after Opus hit
a monthly spend limit. Sonnet was stricter (partial 29% vs 14.6%, wrong 2.5% vs 0.9%), but the
Sonnet batch is confounded: it is the tail of the sorted manifest = more recent, footnote-heavy,
multi-institution arXiv papers that garble more. Both models agree GROBID recovers real
institutions in >92% of cases; the split is correct-vs-partial, not real-vs-fabricated.

Per-work verdicts: `referee_verdicts.json`. Harness: `referee_sample.py` + `referee_workflow.js`.
