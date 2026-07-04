"""The Flatpak ships exactly the files meson.build installs — a module
missing from py_sources imports fine from the repo (so tests and the
headless harness stay green) and then crashes the installed app at
startup with ModuleNotFoundError. This computes the app's real local
import closure from main.py and pins it against the meson list.
Regression guard for the 2026-07-04 release, which shipped without
backup.py, search_controller.py and search_query.py."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_IMPORT = re.compile(r'^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)',
                     re.MULTILINE)


def _meson_py_sources():
    text = (REPO / 'meson.build').read_text()
    block = text[text.index('py_sources = files('):]
    block = block[:block.index(')')]
    return set(re.findall(r"'([^']+\.py)'", block))


def _local_imports(module_file):
    names = set(_IMPORT.findall((REPO / module_file).read_text()))
    return {f'{n}.py' for n in names if (REPO / f'{n}.py').is_file()}


def test_meson_installs_the_full_import_closure():
    listed = _meson_py_sources()
    closure, frontier = set(), {'main.py'}
    while frontier:
        f = frontier.pop()
        closure.add(f)
        frontier |= _local_imports(f) - closure
    missing = sorted(closure - listed)
    assert not missing, (
        f'imported by the app but not installed by meson.build: {missing}')
