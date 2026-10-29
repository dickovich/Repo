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
- `detail_circled_eagle.png` and `detail_circled_dfrx.png` (0.2 mm folder only): the areas circled in review, showing the source, the previous version and this version, side by side.

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
3. **Facets** (`tools/facets.py`):
   - **Segmenting:** the flattened render is split into small regions, then neighbouring regions are merged when they're the same material and no groove runs between them. The result is one region per armour plate, letter or panel.
   - **Materials:** each facet gets one material: black, grey, copper or green. Dark-metal plates on the eagle print grey.
   - **Bevels:** thin facets (bevel highlights, edge reflections) take the material of the plate they frame. On the eagle, a copper or green plate claims its own bevel first.
4. **Plate edges:** wherever two metal plates meet along a groove in the render, even a faint one, a black line is kept between them, so plates stay distinct once all metal is grey.
5. **Special areas:**
   - **Eye:** traced per pixel (almond socket, C-shaped iris, lid line). The iris rings are then smoothed as concentric bands around their centre.
   - **Talons:** traced from brightness, because they grip the dark ring and would otherwise merge with it.
   - **Side B line-work:** redrawn exactly. The radar rings are true circles around the fitted radar centre (1.8 mm, 0.2 mm right of the face centre), drawn over the angles where the render has them. Their ticks become radial strokes, and spokes and frame lines become straight segments. Specks and texture are dropped.
   - **Exact geometry:** side B's green markers are exact triangles, the gem is an exact square in a clean dark setting, and the crosshair is a straight bar.
6. **Clean outlines:**
   - **Notches:** shallow notches in a panel's outline, left by lighting along its edge, are filled.
   - **Straight edges:** each panel is smoothed on its own (it can grow only into black, so panels never merge), then redrawn as a polygon. Side B's letters and X arms get a stronger pass.
   - **Exceptions:** lettering, the eye and the digits keep their traced curves.
7. **Lettering:** the render's own letterforms are kept. The typo "SECON**O**S" is corrected to **"SECONDS"** by turning the O into a D in the same typeface.
8. **Printable widths:** lines narrower than the nozzle can print are widened to the minimum, with grooves widened evenly along their centreline. Each colour is then vectorised and cut from the coin body as a 0.6 mm inlay.

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
- **Remaining artefact:** a small grey wedge is left where a copper plate fades to grey at its tip in the render (the right tip of the copper chevron on the eagle's neck).

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
  - `--no-smooth-lines`: keep line-work as traced.
- **Coin geometry:** `--size`, `--thickness`, `--inlay`, `--chamfer`, `--rim`, `--rim-edge`.
- **Debugging:** `COIN_DEBUG=<dir>` saves the label map after each processing stage.
