"""Trim the spine to the scoring fields the web app needs, for every settlement.

Distance and commute are no longer baked in: they depend on the anchor the user
picks, and arrive from /api/anchor at runtime."""
import json, sys
from pathlib import Path

import atomicjson

OUT = Path(__file__).resolve().parent.parent / "data/out"
KEEP = ["ksh", "name", "megye", "lat", "lon",
        "pop_2022", "pop_trend_21y_pct",
        "unemployment_pct", "families_with_children_pct",
        "dwelling_vacancy_pct", "dwelling_comfort_pct",
        "school_score_mean", "school_vs_national", "school_beats_prediction",
        "ovoda_sites", "ovoda_places", "primary_sites",
        "gp_vacant", "gp_vacant_since",
        "house_price_m2", "house_price_year", "house_tx", "house_price_trend_pct",
        "house_120m2_mhuf", "house_price_last_m2",
        "flat_price_m2", "flat_price_year", "flat_tx", "flat_price_last_m2",
        "soil_ph", "soil_om_pct", "soil_sand_pct", "soil_silt_pct", "soil_clay_pct",
        "soil_texture", "garden_score",
        "in_floodway", "in_floodplain", "in_waterlogged",
        "elevation_m", "slope_deg", "aspect_deg", "local_relief_m",
        "south_facing", "frost_risk",
        "crime_rate_county", "crime_trend_county", "crime_year",
        "precip_mm_yr", "rain_days_yr", "wind_kmh_mean",
        "hot_days_yr", "last_frost_doy", "frost_free_days",
        "pm25_annual", "pm25_winter", "no2_annual", "pv_kwh_kwp",
        "lc_tree_pct", "lc_grass_pct", "lc_crop_pct", "lc_built_pct", "lc_water_pct",
        "relief_class", "bigriver_km", "bigriver_name", "lake_km", "lake_name",
        "pollution_nearest_km", "pollution_sources_3km",
        "landfill_km", "quarry_km", "wwtp_km", "works_km",
        "op_status", "op_summary", "op_sources", "op_date",
        ]   # commute + distance now arrive per-anchor from /api/anchor
# Trimmed: 30 further spine fields nothing in app/ reads (~2.0 MB of the 8.0 MB the
# browser downloads). The plot panel gets the full detail from /api/plot, which reads
# settlements.json directly — check serve.py's field list before adding one back here.

# Empty in every good build so far: fetch_landscape_water writes bigriver_km/lake_km but
# never the matching name. A real gap, pre-existing and separate — exempted by name so
# the coverage assert below stays loud about everything else.
ALLOW_EMPTY = {"bigriver_name", "lake_name"}
# Web-opinion summaries are paid and collected in rounds (pilot, then the 90 km ring), so
# mostly-empty is their normal state, not a skipped fetcher.
ALLOW_EMPTY |= {"op_status", "op_summary", "op_sources", "op_date"}


def main():
    spine = json.loads((OUT / "settlements.json").read_text(encoding="utf-8"))
    ring = [{k: s.get(k) for k in KEEP} for s in spine if s.get("lat")]
    ring.sort(key=lambda s: s["name"])
    miss = {k: sum(1 for s in ring if s.get(k) is None) for k in KEEP}
    print("fields with missing values:", {k: v for k, v in miss.items() if v})
    # A column that is all-but-empty means a fetcher was skipped or ran out of order
    # (see the ORDERING CONSTRAINT in build_all.sh) — valid JSON, silently wrong app.
    # Checked before the write, so a bad spine never becomes the file the browser loads.
    empty = {k: v for k, v in miss.items()
             if v > 0.9 * len(ring) and k not in ALLOW_EMPTY}
    assert not empty, f"columns >90% empty, a fetcher did not run: {empty}"
    dest = OUT / "app_data.json"
    atomicjson.write_json(dest, ring, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(ring)} settlements (nationwide) -> {dest} ({dest.stat().st_size/1024:.0f} KB)")
    return ring


if __name__ == "__main__":
    r = main()
    assert len(r) > 3000 and all(s["lat"] and s["lon"] for s in r), "bad app data"
    print("self-check OK")
