# bestLocation — visual spec

Register **A: dark cartographic instrument**. Flat 2D main view, one accent ramp,
a separate 3D view reserved for terrain/aspect where relief is the actual subject.

## Reference

CARTO **Dark Matter** (`basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json`),
measured 2026-08-31 by parsing the style spec directly — these are the authored
colour values, not pixels sampled through a screenshot and a JPEG encoder.

Caveat: style-spec values, not rendered output. Antialiasing, layer opacity and
blending shift the on-screen result slightly. Re-measure from a capture once the
first real map renders.

## Measured basemap palette

| Role | Hex | HSV | Rel. luminance |
|---|---|---|---|
| Ground / background | `#0e0e0e` | H0 S0 **V5** | 14 |
| Landcover, parks (fill) | `#0e0e0e` | H0 S0 V5 | 14 |
| Minor structure, casings | `#1a1a1a`–`#232323` | H0 S0 V10–14 | 26–35 |
| Paths, poi_park | `#262626`–`#515151` | H0 S0 V15–32 | 38–81 |
| **Water** | `#2c353c` | **H206 S27 V24** | 52 |
| Waterway | `#3f5a6d` | H205 S42 V43 | 86 |
| **Roads (arterial workhorse)** | `#414758` | **H224 S26 V35** | 71 |
| Roads (primary, brighter) | `#535666` | H231 S19 V40 | 87 |
| Boundaries (country inner) | `#5c5e5e`–`#8a8a8a` | H0–180 S0–2 V37–40 | ~95 |
| Labels — village / hamlet | `#9a9999`–`#b6b4b4` | H0 S1 V60–71 | — |
| Labels — town / city | `#ccd0e4`–`#e9eff6` | H212–230 S5–11 V89–96 | — |
| Label halo | `#181818`–`#222222` | H0 S0 V9–13 | — |

### The two rules that fall out of the measurement

1. **The entire basemap lives in S ≤ 27 and V ≤ 40.** Every chromatic element is a
   cool desaturated blue, H 195–235. Labels are the only thing above V 55, and they
   are near-neutral.
2. Therefore **everything warm, and everything above S 35 / V 50, is unoccupied.**
   That is where the data goes. Zero collision with the basemap on either axis —
   which is the whole reason this register works for a 10-layer stack.

## Score ramp

**magma, domain truncated to [0.25, 1.0]** and remapped. Perceptually uniform,
monotonic in lightness (so it survives greyscale printing and every form of colour
blindness), and it starts near-black — meaning it grows *out of* the basemap
instead of sitting on top of it.

| Score | Hex | HSV | Contrast vs `#0e0e0e` |
|---|---|---|---|
| 0.00 | `#7e1f81` | H298 S76 V51 | 2.2:1 |
| 0.20 | `#aa2c7a` | H323 S74 V67 | 3.1:1 |
| 0.40 | `#d33e68` | H343 S71 V83 | 4.3:1 |
| 0.60 | `#f25a54` | H2 S65 V95 | 5.8:1 |
| 0.80 | `#fe875a` | H16 S64 V99 | 8.1:1 |
| 1.00 | `#feb578` | H27 S53 V100 | 11.1:1 |

Truncating at 0.25 is deliberate: raw magma's bottom third sits at 0.9–1.6:1 against
this background, so the worst settlements would simply disappear rather than read as
"scored low". Cut the tail and the whole range stays legible. Reserve the pale
`#fcfdbf` top stop for selection highlight, not for data.

Fill opacity 0.75 over the basemap; 1.0 on hover. Selected settlement gets a 1.5px
`#fcfdbf` stroke — the only pure-bright element on screen.

## Layer accent hues

Overlay layers must not compete with the score surface. Each gets one hue, all at
S 60–75 / V 80–95, chosen well away from the ramp's H 298→27 arc:

| Layer group | Hue | Hex |
|---|---|---|
| Education | H150 (green) | `#3ddc84` |
| Healthcare | H190 (cyan) | `#2ed3d3` |
| Transport / rail | H45 (amber) | `#f5c542` |
| Soil / garden | H90 (lime) | `#94d82d` |
| Hazard (flood, belvíz, noise) | H0 (red) | `#ff4d4d` |
| Amenities | H265 (violet) | `#9d7cff` |

Hazard red is the only layer allowed to be alarming, and only ever as an outline or
hatch — never a fill, or it competes with the low end of the score ramp.

## UI chrome

- Panel `#141414`, border `#262626`, hover `#1c1c1c` — one step above ground so
  panels sit on the map without a drop shadow.
- Text primary `#e9eff6` (matches the reference's brightest label), secondary
  `#9a9999`, muted `#8a8a8a`.
- Type: Inter for UI, `tabular-nums` for every number in the ranked table.
- Slider track `#262626`, fill and thumb in the layer's own accent hue — the control
  is colour-coded to the thing it controls.
- Radius: 6px. Motion: 150ms ease-out, and nothing animates on the map itself except
  score recomputation (200ms colour interpolation).

## Definition of done for the look

Capture the main view at the Budapest-centred camera the app opens on and check:
1. Basemap measures S ≤ 27, V ≤ 40 everywhere outside labels.
2. Score surface hue lands within 5° of the ramp table above.
3. Lowest-scoring settlement is still distinguishable from ground (≥ 2:1).
4. Every overlay is separable from the score surface by hue alone at 80% zoom-out.
