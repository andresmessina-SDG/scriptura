"""The genealogy table, its geometry and its plates.

No display required: `genealogy_bridge`, `genealogy_layout` and
`genealogy_svg` import no GTK, which is the reason they are separate from
`genealogy_reader` at all. The reader's own widget — the Cairo paint, the
Pango measurement and the hit list — is covered in test_genealogy_reader.py,
which draws every chart onto an image surface.

The assertions here are mostly about honesty rather than pixels — that a
telescoped edge stays telescoped, that a name is not an identity, that a
number never appears without the tradition it was computed under.
"""

import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import genealogy_bridge as gb          # noqa: E402
import genealogy_layout as gl          # noqa: E402
import genealogy_svg as gsvg           # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── the table ──────────────────────────────────────────────────────────────

def test_every_edge_cites_a_parsable_verse():
    """The rule the whole design rests on. An uncited edge is an assertion."""
    for e in gb.document()['edges']:
        assert e['ref']['book'], e
        assert e['ref']['chapter'] > 0, e
        assert e['ref']['verse'] > 0, e


def test_every_edge_joins_two_known_people():
    people = gb.document()['people']
    for e in gb.document()['edges']:
        assert e['parent'] in people, e
        assert e['child'] in people, e
        if e['mother']:
            assert e['mother'] in people, e


def test_telescoped_edges_say_how_many_and_who_names_them():
    """"Three generations omitted" with no cross-citation tells a reader
    something is missing and gives them nowhere to look."""
    found = 0
    for e in gb.document()['edges']:
        if e['kind'] != 'descends':
            continue
        found += 1
        assert e['omits'] > 0, e
        assert gb.parse_ref(e['cross']) is not None, e
    assert found >= 2, 'Matthew telescopes at least twice; the table lost one'


def test_matthew_omits_the_three_kings_chronicles_names():
    """Matt 1:8 runs Joram to Uzziah; 1 Chr 3:11-12 puts three kings between
    them. A chart that drew this as an ordinary begetting would teach
    something false."""
    edges = gb.chain('abraham', 'jesus', 'Matthew')
    step = [e for e in edges
            if e['parent'] == 'joram' and e['child'] == 'uzziah']
    assert len(step) == 1
    assert step[0]['kind'] == 'descends'
    assert step[0]['omits'] == 3
    assert step[0]['cross'].startswith('1 Chronicles 3')
    # And the men themselves are in the table, so a reader who looks one up is
    # told who does name him.
    for pid in ('ahaziah', 'joash', 'amaziah'):
        assert pid in gb.document()['people']


def test_a_name_is_not_an_identity():
    """Matthew names two different men Jacob — the patriarch in 1:2 and
    Joseph's father in 1:15. Folding them together closed the chain into a
    loop and lost the end of the genealogy; that is what this guards."""
    hits = gb.resolve('Jacob', 'Matthew', 1, 15)
    assert len(hits) >= 2, 'both Jacobs should be offered, never one silently'
    assert set(hits) >= {'jacob', 'jacob_f'}
    chain = gb.chain('abraham', 'jesus', 'Matthew')
    assert chain, 'the Matthew chain must reach Jesus'
    assert chain[-1]['child'] == 'jesus'


def test_one_person_many_surface_forms():
    """Ruth 4 says Pharez, Matthew says Phares, and they are one man. The id
    is the key; the surface string never is."""
    assert gb.resolve('Pharez')[0] == gb.resolve('Phares')[0] == 'perez'
    assert gb.resolve('Booz')[0] == gb.resolve('Boaz')[0] == 'boaz'


def test_surface_lookup_ignores_case_and_accents():
    """Spanish writes JUDÁ, and a split accent already cost this app 826
    occurrences of that exact word once."""
    assert gb.resolve('JUDAH') == gb.resolve('judah') == gb.resolve('Judah')


def test_matthew_and_luke_agree_at_exactly_the_shared_names():
    """They touch at Abraham through David, at Shealtiel and Zerubbabel, and
    at Jesus — and nowhere else. An earlier build reported that they disagreed
    about the father of Phares, because Luke's "Juda" had been given an id of
    its own."""
    mt = [e['parent'] for e in gb.chain('abraham', 'jesus', 'Matthew')]
    lk = [e['parent'] for e in gb.chain('god', 'jesus', 'Luke')]
    shared = [p for p in mt if p in set(lk)]
    assert 'judah' in shared
    assert 'david' in shared
    assert 'shealtiel' in shared and 'zerubbabel' in shared
    # Solomon is Matthew's route and Nathan is Luke's; neither may be shared.
    assert 'solomon' not in shared
    assert 'nathan' not in shared


def test_lukes_extra_cainan_is_a_different_man():
    """Luke names a Cainan between Arphaxad and Sala that the Hebrew of
    Genesis 11 does not. Folding him into the Cainan of Genesis 5 would erase
    the one place Luke visibly follows a different text."""
    assert 'cainan_lk' in gb.document()['people']
    assert gb.resolve('Cainan', 'Luke', 3, 36)[0] == 'cainan_lk'


def test_matthews_last_step_is_not_a_begetting():
    """Matt 1:16 stops saying "begat". Jesus is born of Mary; Joseph is her
    husband. A chain that rendered these as two more fathers would be putting
    words in the evangelist's mouth."""
    chain = gb.chain('abraham', 'jesus', 'Matthew')
    kinds = [e['kind'] for e in chain[-2:]]
    assert kinds == ['husband', 'born_of']


def test_lukes_last_step_is_a_claim_not_a_link():
    chain = gb.chain('god', 'jesus', 'Luke')
    assert chain[0]['kind'] == 'of_god'
    assert chain[-1]['kind'] == 'supposed'


def test_matthew_counts_fourteen_fourteen_and_thirteen():
    """Matthew asserts three sets of fourteen (1:17) and writes thirteen in
    the third. The chart prints what is there and flags the shortfall; it must
    never renumber to make the claim come out."""
    chain = gb.chain('abraham', 'jesus', 'Matthew')
    counts = [n for _marker, n in gl.register_sets('abraham', chain)]
    assert counts == [14, 14, 13]


def test_the_four_women_hang_on_the_right_children():
    """Matthew attaches each woman to the child, not the father: "Salmon begat
    Booz of Rachab" makes Rahab Boaz's mother. Getting this wrong on David
    rather than Solomon is a mistake this project has already made once."""
    mothers = {e['child']: e['mother']
               for e in gb.chain('abraham', 'jesus', 'Matthew') if e['mother']}
    assert mothers == {'perez': 'tamar', 'boaz': 'rahab',
                       'obed': 'ruth', 'solomon': 'bathsheba'}
    assert 'david' not in mothers


# ── the lifespans ──────────────────────────────────────────────────────────

def test_lifespans_only_ship_for_a_tradition_we_have_the_text_for():
    """No year on screen without its source named. The Septuagint and
    Samaritan figures differ genuinely, and the app carries neither text, so
    they are offered greyed rather than filled in from memory."""
    trads = dict((k, have) for k, _label, have in gb.traditions())
    assert trads['mt'] is True
    assert trads['lxx'] is False
    assert trads['sam'] is False
    assert gb.lifespans('lxx') == []


def test_methuselah_dies_in_the_flood_year():
    """Arithmetic on Genesis 5:3-32 and 7:6, not a chronology from anywhere
    else. If the table is edited and this stops being true, the table is
    wrong — this is the fact the whole lifespan chart exists to show."""
    rows = gb.lifespans('mt')
    born, acc = {}, 0
    for ls in rows:
        born[ls['person']] = acc
        acc += ls['begat']
    death = {ls['person']: born[ls['person']] + ls['total'] for ls in rows}
    flood = born['noah'] + 600
    assert flood == 1656
    assert death['methuselah'] == flood


def test_adam_is_alive_when_lamech_is_born():
    """The other thing no list can show."""
    rows = gb.lifespans('mt')
    born, acc = {}, 0
    for ls in rows:
        born[ls['person']] = acc
        acc += ls['begat']
    adam = next(ls for ls in rows if ls['person'] == 'adam')
    assert born['lamech'] < born['adam'] + adam['total']


# ── markers ────────────────────────────────────────────────────────────────

def test_a_genealogy_chapter_gets_one_marker_not_fifteen():
    """A mark per verse in Matthew 1 marks every line on the page, which marks
    nothing. Dense chapters get one way in."""
    assert len(gb.verses_with_people('Matthew', 1)) > 10
    assert len(gb.marker_verses('Matthew', 1)) == 1
    assert len(gb.marker_verses('Genesis', 5)) == 1


def test_a_sparse_chapter_keeps_its_per_verse_markers(monkeypatch):
    """Where the reference is rare the marker is a cue, exactly like the
    artifact marker — so the thinning must be a threshold, not a blanket.

    Driven directly rather than by finding an example: every chapter the
    curated table currently touches IS a genealogy chapter, so real data
    exercises only one side of the rule. When the table grows to cover a
    narrative chapter that names two or three people, this is the behaviour it
    will get."""
    monkeypatch.setattr(gb, 'verses_with_people',
                        lambda book, chapter: {4, 11})
    assert gb.marker_verses('Genesis', 22) == {4, 11}
    monkeypatch.setattr(gb, 'verses_with_people',
                        lambda book, chapter: {1, 2, 3, 4})
    assert gb.marker_verses('Genesis', 22) == {1}


def test_no_markers_where_the_table_is_silent():
    assert gb.verses_with_people('John', 1) == set()
    assert gb.marker_verses('John', 1) == set()


# ── the peek fragment ──────────────────────────────────────────────────────

def test_fragment_answers_parents_and_children():
    frag = gb.fragment_for('Booz', 'Matthew', 1, 5)
    assert frag is not None
    assert [p[0] for p in frag['parents']] == ['salmon']
    assert [c[0] for c in frag['children']] == ['obed']
    assert frag['mother'] == ('rahab', 'Rachab')


def test_fragment_gathers_citations_onto_one_row():
    """Boaz is Salmon's son in three books. Three rows saying "Salmon" would
    fill the peek with the same answer three times, and the peek has 140-320px
    of body to work with."""
    frag = gb.fragment_for('Boaz', 'Ruth', 4, 21)
    assert len(frag['parents']) == 1
    refs = frag['parents'][0][2]
    assert refs.count('·') == 2
    # The book being read leads.
    assert refs.startswith('Ruth 4:21')


def test_fragment_offers_the_chart_for_the_book_being_read():
    assert gb.fragment_for('Booz', 'Matthew', 1, 5)['chart'] == 'matthew'
    assert gb.fragment_for('Boaz', 'Ruth', 4, 21)['chart'] == 'ruth'


def test_fragment_never_silently_picks_a_jacob():
    frag = gb.fragment_for('Jacob', 'Matthew', 1, 15)
    assert frag['ambiguous'], 'the other Jacob must be offered'


def test_chart_offered_is_one_the_person_appears_on():
    """Judah is cited from Genesis and so is the Adam-to-Noah chain, but Judah
    is not on it. Matching by book alone sent the reader to a chart their
    person was not in."""
    for pid in ('judah', 'adam', 'boaz', 'jesus'):
        cid = gb.chart_containing(pid)
        assert cid, pid
        assert pid in gb.chart_people(cid), (pid, cid)


def test_unknown_word_gets_no_fragment():
    assert gb.fragment_for('notwithstanding', 'Matthew', 1, 5) is None


# ── geometry ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize('cid', [c['id'] for c in gb.charts()])
def test_every_chart_draws_something(cid):
    plate = gl.build(cid, gl.estimate, 760)
    assert plate.height > 0
    assert plate.prims
    assert plate.alt, 'a drawn chart with no text equivalent is invisible'


@pytest.mark.parametrize('cid', [c['id'] for c in gb.charts()])
def test_nothing_runs_off_its_plate(cid):
    """The bug this app has shipped twice: a translated string in a fixed
    container overflows. Measured, not eyeballed."""
    plate = gl.build(cid, gl.estimate, 760)
    for p in plate.prims:
        if p.kind == 'text':
            w = gl.estimate(p.text, p.size, p.weight)
            x0 = (p.x if p.anchor == 'start' else
                  p.x - w / 2 if p.anchor == 'middle' else p.x - w)
            assert x0 >= -1, (cid, p.text)
            assert x0 + w <= plate.width + 1, (cid, p.text, x0 + w)


def test_a_short_chain_is_never_folded_away():
    """Genesis 5 is ten plain begettings, and a rule that only asked "is this
    run plain?" folded the whole chart into one row reading "9 generations,
    collapsed"."""
    assert gl._collapsible(gb.chain('adam', 'noah', 'Genesis')) == []
    plate = gl.build('gen5', gl.estimate, 760)
    names = {p.text for p in plate.prims if p.kind == 'text'}
    assert 'Methuselah' in names
    assert 'Adam' in names and 'Noah' in names


def test_a_long_chain_folds_in_chunks_not_one_swallow():
    """Luke's sixty-seven begettings folded into a single row once, and the
    chart lost its entire middle."""
    runs = gl._collapsible(gb.chain('god', 'jesus', 'Luke'))
    assert len(runs) > 3
    assert all(stop - start <= gl.COLLAPSE_MAX_RUN for start, stop in runs)


def test_opening_a_fold_makes_the_chart_taller():
    closed = gl.build('luke', gl.estimate, 760)
    opened = gl.build('luke', gl.estimate, 760, expanded={0})
    assert opened.height > closed.height


def test_wider_names_widen_the_layout_not_overflow_it():
    """The measure function is injected precisely so a longer language does
    not silently overrun. Feed it a measurer that says everything is twice as
    wide and nothing may leave the plate."""
    wide = lambda t, s, w='normal': gl.estimate(t, s, w) * 2      # noqa: E731
    for c in gb.charts():
        plate = gl.build(c['id'], wide, 760)
        for p in plate.prims:
            if p.kind == 'text' and p.anchor == 'start':
                assert p.x + wide(p.text, p.size, p.weight) <= plate.width + 1, \
                    (c['id'], p.text)


def _boxes(plate, measure):
    """What each drawable covers, the way the widget paints it: a layout's
    top edge sits at `y - size`, and a chip is its own rectangle."""
    out = []
    for p in plate.prims:
        if p.kind == 'text' and p.text.strip():
            w = measure(p.text, p.size, p.weight)
            x = (p.x if p.anchor == 'start' else
                 p.x - w / 2 if p.anchor == 'middle' else p.x - w)
            out.append((x, p.y - p.size, w, p.size * 1.2, p.text))
        elif p.kind == 'chip':
            out.append((p.x, p.y, p.w, p.h, p.text))
    return out


@pytest.mark.parametrize('cid', [c['id'] for c in gb.charts()])
def test_no_chip_is_drawn_over_a_name(cid):
    """His narrow screenshots, made into a check.

    A chip is placed from the right edge and a name from the left, and nothing
    reflows between them: squeeze the plate and the verse lands on the person.
    It shipped in Spanish and Russian at 700px and cleared the English by six
    pixels, which is [[i18n-width-traps]] once more — so this measures with a
    measurer wider than any real face rather than trusting one language's
    metrics."""
    wide = lambda t, s, w='normal': gl.estimate(t, s, w) * 1.6   # noqa: E731
    for width in (560.0, 700.0, 1040.0):
        boxes = _boxes(gl.build(cid, wide, width), wide)
        chips = [b for b in boxes if b[3] == gl.CHIP_H]
        for c in chips:
            mid = c[1] + c[3] / 2
            for b in boxes:
                # Only what shares the chip's line: this is the column rule,
                # and a caption on the line below is a separate question the
                # build audit measures in ink.
                if b is c or abs(b[1] + b[3] / 2 - mid) > 6:
                    continue
                assert min(c[0] + c[2], b[0] + b[2]) - max(c[0], b[0]) <= 0.5, \
                    (cid, width, c[4], 'over', b[4])


def test_a_chart_takes_the_width_it_needs():
    """A chart is allowed to refuse a pane. Its columns are fixed, so the
    honest answer to a narrow pane is a wider plate painted down — not a
    squeezed one with the chip on top of the name."""
    wide = lambda t, s, w='normal': gl.estimate(t, s, w) * 1.6   # noqa: E731
    assert gl.build('matthew', wide, 500.0).width > 500.0
    # And it does not inflate a plate past what the chart can use. The verse
    # chips are placed from the right edge and the names from the left, so a
    # pane wider than the chart used to pull them apart: Genesis 5 put its
    # citation 615px from the name it belongs to at 1040px.
    capped = gl.build('gen5', wide, 1040.0).width
    assert capped < 1040.0
    assert gl.build('gen5', wide, 2000.0).width == capped


def test_the_register_rail_reserves_room_for_its_widest_label():
    """The reservation was one specimen count string; the band labels beside
    it are wider — «От переселения до Христа» by thirty pixels, and even the
    English by eight — so the rail printed into the verse chips."""
    wide = lambda t, s, w='normal': gl.estimate(t, s, w) * 1.6   # noqa: E731
    plate = gl.build('matthew', wide, 900.0)
    labels = {gl._(lab) for lab in gl.REGISTER_LABELS}
    rail = [p for p in plate.prims if p.kind == 'text' and p.text in labels]
    assert rail, 'the register rail did not draw'
    chips = [p for p in plate.prims if p.kind == 'chip']
    assert chips
    left_edge = min(p.x - wide(p.text, p.size, p.weight) for p in rail)
    assert max(c.x + c.w for c in chips) <= left_edge


def test_the_covenant_thread_is_gold_on_every_structure():
    """The thread is what makes the charts one system rather than several
    drawings; it must not be a per-chart decision."""
    for cid in ('gen5', 'matthew', 'gen5_lives', 'house_jacob'):
        plate = gl.build(cid, gl.estimate, 760)
        assert any(p.role == 'thread' for p in plate.prims), cid


def test_lifespan_plate_names_its_tradition():
    plate = gl.build('gen5_lives', gl.estimate, 760)
    labels = {p.text for p in plate.prims if p.kind == 'chip'}
    assert 'Masoretic Text' in labels
    assert 'Reckoned under the Masoretic Text.' in plate.alt


def test_hit_regions_cover_the_verse_chips():
    plate = gl.build('gen5', gl.estimate, 760)
    verse_hits = [h for h in plate.hits if h.kind == 'verse']
    assert verse_hits
    for h in verse_hits:
        assert re.match(r'^.+\|\d+\|\d+$', h.payload), h.payload


# ── the SVG backend ────────────────────────────────────────────────────────

@pytest.mark.parametrize('dark', [False, True])
def test_svg_parses_and_carries_its_text_equivalent(dark):
    from xml.dom import minidom
    plate = gl.build('matthew', gl.estimate, 760)
    svg = gsvg.render(plate, dark=dark)
    doc = minidom.parseString(svg)
    assert doc.getElementsByTagName('title')
    desc = doc.getElementsByTagName('desc')
    assert desc and desc[0].firstChild.data.strip()


def test_svg_uses_no_css_variables():
    """librsvg does not resolve `var()`, and the first version of this backend
    rendered every plate as a black rectangle because of it. The theme is a
    render parameter instead."""
    for dark in (False, True):
        svg = gsvg.render(gl.build('gen5', gl.estimate, 760), dark=dark)
        assert 'var(--' not in svg


def test_light_and_dark_plates_actually_differ():
    plate = gl.build('gen5', gl.estimate, 760)
    assert gsvg.render(plate, dark=False) != gsvg.render(plate, dark=True)


# ── the tools ──────────────────────────────────────────────────────────────

def test_the_build_audit_is_clean():
    """`tools/gen_genealogy.py` is the atlas's build-time guarantee applied to
    this table. A clean run is the contract."""
    r = subprocess.run([sys.executable,
                        os.path.join(_ROOT, 'tools', 'gen_genealogy.py'),
                        '--check'],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_generated_strings_are_in_sync_with_the_table():
    """xgettext cannot read TOML, so the msgids are mirrored into
    genealogy_strings.py. A curator who adds a person and forgets to
    regenerate should get a red test now, not an untranslatable name later."""
    r = subprocess.run([sys.executable,
                        os.path.join(_ROOT, 'tools',
                                     'gen_genealogy_strings.py'), '--check'],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_every_translatable_field_reaches_the_pot_file():
    """Spot-check the bridge and the mirror agree on what a msgid looks like:
    a person name is extracted WITH its context, because several of these are
    also book names."""
    import genealogy_strings
    src = open(genealogy_strings.__file__, encoding='utf-8').read()
    assert "C_('person', 'Ruth')" in src
    assert "C_('person', 'Judah')" in src
    # ...and the plain fields without one.
    assert "N_('The Book of Generations')" in src


def test_person_names_are_translated_through_a_context():
    """`Ruth` the woman and `Ruth` the book are one word in English and need
    not be in every language."""
    assert gb.person_name('ruth') == 'Ruth'
    assert gb.person_name('judah') == 'Judah'


def test_module_registers_with_the_content_registry():
    import content
    assert content.type_key(gb.MODULE_KEY) == 'genealogy'
    assert gb.MODULE_KEY in content.readable_module_names()


def test_module_info_is_complete():
    info = gb.info()
    for key in ('description', 'type', 'license', 'about'):
        assert info.get(key), key


def test_no_chart_cites_a_book_it_is_not_drawn_from():
    """A chart's whole claim is that every line cites the passage in front of
    you. The last row has no next edge and looked for any verse where the
    person begets — which put "Matthew 1:2" on the final row of a Genesis 11
    chart and "Matthew 1:6" on the final row of Ruth 4."""
    for c in gb.charts():
        if c['structure'] not in ('spine',):
            continue
        book = gb.passage_book(c['passage'])
        plate = gl.build(c['id'], gl.estimate, 760)
        # The `omit` chips are the cross-citations on a telescoped edge, and
        # pointing at another book is their entire job — "three generations
        # omitted here; 1 Chronicles 3:11-12 names them". Only the row chips,
        # which say where this line is written, have to stay in the passage.
        foreign = [p.text for p in plate.prims
                   if p.kind == 'chip' and p.text and p.role == 'link'
                   and not p.text.startswith(gb.book_label(book))]
        assert not foreign, f'{c["id"]} draws from {book} and cites {foreign}'


def test_the_display_name_router_knows_this_module():
    """`sword_bridge.display_name` is a chain of `is_x_module` branches, and a
    feature that forgets to add one shows its raw key in the pane header —
    which is what "BookOfGenerations" was doing above a document titled The
    Book of Generations."""
    import sword_bridge

    for name in gb.module_names():
        assert sword_bridge.display_name(name) == gb.display_name()
        assert sword_bridge.display_name(name) != name


# ── What is drawn on top of what ────────────────────────────────────────────
# Two defects the checks above could not see, because one only compared
# chips against names and the other only asked whether text stayed inside
# the plate. Both shipped.

@pytest.mark.parametrize('cid', [c['id'] for c in gb.charts()])
def test_no_rule_is_drawn_through_a_name(cid):
    """A rule painted after the text it crosses is a strike-through.

    The two column rails on the side-by-side chart were appended last and
    drawn as single lines, so they ran through the middle of every label
    centred on their column — `Jech|onias`, `Ne|ri`, `Mar|y`, `Jos|eph`,
    «Иехо|ния» — in both themes and all three languages. Paint order is the
    test: the lifespan chart's axis gridlines also cross three labels, but
    they are drawn first and the text is on top of them.
    """
    wide = lambda t, s, w='normal': gl.estimate(t, s, w) * 1.6   # noqa: E731
    for width in (560.0, 700.0, 1040.0):
        prims = gl.build(cid, wide, width).prims
        rules = [(n, p) for n, p in enumerate(prims)
                 if p.kind == 'line' and abs(p.x2 - p.x) < 0.5]
        for n, p in enumerate(prims):
            if p.kind != 'text' or not p.text.strip():
                continue
            w = wide(p.text, p.size, p.weight)
            x0 = (p.x if p.anchor == 'start' else
                  p.x - w / 2 if p.anchor == 'middle' else p.x - w)
            for rn, r in rules:
                if rn < n:          # painted under the word: the word wins
                    continue
                lo, hi = min(r.y, r.y2), max(r.y, r.y2)
                across = min(hi, p.y) - max(lo, p.y - p.size)
                assert not (x0 + 2 < r.x < x0 + w - 2 and across > 0), \
                    (cid, width, 'rule through', p.text)


@pytest.mark.parametrize('cid', [c['id'] for c in gb.charts()])
def test_a_collapsed_run_never_cuts_a_name_in_half(cid):
    """`Naasso…`, `Cosa…`, `N…`, «Авраа…», `Josafa…` — two thirds of the
    previews, in every language and at every width. A trimmed name cannot be
    told from a misspelt one, and on these charts that is the distinction
    that matters most."""
    wide = lambda t, s, w='normal': gl.estimate(t, s, w) * 1.6   # noqa: E731
    for width in (560.0, 700.0, 900.0, 1040.0):
        for p in gl.build(cid, wide, width).prims:
            if (p.kind == 'text' and p.text.endswith('…')
                    and gl.NAME_SEP in p.text):
                assert p.text.endswith(gl.NAME_SEP + '…'), \
                    (cid, width, p.text)
