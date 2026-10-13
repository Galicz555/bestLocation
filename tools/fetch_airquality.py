"""Air pollution per settlement, from the CAMS Europe reanalysis via Open-Meteo.

RESOLUTION: CAMS Europe is ~0.1 degree (~11 km), so settlements share a grid cell -
this is a regional signal, not a street-level one. Hungary's own OLM network is ~60
stations nationwide, which cannot score 3,178 settlements at all, so a modelled
surface is the only option that covers the country.

Reference year 2024. We keep the WINTER mean separately because that is where domestic
wood burning shows up - a village can look clean on the annual average and be smoky
every January.

Thresholds for context: WHO annual guideline PM2.5 = 5 µg/m³, PM10 = 15, NO2 = 10.
The EU limit is far looser (PM2.5 = 25, tightening to 10 by 2030).
"""
import json, statistics, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import atomicjson

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
API = "https://air-quality-api.open-meteo.com/v1/air-quality"
UA = "bestLocation/0.1 (personal house-search tool)"
CACHE = RAW / "cams_air.json"
YEAR = 2024
GRID = 0.2


def cell(lat, lon):
    return (round(lat / GRID) * GRID, round(lon / GRID) * GRID)


def query(lat, lon):
    q = urllib.parse.urlencode({
        "latitude": f"{lat:.2f}", "longitude": f"{lon:.2f}",
        "start_date": f"{YEAR}-01-01", "end_date": f"{YEAR}-12-31",
        "hourly": "pm2_5,nitrogen_dioxide", "timezone": "Europe/Budapest",
        "domains": "cams_europe"})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            r = urllib.request.urlopen(req, timeout=180)
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 0) or 20 * (attempt + 1))
    with r:
        h = json.loads(r.read())["hourly"]
    t = h["time"]
    out = {}
    for key, field in (("pm25", "pm2_5"), ("no2", "nitrogen_dioxide")):
        v = [(t[i], x) for i, x in enumerate(h[field]) if x is not None]
        if not v:
            continue
        win = [x for ts, x in v if ts[5:7] in ("12", "01", "02")]
        out[f"{key}_annual"] = round(statistics.mean(x for _, x in v), 1)
        out[f"{key}_winter"] = round(statistics.mean(win), 1) if win else None
    return out


def main():
    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    cells = {}
    for s in spine:
        if s.get("lat"):
            la, lo = cell(s["lat"], s["lon"])
            cells[f"{la:.1f},{lo:.1f}"] = (la, lo)
    # retry cached failures: a transient 429 must not become a permanent gap
    todo = [k for k in cells if k not in cache or "_err" in cache[k]]
    print(f"CAMS cells: {len(cells)} total, {len(todo)} to fetch", flush=True)

    if todo:
        def work(k):
            try:
                return k, query(*cells[k])
            except Exception as e:
                return k, {"_err": str(e)[:60]}
        done = 0
        with ThreadPoolExecutor(max_workers=2) as ex:
            for k, v in ex.map(work, todo):
                cache[k] = v
                done += 1
                if done % 50 == 0:
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
        s["air_year"] = YEAR
        hit += 1
    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    print(f"attached: {hit}/{len(spine)}")
    for k in ("pm25_annual", "pm25_winter", "no2_annual"):
        v = sorted(s[k] for s in spine if s.get(k) is not None)
        if v:
            print(f"  {k:12} {v[0]}..{v[-1]}  median {v[len(v)//2]} µg/m³")
    return spine


def demo():
    spine = main()
    got = [s for s in spine if s.get("pm25_annual")]
    assert len(got) > 3000, len(got)
    for s in got:
        assert 2 < s["pm25_annual"] < 60, (s["name"], s["pm25_annual"])
        assert s["pm25_winter"] >= s["pm25_annual"] * 0.5
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
