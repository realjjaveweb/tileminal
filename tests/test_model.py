from typing import Any

import pytest

from tileminal.files import HOME
from tileminal.model import Node, node_panes, node_ratio, pane_name, renew_ids, validate_node, validate_tab


def terminal(directory: str, uuid: str = 'id') -> Node:
    return {'type': 'Terminal', 'uuid': uuid, 'directory': directory}


def split(orientation: int, child1: Node, child2: Node, ratio: float = 0.5) -> Node:
    return {'type': 'Paned', 'orientation': orientation, 'ratio': ratio, 'child1': child1, 'child2': child2}


LAYOUT = split(0, terminal('/a', 'a'), split(1, terminal('/b', 'b'), terminal('/c', 'c')))


def test_validate_counts_terminals() -> None:
    assert validate_node(LAYOUT) == 3


def test_validate_accepts_percentages() -> None:
    node = {'type': 'Paned', 'orientation': 1, 'position': 60, 'child1': terminal('/a'), 'child2': terminal('/b')}
    assert validate_node(node) == 2


@pytest.mark.parametrize(
    'node',
    [
        None,
        {'type': 'Window'},
        {'type': 'Terminal', 'directory': 42},
        split(2, terminal('/a'), terminal('/b')),
        {'type': 'Paned', 'orientation': 0, 'child1': terminal('/a')},
    ],
)
def test_validate_rejects_broken_nodes(node: Any) -> None:
    with pytest.raises(ValueError):
        validate_node(node)


def test_validate_rejects_endless_nesting() -> None:
    node = terminal('/a')
    for _ in range(100):
        node = split(0, node, terminal('/b'))
    with pytest.raises(ValueError):
        validate_node(node)


def test_tab_must_be_a_session_object() -> None:
    assert validate_tab({'type': 'Session', 'child': LAYOUT}) == 3
    with pytest.raises(ValueError):
        validate_tab(LAYOUT)


def test_panes_in_reading_order() -> None:
    assert [pane['directory'] for pane in node_panes(LAYOUT)] == ['/a', '/b', '/c']


@pytest.mark.parametrize(
    ('node', 'ratio'),
    [({'ratio': 0.3}, 0.3), ({'position': 70}, 0.7), ({}, 0.5), ({'ratio': 2}, 0.95), ({'ratio': -1}, 0.05)],
)
def test_ratio(node: Node, ratio: float) -> None:
    assert node_ratio(node) == ratio


@pytest.mark.parametrize(
    ('node', 'name'),
    [
        (terminal('/srv/www/api/'), 'api'),
        (terminal(HOME), '~'),
        (terminal('/'), '/'),
        ({**terminal('/srv'), 'title': 'Server'}, 'Server'),
    ],
)
def test_pane_name(node: Node, name: str) -> None:
    assert pane_name(node) == name


def test_renew_ids() -> None:
    layout = split(0, terminal('/a', 'same'), terminal('/b', 'same'))
    renew_ids(layout)
    ids = {pane['uuid'] for pane in node_panes(layout)}
    assert len(ids) == 2
    assert 'same' not in ids
