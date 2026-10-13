"""Sunshine and PV yield per settlement, from the JRC PVGIS API.

PVGIS is a point service, so we query each settlement centroid once and cache it.
Underlying model is SARAH3 (~5 km satellite-derived irradiation), so this resolves
regions rather than neighbouring villages - fine, because sunshine genuinely varies
at regional scale.

  ghi_kwh_m2   annual global irradiation on a horizontal plane
  pv_kwh_kwp   annual yield of 1 kWp at the optimal tilt (roof planning)
  opt_tilt     the optimal tilt PVGIS picks for that latitude
"""
import json, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import atomicjson

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
API = "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc"
UA = "bestLocation/0.1 (personal house-search tool)"
CACHE = RAW / "pvgis.json"


def query(lat, lon):
    q = urllib.parse.urlencode({"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "peakpower": 1,
                                "loss": 14, "optimalangles": 1, "outputformat": "json"})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.loads(r.read())
    t = d["outputs"]["totals"]["fixed"]
    m = d["inputs"]["mounting_system"]["fixed"]
    return {"pv_kwh_kwp": round(t["E_y"]), "ghi_kwh_m2": round(t["H(i)_y"]),
            "opt_tilt": m["slope"]["value"], "opt_azimuth": m["azimuth"]["value"]}


def main():
    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    # retry cached failures: a transient connection reset must not become a permanent gap
    todo = [s for s in spine if s.get("lat") and "_err" in cache.get(s["ksh"], {"_err": ""})]
    print(f"PVGIS: {len(todo)} to query ({len(cache)} cached)", flush=True)

    if todo:
        def work(s):
            try:
                return s["ksh"], query(s["lat"], s["lon"])
            except Exception as e:
                return s["ksh"], {"_err": str(e)[:60]}
        done = 0
        with ThreadPoolExecutor(max_workers=4) as ex:   # polite: PVGIS is a public service
            for ksh, v in ex.map(work, todo):
                cache[ksh] = v
                done += 1
                if done % 200 == 0:
                    print(f"  {done}/{len(todo)}", flush=True)
                    atomicjson.write_json(CACHE, cache)
        atomicjson.write_json(CACHE, cache)

    errs = sum(1 for v in cache.values() if "_err" in v)
    hit = 0
    for s in spine:
        v = cache.get(s["ksh"])
        if not v or "_err" in v:
            continue
        s.update(v)
        hit += 1
    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    vals = sorted(s["pv_kwh_kwp"] for s in spine if s.get("pv_kwh_kwp"))
    print(f"attached: {hit}/{len(spine)}   errors: {errs}")
    if vals:
        print(f"  PV yield kWh/kWp: {vals[0]}..{vals[-1]}, median {vals[len(vals)//2]}")
    return spine


def demo():
    spine = main()
    got = [s for s in spine if s.get("pv_kwh_kwp")]
    assert len(got) > 3000, len(got)
    for s in got:
        assert 900 < s["pv_kwh_kwp"] < 1500, (s["name"], s["pv_kwh_kwp"])
        assert 1000 < s["ghi_kwh_m2"] < 1800, (s["name"], s["ghi_kwh_m2"])
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
