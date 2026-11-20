"""Attach unfilled GP and dentist practices (OKFO) to the spine.

Polarity: these tables list settlements WITH a vacancy. Absence from them means no
known vacancy - the good state - not "confirmed doctor". Stored as counts so the UI
can say "1 unfilled practice" rather than implying a clean bill of health.
"""
import json, re, sys, urllib.request
from pathlib import Path

import atomicjson

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
SRC = {
    "gp": "https://alapellatas.okfo.gov.hu/tajekoztato-a-tartosan-betoltetlen-haziorvosi-korzetekrol/",
    "dentist": "https://alapellatas.okfo.gov.hu/tajekoztato-a-tartosan-betoltetlen-fogorvosi-korzetekrol/",
}
DATE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
ROMAN = {v: i + 1 for i, v in enumerate(
    "I II III IV V VI VII VIII IX X XI XII XIII XIV XV XVI XVII XVIII XIX XX XXI XXII XXIII".split())}
# The OKFO tables degrade o/u to o/u in places (Almasfuzito, Besenyotelek), so match on a fold.
FOLD = str.maketrans({"ő": "o", "ű": "u", "ó": "o", "ö": "o", "ú": "u", "ü": "u"})


def fold(t):
    t = (t or "").strip()
    if t.startswith("Budapest "):
        r = t.removeprefix("Budapest ").removesuffix(" kerület").rstrip(".")
        if r in ROMAN:
            t = f"Budapest {ROMAN[r]:02d}. ker."
    return t.casefold().translate(FOLD)


def html(name, url):
    dest = RAW / f"okfo_{name}.html"
    if not dest.exists() or dest.stat().st_size == 0:
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
    return dest.read_text(encoding="utf-8", errors="replace")


def rows(doc):
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", doc, re.S | re.I):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ")).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        yield cells


def parse(name, url, known):
    """Both tables share a shape: ... postcode, settlement, vacant-from, long-term-from."""
    out, skipped = {}, []
    for c in rows(html(name, url)):
        if len(c) < 5:
            continue
        # settlement is the cell right after a 4-digit postcode
        town = next((c[i + 1] for i, v in enumerate(c[:-1]) if re.fullmatch(r"\d{4}", v)), None)
        if not town:
            continue
        town = town.split("(")[0].strip()
        key = known.get(fold(town))
        if not key:
            skipped.append(town)
            continue
        town = key
        dates = sorted(v for v in c if DATE.match(v))
        rec = out.setdefault(town, {"n": 0, "types": set(), "since": None})
        rec["n"] += 1
        if c[1] and len(c[1]) <= 8:
            rec["types"].add(c[1])
        if dates and (rec["since"] is None or dates[0] < rec["since"]):
            rec["since"] = dates[0]
    print(f"  {name:8} {len(out)} settlements with a vacancy"
          + (f"; {len(set(skipped))} unmatched names e.g. {sorted(set(skipped))[:3]}" if skipped else ""))
    return out


def main():
    # Simplification: all 33 Budapest dentist rows carry one central postcode (1088), so they cannot be
    # split by district the way schools are; they stay on the city-wide row, which the app skips.
    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    known = {fold(s["name"]): s["name"] for s in spine}
    gp = parse("gp", SRC["gp"], known)
    dent = parse("dentist", SRC["dentist"], known)

    for s in spine:
        g, d = gp.get(s["name"]), dent.get(s["name"])
        s["gp_vacant"] = g["n"] if g else 0
        s["gp_vacant_since"] = g["since"] if g else None
        s["gp_vacant_types"] = sorted(g["types"]) if g else []
        s["dentist_vacant"] = d["n"] if d else 0

    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    print(f"\nsettlements with an unfilled GP practice     : {sum(1 for s in spine if s['gp_vacant'])}")
    print(f"settlements with an unfilled dental practice : {sum(1 for s in spine if s['dentist_vacant'])}")
    ring = [s for s in spine if (s['dist_bp_km'] or 999) <= 70 and s['gp_vacant']]
    print(f"  of which within 70 km of Budapest          : {len(ring)}")
    return spine


def demo():
    spine = main()
    vac = [s for s in spine if s["gp_vacant"]]
    assert 300 < len(vac) < 1200, f"{len(vac)} settlements with vacancies - table shape changed?"
    assert all(s["gp_vacant_since"] is None or s["gp_vacant_since"] >= "2000.01.01" for s in spine)
    assert sum(s["gp_vacant"] for s in spine) >= len(vac)
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
