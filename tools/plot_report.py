"""Stage 2: everything we know about ONE plot, not a settlement.

    plot_report.py --address "Budapest, Deák Ferenc tér"
    plot_report.py --at 47.4977 19.0544
    plot_report.py --at 47.4977 19.0544 --html brief.html

The settlement map ranks villages. This answers the question a village-level score
cannot: is THIS garden any good. Same sources, sampled at the point.
"""
import argparse, json, math, os, sys, urllib.parse, urllib.request
from pathlib import Path

import numpy as np
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_soil, fetch_terrain, fetch_pollution                  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
UA = "bestLocation/0.1 (personal house-search tool)"
DRIVE_KMH, PARK_MIN, EGRESS_MIN = 40.0, 5, 15
# The soil sample is a live call to the TAKI server, whose licence is undeclared: off unless
# asked for. Without it the report's garden section says the soil source is unavailable.
SOIL_LIVE = os.environ.get("SOIL_LIVE") == "1"


def haversine(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    h = (math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p)
         * math.sin((lo2 - lo1) * p / 2) ** 2)
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def geocode(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "json", "limit": 1, "countrycodes": "hu"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        res = json.loads(r.read())
    if not res:
        raise SystemExit(f"could not geocode: {q!r}")
    return float(res[0]["lat"]), float(res[0]["lon"]), res[0]["display_name"]


_water_trees = {}


def _trees():
    """Build the flood/waterlogging indexes once; a click must not rebuild them."""
    if not _water_trees:
        for lid, name in ((8, "floodway"), (11, "floodplain"), (14, "waterlogged")):
            f = RAW / f"vir_{lid}.geojson"
            if not f.exists():
                _water_trees[name] = None
                continue
            geoms = [shape(x["geometry"]) for x in json.loads(f.read_text())["features"]
                     if x.get("geometry")]
            _water_trees[name] = STRtree(geoms)
    return _water_trees


def water(lat, lon):
    p = Point(lon, lat)
    out = {}
    for name, tree in _trees().items():
        out[name] = None if tree is None else any(
            tree.geometries.take(i).contains(p) for i in tree.query(p))
    return out


_fib = {}


def fibre(lat, lon):
    if "pts" not in _fib:
        pts = OUT / "fibre_unserved.npy"
        _fib["pts"] = np.load(pts) if pts.exists() else None
        _fib["addr"] = (json.loads((OUT / "fibre_unserved_addr.json").read_text(encoding="utf-8"))
                        if pts.exists() else [])
    a = _fib["pts"]
    if a is None:
        return None
    d = np.hypot((a[:, 0] - lat) * 111.0, (a[:, 1] - lon) * 111.0 * math.cos(math.radians(lat)))
    i = int(np.argmin(d))
    return {"nearest_km": round(float(d[i]), 3), "address": _fib["addr"][i],
            "within_100m": int((d < 0.1).sum()), "within_500m": int((d < 0.5).sum())}


_stations = []


def rail(lat, lon):
    if not _stations:
        f = OUT / "rail_stations.json"                 # absent from the sample dataset
        if not f.exists():
            return None
        _stations.extend(json.loads(f.read_text(encoding="utf-8")))
    st = _stations
    best = None
    for s in st:
        d = haversine((lat, lon), (s["lat"], s["lon"]))
        total = s["rail_min"] + d / DRIVE_KMH * 60 + PARK_MIN + EGRESS_MIN
        if best is None or total < best[0]:
            best = (total, d, s)
    if not best:
        return None
    total, d, s = best
    return {"station": s["name"], "km": round(d, 1), "rail_min": s["rail_min"],
            "trains_am": s["trains_am"], "terminus": s["terminus"], "door_to_desk": round(total)}


_spine, _bnd = [], {}


def _boundaries():
    """ksh -> polygon, plus an index. Containment beats nearest-centroid: a plot near a
    village edge belongs to the settlement it is IN, not the one it is closest to."""
    if not _bnd:
        f = OUT / "boundaries.json"
        if f.exists():
            raw = json.loads(f.read_text(encoding="utf-8"))
            _bnd["ksh"] = list(raw)
            _bnd["geoms"] = [shape(g) for g in raw.values()]
            _bnd["tree"] = STRtree(_bnd["geoms"])
        else:
            _bnd["tree"] = None
    return _bnd


def settlement(lat, lon):
    if not _spine:
        _spine.extend(r for r in json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
                      if r.get("lat"))
    b = _boundaries()
    if b.get("tree") is not None:
        p = Point(lon, lat)
        for i in b["tree"].query(p):
            if b["geoms"][i].contains(p):
                ksh = b["ksh"][i]
                hit = next((r for r in _spine if r["ksh"] == ksh), None)
                if hit:
                    return hit, round(haversine((lat, lon), (hit["lat"], hit["lon"])), 1), True
    r = min(_spine, key=lambda x: haversine((lat, lon), (x["lat"], x["lon"])))
    return r, round(haversine((lat, lon), (r["lat"], r["lon"])), 1), False


def _try(fn, *a):
    """Simplification: one dead upstream must not take the whole report with it.

    soil, terrain and pollution each hit a live endpoint; the rest of collect()
    reads local files. A network failure in one degrades that section to missing
    data, which every consumer already renders as a dash.
    """
    try:
        return fn(*a) or {}
    except Exception as e:
        print(f"plot: {fn.__module__}.{fn.__name__} failed — {e}", file=sys.stderr)
        return {}


def collect(lat, lon):
    soil = _try(fetch_soil.sample, lon, lat) if SOIL_LIVE else {}
    tex = fetch_soil.usda(soil.get("soil_sand_pct"), soil.get("soil_silt_pct"),
                          soil.get("soil_clay_pct"))
    ter = _try(fetch_terrain.terrain, lat, lon)
    sett, dist, inside = settlement(lat, lon)
    return {
        "lat": lat, "lon": lon,
        "soil": soil | {"texture": tex, "garden_score": fetch_soil.garden(soil, tex)},
        "terrain": ter | {"south_facing": fetch_terrain.south_facing(
                              ter.get("aspect_deg"), ter.get("slope_deg", 0)),
                          "frost_risk": fetch_terrain.frost_risk(ter) if ter else None},
        "water": water(lat, lon), "fibre": fibre(lat, lon), "rail": rail(lat, lon),
        "pollution": _try(fetch_pollution.sample, lat, lon),
        "settlement": sett, "settlement_km": dist, "inside_settlement": inside,
    }


def fmt(d, label):
    s, t, w, f, r, st = d["soil"], d["terrain"], d["water"], d["fibre"], d["rail"], d["settlement"]
    L = [f"\n{'='*66}", f" {label}", f" {d['lat']:.5f}, {d['lon']:.5f}"
         f"   ·   {st['name']} ({st['megye'] or '—'})"
         f"{'' if d['inside_settlement'] else ' [nearest — point is outside any settlement]'}"
         f", centre {d['settlement_km']} km away",
         "=" * 66, "\nGARDEN"]
    L.append(f"  texture         {s.get('texture') or '—'}"
             f"   (sand {s.get('soil_sand_pct')}%  silt {s.get('soil_silt_pct')}%  clay {s.get('soil_clay_pct')}%)")
    L.append(f"  pH              {s.get('soil_ph')}        organic matter {s.get('soil_om_pct')}%"
             f"   lime {s.get('soil_lime_pct')}%")
    L.append(f"  garden score    {s.get('garden_score')}/100")
    asp = t.get("aspect_deg")
    L += ["\nTERRAIN",
          f"  elevation       {t.get('elevation_m')} m   slope {t.get('slope_deg')}°"
          f"   local relief {t.get('local_relief_m')} m",
          f"  aspect          {asp if asp is not None else 'flat'}"
          f"{'' if asp is None else '°'}   south-facing {t.get('south_facing') if t.get('south_facing') is not None else '—'}",
          f"  frost pocket    {t.get('frost_risk')}/100   (TPI {t.get('tpi_m')} m)"]
    L += ["\nWATER"]
    for k, v in w.items():
        L.append(f"  {k:14}  {'YES — avoid' if v else 'no'}")
    if f:
        L += ["\nBROADBAND (NMHH unserved survey, 2024-12-31)",
              f"  unserved addresses within 100 m: {f['within_100m']}   within 500 m: {f['within_500m']}",
              f"  nearest unserved: {f['nearest_km']} km — {f['address']}",
              "  NOTE: absence from the unserved list is not proof fibre is available."]
    po = d.get("pollution") or {}
    if po.get("pollution_nearest_km") is not None:
        L += ["\nPOINT SOURCES (OSM)"]
        for k, lab in (("landfill", "landfill"), ("quarry", "quarry"),
                       ("wwtp", "sewage plant"), ("works", "factory")):
            if po.get(f"{k}_km") is not None:
                L.append(f"  {lab:14}  {po[f'{k}_km']:.2f} km"
                         + (f"  — {po[f'{k}_name']}" if po.get(f"{k}_name") else "")
                         + (f"   [{po[f'{k}_within3']} within 3 km]" if po[f"{k}_within3"] else ""))
    if r:
        L += ["\nCOMMUTE",
              f"  {r['door_to_desk']} min door-to-desk  =  {r['km']} km to {r['station']}"
              f" + {r['rail_min']} min rail → {r['terminus']} + {EGRESS_MIN} min",
              f"  morning trains  {r['trains_am']} (06:00–09:00)"]
    L += [f"\nSETTLEMENT CONTEXT ({st['name']})",
          f"  house price     {st.get('house_price_m2') or '—'} eFt/m²"
          f" ({st.get('house_price_year') or '—'}, {st.get('house_tx') or 0} sales)"
          f"   → 120 m² ≈ {st.get('house_120m2_mhuf') or '—'} M Ft",
          f"  population      {int(st.get('pop_2022') or 0):,}"
          f"  ({st.get('pop_trend_21y_pct'):+}% since 2001)",
          f"  school          {st.get('school_score_mean') or '—'}"
          f" ({st.get('school_vs_national'):+} vs national)" if st.get('school_vs_national') is not None
          else "  school          no measured school",
          f"  óvoda           {st.get('ovoda_sites') or 0} site(s), {st.get('ovoda_places') or 0} places",
          f"  GP practice     {'UNFILLED since ' + str(st.get('gp_vacant_since')) if st.get('gp_vacant') else 'filled'}"]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--address")
    ap.add_argument("--at", nargs=2, type=float, metavar=("LAT", "LON"))
    ap.add_argument("--html")
    a = ap.parse_args()
    if a.address:
        lat, lon, label = geocode(a.address)
    elif a.at:
        lat, lon = a.at
        label = f"{lat}, {lon}"
    else:
        ap.error("give --address or --at LAT LON")
    d = collect(lat, lon)
    text = fmt(d, label)
    print(text)
    if a.html:
        Path(a.html).write_text(
            f"<meta charset=utf-8><title>{label}</title>"
            f"<body style='background:#0e0e0e;color:#e9eff6;font:13px/1.5 monospace;padding:24px'>"
            f"<pre>{text}</pre>", encoding="utf-8")
        print(f"\nwrote {a.html}")
    return d


if __name__ == "__main__":
    main()
