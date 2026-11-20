# bestLocation

Ranks all 3,178 Hungarian settlements against your own weighting of ~20 metrics —
schools, commute, soil, air quality, price, landscape — as a single-page dark
cartographic app over a static JSON dataset.

The product language is Hungarian; the code, comments and commits are English.

## Run it

Two ways. Both serve the same app at `http://localhost:8731/app/index.html`.

### Local (development)

```sh
python -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python tools/serve.py
```

`serve.py` is stdlib `http.server` — no build step, no bundler. Edit a file in `app/`
and reload the page.

It binds to `127.0.0.1` on purpose: it serves the whole repository directory, so it
stays off your LAN unless you ask. Set `HOST=0.0.0.0` to override.

### Docker

The image is the **runtime only** — it serves the app, it does not build the dataset.
`data/` is mounted rather than copied: it is ~1GB, gitignored, and regenerable.

```sh
docker build -t bestlocation .
docker run --rm --restart=unless-stopped \
  -p 127.0.0.1:8731:8731 \
  --user "$(id -u):$(id -g)" \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/data/out/commute:/app/data/out/commute" \
  -v "$PWD/data/raw/terrain:/app/data/raw/terrain" \
  bestlocation
```

Build the dataset on the host first (see below) — the container expects a populated
`data/out/`, and refuses to start without it rather than serving a broken app.

Two of those flags are load-bearing, not decoration:

- **The two extra `-v` mounts.** The bulk of `data/` is read-only, but the server writes
  two caches at request time: `commute.cached()` is write-through, so on a fully read-only
  mount *every new anchor returns 500*, and `fetch_terrain.tile()` writes downloaded
  elevation tiles — that failure is swallowed silently and terrain, slope, aspect and frost
  come back `null` with no error. Punching those two holes is cheaper than moving the caches.
- **`-p 127.0.0.1:8731:8731`.** The image sets `HOST=0.0.0.0` so the port publish works at
  all; binding the published side to loopback keeps it off your LAN. Drop the `127.0.0.1:`
  only when you actually intend to expose it, and read the note below first.

Exposing it publicly needs more than a port change: put a reverse proxy in front for TLS,
gzip and request timeouts, and note that `data/raw/` holds CC BY-NC and non-redistributable
sources (see `docs/data-sources.md`) that must not be served to the open internet.

## Data

`data/raw/` and the large products in `data/out/` are gitignored: ~1GB, all
regenerable, none of it worth diffing.

```sh
sh tools/build_all.sh            # full rebuild, in dependency order
PY=echo sh tools/build_all.sh    # dry-run: print the steps without running them
sh tools/build_all.sh --check    # run each step's self-check instead
```

`tools/build_all.sh` is the only place the rebuild order is written down — run it
rather than invoking fetchers by hand. Every `fetch_*.py` read-modify-writes the same
`settlements.json`, so they must run serialised, and one pair is genuinely
order-dependent (the script marks it).

Raw inputs (xlsx/csv/geojson under `data/raw/`) are downloaded by hand or by
`tools/dl_worldcover.sh`; `build_all.sh` turns raw into the dataset.

Every endpoint, its licence, and whether it was verified: `docs/data-sources.md`.

## Layout

- `app/` — the frontend. No framework, no build step, MapLibre GL from CDN. Plain
  classic scripts loaded in order by `index.html`.
  - `index.html` markup · `style.css` all styling · `lang.js` the Hungarian strings
  - `config.js` — `METRICS`, `FILTERS`, the score ramp. **Edit here to add a metric.**
  - `score.js` — the scoring math, kept DOM-free so it can be tested directly
  - `app.js` — rendering, map, handlers
- `tools/fetch_*.py` — one script per upstream source
- `tools/build_*.py` — spine, boundaries, and the trimmed `app_data.json` the browser loads
- `tools/serve.py`, `plot_report.py`, `commute.py` — the server and its two API routes
- `docs/` — data sources, visual spec

## Checks

```sh
node tools/test_score.mjs                          # 16 asserts on the scoring math
./.venv/bin/python tools/fetch_soil.py --check     # any fetch_*.py: its own self-check
```

`test_score.mjs` is the only check that runs on a clean checkout. **The `--check` demos are
not tests**: each one calls `main()`, which rewrites `data/out/settlements.json`, and most
need `data/raw/` (~1GB, gitignored) or a live upstream. Treat them as a build-verification
pass on a machine that already has the data, not as a suite — and snapshot
`settlements.json` if you run one outside a real rebuild.

`test_score.mjs` loads the real `config.js` and `score.js` with no stubs, and pins the
properties the product depends on: percentiles are rank-based and direction-aware,
missing data abstains instead of scoring zero, and the score is scale-free in the
weights (which is why 0–10 sliders are safe).

The closest thing to a smoke test — screenshots the running app at a fixed camera and
reports console errors and failed requests:

```sh
PLAYWRIGHT_BROWSERS_PATH=./.pw-browsers node tools/capture.mjs \
  http://127.0.0.1:8731/app/index.html /tmp/shot.png 1680x1000
```

## Conventions

- KSH settlement code (`ksh`) is the join key everywhere.
- Prefer stdlib. The only npm dependency is Playwright, for screenshots.
