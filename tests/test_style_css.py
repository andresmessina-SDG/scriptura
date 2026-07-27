"""Three things `data/style.css` may not say, all learned the hard way on the
listening pill: a large corner radius on a popover's `contents`, which stops
the popover opening at all; a `min-width` on a progress bar's `progress` node,
which stops the bar telling the truth (both 2026-07-25); and a child chain
through `buttoncontent`, which matches nothing (2026-07-26). None of them shows
up in a behavioural test — the widgets are built, wired and reported exactly
right, and only the rendering is wrong — so they are pinned here, on the
stylesheet."""

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


def test_nothing_reaches_through_buttoncontent_as_a_child():
    """An Adw.ButtonContent is `buttoncontent > box > image|label`, and the box
    is libadwaita's own. So `> buttoncontent > label` names a node that does not
    exist: it fails silently, exactly as `button.audio-pill-rate` did on the
    GtkMenuButton, and the switch on the pill kept Adwaita's bold label through
    two rounds of reading the CSS. Reach past it with a descendant selector."""
    for selector, _body in _rules():
        assert not re.search(r'buttoncontent\s*>', selector), (
            f'{selector} reaches through buttoncontent with a child combinator '
            f'— there is a box in between, so this matches nothing; write it as '
            f'a descendant')


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


#: Every control below sat under WCAG 2.5.8's 24px floor and was lifted over
#: it by vertical padding alone — the ink never moved. The value recorded is
#: the padding each one needs to clear 24px at the GNOME default UI font,
#: measured on a real widget under a headless compositor. Two sweeps have now
#: had to find these (2026-07-17, 2026-07-27), so they are pinned here.
MIN_VERTICAL_PADDING = {
    'button.chart-bar': 3,
    'button.lex-depth-link': 5,
    'button.interlinear-chip': 4,
    '.tag-chip': 5,
    'button.catena-copy': 4,
    'button.catena-more': 2,
    'button.catena-chip': 3,
    'button.stone-chip': 3,
    'button.genbook-synopsis-toggle': 3,
}


def _vertical_padding(value):
    """The top padding of a `padding:` shorthand, in px."""
    parts = value.split()
    if not parts:
        return None
    lengths = _LENGTH.findall(parts[0])
    return float(lengths[0]) if lengths else None


def test_tight_controls_keep_the_padding_that_clears_24px():
    """These controls all set `min-height: 0` to buy the app's tight visual
    rhythm, which hands the whole hit target to padding and the font. That is
    a deliberate trade, but it means a padding value here is not cosmetic —
    it is the only thing holding the control over the 24px target-size floor
    (WCAG 2.5.8, Level AA, and legally required under the EAA since
    2025-06-28). Shrinking one to tighten the look silently breaks that, and
    nothing on screen says so: the control looks fine and simply becomes
    harder to hit."""
    seen = set()
    for selector, body in _rules():
        want = MIN_VERTICAL_PADDING.get(selector)
        if want is None:
            continue
        padding = _declaration(body, 'padding')
        if padding is None:
            continue
        seen.add(selector)
        got = _vertical_padding(padding)
        assert got is not None and got >= want, (
            f'{selector} sets padding: {padding} — its vertical padding is '
            f'the only thing keeping it over the 24px hit-target floor, and '
            f'it needs at least {want}px')
    missing = set(MIN_VERTICAL_PADDING) - seen
    assert not missing, (
        f'{sorted(missing)} no longer carry a padding declaration — either '
        f'the selector was renamed or the floor is now unguarded')
