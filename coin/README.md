# dFRX challenge coin: flat-face, 4-colour 3D-print files

A two-sided, 60 mm hexagonal challenge coin made from the two supplied renders. Both faces are
**flat colour inlays**: every colour sits level, and the detail comes from colour only.

| Face | Source | Print face | Before / after |
|---|---|---|---|
| A: eagle / "Faster response when seconds matter" | `src/side_a_eagle.png` | `stl/side_a_eagle_face.png` | `stl/compare_side_a_eagle.png` |
| B: dFRX / "Drone as first responder" | `src/side_b_dfrx.png` | `stl/side_b_dfrx_face.png` | `stl/compare_side_b_dfrx.png` |

## Files (`stl/`)

Each set has one STL per filament, all on the same origin, plus a `_4colour.3mf` containing all four.

| Set | What it is |
|---|---|
| `coin_one_piece_*` (recommended) | The whole coin in one print, 3.4 mm thick. The eagle face is printed **against the build plate** (mirrored in the file, so it reads correctly once you flip the coin). The dFRX face is inlaid in the top layers. No glue and no seam. |
| `half_a_eagle_*`, `half_b_dfrx_*` | Alternative: two 1.7 mm halves, each printed face-down, then glued back-to-back. Both faces get the smooth plate finish, but you need glue and you get an edge seam. |
| `v1_raised_relief/` | Previous raised-relief version, kept for reference. |

| Suffix | Filament | Contains |
|---|---|---|
| `_dark` | black / charcoal | background, the outlines between the feathers and facets, motto lettering, core and edge |
| `_silver` | silver | rim, eagle body and feathers, motto band, dFRX letters, radar rings |
| `_copper` | copper / orange | wing accents, "DRONE AS FIRST RESPONDER", 000 / 131444 |
| `_green` | lime green | dial ticks, eye, glow inlays, X centre, markers |

## Geometry (defaults)

- **Size:** hexagon 60 mm across corners (52 mm across flats), 3.4 mm thick, with a 0.4 mm 45° chamfer on both face edges.
- **Inlay:** colours are 0.6 mm deep on each face, which is enough for light colours to be opaque over black.
- **Detail limit:** nothing is narrower than 0.38 mm, the narrowest line a 0.4 mm nozzle reliably prints. Finer source detail is either widened to 0.38 mm or dropped.
- **Mesh check:** every STL is a closed (watertight) mesh, and the colour bodies don't overlap (boundary overlap under 0.002 mm).

## Printing (Bambu Studio / OrcaSlicer, 0.4 mm nozzle)

1. Import the four `coin_one_piece_*.stl` files together, or the 3MF. When asked, choose **"load as a single object with multiple parts"**. Then assign the dark, silver, copper and green filaments.
2. Keep each colour as a separate part; don't use paint-on colour. Separate parts keep all four colours on the same layers.
3. Suggested settings:
   - **0.1 mm layers**, at least through the bottom and top 0.6 mm. Variable layer height can use 0.2 mm in the dark core.
   - First-layer line width about 0.3 mm.
   - Arachne wall generator.
   - **Ironing on the top surface**, for the dFRX face.
   - Prime tower or "flush into infill" on.
4. Bed adhesion is the main risk: the first layer is many small separate pieces. Wash the build plate with dish soap and dry it fully. A smooth PEI or textured plate both work; the plate texture becomes the eagle face's finish.
5. Print one test coin before a batch run.

## Changes from the source art

- **Motto spelling fixed.** The source render reads "SECON**O**S". The lettering is redrawn from a font (Inter Black) so it reads **"SECONDS"**.
- **000 / 131444 redrawn** from a font for clean edges.
- **Rim redrawn** as a clean hexagon.
- **Two metal tones become one.** A flat face can't show the render's gunmetal tone. Gunmetal feathers print silver, and the dark outlines around each feather keep the facets distinct.
- **Bronze reflections removed.** Copper-coloured reflections on side B's radar lines print silver; copper on that face is lettering only.
- **No lighting effects.** The render's shading, gloss and glow can't be printed; each colour region is a single flat colour.

## Regenerating

```bash
pip install -r requirements.txt
python3 tools/build_coin.py --size 60 --thickness 3.4 --inlay 0.6 --min-feature 0.38
python3 tools/render_preview.py        # refreshes stl/render_*.png
```

Use `--min-feature 0.22` if you print with a 0.2 mm nozzle; more fine detail survives.
