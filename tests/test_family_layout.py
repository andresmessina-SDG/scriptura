"""The Family view's geometry: pure numbers, no display needed."""
import bible_family as bf
import family_layout as fl


def test_every_family_bible_has_one_place():
    pos = fl.positions()
    members = bf.family_members()
    assert len(members) == 37
    assert set(pos) == set(members)
    root = set(bf.family_data()['root'])
    laned = [i for lane in fl.lanes() for i in lane.members]
    assert len(laned) == len(set(laned))
    assert set(members) == root | set(laned)


def test_the_membership_rule():
    """Read today or a landmark, plus every Bible they revise or reword.
    A 'drew on' debt does not pull a Bible in (the Confraternity NT)."""
    m = set(bf.family_members())
    assert {'kjv', 'esv', 'niv2011', 'njps', 'wycliffe'} <= m
    assert {'tyndale', 'bishops', 'rv', 'asv', 'rsv'} <= m   # ancestors
    assert 'confraternity' not in m
    assert 'leb' not in m                                     # read by few


def test_lanes_run_from_word_for_word_to_free():
    lanes = fl.lanes()
    xs = [lane.x for lane in lanes]
    assert xs == sorted(xs)
    assert lanes[0].name == 'NASB' and lanes[-1].name == 'The Message'


def test_time_runs_down_and_never_back():
    ys = [fl.year_y(y) for y in range(1611, 2026)]
    assert ys == sorted(ys)
    assert fl.year_y(1611) == fl.AXIS_TOP
    root_y = max(y for _x, y in (tuple(v) for v in
                                 bf.family_data()['root'].values()))
    assert root_y < fl.AXIS_TOP - 52          # the root sits above the rule


def test_no_two_bibles_crowd_each_other():
    pos = list(fl.positions().items())
    for i, (a, (ax, ay)) in enumerate(pos):
        for b, (bx, by) in pos[i + 1:]:
            assert (ax - bx) ** 2 + (ay - by) ** 2 > 18 ** 2, (a, b)


def test_a_same_row_edge_dips_below_its_row():
    """Coverdale to Matthew's: a straight line struck through the label."""
    a, b = (230.0, 190.0), (430.0, 190.0)
    _p0, p1, p2, _p3 = fl.edge_curve(a, b)
    assert p1[1] > 190 + 20 and p2[1] > 190 + 20
    _p0, p1, _p2, _p3 = fl.edge_curve((100.0, 100.0), (100.0, 400.0))
    assert p1 == (100.0, 250.0)


def test_root_labels_run_right_and_late_ones_left_near_the_edge():
    assert not fl.label_left(780, root=True)       # Douay–Rheims
    assert fl.label_left(830)                       # The Message
    assert not fl.label_left(300)


def test_margin_notes_are_in_time_order():
    ys = [n.y for n in fl.notes()]
    assert ys == sorted(ys) and len(ys) == 6
