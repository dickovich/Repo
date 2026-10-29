# dFRX challenge coin: 4-colour 3D-print files

A two-sided hexagonal challenge coin made from the two supplied renders:

| Side | Source | Preview |
|---|---|---|
| A: eagle / "Faster response when seconds matter" | `src/side_a_eagle.png` | `stl/side_a_eagle_render.png` |
| B: dFRX / "Drone as first responder" | `src/side_b_dfrx.png` | `stl/side_b_dfrx_render.png` |

## Files (`stl/`)

For each side there's one STL per filament. They share the same origin, so they load already aligned:

| File suffix | Filament | Contains |
|---|---|---|
| `_dark.stl` | black / charcoal | base plate, raised gunmetal feathers, motto lettering |
| `_silver.stl` | silver | rim, eagle body, motto band, dFRX letters, radar lines |
| `_copper.stl` | copper / orange | wing accents, "DRONE AS FIRST RESPONDER", 000 / 131444 |
| `_green.stl` | lime green | dial ticks, eye, glow inlays, X centre, markers |

`*_4colour.3mf` holds the same four bodies in one file, for Bambu Studio, OrcaSlicer or PrusaSlicer.

## Geometry (defaults)

- Hexagon **50 mm across corners** (43.3 mm across flats).
- Each side is a **half-coin 2.0 mm thick**, printed face-up. Glue the two halves back-to-back for a **4.0 mm coin**.
- Relief heights: base/field 1.0 mm, green and gunmetal 1.4, copper and motto ink 1.6, silver 1.8, rim 2.0.
- The colour changes all happen in the top 1.0 mm, so purge waste stays low.
- Every STL is a closed (watertight) mesh, and the colour bodies don't overlap (the boundary overlap is under 0.5 mm³ per side).

## Printing

1. Import all four STLs of one side together. When the slicer asks, choose **"load as a single object with multiple parts"**.
2. Assign a filament to each part: dark, silver, copper, green.
3. Suggested settings: 0.4 mm nozzle, **0.12 mm layers** (0.08 is better for the lettering), Arachne walls, ironing off, and the prime tower or "flush into infill" on.
4. Print both halves face-up. Glue them back-to-back with thin CA or 2-part epoxy, and line up the top edges. Side B's "top" is the green triangle at 12 o'clock.

## Changes from the source art

- **Motto spelling fixed.** The source render reads "SECON**O**S". The lettering is redrawn from a font (Inter Black) along the band so it reads **"SECONDS"**.
- **000 / 131444 redrawn** from a font. The rendered digits were too fuzzy to trace.
- **The rim is redrawn** as a clean hexagon. The render's perspective-distorted, shadowed rim isn't used.
- **Four colours only.** The source has two metal tones on the eagle. The darker "gunmetal" feathers are printed in the dark filament, raised 0.4 mm above the field, so they show by relief instead of colour.
- **Hairlines widened.** Lines thinner than 0.42 mm (radar rings, ticks) are widened to 0.42 mm. A 0.4 mm nozzle can't lay down anything finer. The finest tick marks and texture are dropped.

## Regenerating / changing size

```bash
pip install -r requirements.txt
python3 tools/build_coin.py --size 50 --base 1.0 --rim 1.6 --min-feature 0.42
python3 tools/render_preview.py        # refresh stl/*_render.png
```

- `--size`: width across corners in mm. 60 mm or larger makes the motto noticeably crisper.
- `--min-feature`: set this to `0.25` if you print with a 0.2 mm nozzle, so less detail gets thickened.
