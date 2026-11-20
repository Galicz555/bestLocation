"""Download the third-party files the static demo ships, every one pinned, into a NEW directory.

    python3 tools/fetch_demo_assets.py [DIR] [--pmtiles BIN]      DIR defaults to data/raw/demo

DIR must not exist. Nothing here carries an identifier of ours: the only header sent is a
generic client name. What lands in DIR (tools/build_demo.py reads exactly this layout):

  maplibre/{maplibre-gl-csp.js, maplibre-gl-csp-worker.js, maplibre-gl.css, LICENSE.txt}
                  maplibre-gl 4.7.1 from the npm tarball (the CSP build: no eval, no inline worker)
  glyphs/<fontstack>/<range>.pbf, OFL.txt      protomaps/basemaps-assets, pinned commit
  sprites/dark{,@2x}.{json,png}, LICENSE.tangrams    same commit; icons derived from tangrams/icons
  sample.pmtiles  only with --pmtiles: `go-pmtiles extract` of the planet build BUILD over BBOX

It also writes app/basemap/style.json (a tracked file, not a download) from the pinned
@protomaps/basemaps package, with {{BASE}} where the page's own URL goes at runtime.
The extract tool is built from source with
    GOPATH=<fresh dir> go install github.com/protomaps/go-pmtiles@v1.31.2
"""
import hashlib, io, json, subprocess, sys, tarfile, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = "bestlocation-demo-fetch/1"

MAPLIBRE = ("https://registry.npmjs.org/maplibre-gl/-/maplibre-gl-4.7.1.tgz",
            "7e8a778cff03abad64ae19674977058616e1cf7c3712cabd1c35461ae465f923")
BASEMAPS = ("https://registry.npmjs.org/@protomaps/basemaps/-/basemaps-5.7.2.tgz",
            "2d5d41b29cdd2364f7092ad439bd9d170b4f38cbec8858cefbe84d0f98125ce6")
ASSETS = "https://raw.githubusercontent.com/protomaps/basemaps-assets/028c18f713baecad011301ff7a69acc39bcc2ae7/"
TANGRAMS_LICENSE = ("https://raw.githubusercontent.com/tangrams/icons/"
                    "92510779634f4a006c61ea70e50cb8c52c765a81/LICENSE.md")
BUILD = "https://build.protomaps.com/20261118.pmtiles"
BBOX, MAXZOOM = "18.55,47.15,19.55,47.85", "12"      # 30 km around Deák tér; z12 = 12 MB raw
FONTS = ("Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic")
RANGES = ("0-255", "256-511", "512-767", "7680-7935", "8192-8447")
STYLE_JS = """
import {layers, namedFlavor} from %s;
const style = {version: 8, glyphs: '{{BASE}}basemap/glyphs/{fontstack}/{range}.pbf',
  sprite: '{{BASE}}basemap/sprites/dark',
  sources: {protomaps: {type: 'vector', tiles: ['{{BASE}}tiles/{z}/{x}/{y}.mvt'], minzoom: 0,
    maxzoom: %s, bounds: [%s],
    attribution: '<a href="https://protomaps.com">Protomaps</a> © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}},
  layers: layers('protomaps', namedFlavor('dark'), {lang: 'hu'})};
process.stdout.write(JSON.stringify(style, null, 1) + '\\n');
"""


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}),
                                timeout=60) as r:
        return r.read()


def pinned(spec):
    data = get(spec[0])
    got = hashlib.sha256(data).hexdigest()
    assert got == spec[1], f"{spec[0]}: sha256 {got}, pinned {spec[1]}"
    return tarfile.open(fileobj=io.BytesIO(data))


def main(dest, pmtiles):
    if dest.exists():
        raise SystemExit(f"{dest} exists; the downloads go into a fresh directory")
    for sub in ("maplibre", "glyphs", "sprites", "basemaps-pkg"):
        (dest / sub).mkdir(parents=True)
    tar = pinned(MAPLIBRE)
    for name in ("maplibre-gl-csp.js", "maplibre-gl-csp-worker.js", "maplibre-gl.css", "LICENSE.txt"):
        (dest / "maplibre" / name).write_bytes(tar.extractfile(f"package/dist/{name}").read())
    pinned(BASEMAPS).extractall(dest / "basemaps-pkg", filter="data")
    for font in FONTS:
        (dest / "glyphs" / font).mkdir()
        for rng in RANGES:
            (dest / "glyphs" / font / f"{rng}.pbf").write_bytes(
                get(ASSETS + urllib.parse.quote(f"fonts/{font}/{rng}.pbf")))
    (dest / "glyphs/OFL.txt").write_bytes(get(ASSETS + "fonts/OFL.txt"))
    for name in ("dark.json", "dark.png", "dark@2x.json", "dark@2x.png"):
        (dest / "sprites" / name).write_bytes(get(ASSETS + "sprites/v4/" + urllib.parse.quote(name)))
    (dest / "sprites/LICENSE.tangrams").write_bytes(get(TANGRAMS_LICENSE))
    pkg = (dest / "basemaps-pkg/package/dist/esm/index.js").resolve().as_uri()
    style = subprocess.run(["node", "--input-type=module", "-e", STYLE_JS % (
        json.dumps(pkg), MAXZOOM, BBOX)], check=True, capture_output=True, text=True).stdout
    out = ROOT / "app/basemap/style.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(style, encoding="utf-8")
    if pmtiles:
        subprocess.run([pmtiles, "extract", BUILD, str(dest / "sample.pmtiles"),
                        f"--bbox={BBOX}", f"--maxzoom={MAXZOOM}"], check=True)
    print(f"downloaded into {dest}; style written to {out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    bin_ = a.pop(a.index("--pmtiles") + 1) if "--pmtiles" in a else None
    if "--pmtiles" in a:
        a.remove("--pmtiles")
    main(Path(a[0] if a else ROOT / "data/raw/demo").resolve(), bin_)
