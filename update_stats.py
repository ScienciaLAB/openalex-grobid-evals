#!/usr/bin/env python3
"""Roll the latest comparison into cumulative stats, flag cases for later
interactive (Claude referee) analysis, and apply the PDF retention policy.

Inputs:  comparison.json (regenerated cumulatively each batch), tei/ (for revision)
Outputs: stats.json         cumulative summary + per-batch history
         SUMMARY.md          human-readable snapshot, regenerated each batch
         flagged_cases.json  works needing interactive diagnosis (PDFs retained)

KEEP_PDFS policy (env, default "flagged"):
  all      keep every downloaded PDF
  flagged  delete processed PDFs except flagged cases
  none     delete every processed PDF
"""

import glob
import json
import os
import re
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEEP_PDFS = os.environ.get("KEEP_PDFS", "flagged")

FLAG_CLASSES = {"disagree", "grobid_empty", "grobid_failed"}


def grobid_revision():
    for path in glob.glob(os.path.join(BASE_DIR, "tei", "*.tei.xml"))[:5]:
        m = re.search(r'type="revision">([^<]+)', open(path).read())
        if m:
            return m.group(1)
    return "unknown"


def main():
    comparison = json.load(open(os.path.join(BASE_DIR, "comparison.json")))
    extractions = json.load(open(os.path.join(BASE_DIR, "grobid_extractions.json")))

    counts = {}
    recalls = []
    flagged = {}
    for wid, v in comparison.items():
        counts[v["class"]] = counts.get(v["class"], 0) + 1
        if v["author_recall"] is not None:
            recalls.append(v["author_recall"])
        if v["class"] in FLAG_CLASSES or v["author_recall"] == 0:
            flagged[wid] = {
                "class": v["class"],
                "author_recall": v["author_recall"],
                "title": v["title"],
                "openalex_affiliations": v["openalex_affiliations"],
                "grobid_affiliations": v["grobid_affiliations"],
            }

    total = len(comparison)
    summary = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "grobid_revision": grobid_revision(),
        "works_compared": total,
        "class_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "mean_author_recall": round(sum(recalls) / len(recalls), 4) if recalls else None,
        "zero_author_recall_works": sum(1 for r in recalls if r == 0),
        "flagged_cases": len(flagged),
    }

    stats_path = os.path.join(BASE_DIR, "stats.json")
    stats = json.load(open(stats_path)) if os.path.exists(stats_path) else {"history": []}
    stats["current"] = summary
    stats["history"].append(summary)
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    with open(os.path.join(BASE_DIR, "flagged_cases.json"), "w") as f:
        json.dump(flagged, f, indent=2, ensure_ascii=False)

    lines = [
        "# GROBID master vs OpenAlex — running summary",
        "",
        f"Updated: {summary['updated']}  |  GROBID revision: `{summary['grobid_revision']}`",
        "",
        f"**{total} works compared** — mean author recall {summary['mean_author_recall']}, "
        f"{summary['zero_author_recall_works']} works with zero author recall, "
        f"{len(flagged)} flagged for interactive diagnosis.",
        "",
        "| class | n | % |",
        "|---|---|---|",
    ]
    for cls, n in summary["class_counts"].items():
        lines.append(f"| {cls} | {n} | {100 * n / total:.1f} |")
    lines += ["", f"Batches recorded: {len(stats['history'])}"]
    with open(os.path.join(BASE_DIR, "SUMMARY.md"), "w") as f:
        f.write("\n".join(lines) + "\n")

    # ---- PDF retention ----
    deleted = 0
    if KEEP_PDFS in ("flagged", "none"):
        for path in glob.glob(os.path.join(BASE_DIR, "pdfs", "*.pdf")):
            wid = os.path.basename(path)[:-4]
            processed = extractions.get(wid, {}).get("status") == "ok"
            keep = (KEEP_PDFS == "flagged" and wid in flagged)
            if processed and not keep:
                os.remove(path)
                deleted += 1

    print(f"stats updated: {total} works, {len(flagged)} flagged, "
          f"{deleted} PDFs removed (KEEP_PDFS={KEEP_PDFS})")


if __name__ == "__main__":
    main()
