"""The Creeds page: its layout helper, and the widget driven without a screen.

The widgets are built and driven, never presented; a display is still needed
to build them (see test_genealogy_reader.py for why that is a skip, not a
failure).
"""
import pytest
from gi.repository import Gdk, GLib, Gtk

Gtk.init_check()
if Gdk.Display.get_default() is None:
    pytest.skip('needs a display: building real GTK widgets without one '
                'segfaults rather than failing',
                allow_module_level=True)

import creeds
import creeds_view as cv
import settings


def _pump(n=20):
    ctx = GLib.MainContext.default()
    for _ in range(n):
        while ctx.pending():
            ctx.iteration(False)


def test_spread_keeps_order_gap_and_bounds():
    items = [{'y': y} for y in (100, 101, 102, 103, 400, 5)]
    cv.spread(items, 24, 0, 500)
    ys = [it['py'] for it in items]
    assert ys == sorted(ys)
    assert all(b - a >= 24 - 1e-9 for a, b in zip(ys, ys[1:]))
    assert ys[0] >= 0 and ys[-1] <= 500
    # A crowded run is centred on its true places.
    run = [it for it in items if 100 <= it['y'] <= 103]
    mean_py = sum(it['py'] for it in run) / 4
    assert abs(mean_py - 101.5) < 1


def test_spread_stays_inside_when_crowded_at_the_foot():
    items = [{'y': 498} for _ in range(5)]
    cv.spread(items, 24, 0, 500)
    assert max(it['py'] for it in items) <= 500


def test_ref_label_keeps_the_verse():
    link = {'ref': '1 Corinthians 15:3-4', 'book': '1 Corinthians'}
    assert cv.ref_label(link).endswith('15:3-4')


@pytest.fixture
def page():
    settings.put('creeds_tab', 'apostles')
    settings.put('creeds_text', 'en')
    pg = cv.CreedsPage(None)
    pg.render()
    _pump()
    return pg


def test_the_page_opens_on_the_apostles_creed(page):
    assert page.current_creed() == 'apostles'
    assert len(page._rows) == len(creeds.phrases('apostles'))


def test_picking_a_line_and_putting_it_down(page):
    page.select_line('5a')
    assert page._sel == '5a'
    assert {link['ref'] for _p, link in page._active()} >= {'Ephesians 4:9'}
    page.select_line('5a')
    assert page._sel is None and not page._active()


def test_picking_a_book_lights_its_lines(page):
    page.select_book('John')
    lines = {p['id'] for p, _l in page._active()}
    assert '12a' in lines and '2b' in lines
    assert page._sel is None


def test_show_line_turns_to_the_creed(page):
    page.show_line('nicene', '7c')
    _pump()
    assert page.current_creed() == 'nicene'
    assert page._sel == '7c'
    assert settings.get('creeds_tab') == 'nicene'


def test_up_and_down_walk_the_lines(page):
    page.select_line('1a')
    page._on_key(None, Gdk.KEY_Down, 0, 0)
    assert page._sel == '1b'
    page._on_key(None, Gdk.KEY_Up, 0, 0)
    assert page._sel == '1a'


def test_escape_puts_the_line_down(page):
    page.select_line('2b')
    assert page._on_escape(None, Gdk.KEY_Escape, 0, 0)
    assert page._sel is None


def test_the_original_text_marks_every_form_of_a_chosen_word(page):
    page.show_line('athanasian', '3')
    page._text_orig.set_active(True)
    _pump()
    markup = page._texts['3'].get_label()
    # "Trinitate" and "Trinitatem" both, and "catholica".
    assert markup.count('underline="single"') == 3
    assert settings.get('creeds_text') == 'orig'


def test_the_disputed_mark_covers_only_the_disputed_words(page):
    page.show_line('athanasian', '23')
    _pump()
    markup = page._texts['23'].get_label()
    assert 'underline="error"' in markup
    assert '>and of the Son</span>' in markup


def test_the_lines_follow_the_reading_size(page):
    """A widget's own CSS provider styles that widget only, so a size loaded
    on the page never reached its lines. Each line carries it now, and a
    line built after the size changes (another creed) carries it too."""
    from gi.repository import Pango

    def size(label):   # in px: GTK sets the font in pixels, 30pt is 40px
        return label.get_pango_context().get_font_description().get_size()

    page.apply_font_size(30)
    _pump()
    text = next(iter(page._texts.values()))
    assert size(text) == 40 * Pango.SCALE
    page.show_line('nicene', '1a')
    _pump()
    assert size(next(iter(page._texts.values()))) == 40 * Pango.SCALE


def test_the_strip_stays_put_while_the_lines_scroll(page):
    """The strip was once as tall as the creed, so a line near the top sent
    its New Testament threads off the foot of the pane. It sits beside the
    scroller now, never in it."""
    assert page._lines.is_ancestor(page._scroll)
    assert not page._strip.is_ancestor(page._scroll)
    assert not page._labels.is_ancestor(page._scroll)
