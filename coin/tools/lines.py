"""Redraw thin line-work (rings, ticks, spokes) as smooth constant-width strokes.

Traced from a raster, thin lines come out kinked and ragged. This finds the thin parts of a mask,
traces their centrelines, smooths each centreline and redraws it anti-aliased at its own median
width (never below the printable minimum), the way a vector redraw of the artwork would.
"""
import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from skimage.morphology import skeletonize

_NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _neighbour_count(sk):
    k = np.ones((3, 3), np.uint8)
    k[1, 1] = 0
    return cv2.filter2D(sk.astype(np.uint8), -1, k, borderType=cv2.BORDER_CONSTANT)


def _trace(sk):
    """Split a skeleton into simple pixel paths (junction pixels removed), each ordered."""
    nbc = _neighbour_count(sk)
    junction = sk & (nbc >= 3)
    paths_mask = sk & ~cv2.dilate(junction.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    n, cc = cv2.connectedComponents(paths_mask.astype(np.uint8), connectivity=8)
    ys, xs = np.nonzero(cc)
    order = np.argsort(cc[ys, xs], kind="stable")
    ys, xs = ys[order], xs[order]
    bounds = np.searchsorted(cc[ys, xs], np.arange(1, n + 1))
    paths = []
    for i in range(1, n):
        py, px = ys[bounds[i - 1]:bounds[i]], xs[bounds[i - 1]:bounds[i]]
        pts = set(zip(py.tolist(), px.tolist()))
        # start from an endpoint if there is one (open path), else anywhere (loop)
        deg = {p: sum((p[0] + dy, p[1] + dx) in pts for dy, dx in _NB) for p in pts}
        start = next((p for p, d in deg.items() if d <= 1), next(iter(pts)))
        closed = all(d >= 2 for d in deg.values())
        path, seen, cur = [start], {start}, start
        while True:
            nxt = [(cur[0] + dy, cur[1] + dx) for dy, dx in _NB
                   if (cur[0] + dy, cur[1] + dx) in pts and (cur[0] + dy, cur[1] + dx) not in seen]
            if not nxt:
                break
            # prefer 4-neighbours so diagonal shortcuts do not skip pixels
            nxt.sort(key=lambda q: abs(q[0] - cur[0]) + abs(q[1] - cur[1]))
            cur = nxt[0]
            seen.add(cur)
            path.append(cur)
        paths.append((np.array(path, float), closed and len(path) > 8))
    return paths, junction


def smooth_lines(mask, min_px, thin_px, sigma=2.5, scale=4):
    """Return mask with its thin parts (narrower than thin_px) redrawn as smooth strokes."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(thin_px) | 1, int(thin_px) | 1))
    m8 = mask.astype(np.uint8)
    thick = cv2.morphologyEx(m8, cv2.MORPH_OPEN, k).astype(bool)
    thin = mask & ~cv2.dilate(thick.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    if not thin.any():
        return mask
    sk = skeletonize(thin)
    dist = cv2.distanceTransform(m8, cv2.DIST_L2, 5)
    paths, junction = _trace(sk)
    h, w = mask.shape
    canvas = np.zeros((h * scale, w * scale), np.uint8)
    for pts, closed in paths:
        if len(pts) < 3:
            continue
        width = max(2.0 * float(np.median(dist[pts[:, 0].astype(int), pts[:, 1].astype(int)])), min_px)
        if len(pts) >= 5:
            pts = gaussian_filter1d(pts, sigma, axis=0, mode="wrap" if closed else "nearest")
        poly = np.round(pts[:, ::-1] * scale + scale / 2).astype(np.int32)
        cv2.polylines(canvas, [poly], closed, 255, max(1, int(round(width * scale))), cv2.LINE_AA)
    # junction pixels: small discs so strokes stay joined where lines cross
    jy, jx = np.nonzero(junction)
    for y, x in zip(jy, jx):
        r = max(dist[y, x], min_px / 2)
        cv2.circle(canvas, (int(x * scale + scale / 2), int(y * scale + scale / 2)),
                   int(round(r * scale)), 255, -1, cv2.LINE_AA)
    redrawn = cv2.resize(canvas, (w, h), interpolation=cv2.INTER_AREA) > 127
    return thick | redrawn
