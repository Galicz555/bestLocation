"""Sample DOSoReMI 100 m topsoil rasters (0-30 cm) at each settlement centroid.

Source: HUN-REN ATK TAKI, https://maps.rissac.hu:6443/arcgis/rest/services/dosoremi
Licence is UNDECLARED (empty copyrightText) - fine for a personal tool, ask TAKI
before anything commercial.

Two deliberate choices:
- TLS verification is off. The server's certificate is EXPIRED (not a chain problem),
  and this is public read-only raster data. Simplification: pinned bypass, revisit if TAKI fixes it.
- USDA texture class is computed from the sand/silt/clay rasters via the standard
  triangle rather than read from layer 9, whose pixel values disagree with the
  fractions (Martonvasar measures 58.6% silt yet layer 9 returns '01-homok').

Centroid caveat: one sample per settlement. Good enough to rank settlements; the plot
you actually buy needs its own sample, which the same endpoint gives at any lat/lon.
"""
import json, ssl, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import atomicjson

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
URL = "https://maps.rissac.hu:6443/arcgis/rest/services/dosoremi/MapServer/identify"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
# One map click must not pin a server thread on a third party we do not control.
SAMPLE_TIMEOUT = 10

FIELDS = {  # layer name fragment -> our field
    "Szervesanyag tartalom": "soil_om_pct",
    "kémhatása": "soil_ph",
    "Mésztartalom": "soil_lime_pct",
    "Agyagtartalom": "soil_clay_pct",
    "Iszaptartalom": "soil_silt_pct",
    "Homoktartalom": "soil_sand_pct",
}


def usda(sand, silt, clay):
    """Standard USDA texture triangle. Percentages of the mineral fraction."""
    if None in (sand, silt, clay):
        return None
    if clay >= 40 and silt < 40 and sand <= 45:            return "clay"
    if clay >= 40 and silt >= 40:                          return "silty clay"
    if clay >= 35 and sand > 45:                           return "sandy clay"
    if 27 <= clay < 40 and sand <= 20:                     return "silty clay loam"
    if 27 <= clay < 40 and 20 < sand <= 45:                return "clay loam"
    if 20 <= clay < 35 and silt < 28 and sand > 45:        return "sandy clay loam"
    if clay < 27 and silt >= 50 and (silt < 80 or clay >= 12): return "silt loam"
    if silt >= 80 and clay < 12:                           return "silt"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:  return "loam"
    if sand - clay * 1.5 >= 70 and sand >= 85:             return "sand"
    if sand >= 70:                                         return "loamy sand"
    return "sandy loam"


@lru_cache(maxsize=4096)
def _sample(lon, lat):
    q = urllib.parse.urlencode({
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "sr": "4326",
        "layers": "all", "tolerance": "2",
        "mapExtent": f"{lon-.02},{lat-.02},{lon+.02},{lat+.02}",
        "imageDisplay": "400,400,96", "returnGeometry": "false", "f": "json"})
    req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": "bestLocation/0.1"})
    with urllib.request.urlopen(req, timeout=SAMPLE_TIMEOUT, context=CTX) as r:
        res = json.loads(r.read())
    out = {}
    for item in res.get("results", []):
        name = item.get("layerName", "")
        val = item.get("attributes", {}).get("Pixel Value")
        for frag, field in FIELDS.items():
            if frag in name and "Megbízhatóság" not in name:
                try:
                    out[field] = round(float(val), 2)
                except (TypeError, ValueError):
                    pass
    return out


def sample(lon, lat):
    """One point sample. Memoised on rounded coordinates: /api/plot spends nearly all
    of its 123 ms in here, and 4 decimals (~11 m) is well inside the 100 m raster's
    own resolution, so a repeat click on the same spot is free."""
    return dict(_sample(round(lon, 4), round(lat, 4)))


def main():
    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    todo = ([s for s in spine if s.get("lat")] if "--all" in sys.argv else
            [s for s in spine if s.get("dist_bp_km") is not None and s["dist_bp_km"] <= 90])
    cache_path = RAW / "soil_samples.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    todo = [s for s in todo if s["ksh"] not in cache]
    print(f"sampling {len(todo)} settlements ({len(cache)} already cached)")

    if todo:
        def work(s):
            try:
                return s["ksh"], sample(s["lon"], s["lat"])
            except Exception as e:
                return s["ksh"], {"_err": str(e)[:70]}
        done = 0
        with ThreadPoolExecutor(max_workers=6) as ex:
            for ksh, vals in ex.map(work, todo):
                cache[ksh] = vals
                done += 1
                if done % 100 == 0:
                    print(f"  {done}/{len(todo)}", flush=True)
                    atomicjson.write_json(cache_path, cache)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        atomicjson.write_json(cache_path, cache)

    errs = sum(1 for v in cache.values() if "_err" in v)
    hit = 0
    for s in spine:
        v = cache.get(s["ksh"])
        if not v or "_err" in v:
            continue
        s.update(v)
        hit += 1
        s["soil_texture"] = usda(v.get("soil_sand_pct"), v.get("soil_silt_pct"),
                                 v.get("soil_clay_pct"))
        s["garden_score"] = garden(v, s["soil_texture"])

    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    print(f"sampled OK: {hit}   errors: {errs}")
    return spine


# Vegetable-growing suitability, 0-100. Loams best, sand and heavy clay worst;
# organic matter rewarded; pH scored against the 6.0-7.5 band most vegetables want.
TEXTURE = {"loam": 100, "silt loam": 95, "silt": 85, "sandy loam": 80, "clay loam": 78,
           "silty clay loam": 72, "sandy clay loam": 65, "loamy sand": 45,
           "silty clay": 45, "clay": 38, "sandy clay": 38, "sand": 20}


def garden(v, texture):
    if texture is None:
        return None
    t = TEXTURE.get(texture, 50)
    om = v.get("soil_om_pct")
    o = 50 if om is None else max(0, min(100, (om - 0.8) / 2.7 * 100))
    ph = v.get("soil_ph")
    if ph is None:
        p = 50
    elif 6.0 <= ph <= 7.5:
        p = 100
    else:
        p = max(0, 100 - abs(ph - 6.75) * 40)
    return round(0.5 * t + 0.25 * o + 0.25 * p)


def demo():
    spine = main()
    by = {s["name"]: s for s in spine}
    m, d = by["Martonvásár"], by["Dabas"]
    # a single 100 m centroid sample moves with the exact point; assert the class band,
    # not one label (Martonvasar reads loam/silt loam depending on the pixel)
    assert m["soil_texture"] in ("loam", "silt loam"), m["soil_texture"]
    assert d["soil_sand_pct"] > 45, d["soil_sand_pct"]
    assert m["garden_score"] > d["garden_score"], "Mezofold must beat Kiskunsag sand"
    got = [s for s in spine if s.get("garden_score") is not None]
    assert len(got) > 550, f"only {len(got)} sampled"
    for s in got:
        assert 0 <= s["garden_score"] <= 100
        assert 2 < s["soil_ph"] < 10, (s["name"], s["soil_ph"])
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
