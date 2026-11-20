"""County-level recorded crime, 2009-2025, from KSH STADAT (iga0008).

RESOLUTION WARNING: this is per VÁRMEGYE, not per settlement. Settlement-level crime
exists in PRE-STAT but sits behind personal Ügyfélkapu login that no automated process
can hold. So every settlement in a county gets the same number - it is a regional
backdrop, not a way to separate two villages. Stored with a `_county` suffix so nothing
can mistake it for local data.

LICENCE CONFLICT, unresolved: the file is served from ksh.hu (site content CC BY 4.0),
but kozadatportal.hu lists the same table as CC BY-NC. Treat as non-commercial.
"""
import csv, io, json, sys, urllib.request
from pathlib import Path

import atomicjson

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
URL = "https://www.ksh.hu/stadat_files/iga/hu/iga0008.csv"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
TREND_FROM = "2015"


def load():
    dest = RAW / "ksh_crime_iga0008.csv"
    if not dest.exists() or dest.stat().st_size == 0:
        req = urllib.request.Request(URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
    # KSH STADAT csv files are latin-2
    return dest.read_text(encoding="latin2", errors="replace")


def num(v):
    v = (v or "").replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    try:
        return float(v)
    except ValueError:
        return None


def main():
    rdr = list(csv.reader(io.StringIO(load()), delimiter=";"))
    header = next(r for r in rdr if r and r[0].startswith("Terület"))
    years = {y: i for i, y in enumerate(header) if y.strip().isdigit()}
    last = max(years, key=int)

    counties, seen = {}, set()
    for row in rdr:
        if len(row) < 3 or not row[0].strip():
            continue
        name, level = row[0].strip(), (row[1] or "").strip()
        if "vármegye" not in level and "főváros" not in level:
            continue
        if name in seen:          # later blocks repeat the counties for other measures
            continue
        seen.add(name)
        counties[name] = {y: num(row[i]) for y, i in years.items()}
    print(f"counties parsed: {len(counties)}  years {min(years,key=int)}–{last}")

    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    pop = {}
    for s in spine:
        key = "Budapest" if not s.get("megye") or s["megye"] == "főváros" else s["megye"]
        pop[key] = pop.get(key, 0) + (s.get("pop_2022") or 0)

    def match(megye, name):
        key = "Budapest" if not megye or megye == "főváros" else megye
        return key == name.strip()

    hit = 0
    for s in spine:
        row = next((v for k, v in counties.items() if match(s.get("megye"), k)), None)
        if not row:
            s["crime_county"] = s["crime_rate_county"] = s["crime_trend_county"] = None
            continue
        hit += 1
        key = "Budapest" if not s.get("megye") or s["megye"] == "főváros" else s["megye"]
        p = pop.get(key) or 0
        s["crime_county"] = row.get(last)
        s["crime_rate_county"] = round(row[last] / p * 100000) if row.get(last) and p else None
        base = row.get(TREND_FROM)
        s["crime_trend_county"] = (round(100 * (row[last] - base) / base)
                                   if base and row.get(last) else None)
        s["crime_year"] = last

    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    print(f"settlements given a county crime figure: {hit}/{len(spine)}")
    seen2 = {}
    for s in spine:
        if s.get("crime_rate_county"):
            seen2[s.get("megye") or "Budapest"] = (s["crime_rate_county"], s["crime_trend_county"])
    print(f"\n{'county':26}{'per 100k':>10}{'since '+TREND_FROM:>14}")
    for k, (r, t) in sorted(seen2.items(), key=lambda kv: -kv[1][0]):
        print(f"{k:26}{r:>10}{(str(t)+'%'):>14}")
    return spine


def demo():
    spine = main()
    got = [s for s in spine if s.get("crime_rate_county")]
    assert len(got) > 3000, f"only {len(got)}"
    for s in got:
        assert 100 < s["crime_rate_county"] < 20000, (s["megye"], s["crime_rate_county"])
    print("\nself-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
