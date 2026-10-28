"""Turn one archived day of SNCF's real-time feed into per-station counts.

Inputs, both from the traines.eu mirror (ODbL, SNCF open data):
- every 2-minute snapshot of the GTFS-RT trip updates feed for that day;
- the static timetable published for that day (or the latest one in the 7 days before).

A train's call at a station is counted only once it is *confirmed*: the last snapshot showing
that call was taken after the train's actual (scheduled + delay) time there, or the call was
reported cancelled. Predictions about stops a train had not yet reached are never counted.
Calls the feed never confirms lower the day's coverage instead of being assumed on time.
"""
import subprocess
import tarfile
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import requests

from . import feed, gtfs
from .common import DEPT_REGION, LATE, LATE15, MIRROR, PARIS

UA = {"User-Agent": "sncf-delay-map (github.com; open data reuse)"}


def fetch(url, dest, attempts=4):
    # The mirror occasionally drops connections; retry with a growing pause.
    for attempt in range(attempts):
        try:
            with requests.get(url, headers=UA, timeout=300, stream=True) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            return
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
            time.sleep(10 * (attempt + 1))


def snapshot_ts(name):
    # "2026-10-26/2026-10-26T00:02:01+01:00.sncf-gtfs-rt-trip-updates"
    return int(datetime.fromisoformat(Path(name).name.split(".")[0]).timestamp())


def process(day, gtfs_url, depts):
    day_start = int(datetime(day.year, day.month, day.day, tzinfo=PARIS).timestamp())
    nxt = day + timedelta(1)
    day_end = int(datetime(nxt.year, nxt.month, nxt.day, tzinfo=PARIS).timestamp())

    with tempfile.TemporaryDirectory() as tmp:
        gz = Path(tmp) / "gtfs.zip"
        fetch(gtfs_url, gz)
        zf = zipfile.ZipFile(gz)
        stops = gtfs.train_stops(zf, depts)
        sched = gtfs.scheduled_calls(zf, stops, day, day_start, day_end)

        tar_path = Path(tmp) / "rt.tar.br"
        fetch(f"{MIRROR}/french-gtfs-rt/{day.isoformat()}.tar.br", tar_path)
        unbrotli = subprocess.Popen(["brotli", "-dc", str(tar_path)], stdout=subprocess.PIPE)
        latest, sizes, bad = {}, [], 0
        with tarfile.open(fileobj=unbrotli.stdout, mode="r|") as tf:
            for m in tf:
                if not m.isfile() or "trip-updates" not in m.name:
                    continue
                ts = snapshot_ts(m.name)
                try:
                    n, calls = feed.parse(tf.extractfile(m).read(), stops, ts)
                except Exception:
                    bad += 1
                    continue
                sizes.append(n)
                for k, c in calls.items():
                    if k not in latest or latest[k][4] <= ts:
                        latest[k] = c
        if unbrotli.wait() != 0:
            raise RuntimeError(f"{day}: archive did not decompress cleanly")

    per_stop = defaultdict(lambda: [0, 0, 0, 0, 0])  # confirmed, late, late15, cancelled, delay seconds
    ter = defaultdict(lambda: [0, 0, 0])              # region -> trains, late, cancelled
    unconfirmed = 0
    for stop_id, sched_ts, delay, cancelled, seen_ts, origin in latest.values():
        if not day_start <= sched_ts < day_end:
            continue
        if not (cancelled or seen_ts >= sched_ts + delay):
            unconfirmed += 1
            continue
        a = per_stop[stop_id]
        a[0] += 1
        if cancelled:
            a[3] += 1
        else:
            a[1] += delay >= LATE
            a[2] += delay >= LATE15
            a[4] += max(delay, 0)
        _, dept, mode, _, _ = stops[stop_id]
        if origin and mode == "ter":
            # SNCF reports TER per region; trains ending in Paris belong to the region they come from.
            region = DEPT_REGION[dept]
            if region == "Île-de-France" and origin in stops:
                region = DEPT_REGION[stops[origin][1]]
            t = ter[region]
            t[0] += 1
            t[1] += not cancelled and delay >= LATE
            t[2] += cancelled

    rows = []
    for stop_id in sorted(set(sched) | set(per_stop)):
        seen, late, late15, canc, delay_s = per_stop.get(stop_id, [0] * 5)
        rows.append((stop_id, sched.get(stop_id, 0), seen, late, late15, canc, delay_s))
    total_sched = sum(sched.values())
    total_seen = sum(r[2] for r in rows)
    # Coverage per stop is capped at its timetable, so re-routed trains cannot inflate it.
    covered = sum(min(r[2], r[1]) for r in rows)
    sizes.sort()
    report = {
        "gtfs": gtfs_url.split("/french-gtfs/")[1][:10],
        "snapshots": len(sizes),
        "unreadable_snapshots": bad,
        "empty_snapshots": sum(1 for s in sizes if s < 50),
        "median_trains_in_feed": sizes[len(sizes) // 2] if sizes else 0,
        "scheduled": total_sched,
        "confirmed": total_seen,
        "unconfirmed": unconfirmed,
        "coverage": round(covered / total_sched, 4) if total_sched else 0,
        "ter_terminus": {r: v for r, v in sorted(ter.items())},
    }
    return stops, rows, report
