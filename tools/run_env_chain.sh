#!/bin/sh
# Serialised: all three read-modify-write settlements.json.
cd "$(dirname "$0")/.." || exit 1
echo "=== climate (NASA POWER) ==="
./.venv/bin/python tools/fetch_climate.py || echo "climate FAILED"
echo "=== air quality (CAMS via Open-Meteo) ==="
./.venv/bin/python tools/fetch_airquality.py || echo "air FAILED"
echo "=== solar retry for the 289 dropped by connection resets ==="
./.venv/bin/python tools/fetch_solar.py || echo "solar FAILED"
echo "=== all environment layers done ==="
