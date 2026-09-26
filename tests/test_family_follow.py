"""Read the difference leading the header and the Bible beside it."""
from types import SimpleNamespace

import window


class _Bible:
    def __init__(self, book, chapter, visible=True):
        self.book, self.chapter = book, chapter
        self._visible = visible
        self.selected = []

    def get_visible(self):
        return self._visible

    def select_verse(self, verse):
        self.selected.append(verse)


def test_read_moves_the_header_and_the_bible_beside_it():
    """Within the chapter on the page only the verse marker moves; to
    another chapter, the header goes there and takes the panes with it."""
    family, bible = _Bible('John', 3), _Bible('John', 3)
    gone = []
    win = SimpleNamespace(pane1=family, pane2=bible,
                          _current_loc=('John', 3),
                          _go_to=lambda *ref: gone.append(ref))
    window.BibleWindow.read_moved(win, family, 'John', 3, 17)
    assert bible.selected == [17] and family.selected == [] and gone == []
    window.BibleWindow.read_moved(win, family, 'John', 4, 1)
    assert gone == [('John', 4, 1)] and bible.selected == [17]
    locked = _Bible('Genesis', 1)           # a pane kept elsewhere
    win.pane2 = locked
    window.BibleWindow.read_moved(win, family, 'John', 3, 18)
    assert locked.selected == []
