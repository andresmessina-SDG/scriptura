"""Tests that keep Tips & Gestures tied to the app it documents.

The Keyboard Shortcuts dialog cannot drift: it reads its accelerators back
from the action map. Nothing registers gestures centrally, so Tips has no such
anchor and it rotted — six of its thirteen rows had become keyboard shortcuts
the shortcuts dialog already stated, while gestures added since went unlisted.

These are the substitute anchor. Pure-Python: the list is data and the
tripwire reads source, so no display is needed.
"""

import ast
import pathlib
import re

import pytest

import onboarding

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Gesture / event-controller construction sites per runtime module. NOT a
#: style rule — a tripwire. When it fails, the app grew or lost a pointer
#: affordance, and the question to answer is whether a reader can find it.
#: Update the number in the same commit that answers it.
#:
#: Most sites are plumbing a reader never thinks about (click-outside-to-close,
#: focus reveals, wheel forwarding) and rightly appear in no list. The ones
#: this list exists to catch are the other kind.
EXPECTED_GESTURE_SITES = {
    'annotation_dialogs.py': 1,
    'archaeology_reader.py': 6,
    'crossref_panel.py': 2,
    # The genealogy charts take a click and a motion controller each. Both
    # are VISIBLE affordances — the cursor becomes a pointer and a tooltip
    # names the target — so they teach themselves and need no Tips row, which
    # is the whole distinction this file's anchor exists to force.
    'genealogy_reader.py': 2,
    'imagery_reader.py': 4,
    'interlinear_view.py': 1,
    'lexicon_panel.py': 1,
    'navigation.py': 1,
    'pane.py': 15,
    'window.py': 10,
}

_GESTURE_CALL = re.compile(
    r'^Gtk\.(Gesture|EventController)\w*(\.new)?$')

#: Key names have no business in a gesture list. Anything matching belongs in
#: the Keyboard Shortcuts dialog instead.
_KEY_MENTION = re.compile(
    r'\b(ctrl|control|shift|alt|super|f\d{1,2}|esc|escape|enter|return|tab|'
    r'space|arrow|backspace|delete|home|end|page ?up|page ?down|keys?)\b',
    re.IGNORECASE)


def _gesture_sites(path: pathlib.Path) -> int:
    """Count constructions of a GTK gesture or event controller in one file.

    Counted from the parse tree rather than by grepping, so a call split
    across lines counts once and a mention inside a comment or docstring
    counts not at all."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return sum(1 for node in ast.walk(tree)
               if isinstance(node, ast.Call)
               and _GESTURE_CALL.match(ast.unparse(node.func)))


def _runtime_modules():
    return sorted(p for p in REPO_ROOT.glob('*.py'))


def _rows():
    for section, rows in onboarding.GESTURES:
        for gesture, result in rows:
            yield section, gesture, result


def test_the_app_has_not_grown_a_gesture_tips_ignores():
    """The anchor. Any change to the app's pointer surface fails here, so
    Tips gets reconsidered instead of quietly falling behind."""
    actual = {p.name: n for p in _runtime_modules()
              if (n := _gesture_sites(p))}
    assert actual == EXPECTED_GESTURE_SITES, (
        'the app\'s gesture surface changed.\n'
        'Decide whether a reader can discover what changed, update '
        'onboarding.GESTURES if not, then correct EXPECTED_GESTURE_SITES '
        'in this file.')


@pytest.mark.parametrize('section,gesture,result', list(_rows()),
                         ids=[g for _s, g, _r in _rows()])
def test_no_row_teaches_a_keystroke(section, gesture, result):
    """Keys live in the Keyboard Shortcuts dialog, which builds itself from
    the action map. A key restated here is a second copy that nothing keeps
    honest — which is exactly how the old Presentation section went stale."""
    for text in (gesture, result):
        assert not _KEY_MENTION.search(text), (
            f'{section!r} row names a key: {text!r}. '
            'Put it in _SHORTCUT_SECTIONS instead.')


def test_no_gesture_is_listed_twice():
    gestures = [g for _s, g, _r in _rows()]
    assert len(gestures) == len(set(gestures))


def test_every_section_has_rows():
    for section, rows in onboarding.GESTURES:
        assert rows, f'{section!r} is empty'


def test_the_presentation_section_is_gone():
    """It held six rows, all of them keyboard shortcuts already stated in the
    shortcuts dialog — nearly half the reference restating another one."""
    assert 'Presentation' not in [s for s, _rows in onboarding.GESTURES]
