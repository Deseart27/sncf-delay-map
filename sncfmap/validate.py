"""Check the dataset against SNCF's own published TER punctuality.

SNCF publishes, per region and month, how many TER trains were scheduled, cancelled, and late
at their terminus (5 min 59 s or more). The dataset records the same thing per day from the
real-time feed (manifest "ter_terminus"), so the two can be compared like for like.

Writes data/validation.json, which the page shows. Exits non-zero when the agreement falls
below the thresholds, so the workflow stops instead of publishing figures that no longer match.
"""
import json
import statistics
import sys
from collections import defaultdict
from datetime import date

import requests

from .build import MIN_COVERAGE
from .common import DATA, ODS

MAX_MEDIAN_GAP = 2.0     # percentage points, |ours - official| for "late or cancelled"
MIN_CORRELATION = 0.85
MIN_MONTH_DAYS = 0.9     # share of a month's days that must pass the coverage check


def official():
    r = requests.get(f"{ODS}/regularite-mensuelle-ter/exports/json", timeout=120)
    r.raise_for_status()
    out = {}
    for x in r.json():
        if x["nombre_de_trains_programmes"]:
            bad = (x["nombre_de_trains_en_retard_a_l_arrivee"] or 0) + (x["nombre_de_trains_annules"] or 0)
            out[(x["date"], x["region"])] = (x["nombre_de_trains_programmes"], bad)
    return out


def main():
    manifest = json.loads((DATA / "manifest.json").read_text())
    days_in_month = defaultdict(int)
    ours = defaultdict(lambda: [0, 0])
    for d, rep in manifest.items():
        if rep["coverage"] < MIN_COVERAGE:
            continue
        m = d[:7]
        days_in_month[m] += 1
        for region, (trains, late, canc) in rep["ter_terminus"].items():
            ours[(m, region)][0] += trains
            ours[(m, region)][1] += late + canc

    def month_len(m):
        y, mo = map(int, m.split("-"))
        return (date(y + mo // 12, mo % 12 + 1, 1) - date(y, mo, 1)).days

    try:
        ref = official()
    except requests.RequestException as e:
        # SNCF's portal being down is not a data problem: keep the last verified result.
        if (DATA / "validation.json").exists() and json.loads((DATA / "validation.json").read_text())["passed"]:
            print(f"could not fetch SNCF's figures ({e!r}); keeping the previous check")
            return
        raise
    rows = []
    for (m, region), (trains, bad) in sorted(ours.items()):
        if (m, region) not in ref or days_in_month[m] < MIN_MONTH_DAYS * month_len(m) or trains < 1000:
            continue
        sched, off_bad = ref[(m, region)]
        rows.append({"month": m, "region": region,
                     "ours": round(bad / trains * 100, 2), "official": round(off_bad / sched * 100, 2)})
    if not rows:
        print("no overlapping months yet")
        return
    gaps = [abs(r["ours"] - r["official"]) for r in rows]
    result = {
        "region_months": len(rows),
        "months": sorted({r["month"] for r in rows}),
        "median_gap_points": round(statistics.median(gaps), 2),
        "mean_difference_points": round(statistics.mean(r["ours"] - r["official"] for r in rows), 2),
        "correlation": round(statistics.correlation([r["ours"] for r in rows], [r["official"] for r in rows]), 3),
        "within_2_points": round(sum(g <= 2 for g in gaps) / len(gaps), 3),
        "rows": rows,
    }
    result["passed"] = result["median_gap_points"] <= MAX_MEDIAN_GAP and result["correlation"] >= MIN_CORRELATION
    (DATA / "validation.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print({k: v for k, v in result.items() if k != "rows"})
    if not result["passed"]:
        sys.exit("validation failed: dataset no longer matches SNCF's published TER figures")


if __name__ == "__main__":
    main()
