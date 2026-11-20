"""Rainfall, wind and the frost window, from NASA POWER (MERRA-2 derived).

Was ERA5 via Open-Meteo, which is finer (~9-30 km) but exhausted its free daily quota
mid-run and then returned 429 regardless of payload size. POWER is coarser but has no
quota, answers in ~1.5 s, and needs no key - so the data exists today rather than
tomorrow. Spot-checked against ERA5 at Martonvasar: 607 vs 653 mm/yr, last spring frost
day 102 vs 92. Same story, slightly smoothed.

RESOLUTION: POWER is ~0.5 x 0.625 degrees, roughly 50 km. It resolves the national
west-wet / east-dry gradient, NOT the difference between neighbouring villages. Settlements
are snapped to a 0.5 degree grid so the sharing is explicit rather than implied.

The garden-relevant part is `last_frost_doy`: the mean day of the last spring frost.
It answers "when can I plant out". It is the REGIONAL frost window - the local frost
pocket effect is a terrain property and lives in `frost_risk` instead.
"""
import json, statistics, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import atomicjson

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
API = "https://power.larc.nasa.gov/api/temporal/daily/point"
UA = "bestLocation/0.1 (personal house-search tool)"
CACHE = RAW / "era5_climate.json"
START, END = "20150101", "20241231"
GRID = 0.5                       # POWER's own grid; finer would be a fiction


def cell(lat, lon):
    return (round(lat / GRID) * GRID, round(lon / GRID) * GRID)


def query(lat, lon):
    q = urllib.parse.urlencode({
        "parameters": "PRECTOTCORR,WS10M_MAX,T2M_MIN,T2M_MAX", "community": "AG",
        "latitude": f"{lat:.3f}", "longitude": f"{lon:.3f}",
        "start": START, "end": END, "format": "JSON"})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            r = urllib.request.urlopen(req, timeout=180)
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503) or attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))
    with r:
        p = json.loads(r.read())["properties"]["parameter"]
    pr, tn, tx, ws = p["PRECTOTCORR"], p["T2M_MIN"], p["T2M_MAX"], p["WS10M_MAX"]
    days = sorted(pr)
    yrs = len({d[:4] for d in days})
    ok = lambda D: [v for v in D.values() if v is not None and v > -900]   # -999 = missing
    last_frost, first_autumn = [], []
    for y in sorted({d[:4] for d in days}):
        sp = [d for d in days if d[:4] == y and d[4:6] <= "06"
              and tn.get(d) is not None and -900 < tn[d] < 0]
        au = [d for d in days if d[:4] == y and d[4:6] >= "09"
              and tn.get(d) is not None and -900 < tn[d] < 0]
        doy = lambda d: date(int(d[:4]), int(d[4:6]), int(d[6:])).timetuple().tm_yday
        if sp:
            last_frost.append(doy(max(sp)))
        if au:
            first_autumn.append(doy(min(au)))
    w = sorted(x * 3.6 for x in ok(ws))          # m/s -> km/h
    return {
        "precip_mm_yr": round(sum(ok(pr)) / yrs),
        "rain_days_yr": round(sum(1 for x in ok(pr) if x > 1) / yrs),
        "wind_kmh_mean": round(statistics.mean(w), 1),
        "wind_kmh_p95": round(w[int(len(w) * 0.95)]),
        "frost_days_yr": round(sum(1 for x in ok(tn) if x < 0) / yrs),
        "hot_days_yr": round(sum(1 for x in ok(tx) if x >= 30) / yrs),
        "last_frost_doy": round(statistics.mean(last_frost)) if last_frost else None,
        "frost_free_days": (round(statistics.mean(first_autumn) - statistics.mean(last_frost))
                            if last_frost and first_autumn else None),
    }


def main():
    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    cells = {}
    for s in spine:
        if s.get("lat"):
            cells.setdefault(f"{cell(s['lat'], s['lon'])[0]:.1f},{cell(s['lat'], s['lon'])[1]:.1f}",
                             cell(s["lat"], s["lon"]))
    # a cached failure (429 during a busy hour) must be retried, not inherited by every later build
    todo = [k for k in cells if k not in cache or "_err" in cache[k]]
    print(f"ERA5 cells: {len(cells)} total, {len(todo)} to fetch "
          f"({len(spine)} settlements share them)", flush=True)

    if todo:
        def work(k):
            try:
                return k, query(*cells[k])
            except Exception as e:
                return k, {"_err": str(e)[:60]}
        done = 0
        with ThreadPoolExecutor(max_workers=3) as ex:     # public free service: be polite
            for k, v in ex.map(work, todo):
                cache[k] = v
                done += 1
                if done % 20 == 0:
                    print(f"  {done}/{len(todo)}", flush=True)
                    atomicjson.write_json(CACHE, cache)
        atomicjson.write_json(CACHE, cache)

    hit = 0
    for s in spine:
        if not s.get("lat"):
            continue
        la, lo = cell(s["lat"], s["lon"])
        v = cache.get(f"{la:.1f},{lo:.1f}")
        if not v or "_err" in v:
            continue
        s.update(v)
        hit += 1
    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    errs = sum(1 for v in cache.values() if "_err" in v)
    print(f"attached: {hit}/{len(spine)}   failed cells: {errs}")
    for k in ("precip_mm_yr", "wind_kmh_mean", "last_frost_doy", "frost_free_days"):
        v = sorted(s[k] for s in spine if s.get(k) is not None)
        if v:
            print(f"  {k:16} {v[0]}..{v[-1]}  median {v[len(v)//2]}")
    return spine


def demo():
    spine = main()
    got = [s for s in spine if s.get("precip_mm_yr")]
    assert len(got) > 3000, len(got)
    for s in got:
        assert 350 < s["precip_mm_yr"] < 1200, (s["name"], s["precip_mm_yr"])
        assert 60 < s["last_frost_doy"] < 160, (s["name"], s["last_frost_doy"])
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
