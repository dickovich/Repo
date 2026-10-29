# dFRX challenge coin: flat-face, multi-colour 3D-print files

A two-sided, 60 mm hexagonal challenge coin made from the two supplied renders. Both faces are
**flat colour inlays**: every colour sits level, and the detail comes from colour only.

## Which folder to use

| Folder | Nozzle | Filaments | Fidelity |
|---|---|---|---|
| `stl/nozzle_0.2/5colour/` | 0.2 mm | 5 | **Closest to the render.** Gunmetal feathers print in their own dark-grey filament. |
| `stl/nozzle_0.2/4colour/` | 0.2 mm | 4 | Gunmetal feathers print dark, outlined by their silver bevel edges. |
| `stl/nozzle_0.4/5colour/` | 0.4 mm | 5 | As above, with lines no finer than 0.38 mm. |
| `stl/nozzle_0.4/4colour/` | 0.4 mm | 4 | As above, with lines no finer than 0.38 mm. |

The 5-colour sets need a printer that holds five filaments at once (for example, a Bambu printer with
two AMS units, or a 5-tool Prusa XL). All the colours are in the same layers, so a manual
mid-print swap won't work.

Each folder has `side_*_face.png` (the face as it will print), `compare_side_*.png` (source on the
left, print on the right) and `render_*.png` (3D previews of the one-piece coin).

## Files (in each folder)

| Set | What it is |
|---|---|
| `coin_one_piece_*` (recommended) | The whole coin in one print, 3.4 mm thick. The eagle face is printed **against the build plate** (mirrored in the file, so it reads correctly once you flip the coin). The dFRX face is inlaid in the top layers. No glue and no seam. |
| `half_a_eagle_*`, `half_b_dfrx_*` | Alternative: two 1.7 mm halves, each printed face-down, then glued back-to-back. Both faces get the plate finish, but you need glue and you get an edge seam. |
| `*_Ncolour.3mf` | All of a set's STLs in one file. |

| Suffix | Filament | Contains |
|---|---|---|
| `_dark` | black | background, grooves between facets, motto lettering, core and edge (plus gunmetal feathers in the 4-colour sets) |
| `_silver` | silver | rim, bright metal facets and bevel highlights, motto band, dFRX letters, radar line-work |
| `_copper` | copper / orange | copper feathers, "DRONE AS FIRST RESPONDER", 000 / 131444 |
| `_green` | lime green | glow inlays, dial ticks, eye, crosshair, markers, X centre |
| `_gunmetal` (5-colour only) | dark grey / gunmetal | the darker metal feathers and facets on the eagle |

`stl/v1_raised_relief/` holds the first, raised-relief version, kept for reference.

## How the artwork is converted

1. The render is rectified onto a regular hexagon, then **flattened with L0 gradient smoothing**.
   This removes the metal texture, scratches and lighting noise but keeps facet edges and grooves
   sharp, so each facet becomes a single flat colour with a crisp edge.
2. Every pixel is classified by CIELAB lightness and hue: background/groove (L < 70), gunmetal
   (70–125), silver (≥ 125), copper (warm), green (including the near-white cores of the glow lines).
3. The darkest gunmetal feathers flatten to the same lightness as the background, so they're found
   by context instead: compact regions enclosed by grooves and silver bevel highlights, lying on the
   eagle and away from the outer frame. The solidity test rejects the long, thin dial ring.
4. Lettering is redrawn from fonts (Inter). The eagle's eye and side B's vertical crosshair are drawn
   as exact geometry.
5. Lines narrower than the nozzle can print are widened to the minimum (0.22 mm for a 0.2 mm
   nozzle, 0.38 mm for 0.4 mm). Anything smaller is dropped. Each colour is then vectorised and cut
   from the coin body as a 0.6 mm inlay.

## Geometry (defaults)

- **Size:** hexagon 60 mm across corners (52 mm across flats), 3.4 mm thick, with a 0.4 mm 45° chamfer on both face edges.
- **Inlay:** colours are 0.6 mm deep on each face, enough for light colours to be opaque over black.
- **Mesh check:** every STL is a closed (watertight) mesh. The colour bodies overlap by under 0.002 mm along their boundaries, which slicers ignore.

## Printing (Bambu Studio / OrcaSlicer)

1. Import all the `coin_one_piece_*.stl` files together, or the 3MF. When asked, choose **"load as a single object with multiple parts"**, then assign a filament to each part.
2. Keep each colour as a separate part; don't use paint-on colour. Separate parts keep every colour on the same layers.
3. Suggested settings:
   - **0.4 mm nozzle:** 0.1 mm layers, at least through the bottom and top 0.6 mm. Variable layer height can use 0.2 mm in the dark core. First-layer line width about 0.3 mm.
   - **0.2 mm nozzle:** 0.06–0.08 mm layers through the inlays. First-layer line width about 0.22 mm. Expect roughly 2–3 times the 0.4 mm print time.
   - Arachne wall generator, ironing on the top surface (dFRX face), and a prime tower or "flush into infill".
4. Bed adhesion is the main risk: the first layer is hundreds of small separate pieces. Wash the build plate with dish soap and dry it fully, level the bed, and slow the first layer down.
5. Print one test coin before a batch run.

## Changes from the source art

- **Motto spelling fixed.** The source render reads "SECON**O**S". The lettering is redrawn so it reads **"SECONDS"**.
- **000 / 131444 and "DRONE AS FIRST RESPONDER" redrawn** from a font. In the trace, the D read as an O and a radar line cut through the N.
- **Rim redrawn** as a clean hexagon.
- **Eye and crosshair** drawn as exact geometry.
- **Bronze reflections removed.** Copper-coloured reflections on side B's radar lines print silver; copper on that face is lettering only.
- **No lighting effects.** The render's shading, gloss and glow can't be printed; each colour region is one flat colour.

## Regenerating

```bash
pip install -r requirements.txt
python3 tools/build_coin.py --min-feature 0.22 --gunmetal filament --out stl/nozzle_0.2/5colour
python3 tools/build_coin.py --min-feature 0.22 --gunmetal dark     --out stl/nozzle_0.2/4colour
python3 tools/build_coin.py --min-feature 0.38 --gunmetal filament --out stl/nozzle_0.4/5colour
python3 tools/build_coin.py --min-feature 0.38 --gunmetal dark     --out stl/nozzle_0.4/4colour
python3 tools/render_preview.py stl/nozzle_0.2/5colour                 # refreshes render_*.png
```

`--gunmetal silver` prints the gunmetal feathers silver instead (a lighter eagle). Other options:
`--size`, `--thickness`, `--inlay`, `--chamfer`, `--rim`.
