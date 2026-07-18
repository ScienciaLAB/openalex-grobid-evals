#!/usr/bin/env python3
"""Compare GROBID header extractions against OpenAlex authorships.

Inputs:  works_metadata.jsonl (OpenAlex), grobid_extractions.json (GROBID)
Output:  comparison.json + printed summary

Per-work classification:
  both_empty              neither OpenAlex nor GROBID has affiliations
  grobid_adds_affiliations OpenAlex has none, GROBID found some (expected win)
  agree                   both have affiliations and they match
  disagree                both have affiliations but they don't line up
  grobid_empty            OpenAlex has raw affiliation strings, GROBID found none
  grobid_failed           GROBID processing failed for the PDF
"""

import json
import os
import re
import unicodedata

from rapidfuzz import fuzz

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def normalize(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return " ".join(s.split())


def authors_match(grobid_name, openalex_name):
    """Fuzzy author-name match, tolerant to initials and name order."""
    a, b = normalize(grobid_name), normalize(openalex_name)
    if not a or not b:
        return False
    if fuzz.token_sort_ratio(a, b) >= 85:
        return True
    # initials-aware: "a nagrani" vs "arsha nagrani"
    ta, tb = a.split(), b.split()
    if ta and tb and ta[-1] == tb[-1]:  # same surname
        ia = {t[0] for t in ta[:-1]}
        ib = {t[0] for t in tb[:-1]}
        if ia and ib and (ia <= ib or ib <= ia):
            return True
    return False


def affiliations_match(grobid_aff, openalex_raw):
    """Decide whether a GROBID structured affiliation and an OpenAlex raw
    affiliation string refer to the same affiliation.

    TODO(luca): this rule directly shapes the agree/disagree statistics.
    Points to weigh: GROBID output is reordered ("Dept, Univ, City, Country")
    vs free-form raw strings; sub-organization granularity (department vs
    university); addresses present on one side only. Replace the default
    below with your preferred rule (~5-10 lines).
    """
    a, b = normalize(grobid_aff), normalize(openalex_raw)
    if not a or not b:
        return False
    return fuzz.token_set_ratio(a, b) >= 80


def classify(oa_affs, gr_affs, gr_status):
    if gr_status != "ok":
        return "grobid_failed"
    if not oa_affs and not gr_affs:
        return "both_empty"
    if not oa_affs:
        return "grobid_adds_affiliations"
    if not gr_affs:
        return "grobid_empty"
    matched = sum(1 for oa in oa_affs if any(affiliations_match(g, oa) for g in gr_affs))
    return "agree" if matched / len(oa_affs) >= 0.5 else "disagree"


def main():
    works = {}
    with open(os.path.join(BASE_DIR, "works_metadata.jsonl")) as f:
        for line in f:
            rec = json.loads(line)
            works[rec["work_id"]] = rec
    with open(os.path.join(BASE_DIR, os.environ.get("GROBID_JSON", "grobid_extractions.json"))) as f:
        grobid = json.load(f)

    out = {}
    counts = {}
    for wid, rec in works.items():
        gr = grobid.get(wid, {"status": "missing", "authors": [], "affiliations": []})
        oa_authors = [a["display_name"] or a["raw_author_name"] or "" for a in rec["authorships"]]
        oa_affs = sorted({s for a in rec["authorships"] for s in a["raw_affiliation_strings"]})
        gr_authors = [a["name"] for a in gr["authors"] if a["name"]]
        gr_affs = gr["affiliations"]

        matched_authors = sum(
            1 for oa in oa_authors if oa and any(authors_match(g, oa) for g in gr_authors)
        )
        cls = classify(oa_affs, gr_affs, gr["status"])
        counts[cls] = counts.get(cls, 0) + 1
        out[wid] = {
            "title": rec["title"],
            "class": cls,
            "openalex_authors": oa_authors,
            "grobid_authors": gr_authors,
            "author_recall": round(matched_authors / len(oa_authors), 3) if oa_authors else None,
            "openalex_affiliations": oa_affs,
            "grobid_affiliations": gr_affs,
            "grobid_status": gr["status"],
        }

    with open(os.path.join(BASE_DIR, os.environ.get("COMPARISON_JSON", "comparison.json")), "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    total = len(out)
    print(f"works compared: {total}")
    for cls in sorted(counts, key=counts.get, reverse=True):
        print(f"  {cls:26s} {counts[cls]:4d}  ({100 * counts[cls] / total:.1f}%)")
    recalls = [v["author_recall"] for v in out.values() if v["author_recall"] is not None]
    if recalls:
        print(f"mean author recall (GROBID finds OpenAlex authors): {sum(recalls) / len(recalls):.3f}")
    zero = sum(1 for r in recalls if r == 0)
    print(f"works where GROBID found none of the OpenAlex authors: {zero}")


if __name__ == "__main__":
    main()
