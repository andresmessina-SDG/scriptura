"""The decoration registry: what paints, where, and when.

These guard the declaration rather than the drawing — the pixels are
verified by the scroll matrix and by eye. What can go wrong here silently
is ordering (a cue disappearing under the band it should sit over) and the
enable flags (a mark painting when the reader never asked for it).
"""
import reading_view as rv


class _View:
    """Just enough view for the registry's callables."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def get_color(self):
        return 'text-colour'


def _by_name(name):
    return next(d for d in rv._DECORATIONS if d.name == name)


def test_paint_order_is_bottom_up():
    # A search hit on a highlighted verse, and a flash on either, must stay
    # visible — so each of these paints over the one before it.
    order = [d.name for d in rv._DECORATIONS]
    assert order.index('verse highlights') < order.index('search match')
    assert order.index('search match') < order.index('search match (current)')
    assert order.index('search match (current)') < order.index(
        'navigation flash')


def test_every_decoration_declares_a_known_layer_and_style():
    styles = {'highlights', 'band', 'underline', 'dotted', 'rule', 'veil'}
    for dec in rv._DECORATIONS:
        assert dec.layer in (rv._BELOW, rv._ABOVE), dec.name
        assert dec.style in styles, dec.name
        # Only the highlight family has no single tag: it is a tag family.
        assert (dec.tag is None) == (dec.style == 'highlights'), dec.name


def test_the_veil_is_the_only_thing_painted_over_the_text():
    above = [d.name for d in rv._DECORATIONS if d.layer == rv._ABOVE]
    assert above == ['focus veil']


def test_rule_and_veil_share_the_unit_tag():
    # They are independent settings over one tag, so either can run alone.
    assert _by_name('sense-unit rule').tag == '_cur_unit'
    assert _by_name('focus veil').tag == '_cur_unit'


def test_the_unit_tag_wakes_the_paint_pass():
    """Regression: the sense-unit rule drew nothing on a clean chapter.

    The paint pass returns early unless some decoration's tag exists, and
    every other tag is created on demand — a pane that has not yet searched,
    flashed a verse or drawn an annotation has none of them. `_cur_unit` was
    left out of that check, so the rule was invisible exactly when nothing
    else was marked. Measured on a clean chapter: 0 rule pixels, 70 after.
    """
    below = [d for d in rv._DECORATIONS if d.layer == rv._BELOW]
    assert '_cur_unit' in [d.tag for d in below]


def test_unit_rule_is_off_unless_asked_for():
    rule = _by_name('sense-unit rule')
    assert not rule.on(_View())                      # never set
    assert not rule.on(_View(_show_unit_rule=False))
    assert rule.on(_View(_show_unit_rule=True))


def test_veil_is_off_at_zero_dim():
    veil = _by_name('focus veil')
    assert not veil.on(_View())                 # never set
    assert not veil.on(_View(_focus_dim=0.0))   # the default: off
    assert veil.on(_View(_focus_dim=0.55))


def test_veil_colour_carries_the_dim_as_alpha():
    colour = rv._veil_colour(_View(_focus_paper='#ffffff', _focus_dim=0.55))
    assert colour is not None
    assert abs(colour.alpha - 0.55) < 1e-6


def test_veil_colour_refuses_an_unparseable_paper():
    assert rv._veil_colour(
        _View(_focus_paper='not-a-colour', _focus_dim=0.55)) is None


def test_decorations_with_a_fixed_colour_resolve_without_a_display():
    for name in ('search match', 'search match (current)',
                 'navigation flash'):
        dec = _by_name(name)
        assert isinstance(dec.colour(rv.BibleTextView), str)
