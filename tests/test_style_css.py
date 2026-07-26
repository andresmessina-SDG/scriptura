"""Two things `data/style.css` may not say, both learned the hard way on the
listening pill (2026-07-25): a large corner radius on a popover's `contents`,
which stops the popover opening at all, and a `min-width` on a progress bar's
`progress` node, which stops the bar telling the truth. Neither shows up in a
behavioural test — the widgets are built, wired and reported exactly right, and
only the rendering is wrong — so they are pinned here, on the stylesheet."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Above this a popover's radius is both pointless to look at and heading for
#: the cliff described in the test below. Ours is 18px.
MAX_POPOVER_RADIUS = 64

_LENGTH = re.compile(r'(\d+(?:\.\d+)?)px')


def _rules():
    """(selector, declarations) for every rule in the stylesheet, one entry
    per selector in a comma-separated list. GTK CSS has no nesting, so a flat
    scan for `… { … }` is the whole grammar."""
    text = re.sub(r'/\*.*?\*/', '', (REPO / 'data' / 'style.css').read_text(),
                  flags=re.DOTALL)
    for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', text):
        for selector in selectors.split(','):
            yield ' '.join(selector.split()), body


def _declaration(body, name):
    for part in body.split(';'):
        prop, _, value = part.partition(':')
        if prop.strip() == name:
            return value.strip()
    return None


def _final_node(selector):
    """The node the rule actually lands on: `.audio-rate-popover > contents`
    styles `contents`, while `.stone-contents button` styles a button."""
    return selector.replace('>', ' ').split()[-1].split(':')[0]


def test_no_popover_contents_carries_a_huge_radius():
    """GTK reserves a popover's declared corner radius inside the surface it
    asks GDK to present: measured on the speed popover, 18px asks for a 118px
    surface, 36px for 152px and 100px for 280px — about twice the radius, on
    top of the sheet. So `border-radius: 9999px`, which is the house idiom for
    a capsule everywhere else in this file, asks for a surface no display can
    give; GDK refuses it, GTK pops the popover straight back down (it emits
    `show`, then `closed`), and the button that owns it does nothing at all
    when clicked. A capsule popover has to name half its own height instead.

    The real cliff is wherever twice the radius leaves the monitor, so this
    ceiling is a sane bound rather than the exact limit."""
    for selector, body in _rules():
        if _final_node(selector) != 'contents':
            continue
        radius = _declaration(body, 'border-radius')
        if radius is None:
            continue
        for length in _LENGTH.findall(radius):
            assert float(length) <= MAX_POPOVER_RADIUS, (
                f'{selector} sets border-radius: {radius} — a popover cannot '
                f'be given a radius this large without failing to open; name '
                f'half the height of its contents box instead')


def test_no_progress_node_carries_a_min_width():
    """That node *is* the fill, so a minimum width on it is not a floor but
    its width: the pill's thread was given `min-width: 24px` along with its
    trough and, on a 90px track, showed 22px filled before a second had played
    and ran ahead of the truth at every fraction after that (0.25 read 39px
    where 22px was true). Whatever a bar needs to keep from vanishing belongs
    on the progressbar or the trough."""
    for selector, body in _rules():
        if _final_node(selector) != 'progress':
            continue
        assert _declaration(body, 'min-width') is None, (
            f'{selector} sets a min-width — the fill must be free to be '
            f'exactly as wide as the fraction it is showing')
