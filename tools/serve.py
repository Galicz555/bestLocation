"""Serve the app plus a /api/plot endpoint, so a map click can sample a point.

Simplification: stdlib http.server. The whole API is one route; a framework would be more
lines of dependency than of code.
"""
import json, os, posixpath, sys, traceback, urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plot_report                                            # noqa: E402
import commute                                                # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# A checkout without a full build (a fresh clone) serves the committed sample instead: the
# same files, a hundred settlements. The build scripts themselves only ever write data/out/.
SAMPLE = not (ROOT / "data/out/app_data.json").exists()
if SAMPLE:
    plot_report.OUT = commute.OUT = ROOT / "data/sample"
    commute.CACHE = commute.OUT / "commute"
# Simplification: loopback by default — this serves the whole repo dir, so it stays off the LAN
# unless asked. The container sets HOST=0.0.0.0 to make -p publishing work.
HOST = os.environ.get("HOST") or "127.0.0.1"   # empty value must not mean all-interfaces

# The document root is the repository. Without this allowlist /.git/config, /.git/index
# and the packfiles all answer 200 — a full dumb-HTTP clone — and data/raw/ (CC BY-NC
# and non-redistributable licensed source data) is browsable. Only what app/ asks for.
STATIC_DIRS = ("/app/",)
STATIC_FILES = ("/data/out/app_data.json", "/data/out/source_dates.json",
                "/data/out/boundaries_ring.geojson")

# Hungary's bounding box. The trust boundary is here, at the parse site: downstream,
# fetch_terrain.window() sizes its grid by 1/cos(lat) (lat=90 asks for 1.9 EiB) and
# commute.cached() writes a ~1 MB file per distinct coordinate.
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 45.5, 48.7, 16.0, 23.0


# The settlement fields /api/plot returns; tools/build_sample.py keeps exactly these too.
PLOT_FIELDS = (
    "name", "megye", "jaras", "pop_2022", "pop_trend_21y_pct", "house_price_m2",
    "house_price_year", "house_tx", "house_120m2_mhuf", "school_score_mean",
    "school_vs_national", "ovoda_sites", "ovoda_places", "primary_sites",
    "gimnazium_sites", "gp_vacant", "gp_vacant_since", "dentist_vacant",
    "crime_rate_county", "crime_trend_county", "crime_year",
    "precip_mm_yr", "rain_days_yr", "wind_kmh_mean", "wind_kmh_p95",
    "frost_days_yr", "hot_days_yr", "last_frost_doy", "frost_free_days",
    "pm25_annual", "pm25_winter", "no2_annual", "air_year",
    "pv_kwh_kwp", "ghi_kwh_m2",
    "lc_tree_pct", "lc_shrub_pct", "lc_grass_pct", "lc_crop_pct", "lc_built_pct", "lc_bare_pct",
    "lc_water_pct", "lc_wetland_pct", "relief_class",
    "bigriver_km", "bigriver_name", "lake_km", "lake_name", "water_km",
    "pollution_nearest_km", "pollution_sources_3km", "pollution_nearest_kind",
    "landfill_km", "quarry_km", "wwtp_km", "works_km")


def latlon(query):
    """lat/lon from a query string, or ValueError. Rejects anything outside Hungary."""
    q = urllib.parse.parse_qs(query)
    try:
        lat, lon = float(q["lat"][0]), float(q["lon"][0])
    except (KeyError, IndexError, ValueError):
        raise ValueError("lat and lon are required and must be numbers")
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        raise ValueError(f"point is outside Hungary ({LAT_MIN}–{LAT_MAX} N, "
                         f"{LON_MIN}–{LON_MAX} E)")
    return lat, lon


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, what):
        """Log the detail, return none of it: exception text leaks absolute paths."""
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        return self._json({"error": f"{what} failed — see the server log"}, 500)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path)
        if path.path == "/api/anchor":
            try:
                lat, lon = latlon(path.query)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            try:
                plot_report.settlement(lat, lon)        # ensures the spine is loaded
                return self._json(commute.cached(lat, lon, plot_report._spine))
            except Exception:
                return self._fail("anchor")
        if path.path == "/api/plot":
            try:
                lat, lon = latlon(path.query)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            try:
                d = plot_report.collect(lat, lon)
            except Exception:
                return self._fail("plot")
            st = d.pop("settlement")
            d["settlement"] = {k: st.get(k) for k in PLOT_FIELDS}
            return self._json(d)
        if path.path == "/":
            self.send_response(302)
            self.send_header("Location", "/app/index.html")
            self.end_headers()
            return
        # normalise first: "/app/../.git/config" starts with "/app/" but translate_path
        # would collapse it back out of the allowlisted directory
        p = posixpath.normpath(urllib.parse.unquote(path.path))
        if p.startswith(STATIC_DIRS) or p in STATIC_FILES:
            if SAMPLE and p in STATIC_FILES:
                self.path = p.replace("/data/out/", "/data/sample/", 1)
            return super().do_GET()
        self.send_error(404, "Not Found")


def warm():
    """Prime the module-level caches, single-threaded, before any request arrives.

    Simplification: this is load-bearing for thread-safety, not just for latency. plot_report's
    _spine/_bnd/_fib/_water_trees/_stations and commute's _net are plain dicts filled
    on first use with no lock; two concurrent first requests under ThreadingHTTPServer
    race them (commute._net.update() half-populated gives KeyError: 'seq'). Deleting
    this as "just an optimisation" opens six races. Upgrade path if it must go: a
    threading.Lock around each lazy initialiser.

    A warm-up must never be a startup gate: collect() makes live HTTPS calls, and the
    static app has to keep serving when a third-party source is down.
    """
    try:
        plot_report.collect(47.4977, 19.0544)      # fibre, water, stations, spine, boundaries
    except Exception:
        print("warm-up: plot_report.collect failed, /api/plot may be slow or down",
              file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    if not commute.has_timetable():
        print("warm-up: no GTFS timetable in data/raw/gtfs/mav, commutes are road estimates",
              file=sys.stderr)
        return
    try:
        commute.network()                          # ~5 s MAV + BKK parse; the one collect() misses
    except Exception:
        print("warm-up: commute.network failed, /api/anchor will not work",
              file=sys.stderr)
        traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8731
    if SAMPLE:
        print("no full build in data/out/: serving the sample dataset in data/sample/", flush=True)
    print("warming caches…", flush=True)
    warm()
    print(f"serving {ROOT} on http://{HOST}:{PORT}  (api: /api/plot?lat=&lon=)", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
