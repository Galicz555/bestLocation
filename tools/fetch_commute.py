"""Morning rail commute to Budapest, computed from the MAV GTFS timetable.

Not a road-distance guess: for a chosen weekday we walk every trip that reaches a
Budapest terminus, and for each upstream station record the actual scheduled journey.

  door-to-desk = access to the station + scheduled rail time + egress in Budapest

Access is a drive at ~40 km/h plus 5 min to park; egress is a flat 15 min from the
terminus to a city-centre desk. Both are stated assumptions, not measurements - the
rail leg in the middle is the real timetable.

Two rounds: direct trains, then journeys with ONE change. The second round is a
backward sweep - for each trip we ask, at every stop, whether alighting there and
catching a connection gets you to Budapest sooner than staying on. Anything needing
two or more changes is reported as no rail service.
"""
import csv, json, math, sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import atomicjson

ROOT = Path(__file__).resolve().parent.parent
GTFS, OUT = ROOT / "data/raw/gtfs/mav", ROOT / "data/out"
BP = {"267": "Keleti", "269": "Nyugati", "3639": "Déli", "3640": "Kelenföld"}
REF_DATE = date(2026, 9, 8)          # a Tuesday inside the feed's validity window
ARRIVE_FROM, ARRIVE_TO = "06:00:00", "09:00:00"
MAX_STATION_KM = 8.0
DRIVE_KMH, PARK_MIN, EGRESS_MIN = 40.0, 5, 15
TRANSFER_MIN = 6          # minimum minutes to change platforms
MAX_JOURNEY_MIN = 240


def rows(name):
    with open(GTFS / name, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def secs(t):
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def haversine(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    h = (math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p)
         * math.sin((lo2 - lo1) * p / 2) ** 2)
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def active_services():
    day = REF_DATE.strftime("%A").lower()
    stamp = REF_DATE.strftime("%Y%m%d")
    ok = set()
    for r in rows("calendar.txt"):
        if r[day] == "1" and r["start_date"] <= stamp <= r["end_date"]:
            ok.add(r["service_id"])
    try:
        for r in rows("calendar_dates.txt"):
            if r["date"] == stamp:
                (ok.add if r["exception_type"] == "1" else ok.discard)(r["service_id"])
    except FileNotFoundError:
        pass
    return ok


def main():
    services = active_services()
    stops = {r["stop_id"]: (r["stop_name"], float(r["stop_lat"]), float(r["stop_lon"]))
             for r in rows("stops.txt") if r["stop_lat"]}
    trips = {r["trip_id"] for r in rows("trips.txt") if r["service_id"] in services}
    print(f"reference day {REF_DATE} ({REF_DATE.strftime('%A')}): "
          f"{len(services)} services, {len(trips)} trips, {len(stops)} stops")

    seq = defaultdict(list)
    for r in rows("stop_times.txt"):
        if r["trip_id"] in trips and r["arrival_time"]:
            seq[r["trip_id"]].append((int(r["stop_sequence"]), r["stop_id"],
                                      r["departure_time"] or r["arrival_time"],
                                      r["arrival_time"]))

    lo, hi = secs(ARRIVE_FROM), secs(ARRIVE_TO)
    best = {}          # origin stop -> dict
    for tid, sts in seq.items():
        sts.sort()
        bp_at = [(i, s) for i, (_, s, _, _) in enumerate(sts) if s in BP]
        if not bp_at:
            continue
        i, bp_stop = bp_at[0]
        arr = secs(sts[i][3])
        if not (lo <= arr <= hi):
            continue
        for _, sid, dep, _ in sts[:i]:
            mins = (arr - secs(dep)) // 60
            if mins <= 0 or mins > 240:
                continue
            b = best.setdefault(sid, {"min": 10 ** 9, "n": 0, "term": None})
            b["n"] += 1
            if mins < b["min"]:
                b["min"], b["term"] = mins, BP[bp_stop]
    print(f"stations with a direct morning train to Budapest: {len(best)}")

    # --- round 2: one change ------------------------------------------------
    # departures[stop] = sorted (departure_secs, arrival_at_BP_secs) from round 1
    departures = {}
    for tid, sts in seq.items():
        bp_at = [(i, st) for i, (_, st, _, _) in enumerate(sts) if st in BP]
        if not bp_at:
            continue
        i, bp_stop = bp_at[0]
        arr = secs(sts[i][3])
        if not (lo <= arr <= hi):
            continue
        for _, sid, dep, _ in sts[:i]:
            departures.setdefault(sid, []).append((secs(dep), arr, BP[bp_stop]))
    for v in departures.values():
        v.sort()

    def connection(stop, ready):
        """Earliest arrival in Budapest from `stop` departing at or after `ready`."""
        opts = departures.get(stop)
        if not opts:
            return None
        import bisect
        i = bisect.bisect_left(opts, (ready, -1, ""))
        return min(opts[i:i + 40], key=lambda o: o[1]) if i < len(opts) else None

    added = 0
    for tid, sts in seq.items():
        best_after = None                     # (arrBP, terminus) reachable by alighting later
        for idx in range(len(sts) - 1, -1, -1):
            _, sid, dep, arr_here = sts[idx]
            if sid in BP:
                best_after = None             # already in Budapest; nothing to improve
                continue
            if best_after is not None:
                d = secs(dep)
                mins = (best_after[0] - d) // 60
                if 0 < mins <= MAX_JOURNEY_MIN:
                    b = best.setdefault(sid, {"min": 10 ** 9, "n": 0, "term": None})
                    if mins < b["min"]:
                        if b["min"] == 10 ** 9:
                            added += 1
                        b["min"], b["term"] = mins, best_after[1] + " (1 change)"
                    b["n"] += 1
            c = connection(sid, secs(arr_here) + TRANSFER_MIN * 60)
            if c and (best_after is None or c[1] < best_after[0]):
                best_after = (c[1], c[2])
    print(f"stations reachable only with one change: +{added} "
          f"(total {len(best)})")

    # cache the served stations so plot-level lookups don't re-read the whole timetable
    atomicjson.write_json(OUT / "rail_stations.json",
        [{"id": sid, "name": stops[sid][0], "lat": stops[sid][1], "lon": stops[sid][2],
          "rail_min": b["min"], "trains_am": b["n"], "terminus": b["term"]}
         for sid, b in best.items() if sid in stops], ensure_ascii=False)

    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    ring = [s for s in spine if (s.get("dist_bp_km") or 999) <= 90 and s.get("lat")]
    served = [(sid, stops[sid]) for sid in best if sid in stops]

    hit = 0
    for s in ring:
        cands = []
        for sid, (nm, la, lo_) in served:
            d = haversine((s["lat"], s["lon"]), (la, lo_))
            if d <= MAX_STATION_KM:
                b = best[sid]
                total = b["min"] + d / DRIVE_KMH * 60 + PARK_MIN + EGRESS_MIN
                cands.append((total, d, nm, b))
        if not cands:
            s["commute_min"] = s["rail_station"] = s["rail_min"] = None
            s["rail_trains_am"] = 0
            s["rail_station_km"] = s["rail_terminus"] = None
            continue
        hit += 1
        total, d, nm, b = min(cands, key=lambda c: c[0])
        s["commute_min"] = round(total)
        s["rail_station"] = nm
        s["rail_station_km"] = round(d, 1)
        s["rail_min"] = b["min"]
        s["rail_trains_am"] = b["n"]
        s["rail_terminus"] = b["term"]

    # Road fallback so settlements off the rail network still get a comparable number.
    # Simplification: crude 55 km/h door-to-door proxy + 20 min; replace with OSRM if it ever matters.
    for s in ring:
        d = s.get("dist_bp_km")
        s["drive_min_est"] = round(d / 55 * 60 + 20) if d else None
        opts = [x for x in (s.get("commute_min"), s["drive_min_est"]) if x]
        s["commute_best_min"] = min(opts) if opts else None
        s["commute_mode"] = ("rail" if s.get("commute_min") and
                             s["commute_min"] <= (s["drive_min_est"] or 10**9) else "road")

    atomicjson.write_json(OUT / "settlements.json", spine, ensure_ascii=False, indent=1)
    got = [s for s in ring if s.get("commute_min")]
    print(f"\nsettlements with a rail commute: {hit}/{len(ring)}")
    if got:
        v = sorted(s["commute_min"] for s in got)
        print(f"  door-to-desk: min {v[0]} median {v[len(v)//2]} max {v[-1]} min")
        print(f"  within 60 min: {sum(1 for x in v if x <= 60)};  within 90: {sum(1 for x in v if x <= 90)}")
    return spine


def demo():
    spine = main()
    by = {s["name"]: s for s in spine}
    for n in ("Vác", "Martonvásár", "Gödöllő"):
        assert by[n].get("commute_min"), f"{n} is on a main line and must have a commute"
        assert by[n]["rail_trains_am"] >= 3, (n, by[n]["rail_trains_am"])
    assert by["Vác"]["rail_terminus"].startswith("Nyugati"), by["Vác"]["rail_terminus"]
    assert by["Martonvásár"]["rail_terminus"].split(" (")[0] in ("Déli", "Kelenföld"), \
        by["Martonvásár"]["rail_terminus"]
    got = [s for s in spine if s.get("commute_min")]
    assert len(got) > 200, f"only {len(got)} settlements served"
    for s in got:
        assert 10 < s["commute_min"] < 300, (s["name"], s["commute_min"])
        assert s["rail_min"] >= 1
    ring = [s for s in spine if (s.get("dist_bp_km") or 999) <= 90]
    assert all(s.get("commute_best_min") for s in ring if s.get("dist_bp_km")), "every ring settlement needs a commute estimate"
    print("self-check OK")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
