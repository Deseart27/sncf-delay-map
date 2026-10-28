"""Static SNCF timetable (GTFS): which train stops exist and how many calls are scheduled per stop."""
import csv
import io
from collections import Counter, defaultdict
from datetime import datetime

from .common import PARIS, stop_mode


def reader(zf, name):
    return csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="utf-8-sig"))


def service_origin(day):
    """GTFS times are measured from noon minus 12h, which differs from midnight on DST days."""
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=PARIS)
    return int(noon.timestamp()) - 12 * 3600


def secs(hms):
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def train_stops(zf, depts):
    """Train stop_id -> (name, département, mode, lat, lon). Stops abroad are dropped."""
    stops = {}
    for r in reader(zf, "stops.txt"):
        mode = stop_mode(r["stop_id"])
        if mode:
            lat, lon = float(r["stop_lat"]), float(r["stop_lon"])
            dept = depts.locate(lon, lat)
            if dept:
                stops[r["stop_id"]] = (r["stop_name"], dept, mode, lat, lon)
    return stops


def scheduled_calls(zf, stops, day, day_start, day_end):
    """Scheduled calls per train stop with a scheduled time inside [day_start, day_end).

    Trips of the previous service day that run past midnight are included, since their calls
    happen on this day.
    """
    wanted = {}
    for offset in (0, 1):
        d = datetime.fromtimestamp(day_start - offset * 86400 + 43200, PARIS).date()
        wanted[d.strftime("%Y%m%d")] = service_origin(d)
    active = defaultdict(list)
    for r in reader(zf, "calendar_dates.txt"):
        if r["exception_type"] == "1" and r["date"] in wanted:
            active[r["service_id"]].append(r["date"])
    trip_dates = {}
    for r in reader(zf, "trips.txt"):
        if r["service_id"] in active:
            trip_dates[r["trip_id"]] = active[r["service_id"]]
    counts = Counter()
    for r in reader(zf, "stop_times.txt"):
        dates = trip_dates.get(r["trip_id"])
        if not dates or r["stop_id"] not in stops:
            continue
        t = secs(r["arrival_time"] or r["departure_time"])
        for ds in dates:
            if day_start <= wanted[ds] + t < day_end:
                counts[r["stop_id"]] += 1
    return counts
