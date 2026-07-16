"""Tests for the reading-typography helpers: poetry line milestones
(_poetry_tokens / _resolve_poetry_markup), the divine-name small-caps
transforms, and the quiet section-heading treatment. All pure string
work — no widget tree needed."""

from pane import (_html_to_markup, _normalize_divine, _poetry_tokens,
                  _resolve_poetry_markup, _smallcap_divine_literals)


def _state(open_level=None, at_ls=True):
    return {'open': open_level, 'at_ls': at_ls}


# ── _poetry_tokens: the three milestone dialects ─────────────────────────────

def test_poetry_tokens_level_dialect():
    # ASV/BSB/LEB: <l level="N" sID/> … <l eID level="N"/>
    html = ('<l level="1" sID="gen1"/>text<l eID="gen1" level="1"/> '
            '<l level="2" sID="gen2"/>more<l eID="gen2" level="2"/>')
    out = _poetry_tokens(html)
    assert out == '[[PLS1]]text[[PLE]] [[PLS2]]more[[PLE]]'


def test_poetry_tokens_esv_dialect():
    # ESV: bare sID = level 1, type="x-indent" = the stepped b-line,
    # eID carries type="x-br".
    html = ('<l sID="x1"/>a-line<l eID="x1" type="x-br"/>'
            '<l sID="x2" type="x-indent"/>b-line<l eID="x2" type="x-br"/>')
    out = _poetry_tokens(html)
    assert out == '[[PLS1]]a-line[[PLE]][[PLS2]]b-line[[PLE]]'


def test_poetry_tokens_lg_and_level_clamp():
    html = '<lg sID="g1"/><l level="7" sID="a"/>x<l eID="a"/><lg eID="g1"/>'
    out = _poetry_tokens(html)
    assert out == '[[PLGS]][[PLS3]]x[[PLE]]'


def test_poetry_tokens_leaves_lb_alone():
    assert _poetry_tokens('prose <lb/> more') == 'prose <lb/> more'


def test_poetry_tokens_container_form():
    assert _poetry_tokens('<l level="2">line</l>') == '[[PLS2]]line[[PLE]]'


# ── _resolve_poetry_markup: breaks, levels, carry ────────────────────────────

def test_resolve_simple_couplet():
    st = _state()
    markup, levels = _resolve_poetry_markup(
        '[[PLS1]]He maketh me to lie down[[PLE]][[PLS2]]He leadeth me[[PLE]]', st)
    assert markup == 'He maketh me to lie down\nHe leadeth me\n'
    assert levels == {0: 1, 1: 2}
    assert st['open'] is None and st['at_ls'] is True


def test_resolve_swallows_inter_line_space():
    # ASV emits '<l eID/> <l sID/>' — the stray space must not lead the
    # next line.
    st = _state()
    markup, levels = _resolve_poetry_markup(
        '[[PLS1]]pastures;[[PLE]] [[PLS1]]He leadeth[[PLE]]', st)
    assert markup == 'pastures;\nHe leadeth\n'
    assert levels == {0: 1, 1: 1}


def test_resolve_line_open_across_verses():
    # Verse leaves its last line open; the next verse continues it and
    # closes it mid-text. The continuation line is the next verse's
    # line 0 (the carry), and its own new line follows.
    st = _state()
    m1, l1 = _resolve_poetry_markup('[[PLS1]]The earth is full', st)
    assert m1 == 'The earth is full'
    assert l1 == {0: 1}
    assert st['open'] == 1 and st['at_ls'] is False
    m2, l2 = _resolve_poetry_markup(
        'of thy riches.[[PLE]][[PLS2]]So is the sea[[PLE]]', st)
    assert m2 == 'of thy riches.\nSo is the sea\n'
    assert l2 == {0: 1, 1: 2}


def test_resolve_poem_starts_mid_verse():
    # Prose then a line start mid-verse: the poem must break onto its
    # own line.
    st = _state()
    markup, levels = _resolve_poetry_markup(
        'And Mary said, [[PLS1]]My soul doth magnify[[PLE]]', st)
    assert markup == 'And Mary said, \nMy soul doth magnify\n'
    assert levels == {1: 1}


def test_resolve_prose_verse_keeps_carry_honest():
    st = _state()
    markup, levels = _resolve_poetry_markup('Plain prose verse.', st)
    assert markup == 'Plain prose verse.'
    assert levels == {}
    assert st['at_ls'] is False


def test_resolve_stanza_gap():
    st = _state()
    markup, levels = _resolve_poetry_markup(
        '[[PLS1]]end of stanza[[PLE]][[PLGS]][[PLS1]]new stanza[[PLE]]', st)
    assert markup == 'end of stanza\n\nnew stanza\n'
    assert levels == {0: 1, 2: 1}


def test_resolve_counts_markup_newlines_not_tags():
    # Line indices count real newlines; Pango tags don't shift them.
    st = _state()
    markup, levels = _resolve_poetry_markup(
        '[[PLS1]]<span foreground="#bb0000">red</span> word[[PLE]]'
        '[[PLS2]]next[[PLE]]', st)
    assert levels == {0: 1, 1: 2}


# ── divine-name small caps ───────────────────────────────────────────────────

def test_normalize_divine_allcaps_lowered():
    assert _normalize_divine('LORD') == 'Lord'


def test_normalize_divine_mixed_case_untouched():
    assert _normalize_divine('Lord’s') == 'Lord’s'
    assert _normalize_divine('I am who I am') == 'I am who I am'


def test_divine_markup_transform_on():
    out = _html_to_markup('<divineName>Lord</divineName> is my shepherd',
                          dark=False, divine_smallcaps=True)
    assert out == ('<span variant="small-caps">Lord</span> is my shepherd')


def test_divine_markup_transform_off_strips():
    out = _html_to_markup('<divineName>Lord</divineName> is my shepherd',
                          dark=False)
    assert out == 'Lord is my shepherd'


def test_literal_lord_wrapped():
    out = _smallcap_divine_literals('the LORD is my shepherd')
    assert out == ('the L<span variant="small-caps">ord</span> '
                   'is my shepherd')


def test_literal_inscriptions_untouched():
    for text in ('HOLINESS TO THE LORD.',
                 'TO THE UNKNOWN GOD.',
                 'KING OF KINGS, AND LORD OF LORDS.'):
        assert _smallcap_divine_literals(text) == text


def test_literal_compound_divine_names_transform():
    # "LORD GOD" / "LORD JEHOVAH" are compound names, not inscriptions.
    out = _smallcap_divine_literals('for the LORD GOD is my strength')
    assert 'L<span variant="small-caps">ord</span>' in out
    assert 'G<span variant="small-caps">od</span>' in out


def test_literal_possessive_inside_span():
    out = _smallcap_divine_literals("the LORD'S house")
    assert out == ('the L<span variant="small-caps">ord\'s</span> house')


def test_literal_skips_tag_content():
    markup = '<span foreground="LORD">the LORD</span>'
    out = _smallcap_divine_literals(markup)
    assert out.startswith('<span foreground="LORD">')
    assert 'the L<span variant="small-caps">ord</span>' in out


# ── section headings ─────────────────────────────────────────────────────────

def test_section_title_quiet_treatment():
    out = _html_to_markup('<title>The Beatitudes</title>after', dark=False)
    assert out.startswith('<span size="90%" weight="bold"')
    assert 'The Beatitudes</span>\nafter' in out
