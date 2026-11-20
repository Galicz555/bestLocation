"""Build the settlement spine: KSH Helysegnevtar x Wikidata (KSH code <-> OSM relation).

The KSH code is the join key for every Hungarian statistical dataset; OSM relation ids
are how we get geometry. Wikidata is the only complete bridge between them.
"""
import csv, json, math, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

import atomicjson

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
HNT_URL = "https://www.ksh.hu/docs/helysegnevtar/hnt_letoltes_2025.xlsx"
# Simplification: WDQS rate-limits hard during outages; QLever serves the same Wikidata graph.
SPARQL_ENDPOINTS = ("https://query.wikidata.org/sparql",
                    "https://qlever.cs.uni-freiburg.de/api/wikidata")
UA = "bestLocation/0.1 (personal house-search tool)"

# Budapest anchor: Deak Ferenc ter. Simplification: single anchor, make it a CLI arg if a second office appears.
ANCHOR = (47.4977, 19.0544)

QUERY = """
SELECT ?ksh ?osm ?lat ?lon WHERE {
  ?item wdt:P939 ?ksh ; wdt:P402 ?osm .
  OPTIONAL { ?item p:P625/psv:P625 [ wikibase:geoLatitude ?lat ; wikibase:geoLongitude ?lon ] }
}
"""


def fetch(url, dest, **kw):
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **kw.get("headers", {})})
    with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def sparql(query, dest, attempts=3):
    """Run a SPARQL query, falling back across endpoints and backing off on 429."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    q = urllib.parse.urlencode({"query": query})
    last = None
    for endpoint in SPARQL_ENDPOINTS:
        for i in range(attempts):
            try:
                return fetch(f"{endpoint}?{q}", dest,
                             headers={"Accept": "application/sparql-results+json"})
            except urllib.error.HTTPError as e:
                last = e
                wait = int(e.headers.get("Retry-After") or 0) or 65 * (i + 1)
                print(f"  {endpoint.split('/')[2]} -> {e.code}; waiting {wait}s", flush=True)
                if e.code not in (429, 500, 502, 503):
                    break
                time.sleep(wait)
            except Exception as e:
                last = e
                print(f"  {endpoint.split('/')[2]} -> {e}", flush=True)
                break
    raise SystemExit(f"all SPARQL endpoints failed: {last}")


def haversine(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    h = (math.sin((la2 - la1) * p / 2) ** 2
         + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2)
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def read_hnt(path):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)["Helységek 2025.01.01."]
    rows = ws.iter_rows(values_only=True)
    for _ in range(3):  # title, sub-header, header
        next(rows)
    out = {}
    for r in rows:
        name, ksh = r[0], r[1]
        if not name or not ksh:
            continue
        ksh = str(ksh).strip()
        out[ksh] = {
            "ksh": ksh, "name": str(name).strip(), "status": r[2], "megye": r[3],
            "jaras": r[5], "jaras_seat": r[6],
            "area_ha": round(float(r[9]), 1) if r[9] not in (None, "") else None,
            "population": int(r[10]) if r[10] not in (None, "") else None,
            "dwellings": int(r[11]) if r[11] not in (None, "") else None,
        }
    return out


def read_wikidata(path):
    sparql(QUERY, path)
    out = {}
    for b in json.load(open(path))["results"]["bindings"]:
        ksh = b["ksh"]["value"].strip()
        rec = out.setdefault(ksh, {"osm_rel": b["osm"]["value"], "lat": None, "lon": None})
        if "lat" in b and rec["lat"] is None:
            rec["lat"], rec["lon"] = float(b["lat"]["value"]), float(b["lon"]["value"])
    return out


def main():
    hnt = read_hnt(fetch(HNT_URL, RAW / "hnt_2025.xlsx"))
    wd = read_wikidata(RAW / "wikidata_crosswalk.json")

    rows, unmatched = [], []
    for ksh, s in sorted(hnt.items(), key=lambda kv: kv[1]["name"]):
        w = wd.get(ksh)
        if not w:
            unmatched.append(s["name"])
            continue
        s |= w
        s["dist_bp_km"] = (round(haversine(ANCHOR, (w["lat"], w["lon"])), 1)
                           if w["lat"] is not None else None)
        rows.append(s)

    OUT.mkdir(parents=True, exist_ok=True)
    atomicjson.write_json(OUT / "settlements.json", rows, ensure_ascii=False, indent=1)
    with open(OUT / "settlements.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    no_coord = sum(1 for r in rows if r["lat"] is None)
    print(f"HNT settlements      : {len(hnt)}")
    print(f"Wikidata KSH entries : {len(wd)}")
    print(f"joined               : {len(rows)}  ({len(rows)/len(hnt)*100:.1f}%)")
    print(f"  without coordinates: {no_coord}")
    print(f"unmatched            : {len(unmatched)}" +
          (f"  e.g. {unmatched[:5]}" if unmatched else ""))
    within = [r for r in rows if r["dist_bp_km"] is not None and r["dist_bp_km"] <= 90]
    print(f"within 90 km of anchor: {len(within)}")
    return rows


def demo():
    """Self-check: the join must be near-total and the anchor maths must be sane."""
    rows = main()
    by_name = {r["name"]: r for r in rows}
    assert len(rows) > 3100, f"join collapsed: only {len(rows)} rows"
    assert sum(1 for r in rows if r["lat"] is None) < 50, "too many settlements without coords"
    bp = by_name["Budapest"]
    assert bp["dist_bp_km"] < 10, f"Budapest is {bp['dist_bp_km']} km from the Budapest anchor?"
    for name, lo, hi in [("Martonvásár", 20, 40), ("Vác", 25, 45), ("Debrecen", 180, 230)]:
        d = by_name[name]["dist_bp_km"]
        assert lo <= d <= hi, f"{name} at {d} km, expected {lo}-{hi}"
    assert by_name["Vác"]["megye"] == "Pest"
    print("\nself-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
