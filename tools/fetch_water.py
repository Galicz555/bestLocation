"""Attach flood / waterlogging exposure from OVF's VIR vector layers.

Why these and not the AKK hazard rasters: the AKK ImageServers (Belviz_Valoszinuseg,
ArteriObl_Hmax*) time out at 90-120s with zero bytes, and the AKK hazard MapServers are
empty shells whose identify returns HTTP 500. The VIR folder answers in ~0.3s and serves
real polygons, so we download once and test points locally instead of hammering it.

  [8]  Hullamter        - the floodway between the levees. Never buy here.
  [11] Arteri oblozet   - the basin a river would flood if a levee failed.
  [14] Vizjarta terulet - land known to be water-affected; the closest open proxy for
                          belviz (inland excess water) at this granularity.

These are hazard indicators, NOT the EU Floods Directive 100-year map. Named as such.
"""
import json, sys, urllib.parse, urllib.request
from pathlib import Path

import atomicjson

from shapely.geometry import shape, Point
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
BASE = "https://geoportal.vizugy.hu/arcgis/rest/services/VIR/Belviz_fokok/MapServer"
LAYERS = {8: "floodway", 11: "floodplain", 14: "waterlogged"}


def fetch(layer):
    dest = RAW / f"vir_{layer}.geojson"
    if not dest.exists() or dest.stat().st_size < 200:
        q = urllib.parse.urlencode({"where": "1=1", "outFields": "*", "returnGeometry": "true",
                                    "outSR": "4326", "f": "geojson"})
        req = urllib.request.Request(f"{BASE}/{layer}/query?{q}",
                                     headers={"User-Agent": "bestLocation/0.1"})
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(req, timeout=300) as r:
            dest.write_bytes(r.read())
    d = json.loads(dest.read_text(encoding="utf-8"))
    geoms = [shape(f["geometry"]) for f in d["features"] if f.get("geometry")]
    geoms = [g for g in geoms if g.is_valid or g.buffer(0).is_valid]
    print(f"  layer {layer:>2} {LAYERS[layer]:12} {len(geoms)} polygons "
          f"({dest.stat().st_size/1024:.0f} KB)")
    return geoms


def main():
    print("downloading VIR polygons:")
    trees = {name: STRtree(fetch(lid)) for lid, name in LAYERS.items()}
    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))

    counts = {k: 0 for k in LAYERS.values()}
    for s in spine:
        if s.get("lat") is None:
            continue
        p = Point(s["lon"], s["lat"])
        for name, tree in trees.items():
            hit = any(tree.geometries.take(i).contains(p) for i in tree.query(p))
            s["in_" + name] = hit
            counts[name] += hit
        fp = trees["floodplain"]
        if len(fp.geometries):
            nearest = fp.geometries.take(fp.nearest(p))
            # degrees -> km, good enough at this latitude for a "how close" signal
            s["floodplain_dist_km"] = round(p.distance(nearest) * 111 * 0.74, 1) if not s["in_floodplain"] else 0.0

    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    ring = [s for s in spine if (s.get("dist_bp_km") or 999) <= 90]
    print("\nnationwide centroids inside:", counts)
    for k in LAYERS.values():
        print(f"  in the 90 km ring, {k:12}: {sum(1 for s in ring if s.get('in_'+k))}/{len(ring)}")
    return spine


def demo():
    spine = main()
    by = {s["name"]: s for s in spine}
    assert by["Martonvásár"]["in_floodway"] is False
    n_fp = sum(1 for s in spine if s.get("in_floodplain"))
    assert 50 < n_fp < 2000, f"{n_fp} settlements in a floodplain looks wrong"
    assert sum(1 for s in spine if s.get("in_floodway")) < 120, "too many centroids in the floodway"
    for s in spine:
        d = s.get("floodplain_dist_km")
        assert d is None or 0 <= d < 400, (s["name"], d)
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
