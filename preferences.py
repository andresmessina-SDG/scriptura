"""The Preferences dialog (Ctrl+,): the settings you set once and live with.

The menu holds places and actions; Appearance, beside the page, holds what
you judge by eye on the text. Everything else is here, in three pages:
General (how the app starts, and in what language), Reading aids (what the
page does as you read) and Study data (backup and the daily copies).

Built fresh each time it opens, so every row reads the stored setting
rather than a copy that could have gone stale. The rows call the window's
own handlers; nothing here keeps state of its own.
"""

from gi.repository import Adw, Gtk

import backup
import night_light
import settings
from a11y import set_accessible_label
from i18n import _, ngettext


class _SectionNote:
    """Stands in for the caption label `_refresh_section_rows` toggles: on an
    Adw row the reason a switch cannot act is its subtitle."""

    def __init__(self, row, text):
        self._row = row
        self._text = text

    def set_visible(self, visible):
        self._row.set_subtitle(self._text if visible else '')


def _switch(title, key, on_change):
    row = Adw.SwitchRow(title=title)
    row.set_active(bool(settings.get(key)))

    def changed(r, _p):
        settings.put(key, r.get_active())
        on_change(r.get_active())
    row.connect('notify::active', changed)
    return row


def _group(title=None):
    g = Adw.PreferencesGroup()
    if title:
        g.set_title(title)
    return g


def _general_page(win, dialog):
    page = Adw.PreferencesPage(
        title=_('General'), icon_name='scriptura-emblem-system-symbolic')

    start = _group(_('Starting'))
    # Off restores direct-to-reading at launch; the change applies from the
    # next launch (the current session's page, if any, is already up).
    start.add(_switch(_('Open to Today'), 'open_to_today', lambda _on: None))

    # Church calendar for the Today page's church-year line. Default None —
    # the ecumenical silence; each option is a tradition's historic calendar.
    # The dialog has the width the menu lacked, so the editions are spelled
    # out in the row itself.
    values = [None, 'anglican', 'roman', 'orthodox', 'orthodox_old']
    editions = [_('None'), _('Anglican (BCP)'), _('Roman (traditional)'),
                _('Orthodox (New Calendar)'), _('Orthodox (Old Calendar)')]
    church = Adw.ComboRow(title=_('Church calendar'),
                          model=Gtk.StringList.new(editions))
    cur = settings.get('church_calendar')
    church.set_selected(values.index(cur) if cur in values else 0)
    church.connect('notify::selected',
                   lambda r, _p: win._set_church_calendar(
                       values[r.get_selected()]))
    start.add(church)
    page.add(start)

    lang = _language_row(win, dialog)
    if lang is not None:
        g = _group(_('Language'))
        g.add(lang)
        page.add(g)
    return page


def _language_row(win, dialog):
    """The UI language, for a reader whose desktop is not in the language
    they read the app in. None when this install has only English — a
    picker with one entry is furniture, not a choice.

    It takes effect on the next launch, and says so: every string on screen
    was translated when its widget was built, and a half-translated window
    would be worse than a clear wait. `_on_language_selected` offers the
    relaunch.
    """
    import i18n
    languages = i18n.available_languages()
    if len(languages) < 2:
        return None
    codes = [c for c, _n in languages]
    row = Adw.ComboRow(title=_('Language'),
                       subtitle=_('Applies next time you open Scriptura'),
                       model=Gtk.StringList.new([n for _c, n in languages]))
    # The language in effect, which is the desktop's when nothing has been
    # chosen — see i18n.current_language.
    current = settings.get('ui_language') or i18n.current_language()
    row.set_selected(codes.index(current) if current in codes else 0)
    row.connect('notify::selected',
                lambda r, _p: win._on_language_selected(
                    codes, languages, r, toast_to=dialog))
    return row


def _reading_aids_page(win):
    page = Adw.PreferencesPage(
        title=_('Reading Aids'), icon_name='scriptura-tips-symbolic')

    def per_pane(setter_name):
        def apply(on):
            for pane in (win.pane1, win.pane2):
                getattr(pane, setter_name)(on)
        return apply

    aids = _group()
    # Behaviour, not typography: dwell on a Strong's word peeks its gloss
    # without a click.
    aids.add(_switch(_('Preview words on hover'), 'hover_preview',
                     per_pane('set_hover_preview')))
    # Both read the sense-units a module marks with section headings. Plenty
    # of translations mark none (KJV, ASV, the Russian Synodal), and on those
    # the switches are honestly unavailable rather than silently inert — see
    # the window's _refresh_section_rows, which these join while the dialog
    # is open.
    needs = _('This translation marks no sections')
    notes = []
    for row in (
            _switch(_('Mark the current sense-unit'), 'mark_current_unit',
                    per_pane('set_mark_current_unit')),
            _switch(_('Quiet the rest of the page'), 'focus_current_unit',
                    per_pane('set_focus_current_unit'))):
        aids.add(row)
        notes.append((row, _SectionNote(row, needs)))
    page.add(aids)

    listening = _group()
    # Spoken readings span both panes (the devotional strip, the psalm
    # control) and the Today page (Daily Strength). On by default; off
    # withdraws every audio control at once for readers who want none.
    def audio(on):
        for pane in (win.pane1, win.pane2):
            pane.set_show_audio(on)
        win._sync_today_listen()
    listening.add(_switch(_('Spoken readings'), 'show_audio', audio))
    page.add(listening)

    evening = _group()
    ev = _switch(_('Evening paper (follows Night Light)'), 'evening_paper',
                 lambda on: (win._start_evening_paper() if on
                             else win._stop_evening_paper()))
    # Off until the session says it has Night Light: the monitor stays inert
    # where the interface is missing (KDE, Xfce, a bare WM), and a switch
    # that flips with no effect promises what the desktop cannot do.
    # Insensitive with a reason, not hidden — the reader may run the app on
    # two machines, and a setting that vanishes is its own puzzle. The
    # STORED value is left alone; this gates the control, not the preference.
    ev.set_sensitive(False)
    ev.set_subtitle(_('Checking whether this desktop provides Night Light…'))

    def answered(available):
        ev.set_sensitive(available)
        ev.set_subtitle('' if available else _(
            'This desktop does not provide Night Light, so the paper '
            'has nothing to follow'))
    night_light.probe(answered)
    evening.add(ev)
    page.add(evening)
    return page, notes


def _study_data_page(win):
    page = Adw.PreferencesPage(
        title=_('Study Data'), icon_name='scriptura-document-save-symbolic')
    g = _group()
    g.set_description(_('Notes, highlights, journal entries, sermons, '
                        'bookmarks and plan progress, in one file.'))
    for icon, label, handler in (
            ('scriptura-document-save-symbolic', _('Back Up…'),
             win._on_backup_clicked),
            ('scriptura-document-open-symbolic', _('Restore…'),
             win._on_restore_clicked)):
        row = Adw.ActionRow(title=label)
        row.add_prefix(Gtk.Image.new_from_icon_name(icon))
        row.set_activatable(True)
        row.connect('activated', handler)
        g.add(row)
    # The copies main() makes at launch. Opening their folder is the whole
    # feature: Restore… already reads any of them.
    daily = Adw.ActionRow(
        title=_('Daily Copies'),
        subtitle=ngettext('The last {n} day, kept on this device',
                          'The last {n} days, kept on this device',
                          backup.DAILY_KEEP).format(n=backup.DAILY_KEEP))
    daily.add_prefix(Gtk.Image.new_from_icon_name(
        'scriptura-document-open-recent-symbolic'))
    daily.set_activatable(True)
    daily.connect('activated', win._on_daily_copies_clicked)
    g.add(daily)
    page.add(g)
    return page


def build(win):
    """A new Preferences dialog for `win`. The caller presents it."""
    dialog = Adw.PreferencesDialog()
    dialog.set_title(_('Preferences'))
    set_accessible_label(dialog, _('Preferences'))
    dialog.add(_general_page(win, dialog))
    aids, notes = _reading_aids_page(win)
    dialog.add(aids)
    dialog.add(_study_data_page(win))

    win._section_rows.extend(notes)
    win._refresh_section_rows()

    def closed(_d):
        for n in notes:
            if n in win._section_rows:
                win._section_rows.remove(n)
        if getattr(win, '_prefs_dialog', None) is dialog:
            win._prefs_dialog = None
    dialog.connect('closed', closed)
    return dialog
