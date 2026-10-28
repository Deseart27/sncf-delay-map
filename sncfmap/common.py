"""Shared paths, constants and geography helpers."""
import json
import re
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"            # the committed dataset
DAYS = DATA / "days"
REF = DATA / "ref"
CACHE = ROOT / ".cache"         # downloads, never committed
SITE = ROOT / "site"            # build output, deployed to GitHub Pages
PARIS = ZoneInfo("Europe/Paris")

MIRROR = "http://mirror.traines.eu"
ODS = "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets"

# GTFS stop_id prefix ("StopPoint:OCE<mode>-<uic>") -> mode bucket. Coaches and shuttles are left out.
MODES = {
    "TGV INOUI": "tgv", "OUIGO": "tgv", "ICE": "tgv", "Lyria": "tgv",
    "INTERCITES": "ic", "INTERCITES de nuit": "ic",
    "Train TER": "ter", "TramTrain": "ter", "Train": "ter",
}

# The feed gives delays in whole minutes. SNCF counts a train late from 5 min 59 s ("more than
# 5 minutes"), which in whole minutes is 6 or more; checked against SNCF's published TER figures.
LATE, LATE15 = 360, 900

REGIONS = {
    "Auvergne-Rhône-Alpes": "01 03 07 15 26 38 42 43 63 69 73 74",
    "Bourgogne-Franche-Comté": "21 25 39 58 70 71 89 90",
    "Bretagne": "22 29 35 56",
    "Centre Val-de-Loire": "18 28 36 37 41 45",
    "Grand Est": "08 10 51 52 54 55 57 67 68 88",
    "Hauts-de-France": "02 59 60 62 80",
    "Île-de-France": "75 77 78 91 92 93 94 95",
    "Normandie": "14 27 50 61 76",
    "Nouvelle Aquitaine": "16 17 19 23 24 33 40 47 64 79 86 87",
    "Occitanie": "09 11 12 30 31 32 34 46 48 65 66 81 82",
    "Pays-de-la-Loire": "44 49 53 72 85",
    "Provence Alpes Côte d'Azur": "04 05 06 13 83 84",
    "Corse": "2A 2B",
}
DEPT_REGION = {d: r for r, ds in REGIONS.items() for d in ds.split()}


def normalize(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", name).strip()


def stop_mode(stop_id):
    # "StopPoint:OCETGV INOUI-87773002" -> "tgv"
    if not stop_id.startswith("StopPoint:OCE"):
        return None
    return MODES.get(stop_id[len("StopPoint:OCE"):].rsplit("-", 1)[0])


class Departments:
    """Station coordinates -> metropolitan département code, using full-resolution boundaries.

    Checked against SNCF's station list: the only disagreements (Grasse, Luc, Romanèche-Thorins)
    are errors in that list. Stations abroad (Monaco, Basel, ...) get no département.
    """

    def __init__(self):
        geo = json.loads((REF / "departements-precise.geojson").read_text())
        self.codes = [f["properties"]["code"] for f in geo["features"]]
        self.tree = STRtree([shape(f["geometry"]) for f in geo["features"]])

    def locate(self, lon, lat):
        p = Point(lon, lat)
        for i in self.tree.query(p):
            if self.tree.geometries[i].contains(p):
                return self.codes[i]
        return None
