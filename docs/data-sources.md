# bestLocation — data sources

Distilled from four parallel research passes, 2026-08-31. Every endpoint marked ✅
was fetched and confirmed by me directly, not taken on the researcher's word.

Join key for the entire app: **KSH settlement code (helységkód)**.

## The spine

| Purpose | Source | Endpoint | Status |
|---|---|---|---|
| OSM ↔ KSH crosswalk | Wikidata P939 + P402 | SPARQL `?i wdt:P939 ?ksh ; wdt:P402 ?osm` | ✅ **3178/3178 complete**, CC0 |
| Settlement names/codes/járás | KSH Helységnévtár | `ksh.hu/docs/helysegnevtar/hnt_letoltes_2025.xlsx` | ✅ 1,370,790 B, 2025-09-30 |
| Settlement polygons (free) | OSM-HU | `data2.openstreetmap.hu/hatarok/kozighatarok.zip` | 2024-07 snapshot |
| Settlement polygons (official) | Lechner INSPIRE AU | `inspire.lechnerkozpont.hu/geoserver/AU/wfs` | ✅ numberMatched=3379, EOV, 2019 vintage |
| Basemap tiles | planetiler → PMTiles → Cloudflare R2 | Geofabrik `hungary-latest.osm.pbf` (308 MiB, daily) | style: Protomaps `dark` (BSD-3 / CC0) |
| Basemap fallback | OpenFreeMap | `tiles.openfreemap.org/styles/dark` | keyless, no quota |

Lechner sells the same boundaries at 960 Ft/polygon (~3M Ft for the country). We
don't need them.

## Trivial — one call or one file

| Layer | Endpoint |
|---|---|
| Population, age, education, employment (2001/2011/2022, all settlements) | KSH census API ✅ — `nepszamlalas2022.ksh.hu/api/dataflows/WBS003/{ver}/d/TIME_PERIOD,TEL_SZ_ADAT:NEME_KEV1,TERUL_GEO5:` returns **1.08 MB covering everything in ONE call**. Read `/api/version` at runtime (V67 drifts). |
| Dwelling stock quality (comfort, internet, solar, rooms) | same API, `WBL003` / `WBL018` |
| **Kompetenciamérés per school + lat/lon + családiháttér-index** | `oktatas.hu/pub_bin/dload/kozoktatas/OKM_adatvizualizacio/OKM_teljes_adatbazis_feladatellatasi_helyekre_2025.xlsx` ✅ (29 MB, 85,986 rows). **Server refuses HEAD; use ranged GET with a browser UA.** |
| Schools + óvoda + capacity, all in one | `kir.oktatas.hu/download/kozerdeku/kir_mukodo_feladatellatasi_helyek_2026_08_30.xlsx` ✅ (13,662 rows × ~140 cols) |
| **Soil: pH, OM, lime, clay/silt/sand, USDA texture, 100 m** | `maps.rissac.hu:6443/arcgis/rest/services/dosoremi/MapServer/identify` ✅ — **11 layers + per-property reliability.** ⚠ TLS cert EXPIRED (verify code 10): bypass deliberately in ingest, don't "fix" the chain. ⚠ layer 9's USDA class pixel values disagree with the fraction rasters — compute texture from sand/silt/clay yourself. ⚠ licence undeclared — email TAKI before any commercial use. |
| Soil: genetic type, talajértékszám, rooting depth | `…/agrotopo/MapServer` ✅ — 3,315 polygons, ~28 km² mean. **Regional flavour only, not a tiebreaker.** |
| Forest sub-compartments | `erdoterkep.nebih.gov.hu/geoserver/wms` ✅ WMS 1.3.0, *Fees: NONE* |
| Natura 2000 | EEA datahub, SHP/GPKG |
| Water/sewer coverage per settlement | KSH T-STAR / STADAT `kor0041` |
| PV yield / sunshine | PVGIS `re.jrc.ec.europa.eu/api/v5_3/PVcalc` ✅ (Budapest = 1034.39 kWh/kWp/yr) |
| Kedvezményezett települések | `njt.hu/jogszabaly/2015-105-20-22`, HTML tables |
| Falusi CSOK list (2631) | `njt.hu/jogszabaly/2015-105-20-22` style HTML, 302/2023 2. melléklet |
| DEM 30 m (slope + aspect) | Copernicus GLO-30, AWS Open Data |

## Easy — a bit of parsing

- **Vacant GP / dentist practices** — `alapellatas.okfo.gov.hu`, ~960-row HTML table, monthly, current to 2026-08-01.
- **Fibre, address-level with EOV coords** — NMHH `nagy_sebessegu_helyhez_kotott_..._251215.xlsx`, 541,349 rows. ⚠ lists **unserved** addresses; absence ≠ confirmed fibre.
- **Unemployment, monthly, per settlement** — NFSZ XLSX, 20 sheets.
- **House prices, NAV-verified transactions** — KSH Ingatlanadattár, **CC BY 4.0**. ✅ The
  app serves its entire dataset as one static file: `ksh.hu/s/ingatlanadattar/inga-data.json`
  (11.5 MB, 72,505 records, 2015–2024). No per-query export. Levels: `szint` 1 = vármegye,
  2 = street, 3 = settlement. Use **`cshaz_ar`** at szint 3 — detached-house price per m² in
  thousand HUF — not `total_ar`, which blends in flats and panel. KSH suppresses cells under
  3 transactions, and `house_price_year` varies per settlement, so always show the vintage.
  **Denominator is the HOUSE's floor area** (KSH módszertan: only transactions "amikor a
  lakás alapterületét is rögzítették"). The plot's value is inside the total price; the
  plot's SIZE is not published, so two houses of equal floor area on a 300 m² and a
  1000 m² plot get the same estimate. For a large-garden search this is a floor, not a
  central estimate.
- **Air quality, modelled 1 km surface** — EEA interpolated maps. The ~60 OLM stations are useless for 500 settlements.
- **Rail electrification + maxspeed** — OSM: 3,927 main-line ways, 100% electrified-tagged, 99.7% maxspeed-tagged.
- **Flood + waterlogging** — ⚠ the AKK hazard services are effectively down: the
  ImageServers (`Belviz_Valoszinuseg`, `ArteriObl_Hmax*`) return **0 bytes after 90–120 s**,
  and the AKK hazard MapServers are empty shells (`layers: []`, `fullExtent: NaN`) whose
  identify returns HTTP 500. ✅ Use `VIR/Belviz_fokok/MapServer` instead — answers in ~0.3 s
  and serves real polygons as GeoJSON: **[8] Hullámtér** (floodway, 55), **[11] Ártéri
  öblözet** (floodplain basin, 116), **[14] Vízjárta terület** (water-affected land, 1315).
  Download once, point-in-polygon locally. These are hazard *indicators*, not the EU Floods
  Directive 100-year map — label them as such. Retry AKK later for the real return periods.
- **Groundwater depth** — `…/services/Talajviz`, weekly.
- **Nitrate hazard** — nitrátérzékeny designation at **MePAR block level** (a few ha), via decree 43/2007 annex.

## Medium

HAKKA local taxes (ASP.NET `__doPostBack`) · KIR körzethatár (per-settlement query) ·
OMSZ climate grids (0.1° ≈ 11 km, plain HTTP directory tree, no API) ·
CLC50 25 m (request form).

## Commute times — the long pole

**r5py (OSM + GTFS) for transit, OSRM for drive.** Everything else is road-only:
OSRM has no timetable concept at all; Mapbox/GraphHopper/ORS offer no transit profile
and ORS caps driving isochrones at 1 h / 120 km; Valhalla's transit isochrones have
open correctness bugs (a 26-min connection missing from a 55-min polygon).

Blocker: **MÁV GTFS is behind a request form** with a human and undocumented licence
terms — days of latency. Submit the MÁV request early.

✅ **BKK static GTFS** — `go.bkk.hu/api/static/v1/public-gtfs/budapest_gtfs.zip` (48 MB zip,
330 MB stop_times, daily; `bkk.hu/gtfs/budapest_gtfs.zip` 301-redirects here). No key. Includes
**MÁV-HÉV H5–H9** (agency `HEV`, route_type 109); the MÁV feed does not. `calendar_dates.txt` only,
no `calendar.txt`. Licence: listed as **CC0-1.0** by Transitland (citing the national NAP portal);
BKK's own page says "teljesen nyilvános és ingyenes" but links no licence text — unconfirmed first-hand.
Used by `tools/commute.py` (walk → MÁV+BKK ≤1 transfer → walk), fetched to `data/raw/gtfs/`.

Compute: 500 centroids → 1 destination, departure window 06:30–08:30, percentiles 50
and 85. Seconds of compute; network build is the slow step.

## Not available — plan without these

| Layer | Why |
|---|---|
| **Crime per settlement** | Exists in PRE-STAT, gated behind personal Ügyfélkapu SSO. County-level alternative is CC BY-NC and too coarse. |
| **Income per settlement** | NAV publishes nothing; TeIR requires registration. Proxy: HAKKA tax revenue per capita + census education. Label as proxy. |
| **Zoning / HÉSZ, belterület** | No national bulk. E-TÉR's map backend doesn't resolve publicly; belterület is paid at Lechner. → **manual per-candidate check in Stage 2.** |
| **Cadastral parcels / aranykorona** | 4,800–5,000 Ft per lookup, Ügyfélkapu, no bulk. DOSoReMI 100 m is better for our purpose anyway. |
| **Births/deaths/migration split** | TeIR-gated. Net change from census + Helységnévtár is enough. |
| **Radon** | 10 km EU grid; fine Hungarian mapping only in Pest + Nógrád. |
| **Noise** | END covers agglomerations and major routes only — most rural villages have no map. **Blank ≠ quiet.** |
| **Habsburg historical maps** | Arcanum/mapire: €50/month, contract-gated. |
| **Solar export capacity** | MEKH needs a POD id from a bill. Point lookup only. |

## Resolution honesty

Too coarse to separate two villages — do not use as a tiebreaker:
50 km (C3S frost) · 31 km (ERA5) · 11 km (OMSZ grids, E-OBS) · 10 km (CAMS, radon) ·
1 km (PESERA erosion) · 28 km² mean polygon (AGROTOPO).

Fine enough to matter: **DOSoReMI 100 m**, MePAR nitrate blocks, GLO-30 30 m,
GWA 250 m wind, EEA air quality 1 km, VIIRS 500 m, all vector layers.

Frost pockets are a valley-floor and aspect effect that **no available climate grid
can see**. Derive frost risk from the 30 m DEM (elevation, aspect, cold-air drainage),
not from a climate raster.

## Licence posture

Clean: KSH (CC BY 4.0), Wikidata (CC0), OSM (ODbL), BKK GTFS (CC0 per Transitland/NAP), Copernicus/EEA/PVGIS, NÉBIH
(fees none). Undeclared but published: TAKI soil, OKFŐ, KIR, NMHH, OVF. Blocked for
commercial use: KSH crime CSVs (CC BY-NC), E-OBS (non-commercial). MÁV GTFS terms are
undocumented — ask when requesting.
