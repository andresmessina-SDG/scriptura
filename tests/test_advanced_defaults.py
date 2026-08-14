"""The Appearance ▸ Advanced toggles ship off unless they earn a place.

Five ship on — section headings, small caps, the coloured drop cap, hover
preview, spoken readings. Every other toggle ships off, including ones not
written yet: a new switch that defaults on quietly enlarges what a first-time
reader is handed, which is the decision this test exists to force back into
the open.

The toggle list is READ OUT OF window.py rather than restated here, so adding
a row is enough to bring it under the rule.
"""

import ast
import pathlib

import pytest

import settings

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The only Advanced toggles that ship on.
DEFAULT_ON = {
    'show_headings',
    'smallcaps_divine',
    'colored_dropcap',
    'hover_preview',
    'show_audio',
}


def _advanced_toggle_keys() -> set[str]:
    """Every settings key wired to a switch in `_build_advanced_toggles`.

    Two sources, because two rows are hand-rolled: the `_adv_switch(label,
    key, setter)` helper, and a bare `settings.put(key, ...)` inside the
    handlers of the rows that span more than one pane (evening paper, spoken
    readings) and so cannot use the helper."""
    tree = ast.parse((REPO_ROOT / 'window.py').read_text(encoding='utf-8'))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == '_build_advanced_toggles')
    keys: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        name = ast.unparse(node.func)
        if name == '_adv_switch' and len(node.args) >= 2:
            key = node.args[1]
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
        elif name == 'settings.put' and node.args:
            key = node.args[0]
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
    return keys


def _defaults() -> dict:
    return next(v for v in vars(settings).values()
                if isinstance(v, dict) and 'show_headings' in v)


def test_the_toggle_list_was_actually_found():
    """Guards the reader above: a walk that silently matched nothing would
    make every test below pass while checking no toggle at all."""
    keys = _advanced_toggle_keys()
    assert len(keys) >= 10, f'only found {sorted(keys)}'
    assert DEFAULT_ON <= keys, f'missing: {sorted(DEFAULT_ON - keys)}'


@pytest.mark.parametrize('key', sorted(_advanced_toggle_keys()))
def test_only_the_named_five_ship_on(key):
    defaults = _defaults()
    assert key in defaults, f'{key} has no default'
    assert bool(defaults[key]) is (key in DEFAULT_ON), (
        f'{key} defaults to {defaults[key]!r}. Advanced toggles ship off '
        f'unless they are one of {sorted(DEFAULT_ON)} — if this one has '
        f'earned a place, add it there in the same commit.')
