"""Where things are on screen: drop zones of a pane and the nearest pane in a direction."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, NamedTuple, TypeVar

Zone = Literal['left', 'right', 'top', 'bottom', 'center']
Direction = Literal['left', 'right', 'up', 'down']
T = TypeVar('T')


class Rect(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int


def drop_zone_at(x: float, y: float, width: float, height: float) -> Zone:
    """The part of a pane a point is over: the nearest edge, or the middle."""
    width, height = max(1.0, width), max(1.0, height)
    dx, dy = x / width - 0.5, y / height - 0.5
    if abs(dx) < 0.2 and abs(dy) < 0.2:
        return 'center'
    if abs(dx) * height > abs(dy) * width:
        return 'left' if dx < 0 else 'right'
    return 'top' if dy < 0 else 'bottom'


def nearest(current: Rect, candidates: Iterable[tuple[T, Rect]], direction: Direction) -> T | None:
    """The candidate next to ``current`` in ``direction``.

    Candidates sharing an edge with ``current`` win over ones that are merely in that direction;
    among those the closest one wins, then the one with the longest shared edge.
    """
    best: T | None = None
    best_score: tuple[bool, int, int] | None = None
    for item, rect in candidates:
        if direction == 'left' and rect.right <= current.left + 2:
            gap, overlap = current.left - rect.right, _overlap(current.top, current.bottom, rect.top, rect.bottom)
        elif direction == 'right' and rect.left >= current.right - 2:
            gap, overlap = rect.left - current.right, _overlap(current.top, current.bottom, rect.top, rect.bottom)
        elif direction == 'up' and rect.bottom <= current.top + 2:
            gap, overlap = current.top - rect.bottom, _overlap(current.left, current.right, rect.left, rect.right)
        elif direction == 'down' and rect.top >= current.bottom - 2:
            gap, overlap = rect.top - current.bottom, _overlap(current.left, current.right, rect.left, rect.right)
        else:
            continue
        score = (overlap <= 0, gap, -overlap)
        if best_score is None or score < best_score:
            best, best_score = item, score
    return best


def _overlap(start1: int, end1: int, start2: int, end2: int) -> int:
    return min(end1, end2) - max(start1, start2)
