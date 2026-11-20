"""Index NMHH's unserved-address survey for point lookup.

POLARITY WARNING, and it matters: this file lists addresses with NO high-speed fixed
connection. Absence from it means "not recorded as unserved" - which is good news, but
it is NOT a confirmation that fibre is available at the door. Never render it as such.

Source: NMHH geographic survey, published 2025-12-15, state-of 2024-12-31.
Coordinates are EOV (EPSG:23700); the sheet's "y" column is easting, "x" is northing.
"""
import json, sys
from pathlib import Path

import numpy as np
import openpyxl
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
SRC = RAW / "nmhh_unserved_fixed.xlsx"
T = Transformer.from_crs("EPSG:23700", "EPSG:4326", always_xy=True)


def main():
    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
    ws = wb["ellátatlan címhelyek"]
    rows = ws.iter_rows(values_only=True)
    next(rows)
    eov, addr = [], []
    for r in rows:
        try:
            eov.append((float(r[2]), float(r[3])))
            addr.append(r[1])
        except (TypeError, ValueError, IndexError):
            continue
    wb.close()
    e = np.asarray(eov, dtype=np.float64)
    lon, lat = T.transform(e[:, 0], e[:, 1])
    OUT.mkdir(parents=True, exist_ok=True)
    np.save(OUT / "fibre_unserved.npy", np.stack([lat, lon]).astype(np.float32).T)
    (OUT / "fibre_unserved_addr.json").write_text(
        json.dumps(addr, ensure_ascii=False), encoding="utf-8")
    print(f"{len(addr)} unserved addresses indexed")
    print(f"  lat {lat.min():.4f}..{lat.max():.4f}   lon {lon.min():.4f}..{lon.max():.4f}")
    print(f"  first: {addr[0]}  ->  {lat[0]:.5f}, {lon[0]:.5f}")
    return lat, lon, addr


if __name__ == "__main__":
    lat, lon, addr = main()
    # Hungary's bounding box, roughly 45.7-48.6 N and 16.1-22.9 E
    assert 45.5 < lat.min() and lat.max() < 48.8, (lat.min(), lat.max())
    assert 16.0 < lon.min() and lon.max() < 23.1, (lon.min(), lon.max())
    assert len(addr) > 400000, len(addr)
    # the first row is in Aba, Fejer county: ~47.03 N, 18.52 E
    assert abs(lat[0] - 47.03) < 0.1 and abs(lon[0] - 18.52) < 0.1, (lat[0], lon[0])
    print("self-check OK")
