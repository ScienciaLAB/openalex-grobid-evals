# GROBID master vs OpenAlex: affiliation extraction on institution-less OA preprints

**Setup.** OpenAlex query `type:preprint, authorships.institutions.lineage:null, open_access.is_oa:true`
(~3.25M works — OA "preprints" where OpenAlex resolved **no institution** for any author).
PDFs fetched via cursor paging; processed by a **local GROBID master** server
(`~/development/projects/grobid-master`, worktree at `origin/master` = `34d8fbdcf`, rev `0.9.0-64`,
wapiti CRF for affiliation-address) with `POST /api/processFulltextDocument`, **no parameters**.
Referee ground truth: Claude reading the first two pages of each sampled PDF.

Pipeline scripts in this directory: `fetch_openalex_pdfs.py` → `run_grobid.py` →
`compare_grobid_openalex.py` → `analyze_three_way.py` → `diagnose_debug.py` / `header_vs_fulltext.py`.

---

## 1. Corpus reality check

Fetching 500 PDFs required walking 1,800 works: 48% expose no PDF URL at all, and 20%
of attempted downloads fail (HTML-instead-of-PDF 34%, 403-blocked, timeouts).
The corpus itself explains much of OpenAlex's missing institutions: it is heavily contaminated
with **non-papers** — Indonesian student coursework (makalah) and books, repository/working-paper
cover pages (IFPRI, MPRA, NBER, IRRI…), slide decks, factsheets, fiction books, plus scanned
microfilm with no text layer. In the refereed sample, **25% of PDFs have no affiliation printed
in the first two pages at all** — no extractor can succeed there.

## 2. GROBID vs OpenAlex (500 works, fulltext endpoint, no params)

| class | n | % |
|---|---|---|
| grobid_adds_affiliations (OpenAlex had none) | 230 | 46.0 |
| both_empty | 163 | 32.6 |
| agree | 60 | 12.0 |
| grobid_empty (OpenAlex had raw strings) | 22 | 4.4 |
| disagree | 22 | 4.4 |
| grobid_failed | 3 | 0.6 |

Mean author recall (GROBID finding OpenAlex's authors): **0.735**; 110/500 works where GROBID
found none of the OpenAlex authors (mostly cover-page/scan/non-paper layouts).

## 3. Referee verdicts (96 works: all disagree/missed + zero-author sample + controls)

| verdict vs printed truth | n |
|---|---|
| grobid_correct | 25 |
| grobid_partial | 5 |
| grobid_wrong | 7 |
| grobid_missed | 32 |
| no_affiliation_printed (GROBID-empty is correct) | 24 |
| grobid_failed (no text layer) | 3 |

**Head-to-head against what is actually printed: GROBID beats OpenAlex 26 : 14.**
GROBID recovers real affiliations OpenAlex lacks nearly twice as often as it loses information
OpenAlex has. On clean scholarly layouts (controls) GROBID is essentially always right.

## 4. Model vs code: diagnosis via the debugMode dev API

Master's endpoints accept `debugMode=1` (+ `models=` filter), returning each model's raw
token/feature/label matrix. This separates *what text the pipeline delivered* from
*what the model predicted*. Findings on the 45 flagged works:

### 4a. CODE BUG — affiliation-instance merge/duplication (confirmed)

The affiliation-address model receives **multiple** correctly-segmented affiliation instances and
labels each one correctly; the downstream TEI aggregation then merges them into one `<affiliation>`,
concatenating same-typed fields.

- `W1596367042`: printed address appears twice on the cover → TEI
  `addrLine="2033 K Street 2033 K Street"`, `postCode="20006-1002 20006-1002"`,
  `settlement="Washington Washington"`. Debug shows two separate, perfectly-labeled sequences.
- `W3122035145` (NBER, Kane & Staiger): Harvard + Dartmouth affiliations scrambled into one string.
- `W1511318241` (header mode): "Clemson University, The World Bank IMF" — three institutions
  comma-merged into one affiliation.

Reproduce:
```bash
curl -F "input=@pdfs/W1596367042.pdf" -F "debugMode=1" -F "models=affiliation-address" \
     http://localhost:8070/api/processHeaderDocument
```

### 4b. CODE/PIPELINE BUG — fulltext mode degrades header extraction (confirmed)

Same PDF, same server: `processHeaderDocument` and `processFulltextDocument` disagree on header
affiliations in **7/45** flagged works, and header mode is closer to the truth in nearly all:

- `W2121781357` (MPRA): header mode → 3 authors each with "Central Bank of Ireland" (correct);
  fulltext mode → **empty** analytic block.
- `W1571399024` / `W1540316733` (IFPRI): header mode finds CEEPA / DSGD (correct, though merge-bugged);
  fulltext mode outputs the publisher street address plus the garbage affiliation **"Effective January"**.
- `W4206013105`: header mode finds "UNIVERSITAS ISLAM NEGERI ALAUDDIN MAKASSAR"; fulltext mode: nothing.

The affiliation-address model is blameless here — in header mode's debug the header model marks the
right `<affiliation>` tokens and the affiliation model labels them correctly. The divergence is in the
fulltext path (segmentation assigns cover/front zones differently before the header model runs).

Reproduce:
```bash
curl -F "input=@pdfs/W2121781357.pdf" http://localhost:8070/api/processHeaderDocument   # has affiliation
curl -F "input=@pdfs/W2121781357.pdf" http://localhost:8070/api/processFulltextDocument # empty analytic
```

### 4c. MODEL limitation — header model never marks the affiliation zone (26/45, the biggest bucket)

`debugMode` shows the header model labeling the printed affiliation text as `<other>`/`<title>`/etc.,
so the affiliation-address model never fires. Typical layouts: working-paper/repository cover pages,
affiliations printed on page 2, footnote-style affiliations ("MIT. Email: aaronson@…"),
prose footnotes ("…are with Ant Group"), ALL-CAPS Indonesian cover sheets. This is a training-data
gap of the **header** model (not affiliation-address) for non-journal layouts.

### 4d. MODEL error — affiliation-address on hard inputs (minor)

- `W4403334191`: ACM footer "UIST '24, October 13-16, 2024, Pittsburgh, PA, USA" parsed as an
  affiliation address (garbage-in from header zoning, but the model also happily labeled a date string).
- `W4399454054`: prose fragment "Lei Liu is with The" labeled as an institution.

### 4e. Input/corpus issues (not GROBID's fault)

- 3 works → HTTP 500 `[NO_BLOCKS] PDF parsing resulted in empty content` + 5 debug-204s:
  scanned images/microfilm with no text layer (pdfalto has nothing to work with).
- `W4246496294`: stylized spaced-letter cover text extracted as character soup
  ("NK E S A NT U NA NI MP E R A T I F…") — tokenization garbage before any model.
- Referee-agent note: one sampled work (`W4377024159`) was initially misjudged by the referee agent
  and corrected by direct re-reading — GROBID was right ("UWE Bristol").

## 5. Conclusions

1. **GROBID master materially improves on OpenAlex** for this corpus: it adds affiliations on 46%
   of works where OpenAlex has none, and against printed truth wins 26:14.
2. The dominant failure is the **header model's zoning** on non-journal layouts (cover pages,
   footnotes, page-2 affiliations) — a model/training-data issue, best addressed with training
   examples of working-paper covers, not code fixes.
3. Two **reproducible code bugs** found via the dev API:
   (a) multi-instance affiliation merge/duplication in TEI aggregation;
   (b) fulltext-mode losing/garbling header affiliations that header mode gets right
   (incl. the absurd "Effective January" affiliation).
4. The **affiliation-address CRF itself is rarely the culprit** — when given the right text it
   labels correctly in almost every diagnosed case.

## 6. Artifacts

| file                                         | content                                                       |
|----------------------------------------------|---------------------------------------------------------------|
| `works_metadata.jsonl`                       | OpenAlex work metadata + authorships for every downloaded PDF |
| `pdfs/`, `tei/`                              | PDFs and raw GROBID TEI                                       |
| `grobid_extractions.json`                    | parsed GROBID authors/affiliations                            |
| `comparison.json`                            | GROBID-vs-OpenAlex per-work classification                    |
| `referee_extractions.json`, `three_way.json` | referee readings + three-way verdicts                         |
| `debug/*.debug.txt`, `diagnosis.json`        | raw debugMode outputs + auto-classification                   |
| `header_vs_fulltext.json`                    | header-mode vs fulltext-mode divergences                      |

## 7. 1,000-PDF refresh

Fetching 1,000 PDFs required walking **3,400 works** (44% no PDF URL; 834 download failures).
GROBID processed 993/1000 (7 × HTTP 500, all `NO_BLOCKS` scans); 684 works got affiliations.

| class                    | n   | % (500-cohort %)   |
|--------------------------|-----|--------------------|
| grobid_adds_affiliations | 525 | 52.5 (46.0)        |
| both_empty               | 264 | 26.4 (32.6)        |
| agree                    | 105 | 10.5 (12.0)        |
| disagree                 | 54  | 5.4 (4.4)          |
| grobid_empty             | 45  | 4.5 (4.4)          |
| grobid_failed            | 7   | 0.7 (0.6)          |

Mean author recall vs OpenAlex: **0.757** (0.735 on the first 500); zero-author works: 195/1000.
The second 500 works confirm the first cohort's picture — proportions are stable, so the
referee-based diagnosis in sections 3–5 stands. The referee/diagnosis pass was run on the
first-500 sample; the per-work data for all 1,000 is in `comparison.json`.

## 8. Branch comparison: master vs `improvement/affiliation-author`

Same 1,000 PDFs re-run on a second server built from `improvement/affiliation-author`
(`360edd6ec`, rev `0.9.0-77`, 26 commits ahead of master). Outputs in `tei_branch/`,
`grobid_extractions_branch.json`, `comparison_branch.json`, diff in `branch_diff.json`.

**Coarse metrics are unchanged** — identical class distribution vs OpenAlex, identical author
recall (0.757), zero class transitions. The branch does not find affiliations master misses;
it changes how found affiliations are **structured**:

| full-corpus diff (1,000 works)          | n                              |
|-----------------------------------------|--------------------------------|
| affiliation strings identical           | 770                            |
| affiliation content changed             | 230                            |
| — gained affiliation instances (splits) | 186                            |
| — lost instances                        | 5                              |
| author→affiliation links changed        | 440 (289 more links, 65 fewer) |

**The branch fixes the section-4a merge/duplication code bug.** Canonical cases:

- `W1596367042` — master: one blob with every address field duplicated
  (`2033 K Street 2033 K Street … Washington Washington`); branch: two clean separate instances,
  no intra-field duplication.
- `W3122035145` — master: Harvard + Dartmouth scrambled into one string; branch: cleanly split
  into the two correct affiliations.
- `W4403334191` — master: one garbage blob mixing two venue lines; branch: split into two
  well-formed instances (still the wrong *content* — that's the header-zoning model issue).

On the 96 refereed works: **1 verdict improved (wrong→correct), 0 regressed**; the 32 misses stay
misses because they are header-model zoning failures upstream of the branch's changes.
The section-4b fulltext-vs-header divergence is also **not** fixed by this branch
(`W2121781357` still loses "Central Bank of Ireland" in fulltext mode).

**Net assessment:** `improvement/affiliation-author` is a strict improvement on this corpus —
it repairs affiliation instance segmentation (the 4a bug) with essentially no regressions, but
recall is untouched: the big remaining win (the 32 missed works) lives in the header model's
zoning, and the 4b fulltext-path divergence remains open.
