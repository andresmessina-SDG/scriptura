"""pane_content.py — per-mode content strategies for BiblePane.

The already-separate reader modes (imagery, catena, archaeology,
interlinear) each render into their own content-stack child and answer the
same handful of questions the pane's render path asks: which stack child to
show, how to render the current position, how to react to a verse broadcast
from a partnered pane, and how to apply the reading font size. The pane used
to branch on `_is_<mode>` flags at each of those sites.

Each mode is now a `PaneContent` bound to the registry key
`content.type_key()` returns, so the pane resolves one object and calls it
instead of re-deriving the mode at every site. Each strategy holds a
back-reference to the owning pane (the Step-1 collaborator pattern): the
render bodies read the pane's position state and drive the pane's reader
verbatim, so behaviour is unchanged by the move.

Genbook and the Bible/devotional core still render into the shared text
view and stay inline in the pane (STRUCTURAL_ANALYSIS.md Step 2, 8c).
"""


class PaneContent:
    """One pane content mode that renders into its own content-stack child."""

    #: Name of the content-stack child this mode renders into.
    stack_child = 'text'

    def __init__(self, pane) -> None:
        self._pane = pane

    def render(self) -> None:
        """Render the current book/chapter/verse position."""
        raise NotImplementedError

    def on_verse(self, verse_num: int) -> None:
        """React to a verse broadcast from a partnered pane. The card views
        follow the broadcast verse; the default records it and re-renders."""
        self._pane._selected_verse = verse_num
        self.render()

    def apply_font_size(self, pt: int) -> None:
        """Match the pane's reading font size. Default: nothing to scale."""


class ImageryContent(PaneContent):
    stack_child = 'imagery'

    def render(self) -> None:
        p = self._pane
        p._imagery.render_for(p._book, p._chapter, p._selected_verse or 1)


class CatenaContent(PaneContent):
    stack_child = 'catena'

    def render(self) -> None:
        p = self._pane
        p._catena.render_for(p._book, p._chapter, p._selected_verse or 1)

    def apply_font_size(self, pt: int) -> None:
        self._pane._catena.apply_font_size(pt)


class InterlinearContent(PaneContent):
    stack_child = 'interlinear'

    def render(self) -> None:
        p = self._pane
        p._interlinear.render_for(
            p._module, p._book, p._chapter, p._selected_verse or 1)

    def on_verse(self, verse_num: int) -> None:
        # Lighter than a full re-render: just move the selection highlight.
        p = self._pane
        p._selected_verse = verse_num
        p._interlinear.select_verse(verse_num)


class ArchaeologyContent(PaneContent):
    stack_child = 'archaeology'

    def render(self) -> None:
        self._pane._archaeology.render()

    def on_verse(self, verse_num: int) -> None:
        return  # standalone document — not verse-keyed

    def apply_font_size(self, pt: int) -> None:
        self._pane._archaeology.apply_font_size(pt)


def build(pane) -> dict:
    """The registry-keyed content strategies for a pane, one per already-
    separate reader mode. Keyed to match `content.type_key()`."""
    return {
        'imagery': ImageryContent(pane),
        'catena': CatenaContent(pane),
        'archaeology': ArchaeologyContent(pane),
        'interlinear': InterlinearContent(pane),
    }
