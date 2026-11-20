"""Attach KSH Ingatlanadattar house prices (NAV-verified transactions) to the spine.

The app serves its whole dataset as one static JSON, so there is no query-by-query
export to grind through. Licence: KSH content is CC BY 4.0.

Levels: szint 1 = varmegye, 2 = street within a town, 3 = settlement ('egyutt').
We use level 3, separately for detached houses (cshaz_ar) and flats in multi-unit
buildings (tobbl_ar) - price per m2 in thousand HUF - never total_ar, which blends them.
"""
import json, statistics, sys, urllib.request
from pathlib import Path

import atomicjson

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
URL = "https://www.ksh.hu/s/ingatlanadattar/inga-data.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
HOUSE_M2 = 120          # the size we price against; a typical village family house
WINDOW_YEARS = 3        # pool the latest years: one year of a small place can be 3-5 sales
KINDS = {"house": ("cshaz_ar", "cshaz_db"),     # detached houses
         "flat": ("tobbl_ar", "tobbl_db")}      # flats in multi-unit buildings (Budapest's stock)


def load():
    dest = RAW / "ksh_ingatlan.json"
    if not dest.exists() or dest.stat().st_size == 0:
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=300) as r:
            dest.write_bytes(r.read())
    return json.loads(dest.read_text(encoding="utf-8"))


def pooled(recs, price, count):
    """Sales-weighted price over the latest WINDOW_YEARS calendar years with data.

    -> (price_m2, sales, latest_year, latest_year_price) or None. A single year of 5 sales
    swung Budapest VIII's house price from 638 to 1384 eFt/m2; pooling damps that without
    reaching back into a different market (2015 prices are half of today's).
    Simplification: plain weighted mean; a median would need per-sale data KSH does not publish.
    """
    have = [r for r in recs if r.get(price) and r.get(count)]
    if not have:
        return None
    last = max(have, key=lambda r: r["ev"])
    win = [r for r in have if r["ev"] > last["ev"] - WINDOW_YEARS]
    n = sum(r[count] for r in win)
    return round(sum(r[price] * r[count] for r in win) / n), n, last["ev"], last[price]


def main():
    rows = [r for r in load() if r["szint"] == 3]
    by = {}
    for r in rows:
        by.setdefault(r["telaz"], []).append(r)
    print(f"settlement-level records: {len(rows)} across {len(by)} settlements")

    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    hit = {k: 0 for k in KINDS}
    for s in spine:
        recs = sorted(by.get(s["ksh"], []), key=lambda r: r["ev"])
        for k in ("price_any_m2", "in_budget", "house_tx_total"):   # retired fields, nothing reads them
            s.pop(k, None)
        for kind, (price, count) in KINDS.items():
            p = pooled(recs, price, count)
            s[f"{kind}_price_m2"], s[f"{kind}_tx"], s[f"{kind}_price_year"], s[f"{kind}_price_last_m2"] = \
                p or (None, None, None, None)
            hit[kind] += bool(p)
        house = [r for r in recs if r.get("cshaz_ar")]
        s["house_120m2_mhuf"] = round(s["house_price_m2"] * HOUSE_M2 / 1000, 1) if s["house_price_m2"] else None
        # trend stays single-year to single-year: pooling both ends would blur a 10-year change
        if len(house) > 1 and house[0]["ev"] < house[-1]["ev"]:
            s["house_price_trend_pct"] = round(100 * (house[-1]["cshaz_ar"] - house[0]["cshaz_ar"]) / house[0]["cshaz_ar"])
            s["house_price_trend_from"] = house[0]["ev"]
        else:
            s["house_price_trend_pct"] = s["house_price_trend_from"] = None

    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    for kind in KINDS:
        got = [s for s in spine if s.get(f"{kind}_price_m2")]
        thin = sum(1 for s in got if s[f"{kind}_tx"] < 10)
        print(f"{kind:5} prices: {hit[kind]} settlements, {thin} of them on fewer than 10 sales "
              f"(median {statistics.median(s[f'{kind}_price_m2'] for s in got):.0f} eFt/m2)")
    return spine


def demo():
    spine = main()
    by = {s["name"]: s for s in spine}
    # Martonvasar, verified against the raw feed: 2022 580x5, 2023 562x8, 2024 528x12 -> 549 on 25
    m = by["Martonvásár"]
    assert (m["house_price_m2"], m["house_tx"], m["house_price_year"], m["house_price_last_m2"]) == (549, 25, 2024, 528), m
    assert pooled([{"ev": 2015, "a": 100, "n": 50}, {"ev": 2024, "a": 900, "n": 1}], "a", "n") == (900, 1, 2024, 900), \
        "a 2015 record must not dilute a 2024 price"
    assert by["Budapest 01. ker."]["house_price_m2"] is None and by["Budapest 01. ker."]["flat_tx"] > 300, \
        "inner Budapest: no houses, plenty of flat sales"
    priced = [s for s in spine if s.get("house_price_m2")]
    assert len(priced) > 800, f"only {len(priced)} priced settlements"
    for s in priced:
        assert 10 < s["house_price_m2"] < 5000, (s["name"], s["house_price_m2"])
        assert s["house_tx"] >= 1
    for s in spine:                                   # a price never exists without its sales count
        for kind in KINDS:
            assert (s[f"{kind}_price_m2"] is None) == (s[f"{kind}_tx"] is None), (s["name"], kind)
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
