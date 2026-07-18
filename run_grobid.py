#!/usr/bin/env python3
"""Run new PDFs in pdfs/ through a local GROBID processFulltextDocument (no parameters).

Continuous-mode behavior: results merge into grobid_extractions.json across batches —
a work already present with status "ok" is never reprocessed, so PDFs deleted later by
disk hygiene (update_stats.py) keep their extraction records.

Outputs:
  tei/{work_id}.tei.xml       raw TEI responses
  grobid_extractions.json     {work_id: {authors: [...], affiliations: [...], status: ...}}
"""

import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from tqdm import tqdm

try:
    import defusedxml.ElementTree as ET
except ImportError:  # TEI comes from our own local GROBID server
    import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE_DIR, "pdfs")
TEI_DIR = os.path.join(BASE_DIR, "tei")
OUT_PATH = os.path.join(BASE_DIR, "grobid_extractions.json")

ENDPOINT = os.environ.get("GROBID_URL", "http://localhost:8070") + "/api/processFulltextDocument"
WORKERS = int(os.environ.get("WORKERS", "3"))
MAX_RETRIES = 3

TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def process_pdf(pdf_path):
    """POST the PDF with only the input field; retry on 503/empty."""
    for attempt in range(MAX_RETRIES):
        try:
            with open(pdf_path, "rb") as f:
                r = requests.post(ENDPOINT, files={"input": f}, timeout=120)
            if r.status_code == 200 and "<teiHeader" in r.text:
                return "ok", r.text
            if r.status_code == 503:  # pool exhausted, back off
                time.sleep(2 * (attempt + 1) + random.random())
                continue
            return f"http {r.status_code}", r.text[:500]
        except requests.RequestException as e:
            if attempt == MAX_RETRIES - 1:
                return f"error: {type(e).__name__}", ""
            time.sleep(2 * (attempt + 1))
    return "retries exhausted", ""


def text_of(el):
    return " ".join("".join(el.itertext()).split()) if el is not None else None


def parse_header(tei_xml):
    """Extract authors and affiliations from the TEI header biblStruct."""
    root = ET.fromstring(tei_xml)
    analytic = root.find(".//tei:teiHeader//tei:sourceDesc/tei:biblStruct/tei:analytic", TEI_NS)
    authors, affiliations = [], {}
    if analytic is None:
        return authors, []
    for author_el in analytic.findall("tei:author", TEI_NS):
        pers = author_el.find("tei:persName", TEI_NS)
        name = None
        if pers is not None:
            first = text_of(pers.find("tei:forename[@type='first']", TEI_NS))
            middle = text_of(pers.find("tei:forename[@type='middle']", TEI_NS))
            last = text_of(pers.find("tei:surname", TEI_NS))
            name = " ".join(p for p in [first, middle, last] if p) or None
        author_affs = []
        for aff_el in author_el.findall("tei:affiliation", TEI_NS):
            org_names = [text_of(o) for o in aff_el.findall("tei:orgName", TEI_NS)]
            addr = text_of(aff_el.find("tei:address", TEI_NS))
            aff_text = ", ".join([o for o in org_names if o] + ([addr] if addr else []))
            key = aff_el.get("key") or aff_text
            if aff_text:
                author_affs.append(aff_text)
                affiliations[key] = aff_text
        if name or author_affs:
            authors.append({"name": name, "affiliations": author_affs})
    return authors, sorted(set(affiliations.values()))


def run_one(work_id):
    pdf_path = os.path.join(PDF_DIR, f"{work_id}.pdf")
    tei_path = os.path.join(TEI_DIR, f"{work_id}.tei.xml")
    if os.path.exists(tei_path):
        with open(tei_path) as f:
            tei = f.read()
        status = "ok"
    else:
        status, tei = process_pdf(pdf_path)
        if status == "ok":
            with open(tei_path, "w") as f:
                f.write(tei)
    if status != "ok":
        return work_id, {"status": status, "authors": [], "affiliations": []}
    try:
        authors, affs = parse_header(tei)
    except ET.ParseError:
        return work_id, {"status": "tei parse error", "authors": [], "affiliations": []}
    return work_id, {"status": "ok", "authors": authors, "affiliations": affs}


def main():
    os.makedirs(TEI_DIR, exist_ok=True)
    results = {}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            results = json.load(f)

    all_ids = sorted(p[:-4] for p in os.listdir(PDF_DIR) if p.endswith(".pdf"))
    todo = [wid for wid in all_ids if results.get(wid, {}).get("status") != "ok"]

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(run_one, wid) for wid in todo]
        for fut in tqdm(as_completed(futures), total=len(futures), desc="grobid"):
            wid, res = fut.result()
            results[wid] = res

    with open(OUT_PATH + ".tmp", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    os.replace(OUT_PATH + ".tmp", OUT_PATH)
    n_ok = sum(1 for r in results.values() if r["status"] == "ok")
    n_affs = sum(1 for r in results.values() if r["affiliations"])
    print(f"total={len(results)} new={len(todo)} ok={n_ok} with_affiliations={n_affs}")


if __name__ == "__main__":
    main()
