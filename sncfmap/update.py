"""Add every archived day that is not in the dataset yet.

Writes, per day, data/days/YYYY-MM-DD.csv.gz (one row per train stop) and its quality report in
data/manifest.json; data/stations.csv collects station names, modes and coordinates. Safe to
rerun: finished days are skipped.

    python -m sncfmap.update              # all missing days
    python -m sncfmap.update --workers 2
"""
import argparse
import csv
import gzip
import json
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import requests

from . import day as day_mod
from .common import DATA, DAYS, MIRROR, PARIS, Departments

# Timetables are archived from 14 Oct 2025, but checked against SNCF's published TER figures the
# feed under-reported disruption until late November 2025 (4 to 7 points), so those days are left out.
FIRST_DAY = date(2025, 12, 1)
COLUMNS = ["stop_id", "scheduled", "confirmed", "late", "late15", "cancelled", "delay_s"]

_depts = None


def listing(path):
    html = requests.get(f"{MIRROR}/{path}/", headers=day_mod.UA, timeout=60).text
    return re.findall(r'href="([^"?/][^"]*)"', html)


def available_days():
    rt = {date.fromisoformat(n[:10]) for n in listing("french-gtfs-rt") if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.tar\.br", n)}
    folders = sorted(date.fromisoformat(f[:10]) for f in listing("french-gtfs") if re.fullmatch(r"\d{4}-\d{2}-\d{2}/", f))
    return rt, folders


def gtfs_url(day, folders, cache={}):
    # That day's timetable, or the latest one published in the week before.
    for i in range(8):
        d = day - timedelta(i)
        if d in folders:
            if d not in cache:
                zips = [f for f in listing(f"french-gtfs/{d}") if f.endswith(".zip")]
                cache[d] = f"{MIRROR}/french-gtfs/{d}/{zips[0]}" if zips else None
            if cache[d]:
                return cache[d]
    return None


def work(day, url):
    global _depts
    _depts = _depts or Departments()
    return day, *day_mod.process(day, url, _depts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--from", dest="start", type=date.fromisoformat, default=FIRST_DAY)
    args = ap.parse_args()

    DAYS.mkdir(parents=True, exist_ok=True)
    manifest_path = DATA / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    stations_path = DATA / "stations.csv"
    stations = {}
    if stations_path.exists():
        with open(stations_path) as f:
            stations = {r["stop_id"]: (r["name"], r["mode"], r["lat"], r["lon"]) for r in csv.DictReader(f)}

    rt_days, folders = available_days()
    today = datetime.now(PARIS).date()
    jobs = []
    for d in sorted(rt_days):
        if d < args.start or d >= today or d.isoformat() in manifest:
            continue
        url = gtfs_url(d, folders)
        if url:
            jobs.append((d, url))
    print(f"{len(jobs)} new days to process", flush=True)

    with ProcessPoolExecutor(args.workers) as pool:
        futures = [pool.submit(work, d, u) for d, u in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                d, stops, rows, report = fut.result()
            except Exception as e:
                # Leave the day out of the manifest so the next run retries it.
                print(f"[{i}/{len(jobs)}] failed: {e!r}", flush=True)
                continue
            with gzip.open(DAYS / f"{d}.csv.gz", "wt", newline="") as f:
                w = csv.writer(f)
                w.writerow(COLUMNS)
                w.writerows(rows)
            # Coordinates, not départements, are stored, so boundary fixes never need a reprocess.
            stations.update({k: (name, mode, lat, lon) for k, (name, _, mode, lat, lon) in stops.items()})
            manifest[d.isoformat()] = report
            print(f"[{i}/{len(jobs)}] {d}: coverage {report['coverage']:.1%}, "
                  f"{report['snapshots']} snapshots, {report['confirmed']} confirmed calls", flush=True)
            # Save as we go, so an interrupted run keeps its progress.
            manifest_path.write_text(json.dumps(dict(sorted(manifest.items())), indent=1, ensure_ascii=False))
            with open(stations_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["stop_id", "name", "mode", "lat", "lon"])
                w.writerows((k, *v) for k, v in sorted(stations.items()))


if __name__ == "__main__":
    main()
