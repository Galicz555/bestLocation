"""Cut the committed sample dataset (data/sample/) out of a full build.

    python3 tools/build_sample.py [SRC]      SRC = a full build's data/out (default: data/out)

The sample is what a fresh clone serves: every settlement within RADIUS_KM of central
Budapest (the 23 districts and their ring, ~110 settlements), run through the same field
lists the app and the server use. Fields from sources that do not permit redistribution are
left out entirely, and the app treats them as missing:
  soil_*, garden_score                     HUN-REN ATK TAKI soil rasters (licence undeclared)
  in_flood*/in_waterlogged, *river*, lake_*, water_km, floodplain_dist_km
                                           OVF water layers (redistribution needs permission)
"""
import json, math, sys
from pathlib import Path

import atomicjson
from build_app_data import KEEP
from build_source_dates import FILES
from serve import PLOT_FIELDS

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data/sample"
CENTRE, RADIUS_KM = (47.4977, 19.0544), 30.0       # Deák Ferenc tér
STRIP_PREFIX = ("soil_", "in_flood", "bigriver_", "lake_")
STRIP = {"garden_score", "in_waterlogged", "water_km", "floodplain_dist_km"}
# source ids whose data the sample does not carry: no "last fetched" date for them
UNDATED = {"soil", "water", "hydro", "gtfs", "fibre"}


def stripped(k):
    return k in STRIP or k.startswith(STRIP_PREFIX)


def km(a, b):
    p = math.pi / 180
    h = (math.sin((b[0] - a[0]) * p / 2) ** 2 + math.cos(a[0] * p) * math.cos(b[0] * p)
         * math.sin((b[1] - a[1]) * p / 2) ** 2)
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def main(src):
    spine = json.loads((src / "settlements.json").read_text(encoding="utf-8"))
    # "Budapest" is the city-wide aggregate the app never ranks; its districts carry it
    keep = sorted((s for s in spine if s.get("lat") and s["name"] != "Budapest"
                   and km(CENTRE, (s["lat"], s["lon"])) <= RADIUS_KM), key=lambda s: s["name"])
    ksh = {s["ksh"] for s in keep}
    DEST.mkdir(parents=True, exist_ok=True)

    def write(name, obj):
        atomicjson.write_json(DEST / name, obj, ensure_ascii=False, separators=(",", ":"))

    write("app_data.json", [{k: s.get(k) for k in KEEP if not stripped(k)} for s in keep])
    plot = ("ksh", "lat", "lon") + PLOT_FIELDS
    write("settlements.json", [{k: s.get(k) for k in plot if not stripped(k)} for s in keep])
    full = json.loads((src / "boundaries.json").read_text(encoding="utf-8"))
    write("boundaries.json", {k: full[k] for k in sorted(ksh) if k in full})
    ring = json.loads((src / "boundaries_ring.geojson").read_text(encoding="utf-8"))
    ring["features"] = [f for f in ring["features"] if f["properties"]["ksh"] in ksh]
    write("boundaries_ring.geojson", ring)
    dates = json.loads((src / "source_dates.json").read_text(encoding="utf-8"))
    (DEST / "source_dates.json").write_text(json.dumps(
        {k: None if k in UNDATED else dates.get(k) for k in FILES}, indent=1), encoding="utf-8")
    size = sum(p.stat().st_size for p in DEST.iterdir() if p.is_file())
    print(f"{len(keep)} settlements -> {DEST} ({size / 1024:.0f} KB)")
    return keep, ring


if __name__ == "__main__":
    keep, ring = main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/out")
    names = {s["name"] for s in keep}
    assert len(keep) > 80 and "Budapest 05. ker." in names and "Budapest" not in names, names
    assert len(ring["features"]) == len(keep), "a sample settlement has no polygon"
    rows = json.loads((DEST / "app_data.json").read_text(encoding="utf-8"))
    leaked = {k for r in rows for k in r if stripped(k)}
    assert not leaked, f"stripped fields in the sample: {leaked}"
    print("self-check OK")
