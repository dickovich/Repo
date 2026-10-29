# dFRX challenge coin: flat-face, 4-colour 3D-print files

A two-sided, 60 mm hexagonal challenge coin made from the two supplied renders. It prints in four
filaments: **black, grey, copper and neon green**. Both faces are flat colour inlays: every colour
sits level, and the detail comes from colour only.

## Which folder to use

| Folder | Nozzle | Dark-metal feathers | Notes |
|---|---|---|---|
| `stl/nozzle_0.2/hatched/` | 0.2 mm | fine grey hatching on black | **Recommended. Closest to the render.** |
| `stl/nozzle_0.2/solid/` | 0.2 mm | solid black, outlined by their grey bevel edges | Simpler and faster to print, but darker than the render |
| `stl/nozzle_0.4/hatched/` | 0.4 mm | hatching (coarser, 0.38 mm lines) | Lettering is below nozzle width; see Known limits |
| `stl/nozzle_0.4/solid/` | 0.4 mm | solid black | |

Each folder has `side_*_face.png` (the face as it will print), `compare_side_*.png` (the source on
the left, the print on the right) and `render_*.png` (3D previews of the one-piece coin).
`stl/previous/` holds earlier versions, kept for reference.

## Files (in each folder)

| Set | What it is |
|---|---|
| `coin_one_piece_*` (recommended) | The whole coin in one print, 3.4 mm thick. The eagle face prints **against the build plate** (mirrored in the file, so it reads correctly once you flip the coin). The dFRX face is inlaid in the top layers. No glue and no seam. |
| `half_a_eagle_*`, `half_b_dfrx_*` | Alternative: two 1.7 mm halves, each printed face-down, then glued back-to-back. |
| `*_4colour.3mf` | All four STLs of a set in one file. |

| Suffix | Filament | Contains |
|---|---|---|
| `_black` | black | background, grooves between facets, motto lettering, rim edge, core |
| `_grey` | grey | rim, metal facets and bevel highlights, dark-feather hatching, motto band, dFRX letters, radar line-work |
| `_copper` | copper | copper feathers, "DRONE AS FIRST RESPONDER", 000 / 131444 |
| `_green` | neon green | glow inlays, dial ticks, eye, lid line, crosshair, gem, markers |

## How the artwork is converted

1. **Rectify:** the render is mapped onto a regular hexagon using its six measured corners.
2. **Flatten:** L0 gradient smoothing removes the metal texture, scratches and lighting noise but keeps facet edges sharp. Each facet becomes one flat colour with a crisp edge.
3. **Classify:** each pixel is assigned by CIELAB lightness and hue:
   - black/groove: L < 70
   - dark metal: L 70–100
   - grey metal: L ≥ 100, including the shaded sides of the tail and talons
   - copper: warm hue
   - neon green: including the near-white cores of the glow lines
4. **Darkest feathers:** they flatten to the same lightness as the background, so they're found by context instead: compact regions enclosed by grooves and bevel highlights, lying on the eagle.
5. **Dark metal in four colours:** it prints as **engraver's hatching**. Fine grey lines run along each feather's long axis at 40% coverage, which matches the render's dark-metal tone (L ≈ 85, between black at ≈ 20 and grey at ≈ 185).
6. **Eye:** traced like the rest of the face (almond socket, C-shaped iris ring, outer ring, crescent, highlight). The dark-green lid line under the brow is picked up along its segment.
7. **Lettering:** the render's own letterforms are kept in both faces. Only one change is made: the render's typo "SECON**O**S" becomes **"SECONDS"**. The misspelt O is turned into a D in the same typeface, with the same outline and stroke weight.
8. **Exact geometry:** side B's green gem and its vertical crosshair are drawn exactly. The rim is a clean hexagon with the render's proportions: a dark outer edge, the grey band, then a dark groove.
9. **Printable widths:** lines narrower than the nozzle can print are widened to the minimum (0.22 mm for a 0.2 mm nozzle, 0.38 mm for 0.4 mm), except in the lettering zones (see Known limits). Each colour is then vectorised and cut from the coin body as a 0.6 mm inlay.

## Geometry (defaults)

- **Size:** hexagon 60 mm across corners (52 mm across flats), 3.4 mm thick, with a 0.4 mm 45° chamfer on both face edges.
- **Inlay:** colours are 0.6 mm deep on each face.
- **Mesh check:** every STL is a closed (watertight) mesh. Adjacent colour bodies share a boundary film averaging 0.002 mm, which slicers ignore.

## Printing (Bambu Studio / OrcaSlicer)

1. Import the four `coin_one_piece_*.stl` files together, or the 3MF. When asked, choose **"load as a single object with multiple parts"**, then assign a filament to each part.
2. Keep each colour as a separate part; don't use paint-on colour.
3. Suggested settings:
   - **0.2 mm nozzle:** 0.06–0.08 mm layers through the inlays, and a first-layer line width of about 0.22 mm.
   - **0.4 mm nozzle:** 0.1 mm layers, and a first-layer line width of about 0.3 mm.
   - Arachne wall generator, ironing on the top surface (dFRX face), and a prime tower or "flush into infill".
4. **The first layer is the eagle face.** It's fine, multi-coloured line-work, including the hatching. Wash the plate with dish soap, level the bed carefully, and slow the first layer down.
5. Print one test coin before a batch run.

## Known limits

- **0.4 mm nozzle lettering:** the motto's strokes and letter gaps in the render are about 0.28–0.33 mm, which is below a 0.4 mm nozzle's width. They're kept as traced, so they keep their shape, and the slicer's variable-width walls resolve them as best they can. Expect softer lettering than with a 0.2 mm nozzle. The 000 / 131444 digits are widened to 0.38 mm, which partly closes the small counters in the 4s.
- **No lighting effects:** the render's gloss, shading and glow can't be printed. Each region is one flat colour.

## Regenerating

```bash
pip install -r requirements.txt
python3 tools/build_coin.py --min-feature 0.22 --gunmetal hatch --out stl/nozzle_0.2/hatched
python3 tools/build_coin.py --min-feature 0.22 --gunmetal black --out stl/nozzle_0.2/solid
python3 tools/build_coin.py --min-feature 0.38 --gunmetal hatch --out stl/nozzle_0.4/hatched
python3 tools/build_coin.py --min-feature 0.38 --gunmetal black --out stl/nozzle_0.4/solid
python3 tools/render_preview.py stl/nozzle_0.2/hatched             # refreshes render_*.png
```

Other options:
- `--gunmetal grey`: the dark feathers print solid grey.
- `--gunmetal filament`: the dark feathers print as a 5th filament.
- `--hatch-pitch`: the hatching line spacing.
- `--size`, `--thickness`, `--inlay`, `--chamfer`, `--rim`, `--rim-edge`: coin geometry.
