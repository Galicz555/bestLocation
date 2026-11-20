"""Emit the real 'last fetched' date for each source, from its cached file's mtime.

Hand-typed dates rot. These come from the artefact the layer was actually built from,
so the UI cannot claim a freshness the data does not have.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/out"

# source id in the app  ->  the file that layer was built from
FILES = {
    "bnd":   "data/raw/kozighatarok.zip",
    "hnt":   "data/raw/hnt_2025.xlsx",
    "cen":   "data/raw/census/age.json",
    "okm":   "data/raw/okm_2025.xlsx",
    "kir":   "data/raw/kir_sites.xlsx",
    "gp":    "data/raw/okfo_gp.html",
    "price": "data/raw/ksh_ingatlan.json",
    "soil":  "data/raw/soil_samples.json",
    "dem":   "data/raw/terrain",
    "water": "data/raw/vir_11.geojson",
    "gtfs":  "data/raw/gtfs/mav/stop_times.txt",
    "fibre": "data/raw/nmhh_unserved_fixed.xlsx",
    "crime": "data/raw/ksh_crime_iga0008.csv",
    "src":   "data/raw/osm_pollution/landfill.json",
    "solar": "data/raw/pvgis.json",
    "clim":  "data/raw/era5_climate.json",
    "air":   "data/raw/cams_air.json",
    "lc":    "data/raw/worldcover_100m.npz",
    "hydro": "data/raw/vir_water_6.geojson",
}


def main():
    out = {}
    for sid, rel in FILES.items():
        p = ROOT / rel
        if not p.exists():
            out[sid] = None
            continue
        ts = p.stat().st_mtime
        out[sid] = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    (OUT / "source_dates.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    missing = [k for k, v in out.items() if v is None]
    print(f"{sum(1 for v in out.values() if v)}/{len(out)} forrás dátumozva")
    if missing:
        print("  hiányzó cache-fájl:", missing)
    for k, v in sorted(out.items(), key=lambda kv: (kv[1] or "")):
        print(f"  {k:7} {v or '—'}")
    return out


if __name__ == "__main__":
    d = main()
    assert sum(1 for v in d.values() if v) >= 15, "túl kevés forrásnak van dátuma"
    print("self-check OK")
