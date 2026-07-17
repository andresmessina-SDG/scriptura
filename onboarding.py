"""First-run discoverability: a re-findable Tips & Gestures reference and a
small set of one-shot contextual hints.

The design across GNOME HIG, Apple HIG, and Nielsen Norman's research
converges on one rule: don't front-load a tour. Teach in context, once,
dismissibly, and keep the reference findable. So hints fire the first time
their context actually occurs — never at launch — then never again (recorded
in settings). Scriptura's restraint is the product, so the ceiling of
intrusiveness is a quiet toast: there are no dimming overlays, spotlights, or
pointer coach-marks. Everything a hint can teach is also listed, permanently,
in the Tips & Gestures dialog (the "find it again later" half of the rule).
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw
from collections.abc import Callable

import settings
from i18n import _


def N_(message: str) -> str:
    """No-op gettext marker — tags module-level strings for extraction; the
    actual translation happens at display time via _()."""
    return message


# key → hint message. Each fires at most once (see HintController). Kept to a
# tight set of the highest-value invisible gestures; the full gesture list
# lives in the Tips dialog, so hints only need to seed discovery, not exhaust
# it. All three teach a gesture that leaves no visual trace at rest.
HINTS: dict[str, str] = {
    'first_render':      N_('Tip: tap a verse to open its cross-references.'),
    'first_verse_click': N_('Tip: right-click a verse for highlights, notes, '
                            'and study tools.'),
    'first_lexicon':     N_('Tip: tap any word to open its lexicon entry.'),
}


# Tips & Gestures reference content: (section, [(gesture, result), ...]).
# N_-marked for extraction; translated at display time.
GESTURES: list[tuple[str, list[tuple[str, str]]]] = [
    (N_('Reading'), [
        (N_('Tap a verse'), N_('Show its cross-references')),
        (N_('Right-click a verse'), N_('Highlights, notes, and study tools')),
        (N_('Double-click a word'), N_('Look it up in the dictionary')),
        (N_('Scroll over the chapter title'), N_('Cycle through chapters')),
    ]),
    (N_('Word study'), [
        (N_('Turn on the lexicon, then tap a word'),
         N_('Open its Strong’s lexicon entry')),
    ]),
    (N_('View'), [
        (N_('Hover the אΩ mark in the header'),
         N_('Reading tools bloom out — lexicon, footnotes, cross-references')),
        (N_('Hover the top edge in reading mode'),
         N_('Bring the toolbar back')),
    ]),
    (N_('Presentation'), [
        (N_('Press F5, or open the menu'),
         N_('Present the passage full-screen')),
        (N_('Arrow keys, Space, or the on-screen controls'),
         N_('Step through the passage')),
        (N_('The V key, or the “V” button'),
         N_('Switch to one verse per slide')),
        (N_('The P key, or the Parallel button'),
         N_('Show both open translations side by side')),
        (N_('Ctrl+L while presenting'),
         N_('Jump to any passage')),
        (N_('+ / − keys, or the zoom controls'),
         N_('Make the text larger or smaller')),
    ]),
]


class HintController:
    """Decides whether a one-shot hint should fire, and records that it has.
    Kept free of GTK: it calls an injected `present(message)`, so the
    fire-once logic is unit-testable without a display. `hints_seen` persists
    as a list in settings (JSON has no set); membership is the fire-once
    guard, and `tips_enabled` is the master switch."""

    def __init__(self, present: Callable[[str], None]) -> None:
        self._present = present

    @staticmethod
    def enabled() -> bool:
        return bool(settings.get('tips_enabled'))

    def maybe_fire(self, key: str) -> bool:
        """Show the hint for `key` if hints are enabled and it hasn't been
        shown before. Returns True iff a hint was actually presented. Safe to
        call on every occurrence of a context — the guard collapses repeats."""
        if not self.enabled() or key not in HINTS:
            return False
        seen = settings.get('hints_seen') or []
        if key in seen:
            return False
        settings.put('hints_seen', [*seen, key])
        self._present(_(HINTS[key]))
        return True


def build_tips_dialog(on_shortcuts: Callable[[], None] | None = None) -> Adw.Dialog:
    """The permanent, re-findable reference. A boxed-list dialog (acceptable
    in a utility window per the design language) grouping gesture -> result.
    A master switch controls whether contextual hints keep appearing, and a
    row hands off to the keyboard-shortcuts dialog so the two references sit
    side by side."""
    dialog = Adw.Dialog()
    dialog.set_title(_('Tips & Gestures'))
    dialog.set_content_width(460)

    toolbar_view = Adw.ToolbarView()
    toolbar_view.add_top_bar(Adw.HeaderBar())
    dialog.set_child(toolbar_view)

    page = Adw.PreferencesPage()
    toolbar_view.set_content(page)

    for section, rows in GESTURES:
        group = Adw.PreferencesGroup(title=_(section))
        for gesture, result in rows:
            row = Adw.ActionRow(title=_(gesture), subtitle=_(result))
            row.set_activatable(False)
            group.add(row)
        page.add(group)

    controls = Adw.PreferencesGroup()
    hint_row = Adw.SwitchRow(
        title=_('Show tips as you go'),
        subtitle=_('One-time hints for hidden gestures'))
    hint_row.set_active(bool(settings.get('tips_enabled')))
    hint_row.connect(
        'notify::active',
        lambda r, _p: settings.put('tips_enabled', r.get_active()))
    controls.add(hint_row)

    if on_shortcuts is not None:
        sc_row = Adw.ActionRow(title=_('Keyboard Shortcuts'))
        sc_row.add_suffix(Gtk.Image(icon_name='go-next-symbolic'))
        sc_row.set_activatable(True)
        sc_row.connect('activated', lambda _r: on_shortcuts())
        controls.add(sc_row)
    page.add(controls)

    return dialog
