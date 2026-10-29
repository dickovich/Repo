"""Turn the two challenge-coin renders into 4-colour, 3D-printable STL parts.

Pipeline per side:
  1. Rectify the (slightly perspective) render onto a regular flat-top hexagon.
  2. Classify every pixel into a material class (field, gunmetal, silver, copper, green).
  3. Side A only: erase the misspelt motto ("SECONOS") and re-letter it along the band.
  4. Replace the rendered rim with a clean geometric rim.
  5. Clean up: majority filter, drop specks, thicken hairlines to the printable minimum.
  6. Vectorise each class, extrude to its relief height, union per filament colour.

Each side is a half-coin printed face-up; the two halves are glued back-to-back.

Usage: python3 tools/build_coin.py [--size 50] [--min-feature 0.42]
"""
import argparse
import json
import os

import cv2
import numpy as np
import manifold3d as m3d
import trimesh
from PIL import Image, ImageDraw, ImageFont
from skimage.morphology import skeletonize

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
FILAMENT = {FIELD: "dark", GUNMETAL: "dark", INK: "dark",
            SILVER: "silver", RIM: "silver", COPPER: "copper", GREEN: "green"}
FILAMENTS = ["dark", "silver", "copper", "green"]

PREVIEW_RGB = {FIELD: (28, 28, 30), GUNMETAL: (62, 62, 66), INK: (10, 10, 10),
               SILVER: (200, 202, 206), RIM: (225, 226, 230),
               COPPER: (214, 128, 84), GREEN: (140, 230, 40)}

MOTTO = "FASTER RESPONSE WHEN SECONDS MATTER"
FONT = "/usr/share/fonts/opentype/inter/Inter-Black.otf"


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


def classify(rgb):
    smooth = cv2.medianBlur(cv2.bilateralFilter(rgb, 9, 40, 7), 5)
    hsv = cv2.cvtColor(smooth, cv2.COLOR_RGB2HSV).astype(np.int16)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    lab = np.full(rgb.shape[:2], FIELD, np.uint8)
    lab[(v >= 66) & (v <= 115)] = GUNMETAL
    lab[v > 115] = SILVER
    lab[(h >= 3) & (h <= 20) & (s > 70) & (v > 90)] = COPPER
    lab[(h >= 28) & (h <= 50) & (s > 90) & (v > 90)] = GREEN
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


def reletter_motto(lab):
    rin, rout = band_profile()
    a0, a1 = -123.0, 6.0                                    # angular span carrying the old lettering
    band = band_mask(rin, rout, a0, a1, pad=6)
    lab = lab.copy()
    lab[band & (lab != SILVER)] = SILVER                    # wipe the old (misspelt) lettering

    # render the motto along the band centreline, one glyph at a time
    mid = lambda a: (rin(a) + rout(a)) / 2
    width = np.mean([rout(a) - rin(a) for a in np.linspace(-110, 0, 20)])
    print(f"  motto band width {width:.0f}px")
    r_mid = mid(-60.0)
    span = 124.0                                            # degrees the original lettering covers
    condense = 0.80                                         # original face is a semi-condensed sans
    scale = 4                                               # supersample for clean glyph edges
    probe = ImageFont.truetype(FONT, 100)
    track = 0.07                                            # extra letter spacing, em (keeps gaps printable)
    em_len = sum(probe.getlength(ch) / 100 * condense + track for ch in MOTTO)
    em = min(np.radians(span) * r_mid / em_len, 0.66 * width / 0.727)   # Inter cap height ~0.727 em
    font = ImageFont.truetype(FONT, int(em * scale))
    adv = [font.getlength(ch) / scale * condense + track * em for ch in MOTTO]
    start = -60.0 - np.degrees(sum(adv) / r_mid) / 2       # centred where the original was
    ink = Image.new("L", (W * scale, H * scale), 0)
    pos = 0.0
    for ch, w in zip(MOTTO, adv):
        a = start + np.degrees((pos + w / 2) / r_mid)
        pos += w
        if ch == " ":
            continue
        r = mid(a)
        gx, gy = BAND_C[0] + r * np.cos(np.radians(a)), BAND_C[1] + r * np.sin(np.radians(a))
        g = Image.new("L", (int(w * scale / condense * 2) + 20, int(em * scale * 1.6)), 0)
        ImageDraw.Draw(g).text((g.width / 2, g.height / 2), ch, font=font, fill=255, anchor="mm")
        g = g.resize((int(g.width * condense), g.height), Image.LANCZOS)
        g = g.rotate(-(a + 90), resample=Image.BICUBIC, expand=True)
        ink.paste(g, (int(gx * scale - g.width / 2), int(gy * scale - g.height / 2)), g)
    ink = np.array(ink.resize((W, H), Image.LANCZOS)) > 110
    lab[ink & band_mask(rin, rout, a0, a1, pad=2)] = INK
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


def reletter_numbers(lab):
    lab = lab.copy()
    scale = 4
    for text, c, ang, cap, wipe in NUMBERS:
        box = rotated_box(c, ang, wipe)
        lab[box] = SILVER                                    # the arm is plain silver under the digits
        font = ImageFont.truetype(FONT, int(cap / 0.727 * scale))
        g = Image.new("L", (int(font.getlength(text) * 1.3) + 40, int(cap * scale * 2.2)), 0)
        ImageDraw.Draw(g).text((g.width / 2, g.height / 2), text, font=font, fill=255, anchor="mm")
        g = g.resize((int(g.width * 0.9), g.height), Image.LANCZOS)
        g = g.rotate(-ang, resample=Image.BICUBIC, expand=True)
        ink = Image.new("L", (W * scale, H * scale), 0)
        ink.paste(g, (int(c[0] * scale - g.width / 2), int(c[1] * scale - g.height / 2)), g)
        ink = np.array(ink.resize((W, H), Image.LANCZOS)) > 110
        lab[ink & box] = COPPER
    return lab


# --- geometry -------------------------------------------------------------------------------
def mask_to_cs(mask, px_mm):
    """Binary mask -> manifold3d CrossSection in mm (centred, y up), grown by half a pixel."""
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    polys = []
    for c in cs:
        if len(c) < 3:
            continue
        c = cv2.approxPolyDP(c, 0.7, True).reshape(-1, 2).astype(float)
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


def build_side(name, args):
    px_mm = args.size / (2 * R_PX)                          # mm per raster pixel
    mm_px = 1 / px_mm
    lab = classify(rectify(name))

    # clean-up: majority vote then remove specks smaller than 0.6 x 0.6 mm
    lab = majority(lab, 5, [FIELD, SILVER, COPPER, GREEN, GUNMETAL])
    for cls in (GUNMETAL, SILVER, COPPER, GREEN):
        lab = drop_specks(lab, cls, (0.6 * mm_px) ** 2, None)

    # lettering is redrawn from a font after clean-up so it stays crisp
    if name == "side_a_eagle":
        lab = reletter_motto(lab)
    else:
        lab = reletter_numbers(lab)

    # thicken hairlines (silver radar lines, copper lettering, green ticks, motto ink)
    min_px = args.min_feature * mm_px
    for cls, into in ((COPPER, (FIELD, GUNMETAL)),
                      (GREEN, (FIELD, GUNMETAL)), (SILVER, (FIELD, GUNMETAL))):
        grow = thicken(lab == cls, min_px) & np.isin(lab, into)
        lab[grow] = cls

    # geometric rim + clip to hexagon
    rim_px = args.rim * mm_px
    outer = hex_mask(R_PX)
    inner = hex_mask(R_PX - rim_px * 2 / np.sqrt(3))        # inset measured across flats
    lab[outer & ~inner] = RIM
    lab[~outer] = 255
    lab[inner & ~hex_mask(R_PX - (rim_px + args.min_feature * mm_px) * 2 / np.sqrt(3))
        & ~np.isin(lab, (FIELD,))] = FIELD                  # keep a clean groove inside the rim

    # preview
    prev = np.zeros((H, W, 3), np.uint8)
    for c, rgb in PREVIEW_RGB.items():
        prev[lab == c] = rgb
    Image.fromarray(prev).save(os.path.join(args.out, f"{name}_preview.png"))

    # relief heights (mm) of each class top surface; base plate is dark, 0..BASE
    base = args.base
    top = {FIELD: base, GUNMETAL: base + 0.4, GREEN: base + 0.4, INK: base + 0.6,
           COPPER: base + 0.6, SILVER: base + 0.8, RIM: base + 1.0}

    # disjoint cross-sections, priority high -> low so boundaries are shared, not doubled
    order = [RIM, SILVER, INK, COPPER, GREEN, GUNMETAL]
    taken = m3d.CrossSection()
    secs = {}
    hexsec = hex_cs(args.size / 2)
    for cls in order:
        sec = (mask_to_cs(lab == cls, px_mm) ^ hexsec) - taken
        taken = taken + sec
        if sec.area() > 0:
            secs[cls] = sec

    # per filament, stack slabs between successive top heights; a tiny open + close removes
    # zero-width slivers and fuses corner-touching regions so every STL is a clean 2-manifold
    eps = 0.004
    parts = {f: [] for f in FILAMENTS}
    parts["dark"].append(m3d.Manifold.extrude(hexsec, base))
    for f in FILAMENTS:
        classes = [c for c in secs if FILAMENT[c] == f]
        z0 = base
        for z in sorted({top[c] for c in classes}):
            sec = m3d.CrossSection.batch_boolean([secs[c] for c in classes if top[c] >= z],
                                                 m3d.OpType.Add)
            sec = sec.offset(-2 * eps, m3d.JoinType.Miter).offset(2 * eps, m3d.JoinType.Miter)
            sec = sec.offset(eps, m3d.JoinType.Miter).offset(-eps / 2, m3d.JoinType.Miter)
            sec = sec.simplify(eps / 4)
            parts[f].append(m3d.Manifold.extrude(sec, z - z0).translate((0, 0, z0)))
            z0 = z

    stats = {}
    meshes = {}
    for f in FILAMENTS:
        if not parts[f]:
            continue
        man = m3d.Manifold.batch_boolean(parts[f], m3d.OpType.Add)
        tm = to_trimesh(man)
        path = os.path.join(args.out, f"{name}_{f}.stl")
        tm.export(path)
        meshes[f] = tm
        stats[f] = dict(triangles=len(tm.faces), volume_mm3=round(tm.volume, 1),
                        watertight=bool(tm.is_watertight))
    return meshes, stats


def export_3mf(meshes, path):
    scene = trimesh.Scene()
    for f, tm in meshes.items():
        scene.add_geometry(tm, node_name=f, geom_name=f)
    scene.export(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=float, default=50.0, help="hexagon width across corners, mm")
    ap.add_argument("--base", type=float, default=1.0, help="base plate thickness per half, mm")
    ap.add_argument("--rim", type=float, default=1.6, help="rim width, mm")
    ap.add_argument("--min-feature", type=float, default=0.42,
                    help="thinnest printable stroke, mm (0.42 for a 0.4 nozzle, 0.25 for 0.2)")
    ap.add_argument("--out", default=os.path.join(ROOT, "stl"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    report = {}
    for name in SRC_CORNERS:
        meshes, stats = build_side(name, args)
        export_3mf(meshes, os.path.join(args.out, f"{name}_4colour.3mf"))
        report[name] = stats
    report["params"] = vars(args)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
