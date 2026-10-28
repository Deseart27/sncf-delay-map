"""Build site/index.html from the dataset: the map template with all figures inlined.

Coverage is checked per département and day: a département's day only counts when the feed
confirmed at least MIN_COVERAGE of its timetabled train stops. Days that fail nationally are
listed on the page, so a gap in the source never shows up as good punctuality.
"""
import csv
import gzip
import json
import time
from collections import defaultdict
from datetime import date, timedelta

from .common import DATA, DAYS, REF, ROOT, SITE, Departments

MIN_COVERAGE = 0.95   # share of a département's timetabled train stops the feed confirmed that day
MIN_STATION = 30      # confirmed calls before a station can appear in a "hardest hit" list
WINDOWS = {"day": 1, "7d": 7, "30d": 30, "12m": 365, "all": None}
MODES = ("all", "tgv", "ic", "ter")


def load_day(d):
    with gzip.open(DAYS / f"{d}.csv.gz", "rt") as f:
        return [(r["stop_id"], *(int(r[k]) for k in ("scheduled", "confirmed", "late", "late15", "cancelled", "delay_s")))
                for r in csv.DictReader(f)]


def dept_coverage(rows, stations):
    sched, seen = defaultdict(int), defaultdict(int)
    for stop_id, s, c, *_ in rows:
        if stop_id in stations:
            dept = stations[stop_id][1]
            sched[dept] += s
            seen[dept] += min(c, s)
    return {d: seen[d] / sched[d] for d in sched if sched[d]}


def aggregate(days, stations):
    # stop -> [scheduled, confirmed, late, late15, cancelled, delay_s]
    acc = defaultdict(lambda: [0] * 6)
    days_counted = defaultdict(int)
    for rows in days:
        ok = {d for d, c in dept_coverage(rows, stations).items() if c >= MIN_COVERAGE}
        for d in ok:
            days_counted[d] += 1
        for stop_id, *vals in rows:
            if stop_id not in stations or stations[stop_id][1] not in ok:
                continue
            a = acc[stop_id]
            for i, v in enumerate(vals):
                a[i] += v
    out = {}
    for mode in MODES:
        depts, named = {}, defaultdict(lambda: [0] * 6)
        for stop_id, a in acc.items():
            if stop_id not in stations:
                continue
            name, dept, m = stations[stop_id]
            if mode != "all" and m != mode:
                continue
            d = depts.setdefault(dept, [0] * 6)
            s = named[(dept, name)]
            for i in range(6):
                d[i] += a[i]
                s[i] += a[i]
        top = defaultdict(list)
        for (dept, name), s in named.items():
            if s[1] >= MIN_STATION:
                top[dept].append({"name": name, "seen": s[1], "bad": s[2] + s[4]})
        out[mode] = {
            dept: {"sched": d[0], "seen": d[1], "late": d[2], "late15": d[3], "canc": d[4],
                   "avg": round(d[5] / 60 / max(d[1] - d[4], 1), 2), "days": days_counted[dept],
                   "top": sorted(top[dept], key=lambda s: (-s["bad"] / s["seen"], -s["seen"]))[:5]}
            for dept, d in depts.items() if d[1] > 0
        }
    return out


def build():
    manifest = json.loads((DATA / "manifest.json").read_text())
    depts = Departments()
    stations = {}
    with open(DATA / "stations.csv") as f:
        for r in csv.DictReader(f):
            dept = depts.locate(float(r["lon"]), float(r["lat"]))
            if dept:
                stations[r["stop_id"]] = (r["name"], dept, r["mode"])
    # Days where the feed failed nationally; individual départements are checked in aggregate().
    included = sorted(d for d, r in manifest.items() if r["coverage"] >= MIN_COVERAGE)
    if not included:
        raise SystemExit("no day passes the coverage check; refusing to build an empty map")
    latest = date.fromisoformat(included[-1])
    cache = {}

    windows = {}
    for key, n in WINDOWS.items():
        start = date.fromisoformat(min(manifest)) if n is None else latest - timedelta(n - 1)
        span = [d for d in sorted(manifest) if start.isoformat() <= d <= latest.isoformat()]
        used = [d for d in span if d in included]
        for d in used:
            if d not in cache:
                cache[d] = load_day(d)
        windows[key] = {
            "from": start.isoformat(), "to": latest.isoformat(),
            "days": len(used),
            # Share of all timetabled train stops in the period that the feed confirmed, before any filtering.
            "coverage": round(sum(manifest[d]["coverage"] * manifest[d]["scheduled"] for d in span)
                              / max(sum(manifest[d]["scheduled"] for d in span), 1), 4),
            "excluded": [{"day": d, "coverage": manifest[d]["coverage"]} for d in span if d not in included],
            "modes": aggregate([cache[d] for d in used], stations),
        }

    geo = json.loads((REF / "departements-display.geojson").read_text())

    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 3), round(c[1], 3)]

    for f in geo["features"]:
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
    validation = DATA / "validation.json"
    payload = {
        "generated": int(time.time()),
        "first_day": min(manifest), "latest": latest.isoformat(),
        "min_coverage": MIN_COVERAGE,
        "names": {f["properties"]["code"]: f["properties"]["nom"] for f in geo["features"]},
        "windows": windows,
        "validation": json.loads(validation.read_text()) if validation.exists() else None,
        "geo": geo,
    }
    SITE.mkdir(exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    html = (ROOT / "web" / "template.html").read_text().replace("/*__DATA__*/null", data)
    (SITE / "index.html").write_text(html)
    return SITE / "index.html"


if __name__ == "__main__":
    print(build())
