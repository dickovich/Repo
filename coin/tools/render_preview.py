"""Render a shaded 3D preview of each assembled half-coin from its four colour STLs.

A small numpy z-buffer rasteriser (orthographic, tilted view) so the preview is depth-correct.
"""
import os
import sys

import numpy as np
import trimesh
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLOURS = {"dark": (0.17, 0.17, 0.18), "silver": (0.80, 0.81, 0.83),
           "copper": (0.82, 0.48, 0.30), "green": (0.55, 0.92, 0.15)}
LIGHT = np.array([-0.45, 0.55, 0.70])
LIGHT /= np.linalg.norm(LIGHT)


def render(stl_dir, side, out, px_per_mm=24, tilt_deg=30, z_exag=2.0):
    t = np.radians(tilt_deg)
    rot = np.array([[1, 0, 0], [0, np.cos(t), -np.sin(t)], [0, np.sin(t), np.cos(t)]])
    size = int(56 * px_per_mm)
    zbuf = np.full((size, size), -np.inf)
    img = np.ones((size, size, 3))
    for name, rgb in COLOURS.items():
        path = os.path.join(stl_dir, f"{side}_{name}.stl")
        if not os.path.exists(path):
            continue
        m = trimesh.load(path)
        v = m.vertices * [1, 1, z_exag]                      # exaggerate relief for visibility
        n = trimesh.triangles.normals(v[m.faces])[0]
        vr = v @ rot.T
        nr = n @ rot.T
        shade = 0.30 + 0.70 * np.clip(n @ LIGHT, 0, 1)
        xy = np.c_[vr[:, 0] * px_per_mm + size / 2, size / 2 - vr[:, 1] * px_per_mm]
        for f, s, nz in zip(m.faces, shade, nr[:, 2]):
            if nz <= 0:
                continue                                     # back-facing
            p = xy[f]
            z = vr[f, 2]
            x0, y0 = np.floor(p.min(0)).astype(int)
            x1, y1 = np.ceil(p.max(0)).astype(int)
            x0, y0 = max(x0, 0), max(y0, 0)
            x1, y1 = min(x1, size - 1), min(y1, size - 1)
            if x1 < x0 or y1 < y0:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            a, b, c = p
            den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(den) < 1e-12:
                continue
            w0 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / den
            w1 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / den
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            zz = w0 * z[0] + w1 * z[1] + w2 * z[2]
            sub = zbuf[y0:y1 + 1, x0:x1 + 1]
            upd = inside & (zz > sub)
            sub[upd] = zz[upd]
            img[y0:y1 + 1, x0:x1 + 1][upd] = np.array(rgb) * s
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(out)


if __name__ == "__main__":
    stl_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stl")
    for side in ("side_a_eagle", "side_b_dfrx"):
        render(stl_dir, side, os.path.join(stl_dir, f"{side}_render.png"))
