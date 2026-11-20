"""Distance to water, per settlement — the 'is it by a river or a lake' dimension.

Source: OVF VIR (same service the flood layers came from), downloaded once as GeoJSON
and tested locally.

  [6] Nagy vízfolyások    46      major rivers (Danube, Tisza, Dráva, Rába…)
  [9] Tavak              503      lakes (Balaton, Velence, Tisza-tó, oxbows, ponds)

Distances are from the settlement centroid, in km.
"""
import json, math, sys, urllib.parse, urllib.request
from pathlib import Path

import atomicjson

from shapely.geometry import shape, Point
from shapely.strtree import STRtree
from shapely.ops import transform

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
BASE = "https://geoportal.vizugy.hu/arcgis/rest/services/VIR/Belviz_fokok/MapServer"
# layer 7 (kis vízfolyások, 15 982) exceeds the service's 10 000 record cap and is
# dropped deliberately: nearly every village has a brook, so it discriminates nothing.
LAYERS = {6: "bigriver", 9: "lake"}


def fetch(layer):
    dest = RAW / f"vir_water_{layer}.geojson"
    if not dest.exists() or dest.stat().st_size < 200:
        q = urllib.parse.urlencode({"where": "1=1", "outFields": "*", "returnGeometry": "true",
                                    "outSR": "4326", "f": "geojson"})
        req = urllib.request.Request(f"{BASE}/{layer}/query?{q}",
                                     headers={"User-Agent": "bestLocation/0.1"})
        with urllib.request.urlopen(req, timeout=600) as r:
            dest.write_bytes(r.read())
    d = json.loads(dest.read_text(encoding="utf-8"))
    geoms, names = [], []
    for f in d["features"]:
        if not f.get("geometry"):
            continue
        try:
            g = shape(f["geometry"])
        except Exception:
            continue
        # 26 MB of river linework makes point-distance queries crawl; ~50 m simplification
        # is invisible at the scale we report (km, one decimal)
        geoms.append(g.simplify(0.0005, preserve_topology=False))
        p = f.get("properties") or {}
        names.append(p.get("NEV") or p.get("Nev") or p.get("nev") or p.get("MEGNEVEZES"))
    print(f"  layer {layer:>2} {LAYERS[layer]:9} {len(geoms)} features "
          f"({dest.stat().st_size/1024/1024:.1f} MB)")
    return geoms, names


def main():
    print("downloading VIR hydrography:")
    data = {name: fetch(lid) for lid, name in LAYERS.items()}
    trees = {k: (STRtree(g), g, n) for k, (g, n) in data.items()}
    print("computing distances…", flush=True)

    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    KM = 111.0
    done = 0
    for s in spine:
        if not s.get("lat"):
            continue
        done += 1
        if done % 500 == 0:
            print(f"  {done}/{len(spine)}", flush=True)
        p = Point(s["lon"], s["lat"])
        kx = math.cos(math.radians(s["lat"]))
        for k, (tree, geoms, names) in trees.items():
            i = tree.nearest(p)
            g = geoms.take(i) if hasattr(geoms, "take") else geoms[i]
            # approximate degrees->km with a latitude-corrected metric
            d = p.distance(g)
            s[f"{k}_km"] = round(d * KM * (0.5 + 0.5 * kx), 2)
            s[f"{k}_name"] = names[i] if i < len(names) else None
        s["water_km"] = min(v for v in (s["bigriver_km"], s["lake_km"]) if v is not None)

    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    for k in ("bigriver_km", "lake_km", "water_km"):
        v = sorted(s[k] for s in spine if s.get(k) is not None)
        print(f"  {k:12} medián {v[len(v)//2]:.1f} km   "
              f"{sum(1 for x in v if x < 2)} település 2 km-en belül")
    return spine


def demo():
    spine = main()
    by = {s["name"]: s for s in spine}
    assert by["Vác"]["bigriver_km"] < 2, by["Vác"]["bigriver_km"]        # on the Danube
    assert by["Siófok"]["lake_km"] < 3, by["Siófok"]["lake_km"]          # on the Balaton
    assert by["Gödöllő"]["bigriver_km"] > 10, by["Gödöllő"]["bigriver_km"]
    got = [s for s in spine if s.get("water_km") is not None]
    assert len(got) > 3000, len(got)
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
