"""Turn the two challenge-coin renders into 4-colour, 3D-printable STL parts.

Pipeline per side:
  1. Rectify the (slightly perspective) render onto a regular flat-top hexagon.
  2. Flatten the render with L0 gradient smoothing (texture and lighting noise go, facet edges
     stay sharp), then segment it into facets (one region per plate, letter or panel; see
     facets.py) and give each facet one material: black, grey, copper or green. Thin facets
     (bevel highlights, reflections) take the material of the plate they frame.
  3. Keep the render's own lettering (lettering zones get only fine clean-up) and correct the
     "SECONOS" typo by turning the misspelt O into a D in the same typeface; draw side B's gem
     and crosshair as exact geometry; dark-metal feathers become fine grey hatching.
  4. Replace the rendered rim with a clean geometric rim measured from the render.
  5. Clean up: majority filter, drop specks, thicken hairlines to the printable minimum.
  6. Vectorise each colour and cut it out of the coin body as a flat inlay.

Flat faces: each face is a level colour inlay (--inlay deep). The one-piece coin prints with the
eagle face against the build plate and the dFRX face inlaid in the top layers; face-down halves
for gluing are also exported.

Usage: python3 tools/build_coin.py [--size 60] [--min-feature 0.38] [--gunmetal dark|silver|filament]
"""
import argparse
import json
import os

import cv2
import numpy as np
import manifold3d as m3d
import trimesh
from PIL import Image
from skimage.morphology import skeletonize

from lines import smooth_lines, radar_redraw
import facets

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# --- canonical raster frame (independent of final coin size) -------------------------------
R_PX = 650.0                                  # hexagon circumradius in the rectified raster
W, H = int(2 * R_PX + 40), int(np.sqrt(3) * R_PX + 40)
CX, CY = W / 2, H / 2

# Face corners measured on the source renders, order: TL, TR, R, BR, BL, L
SRC_CORNERS = {
    "side_a_eagle": [(340, 48), (987, 48), (1309, 584), (990, 1104), (304, 1104), (11, 576)],
    "side_b_dfrx":  [(339, 51), (976, 49), (1300, 582), (991, 1104), (304, 1104), (14, 576)],
}

# material classes in the label map
FIELD, SILVER, COPPER, GREEN, GUNMETAL, RIM, INK = range(7)

# filament each class is printed in
# the four filaments: black, grey (the render's silver metal), copper and neon green
FILAMENT = {FIELD: "black", GUNMETAL: "gunmetal", INK: "black",
            SILVER: "grey", RIM: "grey", COPPER: "copper", GREEN: "green"}
FILAMENTS = ["black", "grey", "copper", "green", "gunmetal"]    # gunmetal only with --gunmetal filament

GREY_RGB = (182, 185, 190)
PREVIEW_RGB = {FIELD: (24, 24, 26), GUNMETAL: (98, 98, 104), INK: (24, 24, 26),
               SILVER: GREY_RGB, RIM: GREY_RGB, COPPER: (196, 112, 64), GREEN: (120, 255, 20)}



def hex_pts(r, cx=CX, cy=CY):
    return [(cx + r * np.cos(np.radians(a)), cy + r * np.sin(np.radians(a)))
            for a in (240, 300, 0, 60, 120, 180)]


def hex_mask(r):
    m = np.zeros((H, W), np.uint8)
    cv2.fillPoly(m, [np.int32(np.round(np.array(hex_pts(r)) * 8))], 1, cv2.LINE_8, shift=3)
    return m.astype(bool)


def rectify(name):
    src = cv2.cvtColor(cv2.imread(os.path.join(ROOT, "src", f"{name}.png"), cv2.IMREAD_UNCHANGED),
                       cv2.COLOR_BGRA2RGB)
    hm, _ = cv2.findHomography(np.float32(SRC_CORNERS[name]), np.float32(hex_pts(R_PX)))
    return cv2.warpPerspective(src, hm, (W, H), flags=cv2.INTER_CUBIC)


def flatten(rgb):
    """L0 gradient smoothing: removes the render's metal texture and lighting noise while
    keeping facet edges and grooves sharp, so each facet becomes one flat colour."""
    return cv2.ximgproc.l0Smooth(rgb, None, 0.01, 2.0)


def classify(flat):
    """Material class per pixel of the flattened render, from CIELAB lightness and hue."""
    lab = cv2.cvtColor(flat, cv2.COLOR_RGB2LAB).astype(np.int16)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    out = np.full(flat.shape[:2], FIELD, np.uint8)         # background and grooves (L < 70)
    out[L >= 70] = GUNMETAL                                # dark metal feathers (L 70-100)
    out[L >= 100] = SILVER                                 # metal incl. shaded sides (tail, talons)
    out[(a >= 140) & (b >= 143) & (L >= 75)] = COPPER
    out[(a <= 124) & (b >= 146) & (L >= 90)] = GREEN          # incl. near-white glow cores
    return out


def eagle_mask(src, mm_px=2 * R_PX / 60, close_mm=3.0):
    """The eagle's silhouette: bright metal (heavily smoothed brightness) away from the rim, frame
    and motto band, largest region, closed so the dark feathers between bright ones are inside."""
    v = cv2.cvtColor(src, cv2.COLOR_RGB2HSV)[..., 2].astype(np.float32)
    m = cv2.GaussianBlur(v, (0, 0), 4) > 64
    edge = cv2.distanceTransform(hex_mask(R_PX).astype(np.uint8), cv2.DIST_L2, 5)
    rin, rout = band_profile()
    # the motto band continues as the segmented outer ring round the dial: exclude that ring
    # except where the talons grip it (lower right, 20-68 degrees)
    ring = band_mask(rin, rout, -180, 20, pad=-6) | band_mask(rin, rout, 68, 180, pad=-6)
    m &= (edge > 4.0 * mm_px) & ~ring
    # open first so thin rings and ticks (< 0.8 mm) drop out; feathers and talons are wider
    ko = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(0.8 * mm_px) | 1,) * 2)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, ko)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(close_mm * mm_px) | 1,) * 2)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    n, cc, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    m = (cc == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    # fill small enclosed holes (dark feathers surrounded by bright ones), not the dial background
    n, cc, st, _ = cv2.connectedComponentsWithStats(1 - m, connectivity=4)
    holes = np.isin(cc, np.where(st[:, cv2.CC_STAT_AREA] < 40 * mm_px ** 2)[0])
    return (m > 0) | holes


def fill_notches(lab, classes, mm_px, max_depth_mm=0.9, min_ratio=2.5, min_area_mm2=1.5,
                 keep=None):
    """Fill shallow dents in a panel's outline (left by shading or highlights along its edge):
    convexity defects no deeper than max_depth_mm and at least min_ratio times wider than
    deep. Real slots and gaps are deep or narrow and are kept. Fills only into black."""
    out = lab.copy()
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(0.6 * mm_px) | 1,) * 2)
    inner = hex_mask(R_PX - 2.6 * mm_px * 2 / np.sqrt(3)).astype(np.uint8)   # rim excluded
    for c in classes:
        # panels only: thin lines touching a panel would join it to other panels
        m = cv2.morphologyEx((lab == c).astype(np.uint8) & inner, cv2.MORPH_OPEN, k)
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        fill = np.zeros_like(m)
        for cnt in cs:
            if cv2.contourArea(cnt) < min_area_mm2 * mm_px ** 2 or len(cnt) < 8:
                continue
            hull = cv2.convexHull(cnt, returnPoints=False)
            try:
                defects = cv2.convexityDefects(cnt, hull)
            except cv2.error:
                continue
            if defects is None:
                continue
            for s0, e0, f0, d in defects.reshape(-1, 4):
                depth = d / 256.0
                span = np.hypot(*(cnt[s0, 0] - cnt[e0, 0]).astype(float))
                if depth < 1.0 or depth > max_depth_mm * mm_px or span < min_ratio * depth:
                    continue
                seg = cnt[s0:e0 + 1, 0] if s0 <= e0 else np.r_[cnt[s0:, 0], cnt[:e0 + 1, 0]]
                cv2.fillPoly(fill, [seg.reshape(-1, 1, 2)], 1)
        grow = (fill > 0) & (out == FIELD)
        if keep is not None:
            grow &= ~keep
        out[grow] = c
    return out


def straighten_large(lab, keep, mm_px, min_area_mm2=12, smooth_mm=0.5, eps_mm=0.18):
    """Large grey shapes (letters, X arms): smooth away notches and spikes under smooth_mm and
    redraw as polygons with eps_mm tolerance. They may only grow into black."""
    big = np.zeros_like(lab, bool)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(0.6 * mm_px) | 1,) * 2)
    inner = hex_mask(R_PX - 2.6 * mm_px * 2 / np.sqrt(3)).astype(np.uint8)   # rim excluded
    m = cv2.morphologyEx((lab == SILVER).astype(np.uint8) & inner, cv2.MORPH_OPEN, k)
    n, cc, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= min_area_mm2 * mm_px ** 2:
            big |= cc == i
    if not big.any():
        return lab
    sub = np.where(big, SILVER, np.where(lab == SILVER, FIELD, lab)).astype(np.uint8)
    sm = straighten(np.where(big, SILVER, FIELD).astype(np.uint8), eps_mm * mm_px, smooth_mm * mm_px)
    grown = (sm == SILVER) & ((lab == FIELD) | big) & ~keep
    shrunk = big & (sm != SILVER) & ~keep
    out = lab.copy()
    out[shrunk] = FIELD
    out[grown] = SILVER
    return out


def straighten(lab, eps_px, smooth_px=0):
    """Redraw every colour region as a polygon (Douglas-Peucker, tolerance eps_px) so panel edges
    are straight lines instead of traced raster steps. Each panel is first smoothed on its own
    (closing then opening with a smooth_px disc: notches and spikes narrower than that go), and
    may only grow into black, so neighbouring panels never merge. Painted grey, then copper, then
    green over black. Contours are drawn in nesting order so nothing inside a hole is lost."""
    out = np.full_like(lab, FIELD)
    d = int(smooth_px) | 1
    disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d)) if smooth_px >= 2 else None
    pad = d + 2
    for c in (SILVER, COPPER, GREEN):
        m = (lab == c).astype(np.uint8)
        if disc is not None:
            n, cc, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
            sm = np.zeros_like(m)
            for i in range(1, n):
                x, y, w, h, _ = st[i]
                x0, y0 = max(x - pad, 0), max(y - pad, 0)
                x1, y1 = min(x + w + pad, W), min(y + h + pad, H)
                comp = (cc[y0:y1, x0:x1] == i).astype(np.uint8)
                grown = cv2.morphologyEx(comp, cv2.MORPH_CLOSE, disc)
                grown &= ((lab[y0:y1, x0:x1] == FIELD) | (comp > 0)).astype(np.uint8)
                grown = cv2.morphologyEx(grown, cv2.MORPH_OPEN, disc)
                if grown.sum() < 0.5 * comp.sum():
                    grown = comp                            # too thin to smooth: keep as traced
                sm[y0:y1, x0:x1] |= grown
            m = sm
        cs, hier = cv2.findContours(m, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
        if hier is None:
            continue
        parent = hier[0][:, 3]
        depth = np.zeros(len(cs), int)
        for i in range(len(cs)):
            j = parent[i]
            while j >= 0:
                depth[i] += 1
                j = parent[j]
        canvas = np.zeros_like(m)
        for dd in range(depth.max() + 1):
            polys = [cv2.approxPolyDP(cs[i], eps_px, True) for i in np.nonzero(depth == dd)[0]]
            polys = [p for p in polys if len(p) >= 3]
            if polys:
                cv2.fillPoly(canvas, polys, 1 if dd % 2 == 0 else 0)
        # a part too small to keep three vertices keeps its traced pixels
        out[(canvas > 0) | ((m > 0) & (cv2.erode(m, np.ones((3, 3), np.uint8)) == 0)
                           & (cv2.dilate(canvas, np.ones((3, 3), np.uint8)) == 0))] = c
    return out


def facet_labels(name, src, flat, raw, mm_px):
    """One material per facet: segment the flattened render into plates/letters/panels
    (facets.segment), decide each region's material, then let thin regions (bevel highlights,
    reflections) take the material of the plate they border."""
    reg, rmat, meanL = facets.segment(flat, raw, {"copper": COPPER, "green": GREEN})
    m = reg.max() + 1
    cnt = np.bincount(reg.ravel(), minlength=m).astype(float)
    if name == "side_a_eagle":
        on = np.bincount(reg.ravel(), weights=eagle_mask(src).ravel(), minlength=m) / cnt >= 0.5
    else:
        on = np.zeros(m, bool)
    cls = np.full(m, FIELD, np.uint8)
    cls[rmat == facets.GREEN_M] = GREEN
    cls[rmat == facets.COPPER_M] = COPPER
    metal = rmat == facets.METAL
    cls[metal & (meanL >= 100)] = SILVER                    # bright metal
    cls[metal & (meanL < 100) & on] = GUNMETAL              # dark metal plates on the eagle
    cls[metal & (meanL < 100) & ~on & (meanL >= 75)] = SILVER   # dim stretches of line-work
    cls = facets.absorb_thin(reg, cls, mm_px, dark=FIELD, keep=(GREEN,),
                             prefer=(GREEN, COPPER) if name == "side_a_eagle" else ())
    lab = cls[reg]
    if name == "side_a_eagle":
        # plate edges: where two metal plates meet along a groove in the render (even a faint
        # one), keep a black line between them, so plates stay distinct once all metal is grey
        L = cv2.cvtColor(flat, cv2.COLOR_RGB2LAB)[..., 0]
        bh = cv2.morphologyEx(L, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        edge = np.zeros(reg.shape, bool)
        edge[:, 1:] |= reg[:, 1:] != reg[:, :-1]
        edge[1:, :] |= reg[1:, :] != reg[:-1, :]
        metal = np.isin(lab, (SILVER, GUNMETAL))
        metal_nb = cv2.erode(metal.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) | metal
        groove = (cv2.dilate(bh, np.ones((3, 3), np.uint8)) >= 14) & (L < 120)
        lab[edge & metal_nb & groove & eagle_mask(src)] = FIELD
    return lab


def hatch_gunmetal(lab, line_px, pitch_px):
    """Engraver's hatching: render each dark-metal feather as fine grey lines on black, run along
    the feather's long axis, so with four filaments it still reads as a darker metal tone."""
    lab = lab.copy()
    n, cc, st, _ = cv2.connectedComponentsWithStats((lab == GUNMETAL).astype(np.uint8), connectivity=8)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    for i in range(1, n):
        x, y, w, h, area = st[i]
        m = cc[y:y + h, x:x + w] == i
        pts = np.c_[np.nonzero(m)[1] + x, np.nonzero(m)[0] + y].astype(np.float32)
        if area < 30:
            lab[y:y + h, x:x + w][m] = FIELD
            continue
        mean = pts.mean(0)
        vec = np.linalg.svd(pts - mean, full_matrices=False)[2]
        nx, ny = vec[1]                                     # normal to the long axis
        d = (xx[y:y + h, x:x + w] - mean[0]) * nx + (yy[y:y + h, x:x + w] - mean[1]) * ny
        stripe = np.mod(d + line_px / 2, pitch_px) < line_px
        sub = lab[y:y + h, x:x + w]
        sub[m & stripe] = SILVER
        sub[m & ~stripe] = FIELD
    return lab


def majority(lab, k, classes):
    votes = np.stack([cv2.blur((lab == c).astype(np.float32), (k, k)) for c in classes])
    return np.asarray(classes, np.uint8)[votes.argmax(0)]


def drop_specks(lab, cls, min_area, fill):
    n, cc, st, _ = cv2.connectedComponentsWithStats((lab == cls).astype(np.uint8), connectivity=8)
    small = np.isin(cc, np.where(st[:, cv2.CC_STAT_AREA] < min_area)[0]) & (lab == cls)
    out = lab.copy()
    if fill is None:
        # fill with the most common neighbouring class
        nb = majority(np.where(small, 255, lab), 9, [c for c in range(7) if c != cls])
        out[small] = nb[small]
    else:
        out[small] = fill
    return out


def thicken(mask, min_px):
    """Redraw hairline features (ones that vanish under an opening of min_px) at min_px wide.

    Components that survive the opening are left untouched, so corners of large shapes keep
    their crisp form; only lines/lettering too fine for the nozzle are widened.
    """
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(min_px) | 1, int(min_px) | 1))
    m8 = mask.astype(np.uint8)
    opened = cv2.morphologyEx(m8, cv2.MORPH_OPEN, k).astype(bool)
    n, cc, st, _ = cv2.connectedComponentsWithStats(m8, connectivity=8)
    kept = np.bincount(cc[opened], minlength=n)
    hair = np.where(kept < 0.5 * st[:, cv2.CC_STAT_AREA])[0]
    hair = hair[hair != 0]
    if len(hair) == 0:
        return mask
    sk = skeletonize(np.isin(cc, hair))
    return mask | cv2.dilate(sk.astype(np.uint8), k).astype(bool)


# --- side A: re-letter the motto band -------------------------------------------------------
BAND_C = (670, 585)          # approximate dial centre in the rectified raster


def band_profile():
    """Inner/outer radius of the motto band as smooth functions of angle (degrees)."""
    runs = np.load(os.path.join(ROOT, "tools", "band_runs.npy"))
    t, ri, ro = runs.T
    keep = t > -118                                     # left end is occluded by the wing
    pin, pout = np.polyfit(t[keep], ri[keep], 2), np.polyfit(t[keep], ro[keep], 2)
    return (lambda a: np.polyval(pin, a)), (lambda a: np.polyval(pout, a))


def band_mask(rin, rout, a0, a1, pad=0):
    yy, xx = np.mgrid[0:H, 0:W]
    ang = np.degrees(np.arctan2(yy - BAND_C[1], xx - BAND_C[0]))
    rad = np.hypot(xx - BAND_C[0], yy - BAND_C[1])
    return (ang >= a0) & (ang <= a1) & (rad >= rin(ang) + pad) & (rad <= rout(ang) - pad)


EYE_C, EYE_R = (1052, 647), 36           # the eye: centre and radius of its traced zone, px
EYE_LID = ((1063, 623), (1099, 668), 5.0)   # lid-line segment under the brow (px), half-width


IRIS_C, IRIS_R = (1050, 648), 24        # the iris: concentric rings round this centre, px


def iris_zone():
    yy, xx = np.mgrid[0:H, 0:W]
    return np.hypot(xx - IRIS_C[0], yy - IRIS_C[1]) <= IRIS_R


def smooth_iris(lab, size=96):
    """Smooth the iris in polar coordinates round its centre: each ring (outer green ring, dark
    ring, C-shaped inner ring, pupil) becomes a clean band with smooth edges, its gaps kept."""
    classes = (FIELD, SILVER, GREEN)
    c = (float(IRIS_C[0]), float(IRIS_C[1]))
    dsize = (size, 720)                                     # radius bins x angle bins (0.5 deg)
    votes = []
    for k in classes:
        m = (lab == k).astype(np.float32)
        pol = cv2.warpPolar(m, dsize, c, IRIS_R + 4, cv2.WARP_POLAR_LINEAR)
        pol = cv2.blur(pol, (9, 41))                        # ~2.5 px radially, ~20 deg round
        votes.append(cv2.warpPolar(pol, (W, H), c, IRIS_R + 4,
                                   cv2.WARP_POLAR_LINEAR | cv2.WARP_INVERSE_MAP))
    best = np.asarray(classes, np.uint8)[np.argmax(np.stack(votes), 0)]
    out = lab.copy()
    z = iris_zone()
    out[z] = best[z]
    return out


def eye_lid_line(flat):
    """The dark-green lid line under the brow has the same tone as the dark ring inside the iris,
    so take dark green as green only along the lid segment."""
    lab = cv2.cvtColor(flat, cv2.COLOR_RGB2LAB).astype(np.int16)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    (x0, y0), (x1, y1), half = EYE_LID
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.array([x1 - x0, y1 - y0], float)
    t = np.clip(((xx - x0) * d[0] + (yy - y0) * d[1]) / (d @ d), 0, 1)
    dist = np.hypot(xx - (x0 + t * d[0]), yy - (y0 + t * d[1]))
    return (dist <= half) & (a <= 116) & (b >= 140) & (L >= 40)


MOTTO_TYPO_O = (1036, 309)              # the second O of the render's "SECONOS" (should be D)


def fix_motto_typo(lab):
    """Keep the render's own lettering and correct only "SECONOS" -> "SECONDS": the misspelt O
    becomes a D in the same typeface (same outline and counter, squared off on the left)."""
    lab = lab.copy()
    rin, rout = band_profile()
    band = band_mask(rin, rout, -128, 8, pad=3)
    ink = (band & (lab == FIELD)).astype(np.uint8)
    n, cc, st, cen = cv2.connectedComponentsWithStats(ink, connectivity=8)
    i = int(np.argmin(np.hypot(cen[1:, 0] - MOTTO_TYPO_O[0], cen[1:, 1] - MOTTO_TYPO_O[1]))) + 1
    cx, cy = cen[i]
    o = (cc == i).astype(np.float32)
    # rotate so the glyph stands upright: its "up" is the outward radial direction
    phi = np.degrees(np.arctan2(cy - BAND_C[1], cx - BAND_C[0])) + 90
    size = 96
    rot = cv2.getRotationMatrix2D((cx, cy), phi, 1.0)
    rot[:, 2] += (size / 2 - cx, size / 2 - cy)
    up = cv2.warpAffine(o, rot, (size, size), flags=cv2.INTER_LINEAR) > 0.5
    ys, xs = np.nonzero(up)
    u0, u1, v0, v1 = xs.min(), xs.max(), ys.min(), ys.max()
    filled = up.copy().astype(np.uint8)
    ff = np.zeros((size + 2, size + 2), np.uint8)
    cv2.floodFill(filled, ff, (0, 0), 2)
    outer = filled != 2                                     # glyph plus its counter
    hole = outer & ~up
    hy, hx = np.nonzero(hole)
    um = (u0 + u1) // 2
    d_outer = outer.copy()
    d_outer[v0:v1 + 1, u0:um + 1] = True                   # straight stem on the left
    d_hole = hole.copy()
    if len(hx):
        stem = hx.min() - u0                                # keep the O's side-stroke weight
        d_hole[hy.min():hy.max() + 1, u0 + stem:(hx.min() + hx.max()) // 2 + 1] = True
    d = (d_outer & ~d_hole).astype(np.float32)
    back = cv2.invertAffineTransform(rot)
    d_img = cv2.warpAffine(d, back, (W, H), flags=cv2.INTER_LINEAR) > 0.5
    lab[cv2.dilate((cc == i).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & band] = SILVER
    lab[d_img] = FIELD
    return lab


# --- side B: re-letter the engraved phone numbers on the X ------------------------------------
# (text, centre px, reading angle deg clockwise, cap height px, wipe box (along, across) px)
NUMBERS = [("000", (1020, 435), -40.0, 36, (150, 56)),
           ("131444", (1062, 688), 53.0, 38, (220, 56))]


def rotated_box(centre, angle, size):
    box = cv2.boxPoints((centre, size, angle))
    m = np.zeros((H, W), np.uint8)
    cv2.fillPoly(m, [np.int32(box)], 1)
    return m.astype(bool)


TAGLINE = ("DRONE AS FIRST RESPONDER", (267, 834, 1087, 877))   # text, x0 y0 x1 y1 of the caps


CROSSHAIR_X, CROSSHAIR_Y = 678, [(140, 400), (902, 1025)]   # side B vertical crosshair, px
GEM_BOX = (880, 480, 1020, 620)                         # side B: search box for the X's green gem


# --- geometry -------------------------------------------------------------------------------
def mask_to_cs(mask, px_mm):
    """Binary mask -> manifold3d CrossSection in mm (centred, y up), grown by half a pixel."""
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    polys = []
    for c in cs:
        if len(c) < 3:
            continue
        c = cv2.approxPolyDP(c, 0.6, True).reshape(-1, 2).astype(float)
        if len(c) < 3:
            continue
        polys.append(np.c_[(c[:, 0] - CX) * px_mm, (CY - c[:, 1]) * px_mm])
    if not polys:
        return m3d.CrossSection()
    sec = m3d.CrossSection(polys, m3d.FillRule.EvenOdd)
    return sec.offset(0.5 * px_mm, m3d.JoinType.Miter)


def hex_cs(r_mm):
    return m3d.CrossSection([np.array([(r_mm * np.cos(np.radians(a)), r_mm * np.sin(np.radians(a)))
                                       for a in range(0, 360, 60)])])


def to_trimesh(man):
    mesh = man.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3],
                           faces=np.asarray(mesh.tri_verts), process=True)


def thicken_lines(mask, min_px):
    """Widen the narrow parts of a large connected region (dark grooves between facets) to
    min_px. Works on the whole region's centreline, so a groove whose width hovers around the
    minimum is widened as one uniform band, not as a string of bumps."""
    m8 = mask.astype(np.uint8)
    sk = skeletonize(mask).astype(np.uint8)
    # prune short spurs (skeleton branches into edge irregularities)
    nb = np.ones((3, 3), np.float32)
    nb[1, 1] = 0
    for _ in range(int(min_px)):
        ends = (sk > 0) & (cv2.filter2D(sk, -1, nb, borderType=cv2.BORDER_CONSTANT) <= 1)
        sk[ends] = 0
    width = 2 * cv2.distanceTransform(m8, cv2.DIST_L2, 5)
    narrow = (sk > 0) & (width < min_px)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(min_px) | 1, int(min_px) | 1))
    return mask | cv2.dilate(narrow.astype(np.uint8), k).astype(bool)


def _debug(lab, name, tag):
    """COIN_DEBUG=dir saves the label map after each stage (for tuning)."""
    d = os.environ.get("COIN_DEBUG")
    if d:
        prev = np.full((H, W, 3), 255, np.uint8)
        for c, rgb in PREVIEW_RGB.items():
            prev[lab == c] = rgb
        Image.fromarray(prev).save(os.path.join(d, f"{name}_{tag}.png"))


TALONS = [(860, 905), (1000, 840), (1130, 900), (1130, 1075), (860, 1075)]   # side A, px

RADAR_C = (678, 564)                    # side B: centre of the radar rings (fitted), px


def redraw_side_b_lines(lab, raw, mm_px, min_px):
    """Side B's line-work drawn exactly: radar rings as true arcs with their ticks, straight
    strokes (spokes, frame lines, green glow strips) as straight segments; specks dropped."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(0.6 * mm_px) | 1,) * 2)
    face = hex_mask(R_PX - 3.5 * mm_px * 2 / np.sqrt(3))   # inside the rim
    zones = traced_zones("side_b_dfrx", mm_px)
    zones[:, CROSSHAIR_X - 8:CROSSHAIR_X + 9] = True        # crosshair is drawn exactly later
    out = lab.copy()
    for c in (SILVER, GREEN):
        m = (lab == c).astype(np.uint8)
        thick = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
        near_thick = cv2.dilate(thick, np.ones((5, 5), np.uint8)).astype(bool)
        thin = (m > 0) & ~near_thick & ~zones & face
        if c == SILVER:
            excl = cv2.dilate(thick, np.ones((9, 9), np.uint8)).astype(bool) | zones | ~face
            rawg = np.isin(raw, (SILVER, GUNMETAL)) & ~excl
            new = radar_redraw(rawg, thin, RADAR_C, mm_px, min_px, bright=(raw == SILVER) & ~excl)
        else:
            # the green glow strips in the letters' slots: straight segments, specks dropped
            new = radar_redraw(np.zeros_like(thin), thin, RADAR_C, mm_px, min_px)
        new &= face & ~zones & ~near_thick
        out[thin] = FIELD
        out[new & (out == FIELD)] = c
    return out


def draw_gem(lab, min_px, mm_px):
    """The X's centre is a square green gem: an exact quadrilateral in a clean dark setting."""
    lab = lab.copy()
    # the X's centre is a square green gem: replace the traced blob with an exact quadrilateral
    gem = np.zeros_like(lab, np.uint8)
    gem[GEM_BOX[1]:GEM_BOX[3], GEM_BOX[0]:GEM_BOX[2]] = lab[GEM_BOX[1]:GEM_BOX[3],
                                                           GEM_BOX[0]:GEM_BOX[2]] == GREEN
    n, cc, st, _ = cv2.connectedComponentsWithStats(gem, connectivity=8)
    if n > 1:
        big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        pts = np.c_[np.nonzero(cc == big)[1], np.nonzero(cc == big)[0]].astype(np.int32)
        hull = cv2.convexHull(pts)
        quad = cv2.approxPolyDP(hull, 0.04 * cv2.arcLength(hull, True), True)
        if len(quad) != 4:
            quad = np.int32(cv2.boxPoints(cv2.minAreaRect(pts)))
        ring = np.zeros_like(gem)
        cv2.fillPoly(ring, [quad.reshape(-1, 2)], 1)
        # the gem's dark setting: a clean band round it (0.45 mm, as in the render)
        band = int(max(min_px, 0.45 * mm_px)) | 1
        grown = cv2.dilate(ring, cv2.getStructuringElement(cv2.MORPH_RECT, (band, band)))
        lab[(grown > 0) & (ring == 0)] = FIELD
        lab[(cc == big) & (ring == 0)] = FIELD
        lab[ring > 0] = GREEN
    return lab


def exact_triangles(lab, cls, mm_px, min_area_mm2=0.8, fit=0.85):
    """Regions that are triangles (the green markers) are redrawn as exact triangles."""
    m = (lab == cls).astype(np.uint8)
    n, cc, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    out = lab.copy()
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < min_area_mm2 * mm_px ** 2:
            continue
        pts = np.c_[np.nonzero(cc == i)[1], np.nonzero(cc == i)[0]].astype(np.float32)
        area, tri = cv2.minEnclosingTriangle(pts.reshape(-1, 1, 2))
        if area <= 0 or st[i, cv2.CC_STAT_AREA] / area < fit:
            continue
        tri = tri.reshape(3, 2)
        c = tri.mean(0)
        tri = c + (tri - c) * np.sqrt(st[i, cv2.CC_STAT_AREA] / area)   # keep the area
        out[(cc == i)] = FIELD
        poly = np.zeros_like(m)
        cv2.fillPoly(poly, [np.int32(np.round(tri * 8))], 1, cv2.LINE_8, shift=3)
        out[poly > 0] = cls
    return out


def traced_zones(name, mm_px):
    """Areas that keep their traced curves instead of being polygonised: lettering, the eye,
    the engraved digits."""
    if name == "side_a_eagle":
        rin, rout = band_profile()
        z = band_mask(rin, rout, -128, 8, pad=0)
        yy, xx = np.mgrid[0:H, 0:W]
        z |= np.hypot(xx - 1052, yy - 647) < 60
    else:
        x0, y0, x1, y1 = TAGLINE[1]
        z = np.zeros((H, W), bool)
        z[y0 - 8:y1 + 8, x0 - 8:x1 + 8] = True
        for _, c, ang, _, wipe in NUMBERS:
            z |= rotated_box(c, ang, wipe)
    return z


def straighten_panels(lab, keep, mm_px, eps_mm, smooth_mm=0.25):
    """Polygonise solid panels; thin line-work and the keep areas stay as they are."""
    keep = keep.copy()
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(0.6 * mm_px) | 1,) * 2)
    for c in (SILVER, COPPER, GREEN):
        m = (lab == c).astype(np.uint8)
        keep |= (m > 0) & ~cv2.dilate(cv2.morphologyEx(m, cv2.MORPH_OPEN, k),
                                      np.ones((5, 5), np.uint8)).astype(bool)
    keep = cv2.dilate(keep.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    return np.where(keep, lab, straighten(lab, eps_mm * mm_px, smooth_mm * mm_px)).astype(np.uint8)


def label_side(name, args):
    """Classified, cleaned label map for one face (unmirrored, as seen)."""
    mm_px = 2 * R_PX / args.size                            # raster pixels per mm
    min_px = args.min_feature * mm_px
    src = rectify(name)
    flat = flatten(src)
    raw = classify(flat)                                    # per pixel, for small lettering
    lab = facet_labels(name, src, flat, raw, mm_px)         # one material per facet
    if name == "side_a_eagle":
        # the talons grip the dark outer ring: facets merge claw and ring there, so the claws
        # are traced from brightness (polished metal, L >= 80) against the dark ring
        L = cv2.cvtColor(flat, cv2.COLOR_RGB2LAB)[..., 0]
        claws = (L >= 80).astype(np.uint8)
        claws = cv2.morphologyEx(claws, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        claws = cv2.morphologyEx(claws, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool)
        talons = np.zeros(lab.shape, np.uint8)
        cv2.fillPoly(talons, [np.int32(TALONS)], 1)
        talons = talons.astype(bool) & (lab != COPPER)
        lab[talons] = np.where(claws[talons], SILVER, FIELD)
        # the eye's rings are finer than the facets: trace it per pixel (as before), so the
        # almond socket, C-shaped iris ring, pupil and crescent all stay
        yy, xx = np.mgrid[0:H, 0:W]
        eye = np.hypot(xx - EYE_C[0], yy - EYE_C[1]) <= EYE_R
        traced = majority(raw, 3, [FIELD, SILVER, COPPER, GREEN, GUNMETAL])
        traced[traced == GUNMETAL] = FIELD                  # dark rings and pupil
        traced[eye & ~iris_zone()] = np.where(raw == GUNMETAL, SILVER, traced)[eye & ~iris_zone()]
        lab[eye] = traced[eye]
        lab = smooth_iris(lab)
        lab[eye_lid_line(flat)] = GREEN
    lab = majority(lab, 3, [FIELD, SILVER, COPPER, GREEN, GUNMETAL])
    for cls in (SILVER, COPPER, GREEN, GUNMETAL, FIELD):
        lab = drop_specks(lab, cls, min_px ** 2, None)
    _debug(lab, name, "1_clean")

    if name == "side_a_eagle":
        # thin grey strips along a dark, copper or green panel are that panel's bevel highlight
        # (lighting, not artwork): they take the panel's colour
        # (dark-metal plates' highlights too: those plates also print grey)
        bird = eagle_mask(src)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(0.4 * mm_px) | 1,) * 2)
        metal = np.isin(lab, (SILVER, GUNMETAL)).astype(np.uint8)
        thin = (metal > 0) & ~cv2.morphologyEx(metal, cv2.MORPH_OPEN, k).astype(bool) & bird
        for c in (COPPER, GREEN):
            near = cv2.dilate((lab == c).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
            lab[thin & near & np.isin(lab, (SILVER, GUNMETAL))] = c

    if name == "side_b_dfrx":
        # on this face the mid-grey pixels are the dimmer stretches of the silver radar lines
        lab[lab == GUNMETAL] = SILVER
    elif args.gunmetal == "grey":
        # dark and grey panels become the same filament: keep the groove that divides them
        # (only where it is a real panel edge: the render's own grooves already are; a dark/grey
        # boundary inside a panel is shading, and gets no line)
        if args.seams:
            gm = (lab == GUNMETAL).astype(np.uint8)
            sv = (lab == SILVER).astype(np.uint8)
            r = max(1, int(round(max(min_px, 0.3 * mm_px) / 2)))
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
            seam = cv2.dilate(gm, k).astype(bool) & cv2.dilate(sv, k).astype(bool)
            lab[seam & np.isin(lab, (GUNMETAL, SILVER))] = FIELD
        lab[lab == GUNMETAL] = SILVER
    elif args.gunmetal == "black":
        lab[lab == GUNMETAL] = FIELD                        # grey bevel edges outline them
    elif args.gunmetal == "hatch":
        # 40% grey coverage matches the render's dark-metal tone (L ~85 between black ~20 and grey ~185)
        pitch = args.hatch_pitch or args.min_feature / 0.4
        lab = hatch_gunmetal(lab, min_px, pitch * mm_px)

    # straight panel edges first, so the grooves widened below follow straight lines
    if args.straighten > 0:
        lab = straighten_panels(lab, traced_zones(name, mm_px), mm_px, args.straighten)
    _debug(lab, name, "2_straight")

    # widen hairlines to the printable minimum: isolated light strokes first, then the dark
    # outlines between facets (dark wins, so facets stay separated)
    for cls in (COPPER, GREEN, SILVER, GUNMETAL):
        grow = thicken(lab == cls, min_px) & (lab == FIELD)
        lab[grow] = cls
    _debug(lab, name, "3_light")
    dark = lab == FIELD
    lab[thicken_lines(dark, min_px) & ~dark] = FIELD
    _debug(lab, name, "4_dark")
    for cls in (SILVER, COPPER, GREEN, GUNMETAL):           # sub-minimum slivers left behind
        lab = drop_specks(lab, cls, (0.8 * min_px) ** 2, FIELD)
    _debug(lab, name, "5_slivers")

    # thin line-work (radar and dial rings, spokes, ticks) redrawn as smooth constant-width
    # strokes; on the eagle face only outside the eagle, whose feather points stay as traced
    if args.smooth_lines and name == "side_b_dfrx":
        lab = redraw_side_b_lines(lab, raw, mm_px, min_px)
    elif args.smooth_lines:
        # only the dial's tick ring under the motto band, kept 3 mm clear of the eagle so claw
        # tips and feather points are not treated as lines
        rin, rout = band_profile()
        yy, xx = np.mgrid[0:H, 0:W]
        ang = np.degrees(np.arctan2(yy - BAND_C[1], xx - BAND_C[0]))
        rad = np.hypot(xx - BAND_C[0], yy - BAND_C[1])
        ticks = (ang >= -135) & (ang <= 25) & (rad < rin(ang) - 2) & (rad > rin(ang) - 4.5 * mm_px)
        scope = ticks & ~cv2.dilate(eagle_mask(src).astype(np.uint8),
                                    np.ones((int(3 * mm_px) | 1,) * 2, np.uint8)).astype(bool)
        m = (lab == SILVER) & scope
        sm = smooth_lines(m, min_px, 0.6 * mm_px, sigma=3.0) & scope
        lab[m & ~sm] = FIELD
        lab[sm & (lab == FIELD)] = SILVER

    # lettering keeps the render's own letterforms: its counters and letter gaps (~0.28 mm) are
    # finer than a 0.4 nozzle's clean-up minimum, so lettering zones get only the fine clean-up
    # and are left for the slicer's variable-width walls to resolve
    fine_px = min(min_px, 0.22 * mm_px)
    fine = majority(raw, 3, [FIELD, SILVER, COPPER, GREEN, GUNMETAL])
    fine[fine == GUNMETAL] = SILVER if name == "side_b_dfrx" else FIELD
    for cls in (SILVER, COPPER, FIELD):
        fine = drop_specks(fine, cls, fine_px ** 2, None)
    if name == "side_a_eagle":
        rin, rout = band_profile()
        zone = band_mask(rin, rout, -128, 8, pad=4)
        fine[zone & (fine == FIELD) & (raw == GUNMETAL)] = SILVER   # shaded band, not ink
    else:
        x0, y0, x1, y1 = TAGLINE[1]
        zone = np.zeros_like(lab, bool)
        zone[y0 - 6:y1 + 6, x0 - 6:x1 + 6] = True
    lab[zone] = fine[zone]

    if name == "side_a_eagle":
        lab = fix_motto_typo(lab)
        # (eye is traced like the rest of the face: its almond socket and C-shaped iris ring are
        #  resolved by the flattened classification)
    else:
        # copper on this face is lettering only; other copper pixels are bronze reflections on
        # the silver radar lines in the render
        x0, y0, x1, y1 = TAGLINE[1]
        tag = np.zeros_like(lab, bool)
        tag[y0 - 8:y1 + 8, x0 - 8:x1 + 8] = True
        text = tag.copy()
        for _, c, ang, _, wipe in NUMBERS:
            text |= rotated_box(c, ang, wipe)
        lab[(lab == COPPER) & ~text] = SILVER
        # the render's own lettering is kept; inside the tagline the grey pixels are bevel
        # highlights on the copper letters, so they print copper
        hi = (lab == SILVER) & tag
        near = cv2.dilate((lab == COPPER).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        lab[hi & near] = COPPER
        # 000 / 131444 are engraved: copper with a dark edge, each stroke ~0.4 mm in all, too narrow
        # for a printable copper core and dark edge both, so each traced digit prints solid copper
        # (traced from the unfiltered classification: clean-up would fill the 4s' small counters)
        cross = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
        for _, c, ang, _, wipe in NUMBERS:
            box = rotated_box(c, ang, wipe)
            digit = (box & np.isin(raw, (COPPER, FIELD, GUNMETAL))).astype(np.uint8)
            digit = cv2.morphologyEx(digit, cv2.MORPH_CLOSE, cross)
            # fill pinholes, keep real counters
            n, cc, st, _ = cv2.connectedComponentsWithStats(1 - digit, connectivity=4)
            for k in range(1, n):
                if st[k, cv2.CC_STAT_AREA] < 12:
                    digit[cc == k] = 1
            digit = cv2.erode(digit, cross) * box.astype(np.uint8)
            # drop copper bevel reflections at the arm's ends: real digits are larger
            n, cc, st, _ = cv2.connectedComponentsWithStats(digit, connectivity=8)
            digit = np.isin(cc, [k for k in range(1, n) if st[k, cv2.CC_STAT_AREA] >= 150])
            digit = thicken(digit, min_px) & box            # strokes to the printable minimum
            lab[box & (lab != GREEN)] = SILVER
            lab[digit] = COPPER
        # the vertical crosshair is a glowing green bar whose near-white core reads as silver in
        # places: draw it as an exact straight bar
        lab = draw_gem(lab, min_px, mm_px)
        half = max(3.0, min_px / 2)
        for y0, y1 in CROSSHAIR_Y:
            lab[y0:y1, int(round(CROSSHAIR_X - half)):int(round(CROSSHAIR_X + half)) + 1] = GREEN

    # final pass: straighten edges touched by the widening and the redraws above; side B's
    # letters and X arms are large plain shapes, so they get a stronger clean-up
    if args.straighten > 0:
        zones = traced_zones(name, mm_px)
        lab = fill_notches(lab, (SILVER, COPPER, GREEN), mm_px, keep=zones)
        lab = straighten_panels(lab, zones, mm_px, args.straighten)
        if name == "side_b_dfrx":
            lab = straighten_large(lab, zones, mm_px)
    if name == "side_b_dfrx":
        lab = exact_triangles(lab, GREEN, mm_px)
        lab = draw_gem(lab, min_px, mm_px)                  # after straightening, so it stays exact

    # geometric rim, measured from the render: a dark outer bevel edge, the grey rim band out to
    # --rim from the edge, then a dark groove; clip to the hexagon
    k = 2 / np.sqrt(3)                                      # across-flats inset -> circumradius
    rim_px = args.rim * mm_px
    edge_px = max(args.rim_edge, args.min_feature) * mm_px
    inner = hex_mask(R_PX - rim_px * k)
    groove = inner & ~hex_mask(R_PX - (rim_px + min_px) * k)
    lab[groove] = FIELD
    lab[hex_mask(R_PX) & ~inner] = RIM
    lab[hex_mask(R_PX) & ~hex_mask(R_PX - edge_px * k)] = FIELD
    lab[~hex_mask(R_PX)] = 255

    prev = np.full((H, W, 3), 255, np.uint8)
    for c, rgb in PREVIEW_RGB.items():
        prev[lab == c] = rgb
    Image.fromarray(prev).save(os.path.join(args.out, f"{name}_face.png"))
    cmp_ = np.full((H, 2 * W + 20, 3), 255, np.uint8)
    cmp_[:, :W], cmp_[:, W + 20:] = src, prev
    Image.fromarray(cmp_).resize((W + 10, H // 2)).save(os.path.join(args.out, f"compare_{name}.png"))
    return lab


def face_sections(lab, args, mirror):
    """Disjoint silver / copper / green (/ gunmetal) cross-sections (mm) for one face."""
    px_mm = args.size / (2 * R_PX)
    hexsec = hex_cs(args.size / 2)
    taken = m3d.CrossSection()
    out = {}
    for f, classes in (("grey", (SILVER, RIM)), ("copper", (COPPER,)), ("green", (GREEN,)),
                       ("gunmetal", (GUNMETAL,))):
        sec = clean((mask_to_cs(np.isin(lab, classes), px_mm) ^ hexsec) - taken)
        taken = taken + sec
        out[f] = sec.mirror((1, 0)) if mirror else sec
    return out


def coin_body(r, thickness, chamfer_bottom, chamfer_top):
    """Hexagonal prism with 45-degree edge chamfers (chamfer given across flats, mm)."""
    def ring(rr, z):
        return [(rr * np.cos(np.radians(a)), rr * np.sin(np.radians(a)), z) for a in range(0, 360, 60)]
    k = 2 / np.sqrt(3)
    pts = (ring(r - chamfer_bottom * k, 0) + ring(r, chamfer_bottom) +
           ring(r, thickness - chamfer_top) + ring(r - chamfer_top * k, thickness))
    return m3d.Manifold.hull_points(pts)


def clean(sec, eps=0.004):
    """Tiny open + close: drop zero-width slivers, fuse corner-touching regions (clean manifolds)."""
    sec = sec.offset(-2 * eps, m3d.JoinType.Miter).offset(2 * eps, m3d.JoinType.Miter)
    sec = sec.offset(eps, m3d.JoinType.Miter).offset(-eps / 2, m3d.JoinType.Miter)
    return sec.simplify(eps / 4)


def assemble(body, hexsec, thickness, inlays):
    """inlays: list of (sections dict, z0, z1). Returns filament -> Manifold.

    Dark is built explicitly (core slab + the dark remainder of each inlay) rather than as
    body minus colours, so it gets the same sliver clean-up and stays a clean 2-manifold.
    """
    parts = {f: [] for f in FILAMENTS}
    core0, core1 = 0.0, thickness
    for secs, z0, z1 in inlays:
        colour = m3d.CrossSection.batch_boolean([s for s in secs.values() if s.area() > 0],
                                                m3d.OpType.Add)
        secs = dict(secs, black=clean(hexsec - colour))
        for f, sec in secs.items():
            if sec.area() > 0:
                # black inlay pieces reach 0.01 mm into the black core so they fuse with it
                # volumetrically; face-to-face contact along the coin edge leaves non-manifold edges
                a, b = (z0, z1 + 0.01) if z0 <= 0 else (z0 - 0.01, z1)
                if f != "black":
                    a, b = z0, z1
                parts[f].append(m3d.Manifold.extrude(sec, b - a).translate((0, 0, a)) ^ body)
        if z0 <= 0:
            core0 = z1
        else:
            core1 = z0
    slab = m3d.Manifold.extrude(hexsec, core1 - core0).translate((0, 0, core0))
    parts["black"].append(slab ^ body)
    return {f: m3d.Manifold.batch_boolean(parts[f], m3d.OpType.Add) for f in FILAMENTS if parts[f]}


def export(parts, out_dir, stem):
    stats, meshes = {}, {}
    for f, man in parts.items():
        tm = to_trimesh(man)
        tm.export(os.path.join(out_dir, f"{stem}_{f}.stl"))
        meshes[f] = tm
        stats[f] = dict(triangles=len(tm.faces), volume_mm3=round(tm.volume, 1),
                        watertight=bool(tm.is_watertight))
    scene = trimesh.Scene()
    for f, tm in meshes.items():
        scene.add_geometry(tm, node_name=f, geom_name=f)
    scene.export(os.path.join(out_dir, f"{stem}_{len(meshes)}colour.3mf"))
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=float, default=60.0, help="hexagon width across corners, mm")
    ap.add_argument("--thickness", type=float, default=3.4, help="finished coin thickness, mm")
    ap.add_argument("--inlay", type=float, default=0.6, help="colour inlay depth per face, mm")
    ap.add_argument("--chamfer", type=float, default=0.4, help="45-degree edge chamfer, mm")
    ap.add_argument("--rim", type=float, default=2.05, help="rim inner edge, mm from the coin edge")
    ap.add_argument("--rim-edge", type=float, default=0.35, help="dark outer bevel edge of the rim, mm")
    ap.add_argument("--min-feature", type=float, default=0.38,
                    help="thinnest printable stroke, mm (0.38 for a 0.4 nozzle, 0.22 for 0.2)")
    ap.add_argument("--gunmetal", choices=("grey", "hatch", "black", "filament"), default="grey",
                    help="darker-metal feathers: fine grey hatching on black (reads as dark metal), "
                         "solid black (grey bevel edges outline them), solid grey, or a 5th filament")
    ap.add_argument("--straighten", type=float, default=0.09,
                    help="polygon tolerance for straight panel edges, mm (0 = off)")
    ap.add_argument("--no-smooth-lines", dest="smooth_lines", action="store_false",
                    help="keep thin line-work as traced instead of redrawing it as smooth strokes")
    ap.add_argument("--seams", action="store_true",
                    help="draw a black line wherever dark metal meets grey (--gunmetal grey)")
    ap.add_argument("--hatch-pitch", type=float, default=None,
                    help="line spacing for --gunmetal hatch, mm (default: 40%% grey coverage; "
                         "grey line = --min-feature wide)")
    ap.add_argument("--out", default=os.path.join(ROOT, "stl", "nozzle_0.4"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    lab_a = label_side("side_a_eagle", args)
    lab_b = label_side("side_b_dfrx", args)
    r, t, d, c = args.size / 2, args.thickness, args.inlay, args.chamfer
    report = {}

    # one-piece coin: eagle face printed against the plate (mirrored so it reads correctly once
    # flipped), dFRX face inlaid in the top layers
    hexsec = hex_cs(r)
    body = coin_body(r, t, c, c)
    parts = assemble(body, hexsec, t, [(face_sections(lab_a, args, True), 0, d),
                            (face_sections(lab_b, args, False), t - d, t)])
    report["coin_one_piece"] = export(parts, args.out, "coin_one_piece")

    # alternative: two face-down halves to glue back-to-back (both faces get the plate finish)
    for name, lab in (("half_a_eagle", lab_a), ("half_b_dfrx", lab_b)):
        body = coin_body(r, t / 2, c, 0)
        parts = assemble(body, hexsec, t / 2, [(face_sections(lab, args, True), 0, d)])
        report[name] = export(parts, args.out, name)

    report["params"] = {k: v for k, v in vars(args).items() if k != "out"}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
