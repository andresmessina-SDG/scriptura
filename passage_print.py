"""Print a passage — a study handout, with the reader's own marks in it.

A thin layout on top of `passage_export`: the same composition the worksheet
uses, set into pages. Nothing here decides what a passage contains; it decides
where the page breaks fall.

The Flatpak gate this feature was held behind is CLEARED (2026-07-26, measured
inside the installed sandbox): `org.freedesktop.portal.Print` is present, its
`version` property answers 4, `Gtk.PrintOperation` constructs, and page setup
resolves. GTK routes printing through that portal under Flatpak, so no
manifest permission is needed and none was added.

The draw path is verified without ever showing a dialog, by running the same
operation in EXPORT mode to a PDF — GTK's own exporter, no PDF dependency.
That exercises pagination and `draw-page` for real. Only the dialog itself
needs a person and a printer, which is Andres's click and not a test's.
"""
from __future__ import annotations

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Pango, PangoCairo

import passage_export
from i18n import _

#: Points. A handout is read at arm's length on paper, not at screen distance.
BODY_PT = 11.0
#: Margin in points — 0.75in, the width a ring binder and a thumb both want.
MARGIN_PT = 54.0
#: The reading serif, so a handout looks like the app it came from.
#: A family LIST, not one family: Pango falls through it per-glyph, and
#: Newsreader carries no Cyrillic — a bare 'Newsreader' sends Russian to
#: whatever fontconfig picks, which here is a SANS face. The chain matches
#: data/style.css so the card and the page set in the same serif.
SERIF = 'Newsreader, Source Serif 4, Charter, Georgia, serif'


class PassagePrinter:
    """Holds the layout between `begin-print` and the last `draw-page`.

    GTK asks how many pages there are before it asks for any of them, and the
    answer depends on how the text sets — so the layout is built once, at the
    page's width, and measured. Keeping it on an object rather than in a
    closure is what lets `draw-page` reuse the same one instead of re-setting
    the text for every page.
    """

    def __init__(self, text: str):
        self._text = text
        self._layout: Pango.Layout | None = None
        #: The y offset, in points, at which each page starts. Recorded from
        #: the layout's own line extents rather than computed.
        self._page_tops: list[float] = [0.0]

    # ── GTK's two questions ──────────────────────────────────────────────
    def begin_print(self, operation, context):
        self._layout = context.create_pango_layout()
        desc = Pango.FontDescription()
        desc.set_family(SERIF)
        desc.set_size(int(BODY_PT * Pango.SCALE))
        self._layout.set_font_description(desc)
        self._layout.set_width(int(context.get_width() * Pango.SCALE))
        self._layout.set_wrap(Pango.WrapMode.WORD)
        self._layout.set_text(self._text, -1)

        # Walk the layout's own lines and note where each page has to start.
        #
        # The obvious version — take the first line's height, divide the page
        # by it, translate by that multiple — is wrong, and the PDF says so:
        # line heights are not uniform (blank lines and wrapped lines differ),
        # so the multiple drifts away from real line boundaries. It sheared
        # the last line of page one in half AND repeated the tail of the verse
        # above it at the top of page two.
        page_height = context.get_height()
        self._page_tops = [0.0]
        walker = self._layout.get_iter()
        while True:
            # (top, BOTTOM) — not (y, height). Reading the second value as a
            # height and adding it to the first doubles every line's foot,
            # which paginates a two-page passage into thirteen pages whose
            # breaks halve toward the end. Measured, after it did exactly
            # that.
            line_top, line_bottom = walker.get_line_yrange()
            if line_bottom / Pango.SCALE - self._page_tops[-1] > page_height:
                # This line does not fit: it begins the next page, whole.
                self._page_tops.append(line_top / Pango.SCALE)
            if not walker.next_line():
                break
        operation.set_n_pages(len(self._page_tops))

    def draw_page(self, _operation, context, page_number):
        if self._layout is None:
            return
        cr = context.get_cairo_context()
        cr.set_source_rgb(0, 0, 0)
        # One layout, drawn through a moving window: shift it up by the pages
        # already printed, and show only this page's band of it.
        #
        # The window closes at the NEXT page's top, not at the page height.
        # A line that begins inside the page but runs past its foot belongs
        # to the next page, and clipping at the full height let its top half
        # draw anyway — the foot of page one carried a sliced row of glyphs.
        page = min(page_number, len(self._page_tops) - 1)
        top = self._page_tops[page]
        band = (self._page_tops[page + 1] - top
                if page + 1 < len(self._page_tops) else context.get_height())
        cr.save()
        cr.rectangle(0, 0, context.get_width(),
                     min(band, context.get_height()))
        cr.clip()
        cr.translate(0, -top)
        PangoCairo.show_layout(cr, self._layout)
        cr.restore()


def build_operation(module: str, book: str, chapter: int,
                    verses: list[int] | None = None, *,
                    notes: bool = True) -> Gtk.PrintOperation:
    """A ready-to-run operation for the passage.

    Separate from running it so the same object can be exported to a PDF in a
    test, which is the only way to exercise pagination without a printer.
    """
    text = passage_export.build(module, book, chapter, verses,
                                notes=notes, markdown=False)
    title = passage_export.format_reference(book, chapter, verses,
                                            version=module)
    printer = PassagePrinter(text)
    operation = Gtk.PrintOperation()
    operation.set_job_name(title)
    operation.set_use_full_page(False)
    operation.set_unit(Gtk.Unit.POINTS)
    setup = Gtk.PageSetup()
    setup.set_top_margin(MARGIN_PT, Gtk.Unit.POINTS)
    setup.set_bottom_margin(MARGIN_PT, Gtk.Unit.POINTS)
    setup.set_left_margin(MARGIN_PT, Gtk.Unit.POINTS)
    setup.set_right_margin(MARGIN_PT, Gtk.Unit.POINTS)
    operation.set_default_page_setup(setup)
    operation.connect('begin-print', printer.begin_print)
    operation.connect('draw-page', printer.draw_page)
    # Kept alive for the operation's lifetime: the handlers are bound methods
    # and GTK holds no reference to the object behind them.
    operation._printer = printer
    return operation


def print_passage(pane, verses, popover=None) -> None:
    """Show the print dialog for the selection. Under Flatpak this is the
    Print portal, which is why no dialog is constructed here by hand."""
    if popover is not None:
        popover.popdown()
    operation = build_operation(pane._module, pane._book, pane._chapter,
                               list(verses))
    try:
        operation.run(Gtk.PrintOperationAction.PRINT_DIALOG, pane.get_root())
    except Exception:
        # A refused portal, no printers, a cancelled job: none of them is a
        # reason to take the app down, and the dialog has already said
        # whatever it had to say.
        if pane._on_toast:
            pane._on_toast(_('Could not print the passage'))
