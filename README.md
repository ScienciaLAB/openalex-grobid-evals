# GROBID-master vs OpenAlex — continuous affiliation-extraction evaluation

Self-contained bundle that measures how much GROBID **master** improves author/affiliation
extraction over OpenAlex, on OA preprints where OpenAlex resolved no institution
(`type:preprint, authorships.institutions.lineage:null, open_access.is_oa:true`, ~3.25M works).
It fetches PDFs continuously, runs them through a local GROBID master
(`processFulltextDocument`, **no parameters**), compares against OpenAlex authorships, and
maintains cumulative statistics until stopped.

## Prerequisites

- Linux/macOS server with: git, curl, Python ≥ 3.9, **JDK 17**
  (no JDK? `curl -s "https://get.sdkman.io" | bash && sdk install java 17.0.10-tem`)
- Disk: with the default `KEEP_PDFS=flagged` only flagged-case PDFs are retained;
  TEI accumulates at ≈ 30–60 MB per 1,000 works.

## Deploy

```bash
ssh <server>
git clone git@github.com:ScienciaLAB/openalex-grobid-evals.git && cd openalex-grobid-evals
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./setup_grobid.sh          # clone + build GROBID master (~10 min first time)
./run_server.sh            # start GROBID on :8070, waits until healthy
nohup ./run_pipeline.sh >> pipeline.log 2>&1 &
```

Review `config.env` first if you want a different batch size, PDF retention, or ports.
Concurrency is capped at 3 parallel requests by design.

## Operate

| action | command |
|---|---|
| watch progress | `tail -f pipeline.log` or `cat SUMMARY.md` |
| stop gracefully (after current stage) | `touch STOP` |
| resume later | `rm -f STOP && nohup ./run_pipeline.sh >> pipeline.log 2>&1 &` |
| stop GROBID server | `./run_server.sh stop` |
| re-point at newer master | `touch STOP`, wait, `./setup_grobid.sh && ./run_server.sh && rm STOP`, relaunch |

Everything is resumable: the OpenAlex cursor persists in `state.json`, downloads and GROBID
results are cached and merged, and a restarted pipeline continues where it stopped instead of
re-walking OpenAlex from the beginning.

## Outputs

| file | content |
|---|---|
| `SUMMARY.md` | human-readable running summary (regenerated every batch) |
| `stats.json` | cumulative stats + per-batch history (timestamps, GROBID revision) |
| `comparison.json` | per-work GROBID-vs-OpenAlex classification |
| `flagged_cases.json` | works needing interactive diagnosis (disagree / grobid_empty / failed / zero author recall) — their PDFs are kept in `pdfs/` |
| `works_metadata.jsonl` | OpenAlex metadata + authorships for every downloaded work |
| `tei/` | raw GROBID TEI per work |
| `fetch_log.json`, `state.json` | fetch accounting + cursor state |

## Retrieving results for interactive analysis

The referee/diagnosis step (Claude reading flagged PDFs and using GROBID's `debugMode=1`
dev API to separate model errors from code bugs) is intentionally **not** part of this bundle —
run it back on the workstation against:

```bash
rsync -av <server>:server-bundle/{SUMMARY.md,stats.json,comparison.json,flagged_cases.json} .
rsync -av <server>:server-bundle/pdfs/ pdfs_flagged/   # flagged-case PDFs only (with default retention)
```

## Classification semantics

Per work: `grobid_adds_affiliations` (OpenAlex had none, GROBID found some), `agree`,
`disagree` (fuzzy affiliation match below threshold), `grobid_empty` (OpenAlex has raw strings,
GROBID none), `both_empty`, `grobid_failed`. Matching is rapidfuzz `token_set_ratio ≥ 80`
after accent/punctuation normalization (`affiliations_match()` in
`compare_grobid_openalex.py` — adjust there if the rule should change).
