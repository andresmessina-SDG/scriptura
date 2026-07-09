"""Word-wrap container for the interlinear surface.

GtkFlowBox is a grid: every child is allocated the column width of the
widest child, which wastes half the surface on whitespace, strands verse
numbers in phantom columns, gives them focusable FlowBoxChild chrome, and
shifts the whole grid horizontally while chunked builds stream in (each
wider arrival re-derives the columns). This container packs children like
words in a paragraph instead: natural widths, line by line, bottom-aligned
within the line. Appending children can only ever add lines below —
nothing already placed moves.

Height-for-width: the line breaking in measure and allocate shares one
helper so the two can never disagree. (Hebrew's RTL variant mirrors x in
that one helper when the TAHOT slice lands.)
"""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GObject

_COL_GAP = 4
_ROW_GAP = 10


class WordFlow(Gtk.Widget):
    """Container of word cells appended in reading order.

    Child sizes are cached Python-side: GTK invalidates a label's measure
    cache after (re)allocation, so a naive layout pass re-runs Pango layout
    on every label of every cell — ~130 ms for the longest chapter, felt as
    resize jank. Word cells never change size except when the view toggles
    a line's visibility, which calls invalidate_sizes()."""

    def __init__(self):
        super().__init__()
        self._sizes = {}       # child -> (natural_w, natural_h)

    def append(self, child):
        child.set_parent(self)

    def remove_all(self):
        self._sizes.clear()
        child = self.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            child.unparent()
            child = nxt

    def invalidate_sizes(self):
        """Call after anything that changes a cell's natural size (the
        view's line-visibility chips)."""
        self._sizes.clear()
        self.queue_resize()

    def _child_size(self, child):
        size = self._sizes.get(child)
        if size is None:
            size = (child.measure(Gtk.Orientation.HORIZONTAL, -1)[1],
                    child.measure(Gtk.Orientation.VERTICAL, -1)[1])
            self._sizes[child] = size
        return size

    def _children(self):
        child = self.get_first_child()
        while child is not None:
            if child.get_visible():
                yield child
            child = child.get_next_sibling()

    def _break_lines(self, width):
        """[(child, x, y, w, h)] placements plus total height for a wrap
        width — the single source of truth for measure AND allocate."""
        placements = []
        x = 0
        y = 0
        line = []          # [(child, x, w, h)] of the current line
        line_h = 0

        def flush():
            nonlocal x, y, line, line_h
            for child, cx, w, h in line:
                # Bottom-align within the line: verse-number labels are
                # shorter than word cells and should sit near the shared
                # bottom edge rather than float at the top.
                placements.append((child, cx, y + (line_h - h), w, h))
            y += line_h + _ROW_GAP
            x = 0
            line = []
            line_h = 0

        for child in self._children():
            w, h = self._child_size(child)
            if line and x + w > width:
                flush()
            line.append((child, x, w, h))
            x += w + _COL_GAP
            line_h = max(line_h, h)
        if line:
            flush()
        total_h = max(0, y - _ROW_GAP) if placements else 0
        return placements, total_h

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            # Minimum = widest single child (any narrower would clip it);
            # natural the same — inside the scroller the viewport hands us
            # its width and our height follows from it.
            widest = 0
            for child in self._children():
                widest = max(widest, self._child_size(child)[0])
            return (widest, widest, -1, -1)
        width = for_size if for_size > 0 else 600
        _placements, total_h = self._break_lines(width)
        return (total_h, total_h, -1, -1)

    def do_size_allocate(self, width, _height, _baseline):
        placements, _total = self._break_lines(width)
        rect = Gdk.Rectangle()
        for child, x, y, w, h in placements:
            rect.x, rect.y, rect.width, rect.height = x, y, w, h
            child.size_allocate(rect, -1)

    def do_dispose(self):
        self.remove_all()
        GObject.Object.do_dispose(self)
