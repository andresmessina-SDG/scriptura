"""Reading a plan day as one session.

Opening a plan passage lights it on the page — the rest of the chapter is
quieted under the reader's own paper — and a pill at the foot of the reading
names where the reader is. When the passage's last verse is in view the pill
offers the next step: on into the next chapter of a passage that runs over
one, then the day's next passage, and after the last, to mark the day read.
The pill's close, or any move of the reader's own elsewhere, ends it.

`PlanSession` is the bookkeeping and knows no GTK; `PlanPill` is the pill.
"""
from gi.repository import Gtk, Pango

import reading_plans
from a11y import set_accessible_label
from audio_pill import FootPill
from i18n import _, book_label


class PlanSession:
    """Where a reader is in a plan day: which passage, which chapter of it."""

    def __init__(self, plan_id: str, day: int,
                 passages: list[reading_plans.Passage], index: int = 0):
        self.plan_id = plan_id
        self.day = day
        self.passages = passages
        self.index = index
        self.chapter = passages[index][1]

    @property
    def passage(self) -> reading_plans.Passage:
        return self.passages[self.index]

    def target(self) -> tuple[str, int, int]:
        """(book, chapter, verse) to open; verse 0 is the chapter's top."""
        book, c, v, _c2, _v2 = self.passage
        return book, self.chapter, v if self.chapter == c else 0

    def lit(self) -> tuple[str, int, int, int]:
        """(book, chapter, first, last) of the verses to light in the
        chapter being read; 0 for either end is the chapter's own."""
        book, c, v, c2, v2 = self.passage
        return (book, self.chapter, v if self.chapter == c else 0,
                v2 if self.chapter == c2 else 0)

    def holds(self, book: str, chapter: int) -> bool:
        """Whether a chapter belongs to the passage being read — the reader
        may page on into its next chapter themselves."""
        b, c, _v, c2, _v2 = self.passage
        return book == b and c <= chapter <= c2

    def follow(self, chapter: int) -> None:
        self.chapter = chapter

    def step(self) -> str:
        """What the end of the lit verses leads to: 'continue' into the
        passage's next chapter, the 'next' passage, or 'done'."""
        if self.chapter < self.passage[3]:
            return 'continue'
        return 'next' if self.index + 1 < len(self.passages) else 'done'

    def advance(self) -> None:
        if self.step() == 'continue':
            self.chapter += 1
        else:
            self.index += 1
            self.chapter = self.passage[1]

    def where(self) -> str:
        """The pill's line while reading: 'Day 11 · Mark 3:19–35 · 2 of 4'."""
        text = reading_plans.passage_text(self.passage,
                                          book_label(self.passage[0]))
        if len(self.passages) == 1:
            return _('Day {n} · {passages}').format(n=self.day + 1,
                                                    passages=text)
        return _('Day {n} · {passage} · {i} of {total}').format(
            n=self.day + 1, passage=text, i=self.index + 1,
            total=len(self.passages))

    def offer(self) -> str:
        """The pill's offer once the lit verses' end is in view."""
        step = self.step()
        if step == 'continue':
            return _('Continue: {passage} →').format(
                passage=f'{book_label(self.passage[0])} {self.chapter + 1}')
        if step == 'next':
            # Named by where it opens, as the step goes there.
            book, c, v, _c2, _v2 = self.passages[self.index + 1]
            start = f'{book_label(book)} {c}:{v}' if v else f'{book_label(book)} {c}'
            return _('Next: {passage} →').format(passage=start)
        return _('Mark day {n} read').format(n=self.day + 1)


class PlanPill(FootPill):
    """The session's pill: where the reader is, then the step on, and a close
    that leaves the session for ordinary reading."""

    def __init__(self, on_step, on_close):
        super().__init__()
        self._where = Gtk.Label(xalign=0.0)
        self._where.add_css_class('audio-pill-ref')
        self._where.set_ellipsize(Pango.EllipsizeMode.END)
        self._where.set_margin_start(10)
        self._where.set_margin_end(6)
        self._step = Gtk.Button()
        self._step.set_valign(Gtk.Align.CENTER)
        self._step.add_css_class('flat')
        self._step.add_css_class('audio-pill-switch')
        self._step.set_visible(False)
        self._step.connect('clicked', lambda _b: on_step())
        close = Gtk.Button(icon_name='scriptura-window-close-symbolic')
        close.set_valign(Gtk.Align.CENTER)
        close.add_css_class('flat')
        close.add_css_class('audio-pill-action')
        close.add_css_class('audio-pill-close')
        close.set_tooltip_text(_('Back to ordinary reading'))
        set_accessible_label(close, _('Back to ordinary reading'))
        close.connect('clicked', lambda _b: on_close())
        self.append(self._where)
        self.append(self._step)
        self.append(close)

    def show_where(self, text: str) -> None:
        self._where.set_label(text)
        self._where.set_visible(True)
        self._step.set_visible(False)

    def show_offer(self, text: str) -> None:
        self._step.set_label(text)
        self._step.set_visible(True)
        self._where.set_visible(False)
