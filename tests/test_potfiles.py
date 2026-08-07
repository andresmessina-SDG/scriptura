"""po/POTFILES.in lists every file whose strings can be translated — and it
is maintained by hand, so it drifts. A module missing from it is invisible
to xgettext: the strings are wrapped in _(), they look translated, they
pass review, and the .pot simply never contains them. Nothing fails. The
first translator to arrive finds part of the app unreachable, and the only
symptom is English in a translated build.

Measured 2026-08-06, before this guard: 9 modules and 103 strings were
missing, 37 of them the whole first-run onboarding.

Same failure as the meson py_sources list (see test_meson_manifest.py) —
a second list of files that must track the code and has no way to say when
it doesn't."""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POTFILES = REPO / 'po' / 'POTFILES.in'


def _listed():
    return [line.strip() for line in POTFILES.read_text().splitlines()
            if line.strip() and not line.startswith('#')]


def _marks_a_literal(path):
    """True if the module calls _() or N_() on a string literal.

    The literal is the point: xgettext extracts what it can read at the
    call site, so `_(name)` — i18n.py looking up a book name marked with
    N_() somewhere else — contributes nothing to the .pot and does not put
    its module on this list."""
    for node in ast.walk(ast.parse(path.read_text())):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ('_', 'N_')
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            return True
    return False


def test_every_module_with_translatable_strings_is_listed():
    listed = set(_listed())
    missing = sorted(p.name for p in REPO.glob('*.py')
                     if _marks_a_literal(p) and p.name not in listed)
    assert not missing, (
        f'these modules mark strings for translation but are not in '
        f'po/POTFILES.in, so xgettext will never see them: {missing}')


def test_no_entry_names_a_file_that_is_gone():
    """A stale entry is the louder half of the same drift: xgettext stops on
    a path it cannot open, so the translation build breaks rather than
    quietly under-collecting."""
    gone = sorted(e for e in _listed() if not (REPO / e).exists())
    assert not gone, f'po/POTFILES.in names files that no longer exist: {gone}'
