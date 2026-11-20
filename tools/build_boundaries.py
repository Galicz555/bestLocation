"""Settlement polygons, joined to KSH codes.

admin8.shp carries names only; place.shp carries KSH_REF on a point inside each
settlement. So we join by containment - which is robust where name matching is not
(Budapest districts, renamed settlements, diacritic damage).

Two outputs:
  boundaries.json         full precision, for server-side point-in-polygon attribution
  boundaries_ring.geojson simplified, for the map's choropleth
"""
import json, sys
from pathlib import Path

import shapefile
from pyproj import Transformer
from shapely.geometry import shape, Point, mapping
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree

from fetch_schools import norm_town

# the OSM-HU shapefiles are EPSG:3857, not WGS84 (checked admin8.prj)
_T = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
to_wgs84 = lambda g: transform(lambda x, y, z=None: _T.transform(x, y), g)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/raw/kozighatarok/kozighatarok"
OUT = ROOT / "data/out"
SIMPLIFY_DEG = 0.0009      # ~70 m, invisible at the zooms this map is used at


def main():
    polys, names = [], []
    r = shapefile.Reader(str(SRC / "admin8.shp"))
    for sr in r.shapeRecords():
        g = shape(sr.shape.__geo_interface__)
        if not g.is_valid:
            g = g.buffer(0)
        polys.append(g)
        names.append(sr.record["NAME"])
    print(f"admin8 polygons: {len(polys)}")

    pts = shapefile.Reader(str(SRC / "place.shp"))
    tree = STRtree(polys)
    by_ksh = {}
    for sr in pts.shapeRecords():
        ksh = str(sr.record["KSH_REF"] or "").strip()
        if not ksh:
            continue
        p = Point(*sr.shape.points[0])
        for i in tree.query(p):
            if polys[i].contains(p):
                by_ksh.setdefault(ksh, []).append(i)
                break
    print(f"place points carrying a KSH code that fell inside a polygon: {len(by_ksh)}")

    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    by_name = {}
    for i, n in enumerate(names):
        by_name.setdefault(n, i)

    full, matched, via_name = {}, 0, 0
    for s in spine:
        idx = by_ksh.get(s["ksh"])
        i = idx[0] if idx else None
        if i is None:
            i = by_name.get(s["name"])
            if i is not None:
                via_name += 1
        if i is None:
            continue
        matched += 1
        full[s["ksh"]] = mapping(to_wgs84(polys[i]))
    print(f"settlements matched to a polygon: {matched}/{len(spine)}  ({via_name} by name)")

    # Budapest's 23 districts are their own KSH rows; admin9 carries their polygons as
    # 'XII. kerület'. The city-wide polygon keeps only what no district covers (Margitsziget),
    # so a point is never in two shapes and never falls through to a nearest-centroid guess.
    ksh_by_name = {s["name"]: s["ksh"] for s in spine}
    r9 = shapefile.Reader(str(SRC / "admin9.shp"))
    districts = {}
    for sr in r9.shapeRecords():
        ksh = ksh_by_name.get(norm_town("Budapest " + sr.record["NAME"]))
        if not ksh:
            continue
        g = shape(sr.shape.__geo_interface__)
        districts[ksh] = g if g.is_valid else g.buffer(0)
    assert len(districts) == 23, f"only {len(districts)}/23 Budapest districts matched a polygon"
    bp = ksh_by_name["Budapest"]
    rest = shape(full[bp]).difference(to_wgs84(unary_union(list(districts.values()))))
    full[bp] = mapping(rest)
    full.update({k: mapping(to_wgs84(g)) for k, g in districts.items()})

    (OUT / "boundaries.json").write_text(json.dumps(full), encoding="utf-8")

    ring = [s for s in spine if s["ksh"] in full]
    feats = []
    for s in ring:
        g = shape(full[s["ksh"]]).simplify(SIMPLIFY_DEG, preserve_topology=True)
        feats.append({"type": "Feature", "geometry": mapping(g),
                      "properties": {"ksh": s["ksh"], "name": s["name"]}})
    fc = {"type": "FeatureCollection", "features": feats}
    (OUT / "boundaries_ring.geojson").write_text(
        json.dumps(fc, separators=(",", ":")), encoding="utf-8")
    print(f"ring polygons written: {len(feats)}  "
          f"({(OUT/'boundaries_ring.geojson').stat().st_size/1024:.0f} KB simplified, "
          f"{(OUT/'boundaries.json').stat().st_size/1024/1024:.1f} MB full)")
    return full, spine


if __name__ == "__main__":
    full, spine = main()
    assert len(full) > 3000, f"only {len(full)} polygons matched"
    by = {s["name"]: s for s in spine}
    from shapely.geometry import shape as _s, Point as _P
    for name, lat, lon in [("Martonvásár", 47.3139, 18.7884), ("Vác", 47.7752, 19.1311),
                           ("Budapest 05. ker.", 47.5000, 19.0500),   # Vörösmarty tér
                           ("Budapest 12. ker.", 47.5100, 18.9700),   # Normafa
                           ("Budapest", 47.5270, 19.0490)]:           # Margitsziget
        g = _s(full[by[name]["ksh"]])
        assert g.contains(_P(lon, lat)), f"{lat},{lon} is not inside {name}'s polygon"
    # districts must not overlap, or a click resolves to whichever the index returns first
    bp = [_s(full[s["ksh"]]) for s in spine if s["name"].startswith("Budapest")]
    overlap = sum(a.intersection(b).area for i, a in enumerate(bp) for b in bp[i + 1:])
    assert overlap < 1e-7, f"Budapest polygons overlap by {overlap:.2e} deg²"
    print("self-check OK")
