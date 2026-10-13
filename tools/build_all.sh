#!/bin/sh
# Rebuild data/out/settlements.json and everything derived from it, in dependency order.
#
# Every fetch_*.py read-modify-writes the same settlements.json, so they must run
# SERIALISED — never background them, never run two at once. Most are order-independent
# beyond that, with one real exception, marked below.
#
# Raw inputs are NOT fetched here: the xlsx/csv/geojson under data/raw/ are downloaded
# by hand or by dl_worldcover.sh. This script turns raw into the app's dataset.
#
# Usage:  sh tools/build_all.sh          full rebuild
#         sh tools/build_all.sh --check  run each step's self-check instead
set -e
cd "$(dirname "$0")/.."
PY=${PY:-./.venv/bin/python}   # override to dry-run: PY=echo sh tools/build_all.sh
MODE="$1"

# data/out/ is gitignored and settlements.json is the only copy of ~1 GB of fetching.
# Keep one rollback; the fetchers write atomically, but a half-finished RUN is still bad.
if [ -f data/out/settlements.json ]; then
  cp data/out/settlements.json data/out/settlements.json.bak
  echo "=== rollback copy: data/out/settlements.json.bak"
fi

run() {                       # run SCRIPT [ARGS...]
  s=$1; shift
  echo "=== $s $*"
  $PY "tools/$s" "$@" $MODE
}

# The spine: KSH code, name, county, geometry, distance to the anchor. Everything
# else decorates it, so nothing can run before this.
run build_spine.py

# Polygons need only ksh + name from the spine, and fetch_landcover reads them: built here,
# not with the derived products, or landcover runs on the previous build's boundaries.
run build_boundaries.py       # spine -> boundaries.json + boundaries_ring.geojson

# Independent decorators, in any order among themselves.
run fetch_census.py
run fetch_schools.py
run fetch_health.py
run fetch_prices.py
run fetch_soil.py
run fetch_water.py
run fetch_crime.py
run fetch_pollution.py
run fetch_landscape_water.py
run fetch_commute.py
# Runtime commute model behind /api/anchor: refresh the daily BKK GTFS (BKK + MÁV-HÉV).
# Needs data/raw/vir_water_6.geojson from fetch_landscape_water.py (the Danube rule), so it
# must stay after it. The MÁV feed under data/raw/gtfs/mav/ is still a manual request.
run commute.py --fetch

# ORDERING CONSTRAINT: fetch_landcover reads local_relief_m to derive relief_class,
# and terrain is what writes it. Landcover before terrain silently yields "sík" for
# every settlement — no error, just a wrong column.
# --all: nationwide, not the 90 km default ring. The anchor can be moved anywhere
# (Szeged, Veszprém), and a ring-only run leaves 2535 rows without relief or frost data.
run fetch_terrain.py --all
run fetch_landcover.py

# Network-heavy and rate-limited; these three are also what run_env_chain.sh runs
# on its own when only the environment layers need refreshing.
run fetch_climate.py
run fetch_airquality.py
run fetch_solar.py

# Re-attaches cached web-opinion summaries (data/raw/opinions.json) to the fresh spine.
# Research results enter the cache only via an explicit: fetch_opinions.py --import FILE...
run fetch_opinions.py

# Derived products the app and the API actually load.
run build_fibre_index.py      # independent of the spine: nmhh xlsx -> npy + addr index
run build_app_data.py         # spine -> app_data.json, the file the browser fetches
run build_source_dates.py     # "last fetched" stamps for the sources panel

echo "=== done"
