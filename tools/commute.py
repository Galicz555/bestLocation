"""Morning commute to ANY anchor, three ways; commute_best_min is the best of them.

  rail     drive <=8 km to a MAV/GYSEV station, scheduled rail (<=1 change) to any station
           within TARGET_KM of the anchor, flat EGRESS_MIN at the far end
  transit  walk <=WALK_KM from the settlement centroid to any stop, scheduled MAV + BKK
           (metro, tram, trolley, bus, HEV) with <=1 transfer, walk <=EGRESS_KM to the anchor
  road     crow-flies distance at ROAD_KMH plus a fixed overhead

Rail keeps the wide "anchor city" radius because most anchors (Szeged, Veszprem) have no
city-transit timetable here; transit needs one, and so is only as good as the BKK area.
"""
import bisect, csv, io, json, math, os, shutil, urllib.request, zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import atomicjson
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parent.parent
GTFS, OUT = ROOT / "data/raw/gtfs/mav", ROOT / "data/out"
BKK_ZIP = ROOT / "data/raw/gtfs/budapest_gtfs.zip"
BKK_URL = "https://go.bkk.hu/api/static/v1/public-gtfs/budapest_gtfs.zip"
RIVERS = ROOT / "data/raw/vir_water_6.geojson"   # written by fetch_landscape_water.py
CACHE = OUT / "commute"

REF_DATE = date(2026, 9, 8)                 # a Tuesday inside the feed's validity window
ARRIVE_FROM, ARRIVE_TO = "06:00:00", "09:00:00"
TARGET_KM = 5.0                             # stations counted as "the destination city"
MAX_STATION_KM = 8.0                        # how far you will drive to your home station
DRIVE_KMH, PARK_MIN, EGRESS_MIN = 40.0, 5, 15
TRANSFER_MIN, MAX_JOURNEY_MIN = 6, 240
ROAD_KMH, ROAD_OVERHEAD_MIN = 55.0, 20      # fallback when there is no usable train
# Transit. Walks are crow-flies times WALK_DETOUR, a calibration knob for street grids.
WALK_KMH, WALK_DETOUR = 5.0, 1.3
WALK_KM, EGRESS_KM, XFER_KM = 1.2, 1.0, 0.3  # access walk, egress walk, walk between stops
XFER_MIN = 3                                # on top of the walk; stands in for platform time
BKK_FROM = "04:30:00"                       # Simplification: drops BKK legs of journeys over 90 min
MODEL_V = 3                                 # bump when a rule below changes cached results
INF = 10 ** 9


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


def walk_s(km):
    return km * WALK_DETOUR / WALK_KMH * 3600


def fetch_bkk():
    """Download the BKK static GTFS (BKK + MAV-HEV), atomically. Daily feed, ~48 MB."""
    BKK_ZIP.parent.mkdir(parents=True, exist_ok=True)
    tmp = BKK_ZIP.with_name(BKK_ZIP.name + ".part")
    req = urllib.request.Request(BKK_URL, headers={"User-Agent": "bestLocation/0.1"})
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    with zipfile.ZipFile(tmp) as z:
        assert {"stops.txt", "trips.txt", "stop_times.txt", "calendar_dates.txt"} <= set(z.namelist())
    os.replace(tmp, BKK_ZIP)


def bkk(name):
    """Header dict + row lists of one file inside the BKK zip, streamed: stop_times is 330 MB."""
    if not BKK_ZIP.exists():
        fetch_bkk()
    with zipfile.ZipFile(BKK_ZIP) as z, z.open(name) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))
        col = {c: i for i, c in enumerate(next(r))}
        yield col
        yield from r


def bkk_service_day():
    """(yyyymmdd, service ids): the feed's busiest weekday matching REF_DATE's.

    The BKK feed rolls every few weeks, so a fixed date would fall out of it at the next
    download. Busiest, not first: a holiday or school-break Tuesday runs fewer services.
    Simplification: calendar_dates.txt only — BKK ships no calendar.txt; revisit if it starts to."""
    it = bkk("calendar_dates.txt")
    col = next(it)
    by = defaultdict(set)
    for r in it:
        if r[col["exception_type"]] == "1":
            by[r[col["date"]]].add(r[col["service_id"]])
    wd = REF_DATE.weekday()
    days = [d for d in by if date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday() == wd]
    if not days:
        raise SystemExit("commute: BKK feed has no service on a matching weekday — re-fetch it")
    day = max(sorted(days), key=lambda d: len(by[d]))
    return day, by[day]


def grid_key(lat, lon):
    return int(lat / 0.012), int(lon / 0.018)      # ~1.33 km cells: 3x3 covers WALK_KM


def near(net, lat, lon, km):
    """[(transit stop index, km)] within km of a point."""
    gy, gx = grid_key(lat, lon)
    out = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for i in net["grid"].get((gy + dy, gx + dx), ()):
                d = haversine((lat, lon), net["tpos"][i])
                if d <= km:
                    out.append((i, d))
    return out


_net = {}


def network():
    """Parse the timetable once; an anchor change must not re-read 415k rows."""
    if _net:
        return _net
    day, stamp = REF_DATE.strftime("%A").lower(), REF_DATE.strftime("%Y%m%d")
    services = {r["service_id"] for r in rows("calendar.txt")
                if r[day] == "1" and r["start_date"] <= stamp <= r["end_date"]}
    try:
        for r in rows("calendar_dates.txt"):
            if r["date"] == stamp:
                (services.add if r["exception_type"] == "1" else services.discard)(r["service_id"])
    except FileNotFoundError:
        pass
    # An empty service set is not "no trains today": it means REF_DATE has fallen out
    # of the feed's validity window, and every settlement would silently drop to the
    # 55 km/h road proxy on a metric with default weight 3.
    if not services:
        raise SystemExit(f"commute: no GTFS services on {REF_DATE} — the feed has rolled "
                         f"over, move REF_DATE into calendar.txt's validity window")
    stops = {r["stop_id"]: (r["stop_name"], float(r["stop_lat"]), float(r["stop_lon"]))
             for r in rows("stops.txt") if r["stop_lat"]}
    trips = {r["trip_id"] for r in rows("trips.txt") if r["service_id"] in services}
    seq = defaultdict(list)
    for r in rows("stop_times.txt"):
        if r["trip_id"] in trips and r["arrival_time"]:
            seq[r["trip_id"]].append((int(r["stop_sequence"]), r["stop_id"],
                                      r["departure_time"] or r["arrival_time"], r["arrival_time"]))
    for v in seq.values():
        v.sort()

    # Transit: one stop index across both feeds, trips as (line, stops, dep s, arr s).
    tname, tpos, tidx, legs = [], [], {}, []

    def stop(key, name, lat, lon):
        if key not in tidx:
            tidx[key] = len(tname)
            tname.append(name)
            tpos.append((lat, lon))
        return tidx[key]

    hi_s = secs(ARRIVE_TO)
    for sts in seq.values():
        leg = [(stop(("m", sid), *stops[sid]), secs(dep), secs(arr))
               for _, sid, dep, arr in sts if sid in stops and secs(arr) <= hi_s]
        if len(leg) > 1:
            ss, dd, aa = zip(*leg)
            legs.append(("MÁV", list(ss), list(dd), list(aa)))

    bday, bsvc = bkk_service_day()
    it = bkk("routes.txt")
    col = next(it)
    line = {r[col["route_id"]]: r[col["route_short_name"]] for r in it}
    it = bkk("trips.txt")
    col = next(it)
    trip_line = {r[col["trip_id"]]: line[r[col["route_id"]]] for r in it
                 if r[col["service_id"]] in bsvc}
    it = bkk("stops.txt")
    col = next(it)
    bstops = {r[col["stop_id"]]: (r[col["stop_name"]], float(r[col["stop_lat"]]),
                                  float(r[col["stop_lon"]])) for r in it if r[col["stop_lat"]]}
    it = bkk("stop_times.txt")
    col = next(it)
    ct, cs, ca, cd, cq = (col[k] for k in ("trip_id", "stop_id", "arrival_time",
                                           "departure_time", "stop_sequence"))
    bseq = defaultdict(list)
    for r in it:                                   # 4.3M rows -> ~200k kept
        if r[ct] in trip_line and BKK_FROM <= r[ca] <= ARRIVE_TO:
            bseq[r[ct]].append((int(r[cq]), stop(("b", r[cs]), *bstops[r[cs]]),
                                secs(r[cd] or r[ca]), secs(r[ca])))
    for tid, sts in bseq.items():
        if len(sts) > 1:
            _, ss, dd, aa = zip(*sorted(sts))
            legs.append((trip_line[tid], list(ss), list(dd), list(aa)))
    del bseq

    grid = defaultdict(list)
    for i, (la, lo) in enumerate(tpos):
        grid[grid_key(la, lo)].append(i)
    net = {"grid": grid, "tpos": tpos}
    # Simplification: crow-flies footpaths within XFER_KM; ignores pathways.txt (metro depths)
    foot = [[(j, round(walk_s(d))) for j, d in near(net, la, lo, XFER_KM)] for la, lo in tpos]

    # Simplification: main Danube channel only, bridges ignored — a drive to a station on the other
    # bank is refused even where a bridge makes it real (Budakalász -> Újpest, Dunavecse ->
    # Dunaújváros). Not shapely.prep(): its lazily built index races under ThreadingHTTPServer.
    river = next(f for f in json.loads(RIVERS.read_text(encoding="utf-8"))["features"]
                 if (f["properties"] or {}).get("VIZFOLYAS") == "Duna")
    danube = LineString(river["geometry"]["coordinates"]).simplify(0.0005)

    _net.update(stops=stops, seq=dict(seq), tname=tname, tpos=tpos, grid=grid, foot=foot,
                trips=legs, bkk_day=bday, danube=danube)
    return _net


def targets(anchor_lat, anchor_lon):
    """sid -> name of the stations counted as arriving in the anchor city."""
    stops = network()["stops"]
    target = {sid: nm for sid, (nm, la, lo) in stops.items()
              if haversine((anchor_lat, anchor_lon), (la, lo)) <= TARGET_KM}
    if not target:                                    # tiny anchor: take the single nearest
        sid = min(stops, key=lambda s: haversine((anchor_lat, anchor_lon),
                                                 (stops[s][1], stops[s][2])))
        target = {sid: stops[sid][0]}
    return target


def stations(anchor_lat, anchor_lon):
    """Best rail journey to the anchor city, per origin station."""
    net = network()
    stops, seq = net["stops"], net["seq"]
    target = targets(anchor_lat, anchor_lon)
    lo_s, hi_s = secs(ARRIVE_FROM), secs(ARRIVE_TO)

    best, departures = {}, {}
    for sts in seq.values():
        hit = next(((i, st) for i, (_, st, _, _) in enumerate(sts) if st in target), None)
        if not hit:
            continue
        i, tstop = hit
        arr = secs(sts[i][3])
        if not (lo_s <= arr <= hi_s):
            continue
        for _, sid, dep, _ in sts[:i]:
            mins = (arr - secs(dep)) // 60
            if 0 < mins <= MAX_JOURNEY_MIN:
                b = best.setdefault(sid, {"min": 10 ** 9, "n": 0, "term": None})
                b["n"] += 1
                if mins < b["min"]:
                    b["min"], b["term"] = mins, target[tstop]
            departures.setdefault(sid, []).append((secs(dep), arr, target[tstop]))
    for v in departures.values():
        v.sort()

    def connect(stop, ready):
        opts = departures.get(stop)
        if not opts:
            return None
        i = bisect.bisect_left(opts, (ready, -1, ""))
        return min(opts[i:i + 40], key=lambda o: o[1]) if i < len(opts) else None

    for sts in seq.values():                          # round 2: one change
        after = None
        for idx in range(len(sts) - 1, -1, -1):
            _, sid, dep, arr_here = sts[idx]
            if sid in target:
                after = None
                continue
            if after is not None:
                mins = (after[0] - secs(dep)) // 60
                if 0 < mins <= MAX_JOURNEY_MIN:
                    b = best.setdefault(sid, {"min": 10 ** 9, "n": 0, "term": None})
                    if mins < b["min"]:
                        b["min"], b["term"] = mins, after[1] + " (1 change)"
                    b["n"] += 1
            c = connect(sid, secs(arr_here) + TRANSFER_MIN * 60)
            if c and (after is None or c[1] < after[0]):
                after = (c[1], c[2])

    return [{"id": sid, "name": stops[sid][0], "lat": stops[sid][1], "lon": stops[sid][2],
             "rail_min": b["min"], "trains_am": b["n"], "terminus": b["term"]}
            for sid, b in best.items() if sid in stops]


def transit(anchor_lat, anchor_lon):
    """stop index -> (stop-to-desk seconds, line label), for the best morning journey.

    Round 1 profiles every stop that reaches the anchor on one vehicle: sorted departures
    with a suffix-minimum of desk arrival, so "board at or after t" is one bisect. Round 2
    scans each trip backwards and at every stop either walks to the desk or changes, via a
    footpath, into a round-1 profile. Simplification: <=1 transfer, and the minimum over the window,
    not a headway-weighted wait — a 30-min-headway bus scores as well as the metro."""
    net = network()
    trips, foot = net["trips"], net["foot"]
    lo_s, hi_s = secs(ARRIVE_FROM), secs(ARRIVE_TO)
    egress = {i: round(walk_s(d)) for i, d in near(net, anchor_lat, anchor_lon, EGRESS_KM)}

    prof = defaultdict(list)
    for line, ss, dd, aa in trips:
        desk = INF
        for j in range(len(ss) - 1, -1, -1):
            if desk < INF:
                prof[ss[j]].append((dd[j], desk, line))
            e = egress.get(ss[j])
            if e is not None and lo_s <= aa[j] + e <= hi_s:
                desk = min(desk, aa[j] + e)
    table = {}
    for s, v in prof.items():
        v.sort()
        suf, m = [None] * len(v), (INF, None)
        for k in range(len(v) - 1, -1, -1):
            if v[k][1] < m[0]:
                m = v[k][1:]
            suf[k] = m
        table[s] = ([x[0] for x in v], suf)
    del prof

    best = {}
    cap = MAX_JOURNEY_MIN * 60
    for line, ss, dd, aa in trips:
        after, via = INF, None
        for j in range(len(ss) - 1, -1, -1):
            s = ss[j]
            if after < INF and after - dd[j] <= cap and after - dd[j] < best.get(s, (INF,))[0]:
                best[s] = (after - dd[j], via)
            e = egress.get(s)
            if e is not None and lo_s <= aa[j] + e <= hi_s and aa[j] + e < after:
                after, via = aa[j] + e, line
            ready = aa[j] + XFER_MIN * 60
            for t, w in foot[s]:
                p = table.get(t)
                if p:
                    i = bisect.bisect_left(p[0], ready + w)
                    if i < len(p[0]) and p[1][i][0] < after:
                        after, via = p[1][i][0], f"{line} → {p[1][i][1]}"
    return best


def for_settlements(anchor_lat, anchor_lon, spine):
    """ksh -> commute record, for every settlement in `spine`."""
    st = stations(anchor_lat, anchor_lon)
    net = network()
    stops, tname, danube = net["stops"], net["tname"], net["danube"]
    tr = transit(anchor_lat, anchor_lon)
    tgt = [stops[sid][1:] for sid in targets(anchor_lat, anchor_lon)]
    out = {}
    # A bounding-box reject before the trig: this is ~700 stations x 3,178 settlements
    # and all but a handful of pairs are far outside MAX_STATION_KM. 110.5 km/degree
    # under-states a real degree, so the box is slightly generous and never clips a
    # station the haversine would have accepted. Measured 1,155 ms -> 162 ms.
    dlat_max = MAX_STATION_KM / 110.5
    for s in spine:
        if not s.get("lat"):
            continue
        dlon_max = dlat_max / max(0.1, math.cos(math.radians(s["lat"])))
        d_anchor = haversine((anchor_lat, anchor_lon), (s["lat"], s["lon"]))
        road = round(d_anchor / ROAD_KMH * 60 + ROAD_OVERHEAD_MIN)
        rec = {"dist_km": round(d_anchor, 1), "drive_min_est": road,
               "commute_min": None, "rail_station": None, "rail_station_km": None,
               "rail_min": None, "rail_trains_am": 0, "rail_terminus": None}
        best = None
        # A station farther away than the destination itself means driving out of the city
        # to ride back in (every Budapest district did this); that is not a rail commute.
        d_dest = min(haversine((s["lat"], s["lon"]), t) for t in tgt)
        for x in st:
            if abs(x["lat"] - s["lat"]) > dlat_max or abs(x["lon"] - s["lon"]) > dlon_max:
                continue
            d = haversine((s["lat"], s["lon"]), (x["lat"], x["lon"]))
            if d > MAX_STATION_KM or d >= d_dest:
                continue
            total = x["rail_min"] + d / DRIVE_KMH * 60 + PARK_MIN + EGRESS_MIN
            if (best is None or total < best[0]) and not danube.intersects(
                    LineString([(s["lon"], s["lat"]), (x["lon"], x["lat"])])):
                best = (total, d, x)
        if best:
            total, d, x = best
            rec.update(commute_min=round(total), rail_station=x["name"],
                       rail_station_km=round(d, 1), rail_min=x["rail_min"],
                       rail_trains_am=x["trains_am"], rail_terminus=x["terminus"])

        # Simplification: access walk from the centroid, not from where people live in a big district
        rec.update(transit_min=None, transit_stop=None, transit_walk_km=None, transit_line=None)
        tbest = min(((walk_s(d) + tr[i][0], i, d) for i, d in near(net, s["lat"], s["lon"], WALK_KM)
                     if i in tr), default=None)
        if d_anchor <= WALK_KM and (tbest is None or walk_s(d_anchor) <= tbest[0]):
            rec.update(transit_min=round(walk_s(d_anchor) / 60), transit_walk_km=round(d_anchor, 1),
                       transit_line="walk")
        elif tbest:
            t, i, d = tbest
            rec.update(transit_min=round(t / 60), transit_stop=tname[i],
                       transit_walk_km=round(d, 1), transit_line=tr[i][1])

        opts = [(v, m) for v, m in ((rec["transit_min"], "transit"), (rec["commute_min"], "rail"),
                                    (road, "road")) if v]
        rec["commute_best_min"], rec["commute_mode"] = min(opts, key=lambda o: o[0])
        out[s["ksh"]] = rec
    return out


def has_timetable():
    return (GTFS / "stops.txt").exists()


def road_only(anchor_lat, anchor_lon, spine):
    """ksh -> commute record from the road estimate alone, for a checkout without the
    timetables (a fresh clone). Simplification: the same 55 km/h crow-flies proxy that
    for_settlements() falls back to when no train or transit route exists."""
    out = {}
    for s in spine:
        if not s.get("lat"):
            continue
        d = haversine((anchor_lat, anchor_lon), (s["lat"], s["lon"]))
        road = round(d / ROAD_KMH * 60 + ROAD_OVERHEAD_MIN)
        out[s["ksh"]] = {"dist_km": round(d, 1), "drive_min_est": road, "commute_min": None,
                         "rail_station": None, "rail_station_km": None, "rail_min": None,
                         "rail_trains_am": 0, "rail_terminus": None, "transit_min": None,
                         "transit_stop": None, "transit_walk_km": None, "transit_line": None,
                         "commute_best_min": road, "commute_mode": "road"}
    return out


def feed_version():
    """Stamp for the cache key, so replacing the timetable retires every cached anchor.
    Simplification: mtimes of the MAV files and the BKK zip — GTFS feed_info.txt is optional and
    MAV does not ship a version in it."""
    return max([int((GTFS / n).stat().st_mtime)
                for n in ("calendar.txt", "stops.txt", "trips.txt", "stop_times.txt")]
               + [int(BKK_ZIP.stat().st_mtime)])


def cached(anchor_lat, anchor_lon, spine):
    if not has_timetable():
        return road_only(anchor_lat, anchor_lon, spine)
    network()                                   # downloads the BKK feed feed_version stamps
    CACHE.mkdir(parents=True, exist_ok=True)
    # MODEL_V retires cached anchors when the commute rules change, as feed_version does for the timetable
    f = CACHE / f"{anchor_lat:.4f}_{anchor_lon:.4f}_{feed_version()}_m{MODEL_V}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    d = for_settlements(anchor_lat, anchor_lon, spine)
    atomicjson.write_json(f, d, ensure_ascii=False, separators=(",", ":"))
    return d


if __name__ == "__main__":
    import sys
    if "--fetch" in sys.argv:                   # refresh the BKK feed; MAV is a manual request
        fetch_bkk()
    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    # positional LAT LON; flags (--fetch, --check) can come in any order around them
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    lat, lon = (float(pos[0]), float(pos[1])) if len(pos) >= 2 else (47.4977, 19.0544)   # Deák tér
    d = cached(lat, lon, spine)
    served = [v for v in d.values() if v["commute_min"]]
    v = sorted(x["commute_best_min"] for x in d.values() if x["commute_best_min"])
    print(f"anchor {lat},{lon}: {len(d)} settlements, {len(served)} with a train")
    print(f"  door-to-desk: min {v[0]}  median {v[len(v)//2]}  within 60: "
          f"{sum(1 for x in v if x <= 60)}")
    by = {s['ksh']: s['name'] for s in spine}
    top = sorted(((x['commute_best_min'], by[k]) for k, x in d.items() if x['commute_best_min']))[:8]
    print("  nearest by time:", ", ".join(f"{n} {m}" for m, n in top))
    if "--check" in sys.argv:   # read-only: writes only the per-anchor cache, never settlements.json
        net = network()
        assert date(*map(int, (net["bkk_day"][:4], net["bkk_day"][4:6], net["bkk_day"][6:]))
                    ).weekday() == REF_DATE.weekday()
        d = {by[k]: x for k, x in for_settlements(47.4977, 19.0544, spine).items()}   # Deák tér
        bp = lambda n: d[f"Budapest {n:02d}. ker."]
        assert bp(1)["commute_min"] is None, "a district must not drive out to ride back in"
        for town in ("Budaörs", "Törökbálint", "Vác", "Gödöllő"):
            assert d[town]["commute_min"], f"{town} lost its real rail commute"
        # Belváros: ~0.4 km from the centroid, a walk or one metro stop
        assert bp(5)["commute_mode"] == "transit" and bp(5)["transit_min"] < 15, bp(5)
        assert bp(13)["transit_min"] < 20 and "M3" in bp(13)["transit_line"], bp(13)
        # Kispest: a bus to M3 then ~15 min underground; BKK's own planner says ~35
        assert 25 <= bp(19)["transit_min"] <= 45 and "M3" in bp(19)["transit_line"], bp(19)
        # Soroksár: H6 is 17 min to Közvágóhíd, then tram 2 and a walk (~44 min from the
        # HÉV stop), plus ~20 min because the centroid sits 1.2 km from it
        assert 40 <= bp(23)["transit_min"] <= 70, bp(23)
        assert d["Vác"]["commute_mode"] == "rail" and "MÁV" in d["Vác"]["transit_line"]
        assert d["Magyarszombatfa"]["commute_mode"] == "road"
        # no district drives to a station on the other bank (Soroksár, Csepel -> Budafok)
        at = {nm: (la, lo) for nm, la, lo in net["stops"].values()}
        for n in range(1, 24):
            r, s = bp(n), next(x for x in spine if x["name"] == f"Budapest {n:02d}. ker.")
            assert r["commute_min"] is None or not net["danube"].intersects(LineString(
                [(s["lon"], s["lat"]), at[r["rail_station"]][::-1]])), r
            assert r["transit_min"], f"district {n} has no transit route"
        assert d["Szentendre"]["rail_station"] is None, "Szentendre drove across the Danube"
        print("self-check OK")
