"""Turn the two challenge-coin renders into 4-colour, 3D-printable STL parts.

Pipeline per side:
  1. Rectify the (slightly perspective) render onto a regular flat-top hexagon.
  2. Flatten the render with L0 gradient smoothing (texture and lighting noise go, facet edges
     stay sharp), then classify each pixel by CIELAB lightness/hue: field, gunmetal, silver,
     copper, green. Side A: recover the darkest feathers by context (enclosed compact regions).
  3. Redraw lettering from fonts (fixing the "SECONOS" typo), the eagle's eye and side B's
     crosshair as exact geometry.
  4. Replace the rendered rim with a clean geometric rim.
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
FILAMENT = {FIELD: "dark", GUNMETAL: "gunmetal", INK: "dark",
            SILVER: "silver", RIM: "silver", COPPER: "copper", GREEN: "green"}
FILAMENTS = ["dark", "silver", "copper", "green", "gunmetal"]   # gunmetal only with --gunmetal filament

PREVIEW_RGB = {FIELD: (28, 28, 30), GUNMETAL: (98, 98, 104), INK: (10, 10, 10),
               SILVER: (200, 202, 206), RIM: (225, 226, 230),
               COPPER: (214, 128, 84), GREEN: (140, 230, 40)}

MOTTO = "FASTER RESPONSE WHEN SECONDS MATTER"
FONT_DIR = "/usr/share/fonts/opentype/inter"
FONT = f"{FONT_DIR}/Inter-Black.otf"            # set in main(): lighter weight for fine nozzles


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
    out[L >= 70] = GUNMETAL                                # darker metal (~L 86)
    out[L >= 125] = SILVER                                 # bright metal and bevel highlights
    out[(a >= 140) & (b >= 143) & (L >= 75)] = COPPER
    out[(a <= 124) & (b >= 146) & (L >= 90)] = GREEN          # incl. near-white glow cores
    return out


def find_dark_feathers(src, flat, mm_px):
    """Darkest gunmetal feathers flatten to the same lightness as the background (L ~56), so
    find them by context: compact regions enclosed by grooves and bevel highlights, lying on
    the eagle, away from the outer frame. Long thin arcs (the dial ring) fail the solidity test."""
    lab = cv2.cvtColor(flat, cv2.COLOR_RGB2LAB).astype(np.int16)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    v = cv2.cvtColor(src, cv2.COLOR_RGB2HSV)[..., 2].astype(np.float32)
    eagle = cv2.GaussianBlur(v, (0, 0), 4) > 64
    bound = (L < 38) | (L >= 125) | ((a >= 140) & (b >= 143)) | ((a <= 124) & (b >= 146))
    bound = cv2.dilate(bound.astype(np.uint8), np.ones((3, 3), np.uint8))
    n, cc, st, cen = cv2.connectedComponentsWithStats(1 - bound, connectivity=4)
    edge_dist = cv2.distanceTransform(hex_mask(R_PX).astype(np.uint8), cv2.DIST_L2, 5)
    keep = []
    for i in range(1, n):
        area = st[i, cv2.CC_STAT_AREA]
        if not 0.3 <= area / mm_px ** 2 <= 40:
            continue
        x, y, w, h = st[i, :4]
        m = cc[y:y + h, x:x + w] == i
        if eagle[y:y + h, x:x + w][m].mean() < 0.5:
            continue
        pts = np.c_[np.nonzero(m)[1] + x, np.nonzero(m)[0] + y].astype(np.int32)
        solidity = area / max(cv2.contourArea(cv2.convexHull(pts)), 1)
        length = max(cv2.minAreaRect(pts)[1]) / mm_px
        if solidity >= 0.7 and length <= 24 and edge_dist[int(cen[i][1]), int(cen[i][0])] >= 4.5 * mm_px:
            keep.append(i)
    feathers = np.isin(cc, keep)
    # regrow by the sealing dilation so the feather meets its groove/highlight
    grown = cv2.dilate(feathers.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    return grown & (L < 125)


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


EYE_C, EYE_R = (1052, 647), 21          # eagle's eye in the rectified raster


def redraw_eye(lab, min_px):
    """The eye's concentric rings are finer than the colour separation resolves: redraw it as a
    dark-rimmed green iris, dark pupil and a silver catch-light."""
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot(xx - EYE_C[0], yy - EYE_C[1])
    lab = lab.copy()
    rim = max(3.0, min_px * 0.6)
    lab[r <= EYE_R + rim] = FIELD
    lab[r <= EYE_R] = GREEN
    lab[r <= max(9.0, min_px)] = FIELD
    glint = max(3.0, min_px / 2)
    lab[np.hypot(xx - (EYE_C[0] - 2), yy - (EYE_C[1] - 13)) <= glint] = SILVER
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


def reletter_tagline(lab):
    """Redraw the copper tagline: the traced D reads as an O and a radar line cuts the N."""
    text, (x0, y0, x1, y1) = TAGLINE
    lab = lab.copy()
    pad = 6
    lab[y0 - pad:y1 + pad, x0 - pad:x1 + pad] = FIELD
    scale = 4
    cap = y1 - y0
    font = ImageFont.truetype(FONT, int(cap / 0.727 * scale))
    # the render's face is narrower and more widely spaced than Inter: condense each glyph and
    # spread the spare width between letters
    condense = 0.82
    glyphs = []
    for ch in text:
        if ch == " ":
            glyphs.append(None)
            continue
        gi = Image.new("L", (int(cap * scale * 2), int(cap * scale * 1.6)), 0)
        ImageDraw.Draw(gi).text((gi.width // 2, int(gi.height * 0.8)), ch, font=font, fill=255,
                                anchor="ms")
        gi = gi.crop(gi.getbbox())
        glyphs.append(gi.resize((max(1, int(gi.width * condense)), gi.height), Image.LANCZOS))
    space = font.getlength(" ") * condense
    ink_w = sum(gi.width if gi else space for gi in glyphs)
    gap = ((x1 - x0) * scale - ink_w) / (len(text) - 1)
    g = Image.new("L", ((x1 - x0) * scale + 50, cap * scale + 50), 0)
    x = 0.0
    for gi in glyphs:
        if gi is None:
            x += space + gap
            continue
        g.paste(gi, (int(x), cap * scale - gi.height + 10))
        x += gi.width + gap
    g = g.crop(g.getbbox()).resize(((x1 - x0) * scale, cap * scale), Image.LANCZOS)
    ink = np.array(g.resize((x1 - x0, cap), Image.LANCZOS)) > 110
    region = lab[y0:y1, x0:x1]
    region[ink] = COPPER
    return lab


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
    """Widen the thin parts of a large connected region (e.g. dark outlines between facets)."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(min_px) | 1, int(min_px) | 1))
    m8 = mask.astype(np.uint8)
    thin = mask & ~cv2.morphologyEx(m8, cv2.MORPH_OPEN, k).astype(bool)
    sk = skeletonize(thin).astype(np.uint8)
    n, cc, st, _ = cv2.connectedComponentsWithStats(sk, connectivity=8)
    long_ = np.where(st[:, cv2.CC_STAT_AREA] >= 1.5 * min_px)[0]
    sk = np.isin(cc, long_[long_ != 0])
    return mask | cv2.dilate(sk.astype(np.uint8), k).astype(bool)


def label_side(name, args):
    """Classified, cleaned label map for one face (unmirrored, as seen)."""
    mm_px = 2 * R_PX / args.size                            # raster pixels per mm
    min_px = args.min_feature * mm_px
    src = rectify(name)
    flat = flatten(src)
    lab = classify(flat)
    if name == "side_a_eagle":
        lab[find_dark_feathers(src, flat, mm_px) & (lab == FIELD)] = GUNMETAL
    lab = majority(lab, 3, [FIELD, SILVER, COPPER, GREEN, GUNMETAL])
    for cls in (SILVER, COPPER, GREEN, GUNMETAL, FIELD):
        lab = drop_specks(lab, cls, min_px ** 2, None)

    if name == "side_b_dfrx":
        # on this face the mid-grey pixels are the dimmer stretches of the silver radar lines
        lab[lab == GUNMETAL] = SILVER
    elif args.gunmetal == "silver":
        lab[lab == GUNMETAL] = SILVER
    elif args.gunmetal == "dark":
        lab[lab == GUNMETAL] = FIELD                        # silver bevel edges outline them

    # widen hairlines to the printable minimum: isolated light strokes first, then the dark
    # outlines between facets (dark wins, so facets stay separated)
    for cls in (COPPER, GREEN, SILVER, GUNMETAL):
        grow = thicken(lab == cls, min_px) & (lab == FIELD)
        lab[grow] = cls
    dark = lab == FIELD
    lab[thicken_lines(dark, min_px) & ~dark] = FIELD
    for cls in (SILVER, COPPER, GREEN, GUNMETAL):           # sub-minimum slivers left behind
        lab = drop_specks(lab, cls, (0.8 * min_px) ** 2, FIELD)

    # lettering is redrawn from a font last so nothing above erodes it
    if name == "side_a_eagle":
        lab = reletter_motto(lab)
        lab = redraw_eye(lab, min_px)
    else:
        # copper on this face is lettering only; other copper pixels are bronze reflections on
        # the silver radar lines in the render
        text = np.zeros_like(lab, bool)
        text[815:900, :] = True                             # DRONE AS FIRST RESPONDER
        lab[(lab == COPPER) & ~text] = SILVER
        lab = reletter_numbers(lab)
        lab = reletter_tagline(lab)
        # the vertical crosshair is a glowing green bar whose near-white core reads as silver in
        # places: draw it as an exact straight bar
        half = max(3.0, min_px / 2)
        for y0, y1 in CROSSHAIR_Y:
            lab[y0:y1, int(round(CROSSHAIR_X - half)):int(round(CROSSHAIR_X + half)) + 1] = GREEN

    # geometric rim + clean groove inside it, clip to hexagon
    rim_px = args.rim * mm_px
    inner = hex_mask(R_PX - rim_px * 2 / np.sqrt(3))
    groove = inner & ~hex_mask(R_PX - (rim_px + min_px) * 2 / np.sqrt(3))
    lab[groove] = FIELD
    lab[hex_mask(R_PX) & ~inner] = RIM
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
    for f, classes in (("silver", (SILVER, RIM)), ("copper", (COPPER,)), ("green", (GREEN,)),
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
        secs = dict(secs, dark=clean(hexsec - colour))
        for f, sec in secs.items():
            if sec.area() > 0:
                parts[f].append(m3d.Manifold.extrude(sec, z1 - z0).translate((0, 0, z0)) ^ body)
        if z0 <= 0:
            core0 = z1
        else:
            core1 = z0
    slab = m3d.Manifold.extrude(hexsec, core1 - core0).translate((0, 0, core0))
    parts["dark"].append(slab ^ body)
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
    ap.add_argument("--rim", type=float, default=1.8, help="rim width, mm")
    ap.add_argument("--min-feature", type=float, default=0.38,
                    help="thinnest printable stroke, mm (0.38 for a 0.4 nozzle, 0.22 for 0.2)")
    ap.add_argument("--gunmetal", choices=("dark", "silver", "filament"), default="dark",
                    help="darker-metal feathers: print silver, print dark (their silver bevel "
                         "edges outline them), or as a 5th filament")
    ap.add_argument("--out", default=os.path.join(ROOT, "stl", "nozzle_0.4"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    global FONT
    # a fine nozzle can hold the source's lighter letter weight; a 0.4 needs the heavier one
    FONT = f"{FONT_DIR}/Inter-{'ExtraBold' if args.min_feature < 0.3 else 'Black'}.otf"

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
