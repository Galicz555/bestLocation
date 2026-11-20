"""Land-cover character per settlement, from ESA WorldCover 10 m (2021, CC BY 4.0).

The 10 m tiles are decimated to a single ~100 m national mosaic first. Land-cover SHARE
of a settlement is a landscape descriptor, not a plot property, so 100 m is ample - and
it turns 3,155 zonal-statistics passes over 500 MB of raster into a fast array lookup.

Classes kept (WorldCover codes):
  10 tree   20 shrub   30 grass   40 crop   50 built   60 bare   80 water   90 wetland
"""
import json, sys
from pathlib import Path

import atomicjson

import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw/worldcover", ROOT / "data/out"
MOSAIC = ROOT / "data/raw/worldcover_100m.npz"
TILES = ["N45E015", "N45E018", "N45E021", "N48E015", "N48E018", "N48E021"]
LON0, LAT1, STEP = 15.0, 51.0, 0.001          # top-left of the mosaic, degrees per cell
W, H = 9000, 6000
NAMES = {10: "tree", 20: "shrub", 30: "grass", 40: "crop", 50: "built",
         60: "bare", 80: "water", 90: "wetland"}


def build_mosaic():
    if MOSAIC.exists():
        return np.load(MOSAIC)["a"]
    a = np.zeros((H, W), dtype=np.uint8)
    for t in TILES:
        f = RAW / f"ESA_WorldCover_10m_2021_v200_{t}_Map.tif"
        if not f.exists():
            print(f"  missing {t}"); continue
        with rasterio.open(f) as ds:
            n = ds.read(1, out_shape=(3000, 3000))     # 10 m -> 100 m, nearest
            b = ds.bounds
        x0 = int(round((b.left - LON0) / STEP))
        y0 = int(round((LAT1 - b.top) / STEP))
        a[y0:y0 + 3000, x0:x0 + 3000] = n
        print(f"  {t} placed at ({x0},{y0})", flush=True)
    np.savez_compressed(MOSAIC, a=a)
    return a


def shares(geom, a):
    """Land-cover shares inside one polygon, as percentages."""
    minx, miny, maxx, maxy = geom.bounds
    c0 = max(0, int((minx - LON0) / STEP)); c1 = min(W, int((maxx - LON0) / STEP) + 2)
    r0 = max(0, int((LAT1 - maxy) / STEP)); r1 = min(H, int((LAT1 - miny) / STEP) + 2)
    if c1 <= c0 or r1 <= r0:
        return None
    win = a[r0:r1, c0:c1]
    tr = rasterio.Affine(STEP, 0, LON0 + c0 * STEP, 0, -STEP, LAT1 - r0 * STEP)
    mask = rasterize([(geom, 1)], out_shape=win.shape, transform=tr, dtype="uint8")
    vals = win[mask == 1]
    if vals.size < 4:                                   # tiny polygon: sample its centre
        vals = win.ravel()
    if vals.size == 0:
        return None
    out, tot = {}, int(vals.size)
    for code, name in NAMES.items():
        out[f"lc_{name}_pct"] = round(100 * int((vals == code).sum()) / tot, 1)
    return out


def check_terrain_ran(spine):
    """relief_class is derived from local_relief_m, which fetch_terrain writes.

    Run landcover first and `s.get("local_relief_m") or 0` reads 0 everywhere, so every
    settlement lands in the "sík" bucket: valid JSON, no error, one silently wrong column.
    build_all.sh documents the order; this is what enforces it.
    """
    if not any(s.get("local_relief_m") is not None for s in spine):
        raise SystemExit("fetch_landcover: settlements.json has no local_relief_m — run "
                         "fetch_terrain.py first (see the ordering note in build_all.sh)")


def main():
    print("building 100 m mosaic:")
    a = build_mosaic()
    print(f"  mosaic {a.shape}, non-zero {100*np.count_nonzero(a)/a.size:.1f}%")
    bnd = json.loads((ROOT / "data/out/boundaries.json").read_text(encoding="utf-8"))
    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    check_terrain_ran(spine)
    hit = 0
    for i, s in enumerate(spine):
        g = bnd.get(s["ksh"])
        if not g:
            continue
        v = shares(shape(g), a)
        if not v:
            continue
        s.update(v)
        # a compact landscape label, from cover + the relief we already have
        # no terrain for this row = unknown relief, not flat: `or 0` labelled 2535 rows "sík"
        relief = s.get("local_relief_m")
        s["relief_class"] = (None if relief is None else "sík" if relief < 30
                             else "enyhén dombos" if relief < 80
                             else "dombos" if relief < 150 else "hegyes")
        hit += 1
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(spine)}", flush=True)
    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    print(f"attached: {hit}/{len(spine)}")
    for k in ("lc_tree_pct", "lc_crop_pct", "lc_grass_pct", "lc_built_pct", "lc_water_pct"):
        v = sorted(s[k] for s in spine if s.get(k) is not None)
        if v:
            print(f"  {k:16} medián {v[len(v)//2]:.1f}%   max {v[-1]:.1f}%")
    import collections
    print("  relief:", dict(collections.Counter(
        s.get("relief_class") for s in spine if s.get("relief_class"))))
    return spine


def demo():
    # the ordering guard, before the expensive run: landcover-before-terrain must stop,
    # not quietly label the whole country "sík"
    try:
        check_terrain_ran([{"ksh": "1"}, {"ksh": "2"}])
        raise AssertionError("terrain-less spine must be rejected")
    except SystemExit:
        pass
    check_terrain_ran([{"ksh": "1"}, {"ksh": "2", "local_relief_m": 40}])

    spine = main()
    by = {s["name"]: s for s in spine}
    got = [s for s in spine if s.get("lc_tree_pct") is not None]
    assert len(got) > 3000, len(got)
    for s in got:
        tot = sum(s[f"lc_{n}_pct"] for n in NAMES.values())
        assert 90 <= tot <= 101, (s["name"], tot)
    # sanity: a Bakony/Pilis village must be far more wooded than an Alföld one
    assert by["Szokolya"]["lc_tree_pct"] > by["Dabas"]["lc_tree_pct"] + 20, \
        (by["Szokolya"]["lc_tree_pct"], by["Dabas"]["lc_tree_pct"])
    assert by["Dabas"]["lc_crop_pct"] > 20, by["Dabas"]["lc_crop_pct"]
    # relief_class must not have collapsed into one bucket
    assert len({s["relief_class"] for s in got}) > 1, "every settlement got the same relief_class"
    assert all(s.get("relief_class") is None for s in spine if s.get("local_relief_m") is None), \
        "a row without terrain must not get a relief_class"
    assert by["Szokolya"]["relief_class"] != "sík", by["Szokolya"]["relief_class"]
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
