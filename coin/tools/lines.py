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


def _runs(cov, gap, min_len):
    """Runs of True in a circular boolean array after closing gaps <= gap bins."""
    n = len(cov)
    c = cov.copy()
    if c.all():
        return [(0, n)]
    if not c.any():
        return []
    # close small gaps (circular)
    k = np.r_[c, c, c]
    out = k.copy()
    i = 0
    while i < len(k):
        if not k[i]:
            j = i
            while j < len(k) and not k[j]:
                j += 1
            if j - i <= gap and i > 0 and j < len(k):
                out[i:j] = True
            i = j
        else:
            i += 1
    c = out[n:2 * n]
    if c.all():
        return [(0, n)]
    start = int(np.argmin(c))                               # begin scanning at a gap
    runs, i = [], 0
    while i < n:
        p = (start + i) % n
        if c[p]:
            j = i
            while j < n and c[(start + j) % n]:
                j += 1
            if j - i >= min_len:
                runs.append(((start + i) % n, j - i))
            i = j
        else:
            i += 1
    return runs


def radar_redraw(mask, clean, centre, mm_px, min_px, bright=None, ring_min_count=80, scale=4):
    """Redraw radar line-work exactly. Rings concentric with centre become true arcs over the
    angles where the render has them, and the ticks standing on them become radial strokes
    (both read from mask, the full-detail trace). Other line-work (spokes, frame lines) is
    taken from clean, the cleaned trace: straight strokes become straight segments, anything
    else is smoothed. Returns the new mask."""
    h, w = mask.shape
    cx, cy = centre
    ys, xs = np.nonzero(mask)
    r = np.hypot(xs - cx, ys - cy)
    ang = np.degrees(np.arctan2(ys - cy, xs - cx))
    dist = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    canvas = np.zeros((h * scale, w * scale), np.uint8)
    used = np.zeros_like(mask)
    # rings: radial histogram peaks
    hist, edges = np.histogram(r, bins=np.arange(0, max(h, w), 1.0))
    sm = np.convolve(hist, np.ones(5), "same")
    peaks = [i for i in range(6, len(sm) - 6) if sm[i] == sm[i - 6:i + 7].max() and sm[i] >= ring_min_count]
    bin_deg = 0.5
    for i in peaks:
        R = edges[i] + 0.5
        near = np.abs(r - R) <= 3.5
        if near.sum() < ring_min_count:
            continue
        R = float(np.median(r[near]))
        near = np.abs(r - R) <= 3.5
        width = max(2 * float(np.median(dist[ys[near], xs[near]])), min_px)
        cov = np.zeros(int(360 / bin_deg), bool)
        cov[((ang[near] + 180) / bin_deg).astype(int) % len(cov)] = True
        gap = int(np.ceil(np.degrees(1.2 * mm_px / R) / bin_deg))          # bridge < 1.2 mm
        min_len = int(np.ceil(np.degrees(1.5 * mm_px / R) / bin_deg))      # arcs >= 1.5 mm
        runs = _runs(cov, gap, min_len)
        for s, n in runs:
            a0 = s * bin_deg - 180
            a1 = a0 + n * bin_deg
            cv2.ellipse(canvas, (int(cx * scale), int(cy * scale)), (int(R * scale), int(R * scale)),
                        0, a0, a1, 255, max(1, int(round(width * scale))), cv2.LINE_AA)
            sel = near & (((ang - a0) % 360) <= (a1 - a0) + bin_deg)
            used[ys[sel], xs[sel]] = True
    ring_px = cv2.dilate(used.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    rest = (mask if bright is None else bright) & ~ring_px     # ticks are bright metal
    other = clean & ~cv2.dilate(ring_px.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    ring_r = [float(np.median(r[np.abs(r - (edges[i] + 0.5)) <= 3.5])) for i in peaks
              if (np.abs(r - (edges[i] + 0.5)) <= 3.5).sum() >= ring_min_count]
    leftover = np.zeros_like(mask)
    tick_px = np.zeros_like(mask)
    # ticks standing on a ring
    n, cc, st, _ = cv2.connectedComponentsWithStats(rest.astype(np.uint8), connectivity=8)
    for k in range(1, n):
        x, y, ww, hh, area = st[k]
        if area < 4:
            continue
        py, px = np.nonzero(cc[y:y + hh, x:x + ww] == k)
        pts = np.c_[px + x, py + y].astype(float)
        mean = pts.mean(0)
        u, sv, vt = np.linalg.svd(pts - mean, full_matrices=False)
        proj = (pts - mean) @ vt[0]
        length = proj.max() - proj.min()
        spread = sv[1] / np.sqrt(len(pts)) if len(sv) > 1 else 0
        wdt = max(2 * float(np.median(dist[py + y, px + x])), min_px)
        # a tick: short radial stroke standing on a ring; drawn from the ring to its far end
        rr = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
        radial = (mean - (cx, cy)) / max(np.hypot(*(mean - (cx, cy))), 1e-6)
        if ring_r and 0.25 * mm_px <= length <= 2.0 * mm_px and abs(vt[0] @ radial) > 0.9:
            Rn = min(ring_r, key=lambda q: min(abs(rr.min() - q), abs(rr.max() - q)))
            if min(abs(rr.min() - Rn), abs(rr.max() - Rn)) <= 10:
                far = rr.max() if abs(rr.max() - Rn) > abs(rr.min() - Rn) else rr.min()
                if abs(far - Rn) >= 0.25 * mm_px:
                    th = np.arctan2(mean[1] - cy, mean[0] - cx)
                    e = np.array([np.cos(th), np.sin(th)])
                    q0 = np.array([cx, cy]) + e * Rn
                    q1 = np.array([cx, cy]) + e * (far - np.sign(far - Rn) * wdt * 0.4)
                    cv2.line(canvas, tuple(np.int32((q0 + 0.5) * scale)),
                             tuple(np.int32((q1 + 0.5) * scale)), 255,
                             max(1, int(round(wdt * scale))), cv2.LINE_AA)
                    tick_px[cc == k] = True
    other &= ~cv2.dilate(tick_px.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    # other line-work, from the cleaned trace
    n, cc, st, _ = cv2.connectedComponentsWithStats(other.astype(np.uint8), connectivity=8)
    for k in range(1, n):
        x, y, ww, hh, area = st[k]
        if area < 0.25 * min_px ** 2:
            continue
        py, px = np.nonzero(cc[y:y + hh, x:x + ww] == k)
        pts = np.c_[px + x, py + y].astype(float)
        mean = pts.mean(0)
        u, sv, vt = np.linalg.svd(pts - mean, full_matrices=False)
        proj = (pts - mean) @ vt[0]
        length = proj.max() - proj.min()
        spread = sv[1] / np.sqrt(len(pts)) if len(sv) > 1 else 0
        wdt = max(2 * float(np.median(dist[py + y, px + x])), min_px)
        if length < 1.0 * mm_px:
            continue                                        # specks and texture, not line-work
        if length >= 2 * wdt and spread <= max(1.5, 0.45 * wdt):
            p0 = mean + vt[0] * proj.min()
            p1 = mean + vt[0] * proj.max()
            # trim the round caps the dilation adds back
            d = vt[0] * (wdt / 2) * 0.8
            q0, q1 = p0 + d, p1 - d
            cv2.line(canvas, tuple(np.int32((q0 + 0.5) * scale)), tuple(np.int32((q1 + 0.5) * scale)),
                     255, max(1, int(round(wdt * scale))), cv2.LINE_AA)
        elif length >= 1.5 * mm_px:
            leftover[cc == k] = True
    out = cv2.resize(canvas, (w, h), interpolation=cv2.INTER_AREA) > 127
    if leftover.any():
        out |= smooth_lines(leftover, min_px, 0.6 * mm_px, sigma=3.0)
    return out
