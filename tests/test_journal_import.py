"""Reading files in as entries.

Export always went out and nothing came in. One file is one entry; the body
is the file. The only guesses are the title and the date, and both are made
from what a file already tells you rather than from what it says.
"""
import journal_import


def test_a_leading_heading_becomes_the_title():
    """And is taken OFF the body — our own export writes the title as a
    heading, so a Scriptura export read back would otherwise repeat it."""
    got = journal_import.read('# On Genesis 1\n\nThe light.\n', 'x.md')
    assert got['title'] == 'On Genesis 1'
    assert got['body'] == 'The light.'


def test_front_matter_wins_over_the_heading():
    text = ('---\ntitle: A day in Romans\ndate: 2026-03-04\n'
            'tags: grace, law\n---\n# Something else\n\nBody.\n')
    got = journal_import.read(text, 'x.md')
    assert got['title'] == 'A day in Romans'
    assert got['date'] == '2026-03-04'
    assert got['tags'] == ['grace', 'law']
    # The heading was not the title, so it stays where the writer put it.
    assert got['body'].startswith('# Something else')


def test_the_file_name_is_the_title_of_last_resort():
    got = journal_import.read('Just prose.\n', '/tmp/on-the-sabbath.md')
    assert got['title'] == 'on the sabbath'


def test_a_dated_file_name_gives_the_date_and_not_the_title():
    got = journal_import.read('Prose.\n', '2026-09-11-on-genesis.md')
    assert got['date'] == '2026-09-11'
    assert got['title'] == 'on genesis'


def test_the_modification_time_is_the_date_of_last_resort():
    got = journal_import.read('Prose.\n', 'x.md', 1757606400.0)
    assert got['date'] == '2025-09-11'


def test_an_ambiguous_date_is_refused_rather_than_guessed():
    """09/11/2026 means one day in the United States and another everywhere
    else. Falling back to the file's own time is defensible; picking is not."""
    text = '---\ndate: 09/11/2026\n---\nProse.\n'
    got = journal_import.read(text, 'x.md', 1757606400.0)
    assert got['date'] == '2025-09-11'


def test_an_empty_file_is_not_an_entry():
    assert journal_import.read('   \n', '') is None


def test_tags_come_in_with_or_without_hashes():
    text = '---\ntags: #prayer; faith\n---\nProse.\n'
    assert journal_import.read(text, 'x.md')['tags'] == ['prayer', 'faith']


def test_nothing_is_anchored_on_the_way_in():
    """A body full of references could be filed into the canon
    automatically. §6.9: an entry must not claim a passage its writer did
    not give it — and anchors can be added in the editor now."""
    got = journal_import.read('See John 3:16 and Romans 5.\n', 'x.md')
    assert 'anchors' not in got
