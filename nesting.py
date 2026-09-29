"""Búsqueda del mejor patrón de repetición para una forma (varias copias de la misma pegatina)."""
import math
import numpy as np
from shapely import affinity
from shapely.prepared import prep
from shapely.geometry import box


def rot(poly, a):
    r = affinity.rotate(poly, a, origin=(0, 0))
    x0, y0, _, _ = r.bounds
    return affinity.translate(r, -x0, -y0)


def ov(a, b):
    return a.intersects(b) and a.intersection(b).area > 1e-3


def min_shift(A, B, dx, dy, lo, hi, tol=0.05):
    if ov(A, affinity.translate(B, hi * dx, hi * dy)):
        return None
    while hi - lo > tol:
        m = (lo + hi) / 2
        if ov(A, affinity.translate(B, m * dx, m * dy)):
            lo = m
        else:
            hi = m
    return hi


def lattices(motif, nmot):
    x0, y0, x1, y1 = motif.bounds
    W, H = x1 - x0, y1 - y0
    ax = min_shift(motif, motif, 1, 0, 0, W + 1)
    row = motif
    for k in (-2, -1, 1, 2):
        row = row.union(affinity.translate(motif, k * ax, 0))
    res = []
    for bx in np.linspace(0, ax, 24, endpoint=False):
        by = min_shift(row, affinity.translate(motif, bx, 0), 0, 1, 0, H + 1)
        res.append((nmot / (ax * by), ax, bx, by))
    res.sort(reverse=True)
    return res[:3]


def build_motifs(Q):
    mots = []
    for a in (0, 90):
        A = rot(Q, a)
        mots.append(([(a, 0.0, 0.0)], A))
        B = rot(Q, a + 180)
        H = A.bounds[3]
        best = None
        for oy in np.linspace(-H * 0.9, H * 0.9, 19):
            ox = min_shift(A, affinity.translate(B, 0, oy), 1, 0, -A.bounds[2], A.bounds[2] + B.bounds[2] + 1)
            if ox is None:
                continue
            U = A.union(affinity.translate(B, ox, oy))
            area = (U.bounds[2] - U.bounds[0]) * (U.bounds[3] - U.bounds[1])
            if best is None or area < best[0]:
                best = (area, ox, oy, U)
        if best:
            _, ox, oy, U = best
            dx, dy = -U.bounds[0], -U.bounds[1]
            mots.append(([(a, dx, dy), (a + 180, ox + dx, oy + dy)], affinity.translate(U, dx, dy)))
    return mots


def fill_sheet(P, Q, motif, ax, bx, by, SW, SH, zona):
    usable = prep(zona)
    rx0, ry0, rx1, ry1 = zona.bounds
    huecos = [g.bounds for g in getattr(box(rx0, ry0, rx1, ry1).difference(zona), 'geoms', [])] or \
             ([box(rx0, ry0, rx1, ry1).difference(zona).bounds] if not box(rx0, ry0, rx1, ry1).difference(zona).is_empty else [])
    pieces = {a: rot(P, a) for a in (0, 90, 180, 270)}
    dims = {a: pieces[a].bounds[2:] for a in pieces}
    g = Q.bounds[2] - P.bounds[2]

    def cabe(a, x, y):
        w, h = dims[a]
        if x < rx0 or y < ry0 or x + w > rx1 or y + h > ry1:
            return False
        if not any(x < hx1 and x + w > hx0 and y < hy1 and y + h > hy0 for hx0, hy0, hx1, hy1 in huecos):
            return True  # rectángulo libre: no hace falta la geometría exacta
        return usable.contains(affinity.translate(pieces[a], x, y))

    best = []
    for ox in np.linspace(0, ax, 6, endpoint=False):
        for oy in np.linspace(0, by, 6, endpoint=False):
            out = []
            for j in range(-3, int(SH / by) + 4):
                for i in range(-int(SW / ax) - 4, int(SW / ax) + 4):
                    X = rx0 - ox + i * ax + j * bx - g
                    Y = ry0 - oy + j * by - g
                    X -= math.floor((j * bx) / ax) * ax
                    for (a, dx, dy) in motif:
                        a %= 360
                        if cabe(a, X + dx + g, Y + dy + g):
                            out.append((a, X + dx + g, Y + dy + g))
            if len(out) > len(best):
                best = out
    return best


def anidar(P, SW, SH, gap, zona):
    """Devuelve la lista de posiciones (angulo, x, y) en mm que más pegatinas mete en la zona."""
    Q = affinity.translate(P.buffer(gap / 2, join_style=2).simplify(0.05), gap / 2, gap / 2)
    best = []
    for motif, M in build_motifs(affinity.translate(Q, -gap / 2, -gap / 2)):
        M0 = affinity.translate(M, -M.bounds[0], -M.bounds[1])
        for _, ax, bx, by in lattices(M0, len(motif)):
            out = fill_sheet(P, Q, motif, ax, bx, by, SW, SH, zona)
            if len(out) > len(best):
                best = out
    return best
