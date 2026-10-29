# dFRX challenge coin: flat-face, 4-colour 3D-print files

A two-sided, 60 mm hexagonal challenge coin made from the two supplied renders. It prints in four
filaments: **black, grey, copper and neon green**.

The design is drawn as clean, solid colour blocks: one colour per panel, straight edges, and black
grooves between panels. The render's lighting effects (bevel highlights, reflections, shading) are
left out rather than printed as thin grey lines.

## Which folder to use

| Folder | Nozzle | Finest line |
|---|---|---|
| `stl/nozzle_0.2/` | 0.2 mm | 0.22 mm, **recommended** |
| `stl/nozzle_0.4/` | 0.4 mm | 0.38 mm (lettering is softer; see Known limits) |

Each folder includes these preview images:
- `side_*_face.png`: each face as it will print.
- `compare_side_*.png`: the source render on the left, the print on the right.
- `render_*.png`: 3D previews of the one-piece coin.
- `detail_before_after.png` (0.2 mm folder only): the source, the previous version and this version, side by side.

`stl/previous/` holds earlier versions, kept for reference.

## Files (in each folder)

| Set | What it is |
|---|---|
| `coin_one_piece_*` (recommended) | The whole coin in one print, 3.4 mm thick. The eagle face prints **against the build plate** (mirrored in the file, so it reads correctly once you flip the coin). The dFRX face is inlaid in the top layers. No glue and no seam. |
| `half_a_eagle_*`, `half_b_dfrx_*` | Alternative: two 1.7 mm halves, each printed face-down, then glued back-to-back. |
| `*_4colour.3mf` | All four STLs of a set in one file. |

| Suffix | Filament | Contains |
|---|---|---|
| `_black` | black | background, grooves between panels, motto lettering, rim edge, core |
| `_grey` | grey | rim, all metal panels (bright and dark metal alike), motto band, dFRX letters, radar and dial line-work |
| `_copper` | copper | copper feathers, "DRONE AS FIRST RESPONDER", 000 / 131444 |
| `_green` | neon green | glow inlays, dial ticks, eye, lid line, crosshair, gem, markers |

## How the artwork is converted

1. **Rectify:** the render is mapped onto a regular hexagon using its six measured corners.
2. **Flatten:** L0 gradient smoothing removes the metal texture, scratches and lighting noise while keeping edges sharp.
3. **Classify:** each pixel is assigned a material by CIELAB lightness and hue. The darkest feathers are found by context, as compact regions enclosed by grooves on the eagle.
4. **Solid panels:** each panel is the area enclosed by the render's black grooves, including the shallower grooves between neighbouring copper feathers. Each panel is filled with the one material it mostly contains. Highlight strips, reflections and shading inside a panel disappear, and the panel keeps its full outline. Thin grey strips along a copper, green or dark panel are that panel's bevel highlight, so they take the panel's colour.
5. **Dark metal:** with four filaments the darker metal can't have its own colour, so dark-metal panels print grey. The black grooves keep each one distinct.
6. **Straight edges:** each panel's outline is smoothed on its own, removing notches and spikes under 0.25 mm. A panel can grow only into black, so neighbouring panels never merge. The outline is then redrawn as a polygon. Lettering, the eye and the digits keep their traced curves.
7. **Line-work:** side B's radar rings and the eagle side's dial ticks are redrawn as smooth strokes of constant width.
8. **Lettering:** the render's own letterforms are kept. The render's typo "SECON**O**S" is corrected to **"SECONDS"** by turning the O into a D in the same typeface. The eye is traced from the render: almond socket, C-shaped iris and lid line. Side B's gem and crosshair are drawn as exact geometry.
9. **Printable widths:** lines narrower than the nozzle can print are widened to the minimum. Grooves are widened evenly along their centreline, so they stay uniform. Each colour is then vectorised and cut from the coin body as a 0.6 mm inlay.

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
4. **The first layer is the eagle face.** Wash the plate with dish soap, level the bed carefully, and slow the first layer down.
5. Print one test coin before a batch run.

## Known limits

- **0.4 mm nozzle lettering:** the motto's strokes and letter gaps in the render are about 0.28–0.33 mm, which is below a 0.4 mm nozzle's width. They're kept as traced, and the slicer resolves them as best it can. The 000 / 131444 digits are widened to 0.38 mm, which partly closes the small counters in the 4s.
- **One grey for all metal:** the render's two metal tones become one grey filament, so the dark-metal feathers are told apart only by their grooves.

## Regenerating

```bash
pip install -r requirements.txt
python3 tools/build_coin.py --min-feature 0.22 --out stl/nozzle_0.2
python3 tools/build_coin.py --min-feature 0.38 --out stl/nozzle_0.4
python3 tools/render_preview.py stl/nozzle_0.2               # refreshes render_*.png
```

Other options:
- **Dark metal:** `--gunmetal black` (solid black), `hatch` (grey hatching) or `filament` (a 5th filament).
- **Outline options:**
  - `--seams`: a black line wherever dark metal meets grey.
  - `--straighten`: the polygon tolerance in mm (0 turns straightening off).
  - `--no-blocks` and `--no-smooth-lines`: keep panels and line-work as traced.
- **Coin geometry:** `--size`, `--thickness`, `--inlay`, `--chamfer`, `--rim`, `--rim-edge`.
- **Debugging:** `COIN_DEBUG=<dir>` saves the label map after each processing stage.
