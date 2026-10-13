"""Attach a short Hungarian summary of what the open web says about living in each settlement.

The research itself is done outside this script (web-search research sessions writing JSON
result files); this script validates those results, merges them into data/raw/opinions.json
keyed by KSH code, and attaches the cache to the spine.

A ONE-OFF collection: a cached result is final and is never overwritten by a later import.
  fetch_opinions.py                        attach cached results to the spine
                                           (what build_all.sh runs, so a rebuild keeps them)
  fetch_opinions.py --import FILE [FILE…]  merge research result files, then attach

Result file: a JSON array of
  {"ksh": "04659", "name": "Martonvásár", "status": "ok"|"thin",
   "summary": "<2-4 Hungarian sentences>"|null, "sources": [{"t": title, "u": "https://…"}]}
"""
import json, re, sys
from datetime import date
from pathlib import Path

import atomicjson

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
CACHE = RAW / "opinions.json"
FIELDS = ("op_status", "op_summary", "op_sources", "op_date")


def validate(r, names):
    """-> cache entry, or raise ValueError naming what is wrong with a research record."""
    ksh = r.get("ksh")
    if names.get(ksh) != r.get("name"):
        raise ValueError(f"ksh {ksh!r} is not {r.get('name')!r} in the spine")
    status = r.get("status")
    if status == "thin":
        return {"status": "thin", "summary": None, "sources": []}
    if status != "ok":
        raise ValueError(f"status {status!r}")
    summary = " ".join(str(r.get("summary") or "").split())
    if not 40 <= len(summary) <= 1200:
        raise ValueError(f"summary length {len(summary)}")
    sources = [{"t": " ".join(str(x.get("t") or x["u"]).split())[:200], "u": x["u"]}
               for x in r.get("sources") or []
               if isinstance(x, dict) and str(x.get("u", "")).startswith(("http://", "https://"))]
    # "two independent sources" is the rule; page 2 of the same forum thread is not a second one
    threads = {re.sub(r"(__oldal-\d+|/oldal/\d+|[?&]page=\d+)$", "", x["u"].rstrip("/")) for x in sources}
    if len(threads) < 2:
        raise ValueError(f"ok needs 2 independent sources, has {len(threads)}")
    return {"status": "ok", "summary": summary, "sources": sources[:6]}


def merge(files, spine, cache):
    names = {s["ksh"]: s["name"] for s in spine}
    added = kept = 0
    rejected = []
    for f in files:
        for r in json.loads(Path(f).read_text(encoding="utf-8")):
            try:
                v = validate(r, names)
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                rejected.append(f"{r.get('name') if isinstance(r, dict) else r!r}: {e}")
                continue
            if r["ksh"] in cache:                      # one-off: the first result stands
                kept += 1
                continue
            cache[r["ksh"]] = v | {"date": date.today().isoformat(), "by": "web research"}
            added += 1
    print(f"import: {added} added, {kept} already cached (left as is), {len(rejected)} rejected")
    for x in rejected:
        print("  rejected", x)
    return cache


def attach(spine, cache):
    hit = {"ok": 0, "thin": 0}
    for s in spine:
        for k in FIELDS:
            s.pop(k, None)                             # no stale copy survives a cache change
        v = cache.get(s["ksh"])
        if not v:
            continue
        s.update(op_status=v["status"], op_summary=v["summary"],
                 op_sources=v["sources"], op_date=v["date"])
        hit[v["status"]] += 1
    return hit


def main():
    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    if "--import" in sys.argv:
        files = [a for a in sys.argv[sys.argv.index("--import") + 1:] if not a.startswith("--")]
        cache = merge(files, spine, cache)
        atomicjson.write_json(CACHE, cache, ensure_ascii=False, indent=1)
    hit = attach(spine, cache)
    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    print(f"attached: {hit['ok']} ok, {hit['thin']} thin, of {len(spine)} settlements")
    return spine, cache


def demo():
    """No network, no writes to the cache: validation rules on hand-made records, then attach."""
    names = {"04659": "Martonvásár"}
    good = {"ksh": "04659", "name": "Martonvásár", "status": "ok",
            "summary": "A helyi fórumokon többen dicsérik a csendes utcákat és a jó vasúti kapcsolatot.",
            "sources": [{"t": "Fórum", "u": "https://forum.example/m"},
                        {"t": "rossz", "u": "javascript:alert(1)"}, "nem objektum",
                        {"t": "Blog", "u": "https://blog.example/m/"}]}
    v = validate(good, names)
    assert [x["u"] for x in v["sources"]] == ["https://forum.example/m", "https://blog.example/m/"], v
    same_thread = [{"u": "https://gyakorikerdesek.hu/q__1-x"}, {"u": "https://gyakorikerdesek.hu/q__1-x__oldal-2"}]
    assert validate(good | {"status": "thin"}, names) == {"status": "thin", "summary": None, "sources": []}
    for bad in (good | {"name": "Tök"}, good | {"status": "maybe"}, good | {"summary": "rövid"},
                good | {"sources": [{"u": "ftp://x"}]}, good | {"sources": same_thread}):
        try:
            validate(bad, names)
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass
    cache = merge([], [], {"04659": {"status": "thin"}})
    assert cache == {"04659": {"status": "thin"}}
    spine, cache = main()
    for s in spine:
        v = cache.get(s["ksh"])
        assert (s.get("op_status") == v["status"]) if v else "op_status" not in s
        assert all(x["u"].startswith(("http://", "https://")) for x in s.get("op_sources") or [])
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
