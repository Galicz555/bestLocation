# Simplification: runtime image only — it serves the app, it does not build the dataset.
# The fetch_*/build_* chain stays on the host: it needs ~1GB of data/raw and live
# upstream APIs. Mount data/ in; see README.
#
# Pinned to a patch release, not the moving `3.14-slim` tag, so a rebuild a year from
# now gets the same interpreter and the same Debian baseline as this one.
FROM python:3.14.7-slim-trixie

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Wheels exist for numpy/shapely/pillow on this base, so no build toolchain.
# requirements-runtime.txt is the serve path only — see the comment in that file.
COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt

COPY app/ app/
COPY tools/ tools/

# The container never writes inside the image; the two cache directories it does write
# are bind mounts, so run with --user matching their owner (see README).
USER nobody

ENV HOST=0.0.0.0
EXPOSE 8731

# Probes a data file rather than index.html: this fails if the data mount disappears,
# not merely if the process died. start-period covers the cache warm-up, which reads
# ~50MB of JSON before the port binds (10-15s on a cold page cache).
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8731/data/out/source_dates.json',timeout=4)"

CMD ["python", "tools/serve.py", "8731"]
