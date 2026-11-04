"""Squarified treemap layout (Bruls, Huizing, van Wijk 2000). Pure and deterministic."""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence


def squarify(values: Sequence[Decimal | float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Rectangles for values (sorted descending by the caller), same order as input."""
    vals = [float(v) for v in values]
    total = sum(vals)
    if total <= 0 or w <= 0 or h <= 0:
        return [(x, y, 0.0, 0.0) for _ in vals]
    scale = w * h / total
    areas = [v * scale for v in vals]
    out: list[tuple[float, float, float, float]] = []
    i = 0
    while i < len(areas):
        side = min(w, h)
        row = [areas[i]]
        j = i + 1

        def worst(r):
            s = sum(r)
            return max(max(side * side * a / (s * s), (s * s) / (side * side * a)) for a in r if a > 0) if s else 0

        while j < len(areas) and worst(row + [areas[j]]) <= worst(row):
            row.append(areas[j])
            j += 1
        s = sum(row)
        if w >= h:
            cw = s / h if h else 0
            off = y
            for a in row:
                ch = a / cw if cw else 0
                out.append((x, off, cw, ch))
                off += ch
            x, w = x + cw, w - cw
        else:
            rh = s / w if w else 0
            off = x
            for a in row:
                rw = a / rh if rh else 0
                out.append((off, y, rw, rh))
                off += rw
            y, h = y + rh, h - rh
        i = j
    return out
