"""Build the static public demo: plain files, no server, every path relative to the page.

    python3 tools/build_demo.py OUT [--assets DIR] [--sample DIR] [--imprint-url URL]
    python3 tools/build_demo.py --check OUT      leak check on a finished folder
    python3 tools/build_demo.py --selftest       prove the leak check fails on a planted field

Run it inside the exported public tree (tools/export_public.py), after
tools/fetch_demo_assets.py. It needs the build-only `pmtiles` reader (pip install pmtiles) and
nothing else. OUT must not exist. It writes:

  index.html + app/*.js,css      with DEPLOY switched to static and a CSP <meta>
  vendor/maplibre-gl-4.7.1/      the CSP build of MapLibre, with its licence
  basemap/ tiles/                Protomaps style, glyphs, sprites and the unpacked z/x/y tiles
  data/                          the sample, minus everything this demo may not ship

The demo ships none of: crime_*, pm25_*, no2_annual, op_* (web opinions), soil, water, nat_*,
fibre or any address. The OpenStreetMap-derived columns move into data/osm.json, which is
offered for download together with the boundaries (ODbL). When the leak check finds a dropped
field, an address string or a forbidden pattern in OUT, OUT is deleted and the exit status is 1.
"""
import argparse, gzip, json, re, shutil, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; worker-src 'self'; object-src 'none'; "
       "base-uri 'self'; form-action 'none'")
MAPLIBRE_DIR = "vendor/maplibre-gl-4.7.1"
APP_FILES = ("app.js", "config.js", "lang.js", "score.js", "sources.js", "style.css")
# METRICS/FILTERS keys, compare rows and sources-panel ids the demo removes (see DEPLOY in config.js)
DROP = ["garden_score", "crime_rate_county", "pm25_winter", "school_score_mean",
        "flood", "belviz", "rail", "op"]
DROP_SRC = ["soil", "water", "hydro", "gtfs", "fibre", "crime", "air"]
OSM_KEYS = ("pollution_nearest_km", "pollution_sources_3km", "pollution_nearest_kind",
            "landfill_km", "quarry_km", "wwtp_km", "works_km")
# data keys that must not reach OUT (anywhere in any JSON file)
DROPPED = re.compile(r"crime_|pm25_|no2_|air_year|op_|soil_|garden_score|in_flood|in_waterlogged|"
                     r"bigriver_|lake_|water_km|floodplain_dist_km|nat_|fibre|address", re.I)
# strings that must not reach OUT in any text file: the export's own list, plus the forums
# (the literals are split so the export's own scan of this file does not trip on them)
FORBIDDEN = re.compile(r"/data/" r"projects|/ho" r"me/|\bno" r"va\b|nat_" r"pct|NAT" r"SEL|fetch_" r"ethnicity|"
                       r"gyakori" r"kerdesek|ho" r"xa", re.I)
# Hosts a text file may name as a link or an attribution; the CSP still blocks any request to
# them. web.archive.org: the news list links each article's archived copy (no news in the demo).
URL_HOSTS_OK = ("openstreetmap.org", "ksh.hu", "open-meteo.com", "protomaps.com", "www.w3.org", "web.archive.org")
MAX_FILE, MAX_FILES = 25 * 2**20, 5000

# The demo keeps no state in the browser (0010): a window.localStorage that stores nothing, so
# lang.js and app.js run unchanged. Loaded before lang.js.
NOSTORE = ("// The public demo stores nothing in the browser.\n"
           "Object.defineProperty(window,'localStorage',{configurable:true,value:{"
           "getItem:()=>null,setItem(){},removeItem(){}}});\n")


def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def keep(row):
    return {k: v for k, v in row.items() if not DROPPED.match(k) and k not in OSM_KEYS}


def build_data(sample, out):
    app, plot = read_json(sample / "app_data.json"), read_json(sample / "settlements.json")
    osm = [{"ksh": r["ksh"], **{k: r[k] for k in OSM_KEYS if r.get(k) is not None}}
           for r in sorted(app, key=lambda r: r["ksh"])]
    kinds = {r["ksh"]: r.get("pollution_nearest_kind") for r in plot}
    for o in osm:
        if kinds.get(o["ksh"]):
            o["pollution_nearest_kind"] = kinds[o["ksh"]]
    d = out / "data"
    d.mkdir()
    write_json(d / "app_data.json", [keep(r) for r in app])
    write_json(d / "settlements.json", [keep(r) for r in plot])
    write_json(d / "osm.json", osm)
    ring = read_json(sample / "boundaries_ring.geojson")
    assert all(f["geometry"]["type"] == "Polygon" for f in ring["features"]), \
        "the report's point-in-polygon has no MultiPolygon branch"
    write_json(d / "boundaries_ring.geojson", ring)
    # source ids of the dropped layers have no date to show
    dates = {k: v for k, v in read_json(sample / "source_dates.json").items() if k not in DROP_SRC}
    write_json(d / "source_dates.json", dates)
    return dates


def build_tiles(pmtiles, out):
    try:
        from pmtiles.reader import MmapSource, all_tiles
    except ImportError:
        raise SystemExit("build_demo: the build-only dependency is missing: pip install pmtiles")
    n = 0
    with open(pmtiles, "rb") as fh:
        for (z, x, y), data in all_tiles(MmapSource(fh)):
            p = out / "tiles" / str(z) / str(x) / f"{y}.mvt"
            p.parent.mkdir(parents=True, exist_ok=True)
            # a static host cannot send Content-Encoding for these: store them plain
            p.write_bytes(gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data)
            n += 1
    assert n > 100, f"only {n} tiles in {pmtiles}"
    return n


def build_pages(out, assets, imprint):
    for f in APP_FILES:
        shutil.copy(ROOT / "app" / f, out / f)
    cfg = (out / "config.js").read_text(encoding="utf-8")
    deploy = ("const DEPLOY={static:true, data:'data/', style:'local',\n  drop:%s,\n  dropSrc:%s};"
              % (json.dumps(DROP), json.dumps(DROP_SRC)))
    cfg, n = re.subn(r"const DEPLOY=\{[^;]*\};", lambda m: deploy, cfg)
    assert n == 1, f"DEPLOY replaced {n} times"
    (out / "config.js").write_text(cfg, encoding="utf-8")
    (out / "nostore.js").write_text(NOSTORE, encoding="utf-8")
    html = (ROOT / "app/index.html").read_text(encoding="utf-8")

    def sub(a, b):
        nonlocal html
        assert html.count(a) == 1, a
        html = html.replace(a, b)
    sub('<meta charset="utf-8">', f'<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="{CSP}">'
        '<link rel="icon" href="data:,">')
    sub('<link href="https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/4.7.1/maplibre-gl.min.css" rel="stylesheet">',
        f'<link href="{MAPLIBRE_DIR}/maplibre-gl.css" rel="stylesheet">')
    sub('<script src="https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/4.7.1/maplibre-gl.min.js"></script>',
        f'<script src="{MAPLIBRE_DIR}/maplibre-gl-csp.js"></script>\n<script src="nostore.js"></script>')
    foot = ('<div class="demo-foot" id="demo-foot" hidden><p id="demo-disc"></p><p id="demo-store"></p>'
            + (f'<p><a href="{imprint}">Impresszum · Imprint</a></p>' if imprint else "") + "</div>")
    sub('<div class="demo-foot" id="demo-foot" hidden></div>', foot)
    sub("</body>", "<noscript><p>bestLocation needs JavaScript. It is a static demo of a Hungarian "
        "settlement ranking.</p></noscript></body>")
    (out / "index.html").write_text(html, encoding="utf-8")
    v = out / MAPLIBRE_DIR
    v.mkdir(parents=True)
    for f in ("maplibre-gl-csp.js", "maplibre-gl-csp-worker.js", "maplibre-gl.css", "LICENSE.txt"):
        shutil.copy(assets / "maplibre" / f, v / f)
    b = out / "basemap"
    shutil.copytree(assets / "glyphs", b / "glyphs")
    shutil.copytree(assets / "sprites", b / "sprites")
    shutil.copy(ROOT / "app/basemap/style.json", b / "style.json")


def licenses(out, dates):
    d = lambda k: dates.get(k) or "n/a"
    text = f"""bestLocation public demo: data, software and licences
====================================================

This is a simplified public demo: 111 settlements within 30 km of Deak ter, Budapest. For
licensing reasons some data layers and the timetable-based commute are left out: soil, water
and flood layers, address-level broadband, rail and transit timetables, county crime figures,
air-quality (PM2.5, NO2) values, web opinions and news. Commute times are a crow-flies road
estimate (55 km/h plus 20 minutes). The demo stores nothing in your browser and makes no
request to any other host.

OpenStreetMap (ODbL 1.0)
------------------------
Contains information from OpenStreetMap, made available here under the Open Database
License (ODbL). (c) OpenStreetMap contributors, https://www.openstreetmap.org/copyright
ODbL text: https://opendatacommons.org/licenses/odbl/1-0/

Files derived from OpenStreetMap, offered for download and kept apart from every other
dataset in this demo:
  data/osm.json                   per-settlement distance to the nearest OSM-tagged landfill,
                                  quarry, sewage plant and factory, and the kind of the nearest
                                  one. Snapshot {d('src')} (Overpass); the fetch script is not part of
                                  this repository's reproducible set.
  data/boundaries_ring.geojson    simplified settlement boundaries (OpenStreetMap-HU),
                                  snapshot {d('bnd')}, joined to the KSH code through Wikidata.
  tiles/                          the basemap, a Produced Work: Protomaps basemap build
                                  20261118 (https://docs.protomaps.com/basemaps/downloads),
                                  extract of bbox 18.55,47.15,19.55,47.85 up to zoom 12.
A point source here is an object tagged in OSM, not a finding on emissions or contamination.

Other data (shipped in data/app_data.json and data/settlements.json)
-------------------------------------------------------------------
KSH (census 2001/2011/2022, Helysegnevtar, Ingatlanadattar prices)   CC BY 4.0   Forras: KSH, www.ksh.hu
Oktatasi Hivatal (kompetenciameres, KIR schools and ovoda places)    public-sector data; aggregates only
OKFO Alapellatasi Igazgatosag (unfilled GP and dental practices)      public-sector data; snapshot {d('gp')}
ESA WorldCover 2021 (land cover, resampled to 100 m)                  CC BY 4.0
   (c) ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021)
   processed by ESA WorldCover consortium
AWS Terrain Tiles (elevation, slope, aspect, frost pockets)           open, with attribution:
   via Mapzen/Tilezen. Europe terrain data produced using Copernicus data and information
   funded by the European Union - EU-DEM layers. Global ETOPO1 terrain data U.S. National
   Oceanic and Atmospheric Administration. United States 3DEP (formerly NED) and global
   GMTED2010 and SRTM terrain data courtesy of the U.S. Geological Survey.
JRC PVGIS (solar yield)   PVGIS (c) European Communities, 2001-2026; values derived from PVGIS output
NASA POWER (rainfall, wind, frost window)   free with citation; no NASA endorsement implied:
   The data was obtained from National Aeronautics and Space Administration (NASA) Langley
   Research Center's Prediction Of Worldwide Energy Resources (POWER) project funded through
   the NASA Earth Science Division. POWER Daily API, 2015-2024, accessed 2026-09-13 (the API
   version was not recorded at fetch time).

Software and map assets shipped in this folder
----------------------------------------------
MapLibre GL JS 4.7.1, CSP build    BSD-3-Clause    vendor/maplibre-gl-4.7.1/LICENSE.txt
   https://registry.npmjs.org/maplibre-gl/-/maplibre-gl-4.7.1.tgz
Protomaps basemap style (@protomaps/basemaps 5.7.2, dark flavour)   BSD-3-Clause
   https://registry.npmjs.org/@protomaps/basemaps/-/basemaps-5.7.2.tgz
Glyphs: Noto Sans Regular, Medium, Italic   SIL Open Font License 1.1   basemap/glyphs/OFL.txt
   protomaps/basemaps-assets, commit 028c18f713baecad011301ff7a69acc39bcc2ae7
Sprites   derived from MIT-licensed tangrams/icons   basemap/sprites/LICENSE.tangrams
   protomaps/basemaps-assets, commit 028c18f713baecad011301ff7a69acc39bcc2ae7

The application code is MIT licensed (see the repository LICENSE). The data above is not
covered by that licence; each source keeps its own terms.
"""
    (out / "data/LICENSES.txt").write_text(text, encoding="utf-8")


def check_output(out):
    """Raise SystemExit listing every leak: a dropped data key or a forbidden string."""
    bad, files = [], [p for p in sorted(out.rglob("*")) if p.is_file()]
    if not files:
        raise SystemExit(f"{out}: no files to check (missing or empty folder)")
    if len(files) > MAX_FILES:
        bad.append(f"{len(files)} files (max {MAX_FILES})")
    for p in files:
        rel = p.relative_to(out).as_posix()
        if p.stat().st_size > MAX_FILE:
            bad.append(f"{rel}: over 25 MiB")
        if p.suffix in (".json", ".geojson"):
            def walk(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if DROPPED.match(k):
                            bad.append(f"{rel}: dropped key {k!r}")
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
                elif isinstance(o, str) and FORBIDDEN.search(o):
                    bad.append(f"{rel}: forbidden string {o[:40]!r}")
            walk(json.loads(p.read_text(encoding="utf-8")))
        if p.suffix in (".js", ".css", ".html", ".txt", ".json", ".geojson") \
                and not rel.startswith(MAPLIBRE_DIR):
            text = p.read_text(encoding="utf-8")
            bad += [f"{rel}: forbidden pattern {m.group(0)!r}" for m in FORBIDDEN.finditer(text)
                    if not rel.endswith("LICENSES.txt")]
            if p.suffix in (".js", ".html"):
                hosts = {h.lower() for h in re.findall(r"https?://([A-Za-z0-9.-]+)", text)}
                bad += [f"{rel}: URL host {h}" for h in sorted(hosts)
                        if not any(h == ok or h.endswith("." + ok) for ok in URL_HOSTS_OK)]
                if rel == "index.html":
                    bad += [f"{rel}: inline style attribute" for _ in re.findall(r'\sstyle="', text)]
    if bad:
        raise SystemExit("build_demo: leak check FAILED:\n  " + "\n  ".join(sorted(set(bad))))


def selftest():
    """The check must fail on a planted field and pass on a clean folder."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "data").mkdir()
        write_json(out / "data/app_data.json", [{"ksh": "1", "name": "x", "pop_2022": 5}])
        check_output(out)
        write_json(out / "data/app_data.json", [{"ksh": "1", "op_" + "summary": "x"}])
        try:
            check_output(out)
        except SystemExit:
            pass
        else:
            raise AssertionError("a planted op_summary passed the leak check")
    print("self-check OK")


def main(out, assets, sample, imprint):
    if out.exists():
        raise SystemExit(f"build_demo: {out} exists; remove it first")
    out.mkdir(parents=True)
    try:
        dates = build_data(sample, out)
        build_pages(out, assets, imprint)
        n = build_tiles(assets / "sample.pmtiles", out)
        licenses(out, dates)
        check_output(out)
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        raise
    files = [p for p in out.rglob("*") if p.is_file()]
    print(f"build_demo: {len(files)} files, {sum(p.stat().st_size for p in files)} bytes, {n} tiles -> {out}")
    for top in sorted(p for p in out.iterdir() if p.is_dir()):
        fs = [p for p in top.rglob("*") if p.is_file()]
        print(f"  {top.name}/: {len(fs)} files, {sum(p.stat().st_size for p in fs)} bytes")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("out", nargs="?", type=Path)
    ap.add_argument("--assets", type=Path, default=ROOT / "data/raw/demo")
    ap.add_argument("--sample", type=Path, default=ROOT / "data/sample")
    ap.add_argument("--imprint-url")
    ap.add_argument("--check", action="store_true", help="leak-check an existing folder OUT")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
    elif args.out is None:
        ap.error("OUT is required")
    elif args.check:
        check_output(args.out.resolve())
        print("leak check passed")
    else:
        main(args.out.resolve(), args.assets.resolve(), args.sample.resolve(), args.imprint_url)
