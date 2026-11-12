"""A part with no text of its own reads as its contents page: each
sub-entry's title, with what it holds or the summary the book prints."""
import genbook_reader as gr
import sword_bridge

ENTRIES = [
    ('/Book III', 'Book III', 0),
    ('/Book III/Chapter I', 'Chapter I', 1),
    ('/Book III/Chapter II', 'Chapter II', 1),
    ('/Volume_2', 'Volume 2', 0),
    ('/Volume_2/The_Third_Treatise', 'The_Third_Treatise', 1),
    ('/Volume_2/The_Third_Treatise/One', 'One', 2),
    ('/Volume_2/The_Third_Treatise/Two', 'Two', 2),
    ('/Volume_2/Epistle', 'Epistle', 1),
]


def test_owens_chapters_carry_the_summary_he_printed(monkeypatch):
    bodies = {
        '/Book III/Chapter I': '<p>Arguments against the universality of '
                               'redemption &mdash; the two first.</p><p>Body.</p>',
        '/Book III/Chapter II': '<p>Containing three other arguments.</p><p>Body.</p>'}
    monkeypatch.setattr(sword_bridge, 'load_genbook_entry', lambda m, p: bodies[p])
    contents = gr._contents_of('CWPDeathOfDeath', ENTRIES, '/Book III')
    assert contents == [
        ('/Book III/Chapter I', 'Chapter I', 0,
         'Arguments against the universality of redemption — the two first.'),
        ('/Book III/Chapter II', 'Chapter II', 0,
         'Containing three other arguments.')]


def test_other_books_get_no_invented_summary_and_parts_say_what_they_hold(monkeypatch):
    monkeypatch.setattr(sword_bridge, 'load_genbook_entry',
                        lambda m, p: '<p>The first paragraph of prose.</p>')
    contents = gr._contents_of('CWPDomesticalDuties', ENTRIES, '/Volume_2')
    assert contents == [
        ('/Volume_2/The_Third_Treatise', 'The Third Treatise', 2, ''),
        ('/Volume_2/Epistle', 'Epistle', 0, '')]


def test_an_unknown_part_has_no_contents():
    assert gr._contents_of('X', ENTRIES, '/Nowhere') == []
