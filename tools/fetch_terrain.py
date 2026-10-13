"""Elevation, slope, aspect and frost-pocket risk from AWS terrarium tiles.

No climate grid can see a frost pocket: the best available is ~11 km, and cold-air
pooling happens at 100 m scale on a valley floor. So we derive it from terrain instead.

Terrarium encoding: elevation_m = (R * 256 + G + B / 256) - 32768.
At z12 and this latitude a pixel is ~26 m, which resolves a garden-scale hollow.

TPI (topographic position index) = point elevation - mean elevation within ~1.6 km.
Strongly negative TPI on calm clear nights is where cold air collects and the late
spring frost takes the apricot blossom. Aspect matters for the same reason in reverse:
a south-facing slope warms earlier and drains cold air away.
"""
import io, json, math, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import atomicjson

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw/terrain", ROOT / "data/out"
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
Z = 12
TILE = 256
WIN_M = 1600          # radius of the neighbourhood TPI is measured against
STRIDE_PX = 5         # ~130 m sampling inside that window


def lonlat_to_px(lat, lon, z=Z):
    n = 2 ** z * TILE
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def m_per_px(lat, z=Z):
    """Ground resolution of one tile pixel, in metres."""
    return 156543.03392 * math.cos(math.radians(lat)) / 2 ** z


_tiles = {}
MAX_TILES = 400          # ~128 KB each; the server holds this dict for its whole life


def tile(tx, ty):
    """Decoded elevation for one tile, memoised. Raises on a tile that will not load.

    A failure is cached too (as None): window() asks for the same tile once per grid
    cell, so an unfetchable tile would otherwise re-issue ~625 requests at timeout=90.
    """
    if (tx, ty) in _tiles:
        got = _tiles[(tx, ty)]
        if got is None:
            raise LookupError(f"tile {Z}/{tx}/{ty} unavailable (cached failure)")
        return got
    if len(_tiles) > MAX_TILES:      # bound lives here: the server calls tile() directly
        _tiles.clear()
    dest = RAW / f"{Z}/{tx}/{ty}.png"
    try:
        if not dest.exists() or dest.stat().st_size == 0:
            dest.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(URL.format(z=Z, x=tx, y=ty),
                                         headers={"User-Agent": "bestLocation/0.1"})
            with urllib.request.urlopen(req, timeout=90) as r:
                dest.write_bytes(r.read())
        a = np.asarray(Image.open(dest).convert("RGB"), dtype=np.float32)
    except Exception:
        _tiles[(tx, ty)] = None
        raise
    el = (a[:, :, 0] * 256 + a[:, :, 1] + a[:, :, 2] / 256) - 32768
    _tiles[(tx, ty)] = el.astype(np.int16)
    return _tiles[(tx, ty)]


def prefetch(points):
    need = set()
    for lat, lon in points:
        x, y = lonlat_to_px(lat, lon)
        r = WIN_M / m_per_px(lat)  # window radius in pixels
        for dx in (-r, 0, r):
            for dy in (-r, 0, r):
                need.add((int((x + dx) // TILE), int((y + dy) // TILE)))
    missing = [t for t in need if not (RAW / f"{Z}/{t[0]}/{t[1]}.png").exists()]
    print(f"tiles needed {len(need)}, downloading {len(missing)}")

    def get(t):
        try:
            tile(*t); _tiles.pop(t, None)
            return True
        except Exception:
            _tiles.pop(t, None)      # drop the negative cache: the main pass may retry
            return False
    if missing:
        done = 0
        with ThreadPoolExecutor(max_workers=12) as ex:
            for ok in ex.map(get, missing):
                done += 1
                if done % 200 == 0:
                    print(f"  {done}/{len(missing)}", flush=True)


def window(lat, lon):
    """Elevation grid around the point, plus the metres-per-sample step."""
    cx, cy = lonlat_to_px(lat, lon)
    res = m_per_px(lat)                              # metres per pixel
    rad = int(WIN_M / res)
    xs = np.arange(-rad, rad + 1, STRIDE_PX)
    grid = np.full((len(xs), len(xs)), np.nan, dtype=np.float32)
    for i, dy in enumerate(xs):
        for j, dx in enumerate(xs):
            px, py = cx + dx, cy + dy
            tx, ty = int(px // TILE), int(py // TILE)
            try:
                grid[i, j] = tile(tx, ty)[int(py) % TILE, int(px) % TILE]
            except Exception:
                pass        # missing/404 tile or out-of-range pixel: that cell stays NaN,
                            # and terrain() returns None if the centre 3x3 is incomplete
    return grid, res * STRIDE_PX


def terrain(lat, lon):
    g, step = window(lat, lon)
    c = g.shape[0] // 2
    z = g[c, c]
    if np.isnan(z):
        return None
    # slope/aspect from the 3x3 immediately around the centre (Horn's method)
    sub = g[c - 1:c + 2, c - 1:c + 2]
    if sub.shape != (3, 3) or np.isnan(sub).any():
        return None
    dzdx = ((sub[0, 2] + 2 * sub[1, 2] + sub[2, 2]) - (sub[0, 0] + 2 * sub[1, 0] + sub[2, 0])) / (8 * step)
    dzdy = ((sub[2, 0] + 2 * sub[2, 1] + sub[2, 2]) - (sub[0, 0] + 2 * sub[0, 1] + sub[0, 2])) / (8 * step)
    slope = math.degrees(math.atan(math.hypot(dzdx, dzdy)))
    aspect = (math.degrees(math.atan2(dzdy, -dzdx)) + 360) % 360 if slope > 0.3 else None
    mean = float(np.nanmean(g))
    return {
        "elevation_m": round(float(z)),
        "slope_deg": round(slope, 2),
        "aspect_deg": None if aspect is None else round(aspect),
        "tpi_m": round(float(z) - mean, 1),
        "local_relief_m": round(float(np.nanmax(g) - np.nanmin(g))),
    }


def south_facing(aspect, slope):
    """1.0 due south, 0 due north; meaningless on flat ground."""
    if aspect is None or slope < 1.0:
        return None
    return round((1 + math.cos(math.radians(aspect - 180))) / 2, 2)


def frost_risk(t):
    """0-100 cold-air pooling risk.

    Pooling needs BOTH conditions: a hollow to collect in (negative TPI) and surrounding
    relief to drain off. A 4 m dip on a 12 m-relief plain is not a frost pocket, so the
    two terms multiply rather than add - an earlier additive version scored flat Great
    Plain villages at 65, which is physically wrong.
    """
    depth = max(0.0, -t["tpi_m"])                     # how far below the surroundings
    relief = t["local_relief_m"]
    risk = min(1.0, depth / 12.0) * min(1.0, relief / 100.0)
    return int(max(5, min(100, round(risk * 100))))


def main():
    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    ring = ([s for s in spine if s.get("lat")] if "--all" in sys.argv else
            [s for s in spine if (s.get("dist_bp_km") or 999) <= 90 and s.get("lat")])
    prefetch([(s["lat"], s["lon"]) for s in ring])

    ok = 0
    for s in ring:
        t = terrain(s["lat"], s["lon"])
        if not t:
            continue
        ok += 1
        s.update(t)
        s["south_facing"] = south_facing(t["aspect_deg"], t["slope_deg"])
        s["frost_risk"] = frost_risk(t)

    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    fr = [s["frost_risk"] for s in ring if s.get("frost_risk") is not None]
    print(f"\nterrain computed for {ok}/{len(ring)}")
    print(f"  elevation range : {min(s['elevation_m'] for s in ring if s.get('elevation_m'))}"
          f"..{max(s['elevation_m'] for s in ring if s.get('elevation_m'))} m")
    print(f"  frost risk      : min {min(fr)} median {sorted(fr)[len(fr)//2]} max {max(fr)}")
    return spine


def demo():
    spine = main()
    by = {s["name"]: s for s in spine}
    # Great Plain settlements sit near 100 m; the Bend and Pilis are higher
    assert 90 < by["Martonvásár"]["elevation_m"] < 140, by["Martonvásár"]["elevation_m"]
    assert by["Szokolya"]["elevation_m"] > by["Dabas"]["elevation_m"], "Bend must top the Plain"
    assert by["Dabas"]["local_relief_m"] < by["Szokolya"]["local_relief_m"]
    got = [s for s in spine if s.get("frost_risk") is not None]
    assert len(got) > 550, f"only {len(got)}"
    for s in got:
        assert 0 <= s["frost_risk"] <= 100
        assert -400 < s["elevation_m"] < 1100, (s["name"], s["elevation_m"])
        assert s["aspect_deg"] is None or 0 <= s["aspect_deg"] <= 360
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
