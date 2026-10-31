"""A popover's arrow stays on its body.

Near a screen edge GTK slides the popover's body onto the screen but leaves
the arrow on the anchor: within 8px of the edge it floats free of the body,
within about 30px it sits on the rounded corner. After GTK places a popover,
the guard points it at the nearest place on the body's straight edge.

Stand-ins only: the geometry is the whole of it. Here the parent sits at the
surface origin, the popover's own surface margin is 24px, and its body is
200x100 at the margin.
"""
import types

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Graphene  # noqa: E402

import gtk_utils  # noqa: E402
from gtk_utils import ARROW_INSET, arrow_target  # noqa: E402


def _rect(x, y, w=1, h=1):
    r = Gdk.Rectangle()
    r.x, r.y, r.width, r.height = x, y, w, h
    return r


def _pop(anchor, body_at):
    """A popover pointing at `anchor` whose body's top-left corner landed at
    `body_at` in the parent's surface."""
    native = types.SimpleNamespace(get_surface_transform=lambda: (0, 0))
    parent = types.SimpleNamespace(
        get_native=lambda: native, get_width=lambda: 1000,
        get_height=lambda: 800,
        compute_point=lambda _n, p: (True, Graphene.Point().init(p.x, p.y)))
    bounds = Graphene.Rect().init(24, 24, 200, 100)
    contents = types.SimpleNamespace(
        get_css_name=lambda: 'contents', get_next_sibling=lambda: None,
        compute_bounds=lambda _p: (True, bounds))
    pop = types.SimpleNamespace(
        get_parent=lambda: parent, get_first_child=lambda: contents,
        get_pointing_to=lambda: (True, anchor),
        get_surface_transform=lambda: (24, 24))
    surface = types.SimpleNamespace(get_position_x=lambda: body_at[0] - 48,
                                    get_position_y=lambda: body_at[1] - 48)
    return pop, surface


def test_an_arrow_off_the_body_moves_onto_its_straight_edge():
    # Anchored 2px from the screen edge; the body was slid to start at 0.
    pop, surface = _pop(_rect(2, 50), (0, 60))
    new = arrow_target(pop, surface)
    assert new.x == ARROW_INSET and new.width == 1
    assert new.y == 50          # still the same distance above the body


def test_the_far_edge_too():
    pop, surface = _pop(_rect(995, 50), (800, 60))
    assert arrow_target(pop, surface).x == 1000 - ARROW_INSET


def test_a_side_arrow_moves_along_the_side():
    # Pointing from the left, 2px from the top of the screen.
    pop, surface = _pop(_rect(50, 2), (60, 0))
    new = arrow_target(pop, surface)
    assert new.y == ARROW_INSET and new.height == 1 and new.x == 50


def test_an_arrow_on_the_straight_edge_is_left_alone():
    pop, surface = _pop(_rect(100, 50), (0, 60))
    assert arrow_target(pop, surface) is None


def test_a_body_too_short_for_the_inset_centres_the_arrow():
    pop, surface = _pop(_rect(2, 50), (0, 60))
    small = Graphene.Rect().init(24, 24, 40, 30)
    pop.get_first_child().compute_bounds = lambda _p: (True, small)
    assert arrow_target(pop, surface).x == 20


def test_the_owner_anchor_comes_back_when_it_closes():
    set_to = []
    pop = types.SimpleNamespace(_arrow_saved=(True, _rect(2, 50)),
                                _arrow_fixes=2,
                                set_pointing_to=set_to.append)
    gtk_utils._restore_pointing(pop)
    assert set_to[0].x == 2 and pop._arrow_fixes == 0
