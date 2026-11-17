import pytest

from tileminal.geometry import Direction, Rect, Zone, drop_zone_at, nearest


@pytest.mark.parametrize(
    ('x', 'y', 'zone'),
    [(50, 50, 'center'), (5, 50, 'left'), (95, 50, 'right'), (50, 5, 'top'), (50, 95, 'bottom')],
)
def test_drop_zones(x: int, y: int, zone: Zone) -> None:
    assert drop_zone_at(x, y, 100, 100) == zone


def test_drop_zone_of_a_wide_pane_uses_relative_distance() -> None:
    assert drop_zone_at(100, 5, 1000, 100) == 'top'
    assert drop_zone_at(20, 50, 1000, 100) == 'left'


def test_drop_zone_of_an_empty_pane() -> None:
    assert drop_zone_at(0, 0, 0, 0) in ('left', 'top')


# 1 | 2
#   |---
#   | 3
LEFT = Rect(0, 0, 100, 200)
TOP_RIGHT = Rect(102, 0, 200, 99)
BOTTOM_RIGHT = Rect(102, 101, 200, 200)
PANES = [('left', LEFT), ('top right', TOP_RIGHT), ('bottom right', BOTTOM_RIGHT)]


@pytest.mark.parametrize(
    ('current', 'direction', 'expected'),
    [
        (BOTTOM_RIGHT, 'left', 'left'),
        (BOTTOM_RIGHT, 'up', 'top right'),
        (TOP_RIGHT, 'down', 'bottom right'),
        (TOP_RIGHT, 'left', 'left'),
        (LEFT, 'left', None),
        (BOTTOM_RIGHT, 'down', None),
    ],
)
def test_nearest(current: Rect, direction: Direction, expected: str | None) -> None:
    others = [(name, rect) for name, rect in PANES if rect != current]
    assert nearest(current, others, direction) == expected


def test_nearest_prefers_a_shared_edge() -> None:
    # A pane straight above beats one further up-left that does not touch the current one's edge
    current = Rect(100, 100, 200, 200)
    above = Rect(100, 0, 200, 98)
    diagonal = Rect(0, 50, 98, 99)
    assert nearest(current, [('diagonal', diagonal), ('above', above)], 'up') == 'above'
