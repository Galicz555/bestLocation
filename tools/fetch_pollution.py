"""Distance to the nearest polluting point source, per settlement.

The CAMS air layer is a modelled BACKGROUND surface at ~11 km. It cannot see that a
landfill sits 800 m upwind of a village. This layer is the point-source complement.

Sources: OpenStreetMap (ODbL), fetched via Overpass:
  landfill  landuse=landfill          906
  quarry    landuse=quarry           2723
  wwtp      man_made=wastewater_plant 1000   (smell, not toxicity)
  works     man_made=works + name    1133   (named factories)

NOT INCLUDED, and the gaps matter:
  - E-PRTR / Industrial Emissions Portal: carries ACTUAL emission quantities and IED
    installations (incl. intensive livestock). The EEA portal API returned 404; only the
    OSM proxy is here, which knows a factory exists but not what it emits.
  - Contaminated land (FAVI-KÁRINFO / OKIR kármentesítés): not obtained.
  - Asbestos: Hungary has no public register. It is a per-building property found by
    survey, not a mappable layer - check it on the specific house.

Distances are from the settlement CENTROID. For a specific plot use plot_report, which
runs the same test at the point.
"""
import json, math, sys
from pathlib import Path

import atomicjson

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw/osm_pollution", ROOT / "data/out"
KINDS = {"landfill": "landfill", "quarry": "quarry", "wwtp": "wwtp", "works": "works"}
NEAR_KM = 3.0


def haversine(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    h = (math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p)
         * math.sin((lo2 - lo1) * p / 2) ** 2)
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def points(kind):
    f = RAW / f"{kind}.json"
    if not f.exists():
        return []
    out = []
    for e in json.loads(f.read_text(encoding="utf-8")).get("elements", []):
        c = e.get("center") or ({"lat": e.get("lat"), "lon": e.get("lon")} if e.get("lat") else None)
        if c and c.get("lat") is not None:
            out.append((c["lat"], c["lon"], (e.get("tags") or {}).get("name")))
    return out


def nearest(lat, lon, pts):
    """Nearest point and how many sit within NEAR_KM."""
    best, near = None, 0
    for la, lo, nm in pts:
        if abs(la - lat) > 0.35 or abs(lo - lon) > 0.5:      # cheap reject before haversine
            continue
        d = haversine((lat, lon), (la, lo))
        if d <= NEAR_KM:
            near += 1
        if best is None or d < best[0]:
            best = (d, nm)
    return best, near


def sample(lat, lon, cache={}):
    if not cache:
        for k in KINDS:
            cache[k] = points(k)
    out = {}
    worst = None
    for k, pts in cache.items():
        b, n = nearest(lat, lon, pts)
        out[f"{k}_km"] = round(b[0], 2) if b else None
        out[f"{k}_name"] = b[1] if b else None
        out[f"{k}_within3"] = n
        if b and (worst is None or b[0] < worst):
            worst = b[0]
    out["pollution_nearest_km"] = round(worst, 2) if worst is not None else None
    out["pollution_sources_3km"] = sum(out[f"{k}_within3"] for k in KINDS)
    return out


def main():
    counts = {k: len(points(k)) for k in KINDS}
    print("OSM point sources:", counts)
    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    hit = 0
    for s in spine:
        if not s.get("lat"):
            continue
        v = sample(s["lat"], s["lon"])
        for k in ("landfill_km", "quarry_km", "wwtp_km", "works_km",
                  "pollution_nearest_km", "pollution_sources_3km"):
            s[k] = v[k]
        s["pollution_nearest_kind"] = min(
            ((v[f"{k}_km"], k) for k in KINDS if v[f"{k}_km"] is not None), default=(None, None))[1]
        hit += 1
    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    print(f"attached: {hit}/{len(spine)}")
    for k in ("landfill_km", "quarry_km", "wwtp_km", "pollution_nearest_km"):
        v = sorted(s[k] for s in spine if s.get(k) is not None)
        if v:
            print(f"  {k:22} medián {v[len(v)//2]:.1f} km   "
                  f"{sum(1 for x in v if x < 2)} település 2 km-en belül")
    print(f"  legalább 1 forrás 3 km-en belül: "
          f"{sum(1 for s in spine if (s.get('pollution_sources_3km') or 0) > 0)}")
    return spine


def demo():
    spine = main()
    got = [s for s in spine if s.get("pollution_nearest_km") is not None]
    assert len(got) > 3000, len(got)
    for s in got:
        assert 0 <= s["pollution_nearest_km"] < 200, (s["name"], s["pollution_nearest_km"])
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
