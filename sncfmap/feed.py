"""Parse one snapshot of SNCF's GTFS-RT trip updates feed."""
from google.transit import gtfs_realtime_pb2 as rt

ADDED, CANCELED = 1, 3
SKIPPED = 1


def parse(raw, stops, seen_ts):
    """Feed bytes -> (number of trains in feed, {(start_date, trip_id, stop_id): Call}).

    A Call is (stop_id, sched_ts, delay, cancelled, seen_ts, origin_stop_id or None).
    The origin is only filled on a train's last stop, where it is needed to tell which region runs it.
    """
    feed = rt.FeedMessage()
    feed.ParseFromString(raw)
    calls = {}
    for e in feed.entity:
        tu = e.trip_update
        # Extra trains are not in the timetable; they have no scheduled call to compare against.
        if tu.trip.schedule_relationship == ADDED:
            continue
        trip_cancelled = tu.trip.schedule_relationship == CANCELED
        updates = tu.stop_time_update
        for i, s in enumerate(updates):
            if s.stop_id not in stops:
                continue
            ev = s.arrival if s.HasField("arrival") else s.departure
            if not ev.time:
                continue
            cancelled = trip_cancelled or s.schedule_relationship == SKIPPED
            calls[(tu.trip.start_date, tu.trip.trip_id, s.stop_id)] = (
                s.stop_id, ev.time - ev.delay, 0 if cancelled else ev.delay, cancelled, seen_ts,
                updates[0].stop_id if i == len(updates) - 1 else None)
    return len(feed.entity), calls
