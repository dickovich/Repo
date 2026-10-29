"""Facet segmentation: one region per armour plate / letter / panel of the render.

The L0-flattened render is split into superpixels (Felzenszwalb), and neighbouring superpixels
are merged when they are the same material and no groove runs between them (shading steps
inside a plate are small; grooves are dark narrow lines). Bevel highlights and reflections are
thin regions: they merge into the plate they border. Each final region gets one material.
"""
import cv2
import numpy as np
from skimage.segmentation import felzenszwalb

DARK, METAL, COPPER_M, GREEN_M = 0, 1, 2, 3


class UF:
    def __init__(self, n):
        self.p = np.arange(n)

    def find(self, x):
        p = self.p
        r = x
        while p[r] != r:
            r = p[r]
        while p[x] != r:
            p[x], x = r, p[x]
        return r

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[b] = a
        return a


def _pairs(seg, weight=None):
    """Adjacent label pairs (4-neighbourhood) with boundary length and optional summed weight."""
    a = np.concatenate([seg[:, :-1].ravel(), seg[:-1, :].ravel()])
    b = np.concatenate([seg[:, 1:].ravel(), seg[1:, :].ravel()])
    w = None
    if weight is not None:
        w = np.concatenate([np.maximum(weight[:, :-1], weight[:, 1:]).ravel(),
                            np.maximum(weight[:-1, :], weight[1:, :]).ravel()])
    m = a != b
    a, b = a[m], b[m]
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    n = int(seg.max()) + 1
    key = lo.astype(np.int64) * n + hi
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    ws = np.bincount(inv, weights=w[m]) if w is not None else None
    return uk // n, uk % n, cnt, ws


def _relabel(seg):
    _, inv = np.unique(seg, return_inverse=True)
    return inv.reshape(seg.shape)


def segment(flat, pix_class, classes, scale=150, dl_merge=40, groove_bh=22, mm_px=21.67):
    """Return (regions, material) with material per region in DARK/METAL/COPPER_M/GREEN_M.

    pix_class: per-pixel class map; classes: dict with keys 'copper', 'green' -> class ids.
    """
    L = cv2.cvtColor(flat, cv2.COLOR_RGB2LAB)[..., 0]
    bh = cv2.morphologyEx(L, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    seg = felzenszwalb(flat, scale=scale, sigma=0.0, min_size=12)
    n = seg.max() + 1
    idx = seg.ravel()
    cnt = np.bincount(idx, minlength=n).astype(float)
    meanL = np.bincount(idx, weights=L.ravel().astype(float), minlength=n) / cnt
    fc = np.bincount(idx, weights=(pix_class.ravel() == classes["copper"]), minlength=n) / cnt
    fg = np.bincount(idx, weights=(pix_class.ravel() == classes["green"]), minlength=n) / cnt
    mat = np.where(fg >= 0.5, GREEN_M, np.where(fc >= 0.5, COPPER_M,
                                                 np.where(meanL < 32, DARK, METAL)))
    # merge same-material neighbours with no groove on their shared boundary
    a, b, blen, bsum = _pairs(seg, bh.astype(float))
    groove = bsum / blen
    ok = (mat[a] == mat[b]) & (np.abs(meanL[a] - meanL[b]) < dl_merge) & (groove < groove_bh)
    uf = UF(n)
    for p, q in zip(a[ok], b[ok]):
        uf.union(p, q)
    root = np.array([uf.find(i) for i in range(n)])
    reg = _relabel(root[seg])
    m = reg.max() + 1
    idx = reg.ravel()
    cnt = np.bincount(idx, minlength=m).astype(float)
    # material of merged regions: area-weighted majority of superpixel materials
    sp_mat_px = mat[seg].ravel()
    votes = np.stack([np.bincount(idx, weights=(sp_mat_px == k), minlength=m) for k in range(4)])
    rmat = votes.argmax(0)
    meanL = np.bincount(idx, weights=L.ravel().astype(float), minlength=m) / cnt
    return reg, rmat, meanL


def absorb_thin(reg, rlab, mm_px, dark, keep=(), prefer=(), max_width_mm=0.5, max_ratio=0.5):
    """Thin regions (bevel highlights, reflections) take the label of the non-dark neighbour
    they share the longest boundary with, if that neighbour is clearly larger. A bevel belongs
    to the inlay it frames, so neighbours labelled in prefer count triple. Thin regions that
    border only dark (free-standing lines) and labels in keep are left alone."""
    m = reg.max() + 1
    edge = np.zeros(reg.shape, bool)
    edge[:, 1:] |= reg[:, 1:] != reg[:, :-1]
    edge[:, :-1] |= reg[:, 1:] != reg[:, :-1]
    edge[1:, :] |= reg[1:, :] != reg[:-1, :]
    edge[:-1, :] |= reg[1:, :] != reg[:-1, :]
    d = cv2.distanceTransform((~edge).astype(np.uint8), cv2.DIST_L2, 5)
    width = np.zeros(m)
    np.maximum.at(width, reg.ravel(), d.ravel())
    width = 2 * width + 1
    area = np.bincount(reg.ravel(), minlength=m)
    a, b, blen, _ = _pairs(reg)
    best_len = np.zeros(m)
    best_nb = np.full(m, -1)
    for x, y, l in zip(np.r_[a, b], np.r_[b, a], np.r_[blen, blen]):
        w = l * (3 if rlab[y] in prefer and rlab[x] not in prefer else 1)
        if rlab[y] != dark and w > best_len[x]:
            best_len[x], best_nb[x] = w, y
    new = rlab.copy()
    thin = (width < max_width_mm * mm_px) & (rlab != dark) & ~np.isin(rlab, keep)
    for r in np.nonzero(thin)[0]:
        nb = best_nb[r]
        if nb >= 0 and area[nb] * max_ratio > area[r]:
            new[r] = rlab[nb]
    return new
