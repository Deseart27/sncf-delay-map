# SNCF delay map

A map of France shaded by how often SNCF trains (TGV, Intercités, TER) are late or cancelled, per département, built from SNCF's own real-time feed and updated daily on GitHub Pages.

## What is measured

Every stop a train makes at a station counts once, in the station's département:

- **late**: arrived more than 5 minutes behind the timetable (departure at the first station). That is SNCF's own definition; the feed gives whole minutes, so it means 6 minutes or more;
- **cancelled**: the whole train, or that stop, was cancelled.

A stop only counts once the feed shows the train has actually reached it. Predictions for stops still ahead are never used. Stops the feed never confirms are not assumed to be on time; they lower **coverage** (confirmed stops ÷ timetable stops), and a département's day is left out when its coverage is too low.

The station is what counts, not the train's origin or destination. A Paris → Marseille TGV that falls 20 minutes behind after Lyon is on time at Paris and Lyon, and late at every stop after that.

## Where the data comes from

- **SNCF GTFS-RT trip updates**: every train running, with its delay at each station, every 2 minutes ([transport.data.gouv.fr](https://transport.data.gouv.fr/datasets/horaires-sncf)). The [traines.eu mirror](http://mirror.traines.eu/) archives every snapshot, one file per day.
- **SNCF GTFS timetable** for the same day, also archived by the mirror (from 14 Oct 2025). The dataset starts on 1 Dec 2025: before that, the archived feed under-reported disruption by 4 to 7 points compared with SNCF's published figures.
- **SNCF station list** (`data/ref/gares_departements.csv`), used to place border stations in the right département.

All under the Open Database License (SNCF open data).

## Accuracy check

SNCF publishes TER punctuality per region and month: trains late at their terminus (5 min 59 s or more) or cancelled. `sncfmap/validate.py` makes the same count from this dataset and compares the two. The results go in `data/validation.json` and on the page. If the agreement drops below the thresholds in `validate.py`, the workflow fails and nothing is published.

## The dataset (`data/`)

| Path | Contents |
|---|---|
| `days/YYYY-MM-DD.csv.gz` | One row per train stop: scheduled, confirmed, late (over 5 min), late15, cancelled, delay_s (sum of delays in seconds) |
| `manifest.json` | Per-day quality report: snapshots, empty snapshots, coverage, timetable used, TER per-train counts by region |
| `stations.csv` | stop_id → name, département, mode (tgv / ic / ter) |
| `validation.json` | Latest comparison with SNCF's TER figures |

## How it updates

`.github/workflows/update.yml` runs every 3 hours. It adds any day the mirror has published (`sncfmap.update`), runs the check (`sncfmap.validate`), rebuilds the page (`sncfmap.build`), commits the new data and deploys `site/` to GitHub Pages. The newest day is normally yesterday, available from about 13:00 Paris time.

## Run locally

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # needs `brotli` (brew install brotli)
.venv/bin/python -m sncfmap.update      # add missing days (first run: ~25 min, ~4 GB downloaded)
.venv/bin/python -m sncfmap.validate
.venv/bin/python -m sncfmap.build && open site/index.html
```

## Not included

- Paris-region Transilien and RER trains, which are a separate network.
- Extra trains that are not in the timetable.
- Cancellations announced before the day's timetable was published, since those trains are already gone from it. This matters on planned strike days.
- Days before 1 Dec 2025 (see above).

The mirror is run by volunteers, not by SNCF. If it stops publishing, the map stays on its last day and says so.
