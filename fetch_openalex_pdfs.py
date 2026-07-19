#!/usr/bin/env python3
"""Fetch one batch of open-access preprint PDFs from OpenAlex (continuous mode).

Filter: type:preprint,authorships.institutions.lineage:null,open_access.is_oa:true

Designed to be called repeatedly by run_pipeline.sh:
  - the OpenAlex cursor and walk counters persist in state.json, so each invocation
    continues where the previous one stopped (no re-walking);
  - each invocation downloads BATCH_SIZE new PDFs (env, default 1000) then exits 0;
  - exits 3 when the OpenAlex cursor is exhausted (loop should stop);
  - exits 1 on persistent API failure (loop should back off and retry).

Outputs (in this directory):
  pdfs/{work_id}.pdf     downloaded PDFs (magic-bytes checked)
  works_metadata.jsonl   one line per successfully downloaded work (appended)
  fetch_log.json         cumulative skip/failure accounting
  state.json             cursor + counters
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE_DIR, "pdfs")
METADATA_PATH = os.path.join(BASE_DIR, "works_metadata.jsonl")
LOG_PATH = os.path.join(BASE_DIR, "fetch_log.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "1000"))
MAILTO = os.environ.get("MAILTO", "luca@sciencialab.com")
API_URL = "https://api.openalex.org/works"
FILTER = "type:preprint,authorships.institutions.lineage:null,open_access.is_oa:true"
SELECT = "id,doi,title,authorships,best_oa_location,primary_location,locations,primary_topic"
PER_PAGE = 200
DOWNLOAD_TIMEOUT = 30
MAX_PDF_BYTES = 30 * 1024 * 1024
DOWNLOAD_WORKERS = int(os.environ.get("WORKERS", "3"))

UA = f"grobid-affiliation-eval/0.1 (mailto:{MAILTO})"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def load_json(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def pdf_url_for(work):
    for loc in [work.get("best_oa_location"), work.get("primary_location")] + (work.get("locations") or []):
        if loc and loc.get("pdf_url"):
            return loc["pdf_url"]
    return None


def work_record(work, pdf_url):
    authorships = []
    for a in work.get("authorships") or []:
        authorships.append({
            "author_position": a.get("author_position"),
            "display_name": (a.get("author") or {}).get("display_name"),
            "raw_author_name": a.get("raw_author_name"),
            "raw_affiliation_strings": a.get("raw_affiliation_strings") or [],
        })
    pt = work.get("primary_topic") or {}
    source = (((work.get("primary_location") or {}).get("source")) or {}).get("display_name")
    return {
        "id": work["id"],
        "work_id": work["id"].rsplit("/", 1)[-1],
        "doi": work.get("doi"),
        "title": work.get("title"),
        "pdf_url": pdf_url,
        "source": source,
        "field": ((pt.get("field") or {}).get("display_name")),
        "domain": ((pt.get("domain") or {}).get("display_name")),
        "authorships": authorships,
    }


def download_pdf(record):
    work_id, url = record["work_id"], record["pdf_url"]
    dest = os.path.join(PDF_DIR, f"{work_id}.pdf")
    if os.path.exists(dest):
        return record, "ok"
    try:
        with requests.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True,
                          headers={"User-Agent": BROWSER_UA}, allow_redirects=True) as r:
            if r.status_code != 200:
                return record, f"http {r.status_code}"
            buf, total = [], 0
            for chunk in r.iter_content(chunk_size=65536):
                buf.append(chunk)
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    return record, "too large"
            data = b"".join(buf)
    except requests.RequestException as e:
        return record, f"error: {type(e).__name__}"
    if not data[:1024].lstrip().startswith(b"%PDF"):
        return record, "not a pdf"
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    return record, "ok"


def main():
    os.makedirs(PDF_DIR, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = UA

    state = load_json(STATE_PATH, {"next_cursor": "*", "walked": 0, "no_pdf_url": 0,
                                   "saved": 0, "exhausted": False})
    if state.get("exhausted"):
        print("cursor already exhausted")
        sys.exit(3)
    log = load_json(LOG_PATH, {"download_failures": []})
    failures = log["download_failures"]

    # never re-record works already saved (works_metadata is the source of truth)
    already_saved = set()
    if os.path.exists(METADATA_PATH):
        with open(METADATA_PATH) as f:
            for line in f:
                already_saved.add(json.loads(line)["work_id"])
    state["saved"] = len(already_saved)
    target = state["saved"] + BATCH_SIZE

    meta_f = open(METADATA_PATH, "a")
    cursor = state["next_cursor"]

    def persist():
        state["next_cursor"] = cursor
        with open(STATE_PATH + ".tmp", "w") as f:
            json.dump(state, f, indent=2)
        os.replace(STATE_PATH + ".tmp", STATE_PATH)
        with open(LOG_PATH, "w") as f:
            json.dump({"walked_works": state["walked"],
                       "works_without_pdf_url": state["no_pdf_url"],
                       "saved_pdfs": state["saved"],
                       "download_failures": failures}, f, indent=2)

    while state["saved"] < target:
        if os.path.exists(os.path.join(BASE_DIR, "STOP")):
            persist()
            print("STOP sentinel found mid-fetch, exiting cleanly")
            break
        if cursor is None:
            state["exhausted"] = True
            persist()
            print("OpenAlex cursor exhausted")
            sys.exit(3)
        for attempt in range(5):
            try:
                resp = session.get(API_URL, params={
                    "filter": FILTER, "select": SELECT, "per-page": PER_PAGE,
                    "cursor": cursor, "mailto": MAILTO,
                }, timeout=60)
                if resp.status_code == 200:
                    break
                time.sleep(5 * (attempt + 1))
            except requests.RequestException:
                time.sleep(5 * (attempt + 1))
        else:
            persist()
            print("OpenAlex API kept failing", file=sys.stderr)
            sys.exit(1)

        page = resp.json()
        cursor = page["meta"].get("next_cursor")
        works = page.get("results", [])
        state["walked"] += len(works)
        if not works:
            cursor = None
            continue

        candidates = []
        for w in works:
            wid = w["id"].rsplit("/", 1)[-1]
            if wid in already_saved:
                continue
            url = pdf_url_for(w)
            if url:
                candidates.append(work_record(w, url))
            else:
                state["no_pdf_url"] += 1

        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            futures = [pool.submit(download_pdf, rec) for rec in candidates]
            for fut in as_completed(futures):
                rec, status = fut.result()
                if status == "ok" and rec["work_id"] not in already_saved:
                    already_saved.add(rec["work_id"])
                    state["saved"] += 1
                    meta_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    meta_f.flush()
                elif status != "ok":
                    failures.append({"work_id": rec["work_id"], "url": rec["pdf_url"],
                                     "status": status})

        persist()
        print(f"walked={state['walked']} saved={state['saved']}/{target} "
              f"no_pdf_url={state['no_pdf_url']} failed={len(failures)}", flush=True)

    meta_f.close()
    print(f"BATCH DONE saved={state['saved']}")


if __name__ == "__main__":
    main()
