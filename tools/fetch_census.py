"""Pull KSH 2022 census dataflows onto the settlement spine.

The census API is undocumented but public. Leaving TERUL_GEO5 empty returns every
settlement in one call, and leaving TIME_PERIOD unvalued returns all three censuses,
so each layer below costs exactly one HTTP request.
"""
import json, sys, urllib.request
from pathlib import Path

import atomicjson

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw/census", ROOT / "data/out"
BASE = "https://nepszamlalas2022.ksh.hu/api"
UA = "bestLocation/0.1 (personal house-search tool)"

# id -> (dataset, dimension path). Lifted from the dashboard's own chart configs.
FLOWS = {
    "age":       ("WBS003", "TIME_PERIOD,TEL_SZ_ADAT:NEME_KEV1+MY_LT15+MY15-64+MY_GE65+FY_LT15+FY15-64+FY_GE65,TERUL_GEO5:"),
    "education": ("WBS003", "TIME_PERIOD:2022,TEL_SZ_ADAT:BISK_V2+LISK1+LISK2+LISK3+LISK4+LISK5+LISKNAP,TERUL_GEO5:"),
    "activity":  ("WBS003", "TIME_PERIOD:2022,TEL_SZ_ADAT:EMP+UNE+INACI+INACE+LT_MWA+GAKT_V1,TERUL_GEO5:"),
    "children":  ("WBC003", "TIME_PERIOD:2022,TEL_CS_ADAT:CSGYESZ_V2+CSGY_0+CSGY_1+CSGY_2+CSGY_3+CSGY_GE4,TERUL_GEO5:"),
    "occupancy": ("WBL018", "TIME_PERIOD:2022,INDICATORS3:LAKAS_OCS_TOTAL+LAKAS_OCS_DW_OC+LAKAS_OCS_DW_NOC,TERUL_GEO5:"),
    "comfort":   ("WBL003", "TIME_PERIOD:2022,INDICATORS2:KOMF_TOTAL+KOMF_COMF1+KOMF_COMF2+KOMF_COMF3+KOMF_COMF4+KOMF_COMF5,TERUL_GEO5:"),
}
# The indicator dimension is named differently per dataset; the value is always the 2nd-to-last key.
DIM = {"WBS003": "TEL_SZ_ADAT", "WBC003": "TEL_CS_ADAT", "WBL018": "INDICATORS3", "WBL003": "INDICATORS2"}


def get(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        return json.load(open(dest, encoding="utf-8"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
    dest.write_bytes(data)
    return json.loads(data)


def version():
    return get(f"{BASE}/version", RAW / "version.json")["version"]


def pull(name, ver):
    ds, dims = FLOWS[name]
    rows = get(f"{BASE}/dataflows/{ds}/{ver}/d/{dims}", RAW / f"{name}.json")
    dim = DIM[ds]
    out = {}
    for r in rows:
        geo = r["TERUL_GEO5"]
        if not geo.isdigit() or len(geo) != 5:   # drop districts ('001') and NUTS ('HU21')
            continue
        v = r.get("OBS_VALUE")
        if v in (None, ""):
            continue
        key = f'{r[dim]}_{r["TIME_PERIOD"]}' if name == "age" else r[dim]
        out.setdefault(geo, {})[key] = float(v)
    print(f"  {name:10} {len(rows):>6} rows -> {len(out)} settlements")
    return out


def pct(num, den):
    return round(100 * num / den, 2) if den else None


def main():
    ver = version()
    print(f"census API version {ver}")
    data = {n: pull(n, ver) for n in FLOWS}

    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    hit = 0
    for s in spine:
        k = s["ksh"]
        a, e = data["age"].get(k, {}), data["education"].get(k, {})
        act, ch = data["activity"].get(k, {}), data["children"].get(k, {})
        occ, cf = data["occupancy"].get(k, {}), data["comfort"].get(k, {})
        if not a:
            continue
        hit += 1
        p01, p11, p22 = (a.get(f"NEME_KEV1_{y}") for y in ("2001", "2011", "2022"))
        s["pop_2001"], s["pop_2011"], s["pop_2022"] = p01, p11, p22
        s["pop_trend_21y_pct"] = pct(p22 - p01, p01) if p01 and p22 else None
        s["pop_trend_11y_pct"] = pct(p22 - p11, p11) if p11 and p22 else None

        kids = (a.get("MY_LT15_2022") or 0) + (a.get("FY_LT15_2022") or 0)
        old = (a.get("MY_GE65_2022") or 0) + (a.get("FY_GE65_2022") or 0)
        s["child_share_pct"], s["elderly_share_pct"] = pct(kids, p22), pct(old, p22)

        s["tertiary_share_pct"] = pct(e.get("LISK5", 0), e.get("BISK_V2"))
        s["unemployment_pct"] = pct(act.get("UNE", 0), (act.get("EMP", 0) + act.get("UNE", 0)))
        with_kids = sum(ch.get(c, 0) for c in ("CSGY_1", "CSGY_2", "CSGY_3", "CSGY_GE4"))
        s["families_with_children_pct"] = pct(with_kids, ch.get("CSGYESZ_V2"))
        s["dwelling_vacancy_pct"] = pct(occ.get("LAKAS_OCS_DW_NOC", 0), occ.get("LAKAS_OCS_TOTAL"))
        # KOMF_COMF1+2 = osszkomfortos + komfortos, i.e. fully/well-appointed dwellings
        s["dwelling_comfort_pct"] = pct(cf.get("KOMF_COMF1", 0) + cf.get("KOMF_COMF2", 0),
                                        cf.get("KOMF_TOTAL"))

    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    print(f"\nenriched {hit}/{len(spine)} settlements -> data/out/settlements.json")
    return spine


def demo():
    """Self-check: known population facts and sane percentage ranges."""
    spine = main()
    by = {s["name"]: s for s in spine}
    assert by["Martonvásár"]["pop_2022"] == 6106, by["Martonvásár"]["pop_2022"]
    assert by["Martonvásár"]["pop_trend_21y_pct"] > 15, "Martonvasar grew ~18% since 2001"
    assert by["Vác"]["pop_2022"] == 34449
    scored = [s for s in spine if s.get("pop_2022")]
    assert len(scored) > 3100, f"only {len(scored)} settlements got census data"
    for f in ("child_share_pct", "elderly_share_pct", "tertiary_share_pct",
              "unemployment_pct", "dwelling_vacancy_pct", "dwelling_comfort_pct"):
        vals = [s[f] for s in scored if s.get(f) is not None]
        assert len(vals) > 3000, f"{f}: only {len(vals)} values"
        assert 0 <= min(vals) and max(vals) <= 100, f"{f} out of range: {min(vals)}..{max(vals)}"
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
