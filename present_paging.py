"""Pure pagination + step-index math for presentation mode.

No GTK and no pixel measurement: the view hands over a per-item weight list and
a capacity, this groups the items into ordered pages; a Stepper tracks which
page is current. Keeping the math pure is what lets the stepping logic be
unit-tested headlessly (mirrors onboarding's injected-callback split).
"""
from __future__ import annotations


def paginate(weights: list[int], capacity: int) -> list[tuple[int, int]]:
    """Group consecutive items into pages by index.

    Each returned ``(start, end)`` is a half-open slice into the items. A page's
    summed weight stays within ``capacity``; the sole exception is a single item
    heavier than ``capacity``, which still takes its own page (a verse is the
    atomic unit — never split, never dropped). ``capacity <= 0`` puts every item
    on its own page, which is how "verse-at-a-time" granularity is expressed.
    """
    n = len(weights)
    if n == 0:
        return []
    if capacity <= 0:
        return [(i, i + 1) for i in range(n)]

    pages: list[tuple[int, int]] = []
    start = 0
    running = 0
    for i, w in enumerate(weights):
        if i == start:
            # The first item of a page always joins it, even over capacity.
            running = w
            continue
        if running + w > capacity:
            pages.append((start, i))
            start = i
            running = w
        else:
            running += w
    pages.append((start, n))
    return pages


def tighten_capacity(capacity: int, viewport: int, natural: int) -> int | None:
    """A smaller budget so a page that measured `natural` px tall fits within
    `viewport` px. Returns None when it already fits (or the inputs are
    unusable), so the caller only re-pages on a real overflow. Proportional with
    a safety margin; the view calls this repeatedly and it converges because it
    only ever shrinks."""
    if capacity <= 0 or viewport <= 0 or natural <= viewport:
        return None
    return max(1, int(capacity * viewport / natural * 0.90))


class Stepper:
    """Tracks the current page over a known page count. Clamped, never wrapped —
    a presenter stepping past either end simply stays on the end page."""

    def __init__(self) -> None:
        self._count = 0
        self._index = 0

    @property
    def index(self) -> int:
        return self._index

    @property
    def count(self) -> int:
        return self._count

    @property
    def at_start(self) -> bool:
        return self._index <= 0

    @property
    def at_end(self) -> bool:
        return self._index >= self._count - 1

    def set_count(self, count: int) -> None:
        """Update the page count, keeping the current index in range. A
        re-paginate (font/size change) can shrink the page count under the
        cursor; clamping keeps the presenter on a valid page instead of blank."""
        self._count = max(0, count)
        self._index = min(self._index, max(0, self._count - 1))

    def _go(self, target: int) -> bool:
        target = max(0, min(target, max(0, self._count - 1)))
        if target == self._index:
            return False
        self._index = target
        return True

    def go_to(self, index: int) -> bool:
        """Jump to a page by index (clamped). Used to re-anchor after a
        re-paginate keeps the presenter on the verse they were reading."""
        return self._go(index)

    def next(self) -> bool:
        return self._go(self._index + 1)

    def prev(self) -> bool:
        return self._go(self._index - 1)

    def home(self) -> bool:
        return self._go(0)

    def end(self) -> bool:
        return self._go(self._count - 1)
