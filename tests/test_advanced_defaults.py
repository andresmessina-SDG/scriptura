"""The reading toggles ship off unless they earn a place.

They live in two places since the menu was split: the type switches on the
menu's Appearance page (appearance_page.py `_build_type_switches`) and the Reading
aids page of Preferences (preferences.py `_reading_aids_page`). One rule
covers both.

Five ship on — section headings, small caps, the coloured drop cap, hover
preview, spoken readings. Every other toggle ships off, including ones not
written yet: a new switch that defaults on quietly enlarges what a first-time
reader is handed, which is the decision this test exists to force back into
the open.

The toggle list is READ OUT OF the source rather than restated here, so adding
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


def _keys_in(module: str, function: str, helper: str) -> set[str]:
    tree = ast.parse((REPO_ROOT / module).read_text(encoding='utf-8'))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == function)
    keys: set[str] = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and ast.unparse(node.func) == helper
                and len(node.args) >= 2):
            key = node.args[1]
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
    return keys


def _advanced_toggle_keys() -> set[str]:
    """Every settings key wired to a reading switch: `_adv_switch(label, key,
    setter)` on the Appearance page and `_switch(title, key, on_change)` on
    the Reading aids page."""
    return (_keys_in('appearance_page.py', '_build_type_switches', '_adv_switch')
            | _keys_in('preferences.py', '_reading_aids_page', '_switch'))


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
