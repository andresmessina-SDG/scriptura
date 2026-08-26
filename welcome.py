"""First-run welcome window — shown when no SWORD or eBible modules are
installed yet.

Rather than dropping a newcomer into the Module Manager (a tree of SWORD
"modules" they have no basis to choose between), this offers three curated
bundles framed by *outcome*, not difficulty: a quick reading-only start, a
recommended reading-plus-study kit, and a full library. The middle bundle is
the suggested default. Whatever they pick, reading starts as soon as the
download finishes; everything is addable or removable later from the Module
Manager (the escape hatch below the cards).

Each bundle is a list of install steps dispatched by `kind` to the owning
bridge. Wrong/unavailable module IDs surface as recoverable warnings — the
only hard requirement for handing off to the main window is that at least one
Bible text ends up installed."""

import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango

import sword_bridge
import open_data
import catena_bridge
import ebible_bridge
import onboarding
import settings
import i18n
from a11y import set_accessible_label


def N_(message):
    """No-op gettext marker. Tags strings in module-level data for xgettext
    extraction; the actual translation happens at display time via _()."""
    return message


# Each step is (kind, ident, label, facet):
#   'sword'    → sword_bridge.install_module(ident)
#   'opendata' → open_data.download_source(ident)
#   'catena'   → catena_bridge.download_and_install()   (ident unused)
#   'ebible'   → ebible_bridge.download_translation_sync(ident, entry)
#                where ident is the eBible translationId. Used for texts
#                CrossWire does not carry at all — the World English Bible
#                is on eBible only.
#
# `facet` is what the module IS to a reader, and the card's summary line is
# counted from it rather than written by hand. The hand-written version drifted
# — a card promised four Bibles and installed five — and every new language
# would have been one more summary to keep in step.
_BIBLE = 'bible'
_COMMENTARY = 'commentary'
_DICTIONARY = 'dictionary'
_LEXICON = 'lexicon'
_NOTES = 'notes'
_XREF = 'cross-references'
_TOPICS = 'topics'
#: Installed and useful, but deliberately absent from the summary: the
#: listening pill is per-pane and keyed to its module, so a card that
#: promises audio while opening on two silent texts promises what the
#: reader's first screen cannot deliver.
_AUDIO = 'audio'


# The three shapes a starting library can take. Defined once, in prose that
# stays true whatever a language's catalogue holds: no tier may name a
# commentary or a dictionary here, because whether one exists is a fact about
# the language, and the summary line below says so per card.
_TIERS = (
    {
        'id': 'reading',
        'title': N_('Just reading'),
        'tagline': N_('Open a Bible and start reading right away.'),
        'size': N_('Smallest download'),
        'recommended': False,
    },
    {
        'id': 'study',
        'title': N_('Reading + study'),
        'tagline': N_('A few translations, and the tools for looking '
                      'closely at a word.'),
        'size': N_('Small download'),
        'recommended': True,
    },
    {
        'id': 'full',
        'title': N_('Full library'),
        'tagline': N_('Everything this language has, from the start.'),
        'size': N_('Larger download'),
        'recommended': False,
    },
)


# What fills those shapes, per language. Adding a language is one entry here
# — the tier titles, taglines and summaries are already translated through
# po/, so nothing new has to be written to give a new language three cards.
#
# `opens` is the pair the reading window should start on — (pane 1, pane 2) —
# written to settings once the bundle is installed. This window is the only
# place that knows WHY a module is present, so it says so rather than leaving
# the main window to infer a default from an alphabetical list (which opened
# the same Bible in both panes, and could open a commentary in pane 1).
# A None pane 2 means single-pane: showing one text twice is not a split.
_CATALOGUE = {
    'en': {
        'reading': {
            'opens': ('BSB', None),
            'items': [
                ('sword', 'BSB', 'Berean Standard Bible', _BIBLE),
            ],
        },
        'study': {
            'opens': ('BSB', 'Historical Commentaries'),
            'items': [
                ('sword',    'BSB',           'Berean Standard Bible', _BIBLE),
                ('ebible',   'engwebp',       'World English Bible', _BIBLE),
                ('sword',    'KJVA',          'King James Bible', _BIBLE),
                ('sword',    'ASV',           'American Standard Version', _BIBLE),
                ('catena',   '',              'Historical Commentaries', _COMMENTARY),
                ('sword',    'Easton',        "Easton's Bible Dictionary", _DICTIONARY),
                ('sword',    'StrongsHebrew', "Strong's Hebrew Lexicon", _LEXICON),
                ('sword',    'StrongsGreek',  "Strong's Greek Lexicon", _LEXICON),
                ('opendata', 'dodson',        'Dodson Greek Lexicon', _LEXICON),
                ('sword',    'TSK',           'Treasury of Scripture Knowledge', _XREF),
            ],
        },
        'full': {
            'opens': ('BSB', 'Historical Commentaries'),
            'items': [
                ('sword',    'BSB',           'Berean Standard Bible', _BIBLE),
                ('ebible',   'engwebp',       'World English Bible', _BIBLE),
                ('sword',    'KJVA',          'King James Bible', _BIBLE),
                ('sword',    'ASV',           'American Standard Version', _BIBLE),
                ('sword',    'YLT',           "Young's Literal Translation", _BIBLE),
                ('sword',    'Geneva1599',    'Geneva Bible (1599)', _BIBLE),
                ('sword',    'Webster',       "Webster's Bible", _BIBLE),
                ('catena',   '',              'Historical Commentaries', _COMMENTARY),
                ('sword',    'MHCC',          "Matthew Henry's Concise Commentary", _COMMENTARY),
                ('sword',    'JFB',           'Jamieson-Fausset-Brown Commentary', _COMMENTARY),
                ('sword',    'Easton',        "Easton's Bible Dictionary", _DICTIONARY),
                ('sword',    'StrongsHebrew', "Strong's Hebrew Lexicon", _LEXICON),
                ('sword',    'StrongsGreek',  "Strong's Greek Lexicon", _LEXICON),
                ('opendata', 'dodson',        'Dodson Greek Lexicon', _LEXICON),
                ('opendata', 'cross_references', 'OpenBible Cross-References', _XREF),
                ('opendata', 'topics',        'OpenBible Topics', _TOPICS),
                ('sword',    'TSK',           'Treasury of Scripture Knowledge', _XREF),
            ],
        },
    },
    'es': {
        # Modern Spanish beside the historic text: the Reina Valera is the
        # one carrying Strong's numbers, so word study happens in pane 2.
        'reading': {
            'opens': ('NBLA', None),
            'items': [
                ('sword', 'NBLA', 'Nueva Biblia de las Américas', _BIBLE),
            ],
        },
        'study': {
            'opens': ('NBLA', 'eBible: spaRV1909'),
            'items': [
                ('sword',    'NBLA',          'Nueva Biblia de las Américas', _BIBLE),
                ('ebible',   'spaRV1909',     'Reina Valera 1909', _BIBLE),
                # The one dictionary a Spanish reader can have. Every
                # dictionary CrossWire and its friends distribute is English,
                # French, Russian or Portuguese, so double-clicking a word —
                # one of the three gestures onboarding teaches — did nothing
                # on this bundle's profiles. Scriptura builds this one from
                # the Spanish Wiktionary and serves it from its own release.
                ('sword',    'Wikcionario',   'Wikcionario', _DICTIONARY),
                ('sword',    'StrongsHebrew', "Strong's Hebrew Lexicon", _LEXICON),
                ('sword',    'StrongsGreek',  "Strong's Greek Lexicon", _LEXICON),
                ('opendata', 'cross_references', 'OpenBible Cross-References', _XREF),
            ],
        },
        # No commentary tier: every Spanish commentary that exists is either
        # in copyright or a modern translation carrying its own, so the full
        # card grows by texts and notes instead — and its summary says so
        # rather than promising a shape the catalogue cannot fill.
        'full': {
            'opens': ('NBLA', 'eBible: spaRV1909'),
            'items': [
                ('sword',    'NBLA',          'Nueva Biblia de las Américas', _BIBLE),
                ('sword',    'LBLA',          'La Biblia de las Américas', _BIBLE),
                ('ebible',   'spaRV1909',     'Reina Valera 1909', _BIBLE),
                # Carries the spoken reading — bible_audio binds it to this
                # exact module, so without it the listening pill has nothing
                # to play.
                ('ebible',   'spabes',        'Biblia en Español Sencillo', _AUDIO),
                # The only Spanish text with notes that carries a licence we
                # could mirror ourselves — CC BY-SA. LBLA and NBLA are
                # CrossWire-only, so no mirror may ever hold them.
                ('ebible',   'spavbl',        'Versión Biblia Libre', _NOTES),
                ('sword',    'Wikcionario',   'Wikcionario', _DICTIONARY),
                ('sword',    'StrongsHebrew', "Strong's Hebrew Lexicon", _LEXICON),
                ('sword',    'StrongsGreek',  "Strong's Greek Lexicon", _LEXICON),
                ('opendata', 'cross_references', 'OpenBible Cross-References', _XREF),
            ],
        },
    },
}

#: The language a first run falls back to when the desktop asks for one this
#: install has no catalogue for.
_DEFAULT_LANG = 'en'


def catalogue_languages():
    """Codes that can offer a starting library, in `available_languages` order.

    The intersection of two lists that are not the same: a language can have
    a compiled UI catalogue and no modules curated for it, and a language can
    have modules long before anyone translates the interface. Only the
    overlap belongs on the first screen, because it is the only set where
    picking a card leads somewhere. The rest stay reachable from the header
    picker and the Module Manager.
    """
    return [(code, name) for code, name in i18n.available_languages()
            if code in _CATALOGUE]


def _summarise(items, gt=None, ngt=None):
    """The card's contents line, counted from the items themselves.

    Written by hand this drifted — a card promised four Bibles and installed
    five — and with a table per language there would be one more of them to
    keep in step for every language added.

    `gt`/`ngt` translate into a language that is not the one the app is
    running in, which is what the language page's cards need: each says what
    it holds in its own words. They default to the running language.
    (Named for their job and not `_`, which would shadow the builtin for the
    whole function and leave every string here untranslated.)
    """
    gt = gt or _
    ngt = ngt or ngettext
    facets = [f for _k, _i, _l, f in items]
    parts = []
    bibles = facets.count(_BIBLE)
    if bibles:
        parts.append(ngt('{n} Bible', '{n} Bibles', bibles).format(
            n=bibles))
    commentaries = facets.count(_COMMENTARY)
    if commentaries:
        parts.append(ngt('{n} commentary', '{n} commentaries',
                         commentaries).format(n=commentaries)
                     if commentaries > 1 else gt('commentary'))
    if _NOTES in facets:
        parts.append(gt('notes'))
    if _DICTIONARY in facets:
        parts.append(gt('dictionary'))
    if _LEXICON in facets:
        parts.append(gt('lexicon'))
    if _XREF in facets:
        parts.append(gt('cross-references'))
    return ' · '.join(parts)


def language_summary(code):
    """What `code` has to offer, written in `code` — e.g. for Spanish under
    an English interface, "3 Biblias · notas · diccionario".

    The largest tier, because this line is the ceiling of what choosing that
    language leads to, not what any one card installs. Counted from the same
    facets as the bundle cards, so a language added to `_CATALOGUE` describes
    itself with no prose written for it.
    """
    table = _CATALOGUE.get(code)
    if not table:
        return ''
    for tier in reversed(_TIERS):
        entry = table.get(tier['id'])
        if entry is not None:
            gt, ngt = i18n.translator_for(code)
            return _summarise(entry['items'], gt, ngt)
    return ''


def bundles_for(language):
    """The cards to offer a reader of `language`, in tier order.

    A tier a language has nothing for is dropped rather than shown empty —
    the shapes are an offer, not a promise every catalogue can keep.
    """
    table = _CATALOGUE.get(language) or _CATALOGUE[_DEFAULT_LANG]
    out = []
    for tier in _TIERS:
        entry = table.get(tier['id'])
        if entry is None:
            continue
        bundle = dict(tier)
        bundle['language'] = language
        bundle['opens'] = entry['opens']
        bundle['items'] = entry['items']
        bundle['summary'] = _summarise(entry['items'])
        out.append(bundle)
    return out


class WelcomeWindow(Adw.ApplicationWindow):
    def __init__(self, on_ready, **kwargs):
        super().__init__(**kwargs)
        self._on_ready = on_ready
        self.set_title(_('Welcome to Scriptura'))
        self.set_default_size(900, 600)

        # Which language's library is on offer. The desktop's answer is the
        # starting point; the first page changes it when this install has
        # more than one to give.
        self._languages = catalogue_languages()
        current = settings.get('ui_language') or i18n.current_language()
        self._language = (current if current in _CATALOGUE else _DEFAULT_LANG)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(self._build_header())
        self.set_content(toolbar_view)

        # Three pages: the language, the bundle chooser it decides, and the
        # install-progress view. The first is skipped when there is only one
        # language to offer — a choice of one is furniture.
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(150)
        if self._offers_a_language_choice():
            self._stack.add_named(self._build_language_page(), 'language')
        self._stack.add_named(self._build_choose(), 'choose')
        self._stack.add_named(self._build_progress(), 'progress')
        self._stack.connect('notify::visible-child-name',
                            self._sync_back_button)
        toolbar_view.set_content(self._stack)
        if self._offers_a_language_choice():
            self._stack.set_visible_child_name('language')
        self._sync_back_button()

    def _build_header(self):
        """Bar with the language picker and no title.

        The page below carries the greeting in large type, so a title here
        would put the same sentence on screen twice, forty pixels apart —
        and the bar is now somewhere the eye goes, because there is a
        control in it.
        """
        header = Adw.HeaderBar()
        header.set_show_title(False)
        lang_btn = self._build_language_button()
        if lang_btn is not None:
            header.pack_end(lang_btn)
        # Getting back to the language is a back arrow in the bar rather than
        # a link in the page: the reader who needs it is one who cannot read
        # the page, and the bar is where a way back always is.
        if self._offers_a_language_choice():
            back = Gtk.Button(icon_name='scriptura-go-previous-symbolic')
            back.add_css_class('flat')
            back.set_tooltip_text(_('Language'))
            set_accessible_label(back, _('Back to language'))
            back.set_visible(False)
            back.connect('clicked', self._on_back_to_language)
            header.pack_start(back)
            self._back_to_lang = back
        return header

    def _sync_back_button(self, *_a):
        back = getattr(self, '_back_to_lang', None)
        if back is not None:
            back.set_visible(
                self._stack.get_visible_child_name() == 'choose')

    def _on_back_to_language(self, _btn):
        self._stack.set_visible_child_name('language')

    # ── Language page ──────────────────────────────────────────────────────

    def _build_language_page(self):
        """The first screen: which language this reader reads in.

        One choice, two effects — it is the language the interface comes up
        in and the language the offered library is in. They were separate
        before, and a Spanish reader met four cards of which three were
        English and one was not, with the interface in whatever the desktop
        had decided: a language was a kind of bundle rather than the question
        above them.

        Each language is written in its own name. The reader who needs this
        page is by definition looking at words they may not read, so the
        one thing on it they must recognise cannot be translated.
        """
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        outer.set_margin_top(20)
        outer.set_margin_bottom(24)
        outer.set_margin_start(28)
        outer.set_margin_end(28)
        outer.set_valign(Gtk.Align.CENTER)

        title = Gtk.Label(label=_('Welcome to Scriptura'))
        title.add_css_class('title-1')
        outer.append(title)

        subtitle = Gtk.Label(
            label=_('Choose your language. It sets the interface, and the '
                    'Bibles offered on the next screen.'))
        subtitle.set_wrap(True)
        subtitle.set_wrap_mode(Pango.WrapMode.WORD)
        subtitle.set_justify(Gtk.Justification.CENTER)
        subtitle.add_css_class('dim-label')
        outer.append(subtitle)

        # A flow rather than a row: the third language to arrive should wrap
        # onto a second line, not squeeze the first two.
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_halign(Gtk.Align.CENTER)
        # A flow box reserves room for `max_children_per_line` whatever it
        # holds, so a fixed 4 left two cards sitting off-centre in the space
        # of four. It is the count until there are enough to want a second
        # row.
        flow.set_max_children_per_line(min(len(self._languages), 4) or 1)
        # Equal cards: only one of them carries the "Detected" badge, and
        # without this that card is taller than the language beside it.
        flow.set_homogeneous(True)
        flow.set_row_spacing(14)
        flow.set_column_spacing(14)
        flow.set_margin_top(8)
        current_card = None
        for code, name in self._languages:
            card = self._make_language_card(code, name)
            flow.append(card)
            if code == self._language:
                current_card = card
        outer.append(flow)

        footnote = Gtk.Label(
            label=_('You can change this later, and add texts in any '
                    'language from the Module Manager.'))
        footnote.add_css_class('caption')
        footnote.add_css_class('dim-label')
        footnote.set_margin_top(4)
        outer.append(footnote)

        if current_card is not None:
            self.set_default_widget(current_card)
            current_card.connect('map', lambda w: w.grab_focus())
        return outer

    def _make_language_card(self, code, name):
        """One language, and what choosing it leads to.

        A card holding nothing but a name was two buttons in a large empty
        window, and gave a reader no way to tell a language with a library
        behind it from a bare interface translation. The line beneath the
        name is counted from that language's own catalogue and written in
        that language, so it needs no prose per language and cannot promise
        what the next screen will not deliver.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_valign(Gtk.Align.START)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # The badge says why this card holds the focus: the desktop already
        # answered this question, and the reader is being shown the answer
        # rather than asked to find it. In its own language, like the name.
        if code == self._language:
            gt, _ngt = i18n.translator_for(code)
            badge = Gtk.Label(label=gt('Detected'))
            badge.add_css_class('welcome-badge')
            badge.set_halign(Gtk.Align.START)
            badge.set_margin_bottom(2)
            box.append(badge)

        label = Gtk.Label(label=name)
        label.add_css_class('title-2')
        label.set_xalign(0)
        box.append(label)

        summary = language_summary(code)
        if summary:
            line = Gtk.Label(label=summary)
            line.set_wrap(True)
            line.set_wrap_mode(Pango.WrapMode.WORD)
            line.set_xalign(0)
            line.set_max_width_chars(24)
            line.add_css_class('caption')
            line.add_css_class('dim-label')
            box.append(line)

        card = Gtk.Button()
        card.set_child(box)
        card.add_css_class('card')
        # Two cards side by side should read as a deliberate pair rather than
        # two buttons that happen to be near each other; a third wraps under
        # them at the same width.
        card.set_size_request(260, -1)
        card.set_valign(Gtk.Align.FILL)
        if code == self._language:
            card.add_css_class('welcome-card-recommended')
        # The name is already the label; the summary is in a language the
        # screen reader is not speaking, so it is not read out.
        set_accessible_label(card, name)
        card.connect('clicked', self._on_language_card, code)
        return card

    def _on_language_card(self, _btn, code):
        if code != self._language or \
                settings.get('ui_language') != code:
            settings.put('ui_language', code)
            i18n.install_language(code)
            self._language = code
            # Every string on screen was translated when its widget was
            # built, so the window has to be built again to speak the new
            # language — and the cards behind this page are a different set
            # now, not merely different words.
            self._rebuild(page='choose')
            return
        self._stack.set_visible_child_name('choose')

    def _offers_a_language_choice(self):
        """Whether the language page has anything to decide.

        Counted from the catalogue, not from the compiled translations: an
        install can speak three languages and hold modules for one, and a
        page of cards that all lead to the same library is a step the reader
        pays for and gains nothing from.
        """
        return len(self._languages) > 1

    # ── Language ───────────────────────────────────────────────────────────

    def _build_language_button(self):
        """The language chooser, in the header where a first run expects it.

        Returns None when this install has only English to offer — a picker
        with one entry is furniture, not a choice.

        Each language is listed in its own name, because the reader who
        needs this control is by definition looking at words they may not
        read. It is the first thing on the first screen for the same reason.
        """
        # The first page is the picker when there is a choice to make, and
        # two controls for one decision on one screen is one too many. The
        # bar keeps it only where the page is skipped — an install with a
        # translation but no catalogue for it can still switch interface.
        if self._offers_a_language_choice():
            return None
        self._languages_ui = i18n.available_languages()
        if len(self._languages_ui) < 2:
            return None
        self._languages = self._languages_ui
        codes = [c for c, _n in self._languages]
        # What is on screen right now, not merely what was chosen: with no
        # override the desktop decides, and a picker claiming English over a
        # Spanish page is worse than no picker.
        current = settings.get('ui_language') or i18n.current_language()
        drop = Gtk.DropDown(
            model=Gtk.StringList.new([n for _c, n in self._languages]))
        drop.set_selected(codes.index(current) if current in codes else 0)
        drop.set_valign(Gtk.Align.CENTER)
        drop.set_tooltip_text(_('Language'))
        set_accessible_label(drop, _('Language'))
        drop.connect('notify::selected', self._on_language_chosen)
        drop.set_sensitive(not getattr(self, '_installing', False))
        self._lang_drop = drop
        return drop

    def _on_language_chosen(self, drop, _param):
        code = self._languages[drop.get_selected()][0]
        if code == settings.get('ui_language'):
            return
        settings.put('ui_language', code)
        i18n.install_language(code)
        # Every string on screen was translated when its widget was built,
        # so the window has to be built again to speak the new language.
        # It is two pages and no reading state, which is exactly why the
        # choice is offered here and not in the main window.
        self._rebuild()

    def _rebuild(self, page=None):
        page = page or self._stack.get_visible_child_name()
        self.set_title(_('Welcome to Scriptura'))
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(self._build_header())
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(150)
        if self._offers_a_language_choice():
            self._stack.add_named(self._build_language_page(), 'language')
        self._stack.add_named(self._build_choose(), 'choose')
        self._stack.add_named(self._build_progress(), 'progress')
        self._stack.connect('notify::visible-child-name',
                            self._sync_back_button)
        toolbar_view.set_content(self._stack)
        self.set_content(toolbar_view)
        if page and self._stack.get_child_by_name(page) is not None:
            self._stack.set_visible_child_name(page)
        self._sync_back_button()

    # ── Chooser page ───────────────────────────────────────────────────────

    def _build_choose(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        outer.set_margin_top(20)
        outer.set_margin_bottom(24)
        outer.set_margin_start(28)
        outer.set_margin_end(28)
        outer.set_valign(Gtk.Align.CENTER)

        title = Gtk.Label(label=_('Welcome to Scriptura'))
        title.add_css_class('title-1')
        outer.append(title)

        subtitle = Gtk.Label(
            label=_('Choose a starting point. Pick the shape that fits how '
                    'you want to work — this is just a head start.'))
        subtitle.set_wrap(True)
        subtitle.set_wrap_mode(Pango.WrapMode.WORD)
        subtitle.set_justify(Gtk.Justification.CENTER)
        subtitle.add_css_class('dim-label')
        outer.append(subtitle)

        cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        cards.set_homogeneous(True)
        cards.set_margin_top(8)
        default_card = None
        for bundle in bundles_for(self._language):
            card = self._make_card(bundle)
            cards.append(card)
            if bundle['recommended']:
                default_card = card
        outer.append(cards)

        footnote = Gtk.Label(
            label=_('You can add or remove anything later from the '
                    'Module Manager.'))
        footnote.add_css_class('caption')
        footnote.add_css_class('dim-label')
        footnote.set_margin_top(4)
        outer.append(footnote)

        # The one line pointing at the gesture reference. Inside the app that
        # reference is reachable two ways, and a newcomer may meet neither: an
        # unlabelled icon in the menu footer, and a button on a hint that fires
        # once and never again. This is the moment a newcomer is actually
        # reading the window, so the line names the dialog as well as opening
        # it — the point is to be re-findable later, not to be read now.
        # It carries the menu footer's own tips icon, which is where the
        # reference lives afterwards and is unlabelled there: seeing the mark
        # once beside its name is what makes it recognisable later.
        tips_btn = Gtk.Button()
        tips_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        # Rounded and set on a disc: a 16px outline glyph sitting left of a
        # label is the exact shape of an unchecked checkbox, and this one
        # opens a dialog rather than toggling anything.
        tips_icon = Gtk.Image(icon_name='scriptura-tips-symbolic')
        tips_icon.add_css_class('welcome-tips-mark')
        tips_row.append(tips_icon)
        tips_row.append(Gtk.Label(
            label=_('New here? See what the pointer can do — Tips & Gestures')))
        tips_btn.set_child(tips_row)
        tips_btn.add_css_class('flat')
        tips_btn.add_css_class('caption')
        tips_btn.set_halign(Gtk.Align.CENTER)
        tips_btn.connect('clicked', self._on_open_tips)
        outer.append(tips_btn)
        self._tips_btn = tips_btn

        mgr_btn = Gtk.Button(label=_('Choose individual modules instead'))
        mgr_btn.add_css_class('flat')
        mgr_btn.set_halign(Gtk.Align.CENTER)
        mgr_btn.connect('clicked', self._on_open_mgr)
        outer.append(mgr_btn)
        self._mgr_btn = mgr_btn

        # The recommended card is the default action (Enter activates it) and
        # takes focus once the page is shown.
        if default_card is not None:
            self.set_default_widget(default_card)
            default_card.connect(
                'map', lambda w: w.grab_focus())
        return outer

    def _make_card(self, bundle):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)

        if bundle['recommended']:
            badge = Gtk.Label(label=_('★ Recommended'))
            badge.add_css_class('welcome-badge')
            badge.set_halign(Gtk.Align.START)
            badge.set_margin_bottom(2)
            box.append(badge)

        title = Gtk.Label(label=_(bundle['title']))
        title.add_css_class('title-4')
        title.set_xalign(0)
        title.set_wrap(True)
        box.append(title)

        tagline = Gtk.Label(label=_(bundle['tagline']))
        tagline.set_wrap(True)
        tagline.set_wrap_mode(Pango.WrapMode.WORD)
        tagline.set_xalign(0)
        tagline.add_css_class('dim-label')
        box.append(tagline)

        summary = Gtk.Label(label=_(bundle['summary']))
        summary.set_wrap(True)
        summary.set_wrap_mode(Pango.WrapMode.WORD)
        summary.set_xalign(0)
        summary.add_css_class('caption')
        summary.set_margin_top(4)
        box.append(summary)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        box.append(spacer)

        size = Gtk.Label(label=_(bundle['size']))
        size.set_xalign(0)
        size.add_css_class('caption')
        size.add_css_class('dim-label')
        size.set_margin_top(8)
        box.append(size)

        card = Gtk.Button()
        card.set_child(box)
        card.add_css_class('card')
        card.set_valign(Gtk.Align.FILL)
        card.set_vexpand(True)
        if bundle['recommended']:
            card.add_css_class('welcome-card-recommended')
        card.connect('clicked', self._on_card_clicked, bundle)
        return card

    def _on_card_clicked(self, _btn, bundle):
        self._installing = True
        if getattr(self, '_lang_drop', None) is not None:
            self._lang_drop.set_sensitive(False)
        # Changing language mid-download would swap the catalogue under the
        # worker thread and leave half of one library beside half of another.
        if getattr(self, '_back_to_lang', None) is not None:
            self._back_to_lang.set_sensitive(False)
        self._back_btn.set_visible(False)
        self._spinner.set_visible(True)
        self._spinner.start()
        self._status.set_text(_('Starting download…'))
        self._stack.set_visible_child_name('progress')
        threading.Thread(
            target=self._install_worker, args=(bundle,),
            daemon=True).start()

    def _on_open_tips(self, _btn):
        # No `on_shortcuts`: that dialog belongs to the reading window, which
        # does not exist yet, so the row drops out rather than pointing at
        # nothing. Offered only on the chooser page — once the install starts,
        # the window closes itself on handoff and would take the dialog with it.
        onboarding.build_tips_dialog().present(self)

    # ── Progress page ────────────────────────────────────────────────────

    def _build_progress(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_start(36)
        box.set_margin_end(36)

        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(36, 36)
        box.append(self._spinner)

        self._status = Gtk.Label(label='')
        self._status.set_wrap(True)
        self._status.set_wrap_mode(Pango.WrapMode.WORD)
        self._status.set_justify(Gtk.Justification.CENTER)
        box.append(self._status)

        self._back_btn = Gtk.Button(label=_('Back to options'))
        self._back_btn.set_halign(Gtk.Align.CENTER)
        self._back_btn.set_visible(False)
        self._back_btn.connect('clicked', self._on_back)
        box.append(self._back_btn)
        return box

    def _on_back(self, _btn):
        self._installing = False
        if getattr(self, '_lang_drop', None) is not None:
            self._lang_drop.set_sensitive(True)
        if getattr(self, '_back_to_lang', None) is not None:
            self._back_to_lang.set_sensitive(True)
        self._stack.set_visible_child_name('choose')

    # ── Install flow ───────────────────────────────────────────────────────

    def _install_worker(self, bundle):
        items = bundle['items']
        failed = []
        # Which repository a module belongs to is recorded in the catalogue,
        # and a first run has no catalogue at all — so install_module falls
        # back to the released repository's zip. That is the wrong place for
        # anything the Lockman repo owns, and it publishes no zips whatever,
        # so NBLA and LBLA simply fail. Fetching the catalogue first is what
        # makes them installable; it also leaves the Module Manager with a
        # list instead of "no catalogue cached yet".
        wanted = [i for kind, i, _l, _f in items if kind == 'sword']
        if wanted:
            GLib.idle_add(self._set_status, _('Reading the module list…'))
            try:
                # A cached catalogue is not necessarily a current one. A
                # profile that read the list before a module was published
                # has no row for it, install_module falls back to the
                # released repository where it has never been, and the
                # download 404s for something that exists — which is how the
                # Spanish dictionary failed to arrive on every profile that
                # had ever opened the Module Manager.
                if (sword_bridge.catalog_timestamp() is None
                        or not all(sword_bridge.catalogue_has(m)
                                   for m in wanted)):
                    sword_bridge.refresh_source()
            except Exception as e:
                # Not fatal: every module in the released repository still
                # installs by zip without it.
                failed.append((_('module list'), str(e)))

        total = len(items)
        for step, (kind, ident, label, _facet) in enumerate(
                items, start=1):
            base = _('({step}/{total}) Downloading {label}…').format(
                step=step, total=total, label=label)
            GLib.idle_add(self._set_status, base)
            try:
                if kind == 'sword':
                    sword_bridge.install_module(ident)
                elif kind == 'opendata':
                    open_data.download_source(
                        ident, on_progress=self._mk_progress(base))
                elif kind == 'catena':
                    catena_bridge.download_and_install(
                        on_progress=self._mk_progress(base))
                elif kind == 'ebible':
                    self._install_ebible(ident)
            except Exception as e:
                failed.append((label, str(e)))
        GLib.idle_add(self._finish_install, failed, bundle)

    def _install_ebible(self, tid):
        """Install one eBible translation by id. Unlike the SWORD and
        open-data steps, the download needs the catalog row alongside the
        id, so a profile that has never opened the Module Manager has to
        fetch the catalog first."""
        entry = next((e for e in ebible_bridge.catalog_entries()
                      if e.get('translationId') == tid), None)
        if entry is None:
            ebible_bridge.download_catalog_sync()
            entry = next((e for e in ebible_bridge.catalog_entries()
                          if e.get('translationId') == tid), None)
        if entry is None:
            raise LookupError(f'{tid} is not in the eBible catalog')
        ebible_bridge.download_translation_sync(tid, entry)

    def _mk_progress(self, base):
        def _progress(done, total):
            if total > 0:
                pct = int(done * 100 / total)
                detail = _('{pct}% ({done} of {total} MB)').format(
                    pct=pct, done=done >> 20, total=total >> 20)
            else:
                detail = _('{done} MB').format(done=done >> 20)
            GLib.idle_add(self._set_status, f'{base} {detail}')
        return _progress

    def _set_status(self, msg):
        self._status.set_text(msg)
        return GLib.SOURCE_REMOVE

    def _record_opening_pair(self, bundle):
        """Persist the pair of modules the reading window should open on.

        Only what actually arrived is written: a step can fail and still leave
        a usable library, and a saved default naming an absent module would
        send the main window straight back to guessing. When there is no
        second module to show — the reading-only bundle, or a commentary that
        failed — the split is turned off rather than filled with a copy of
        pane 1."""
        import settings
        # Every backend that can supply a pane, or a bundle opening on an
        # eBible text would record nothing and leave the window guessing —
        # the exact failure this method exists to prevent.
        present = (set(sword_bridge.module_names())
                   | set(catena_bridge.module_names())
                   | set(ebible_bridge.module_names()))
        pane1, pane2 = bundle['opens']
        if pane1 in present:
            settings.put('pane1_module', pane1)
        if pane2 is not None and pane2 in present:
            settings.put('pane2_module', pane2)
            settings.put('split_pane_mode', True)
        else:
            settings.put('split_pane_mode', False)

    def _finish_install(self, failed, bundle):
        # The one hard requirement: a Bible-text module must now exist, or the
        # main window has nothing to open. Everything else is recoverable from
        # the Module Manager later.
        installed = sword_bridge.module_names()
        has_bible = any(
            sword_bridge.module_type(m) == 'Biblical Texts' for m in installed
        )

        if not has_bible:
            details = ('; '.join(f'{n}: {e}' for n, e in failed)
                       or _('unknown error'))
            self._spinner.stop()
            self._spinner.set_visible(False)
            self._status.set_text(
                _('Couldn’t download a Bible — please check your connection '
                  'and try again. ({details})').format(details=details))
            self._back_btn.set_visible(True)
            return GLib.SOURCE_REMOVE

        self._record_opening_pair(bundle)

        if failed:
            names = ', '.join(n for n, _err in failed)
            self._status.set_text(
                _('Installed with warnings — these can be retried later from '
                  'the Module Manager: {names}').format(names=names))
        else:
            self._status.set_text(_('Done. Opening Scriptura…'))
        self._spinner.stop()
        self._spinner.set_visible(False)

        # Hand off to main.py to construct the real window.
        GLib.timeout_add(600, self._handoff)
        return GLib.SOURCE_REMOVE

    def _handoff(self):
        self._on_ready()
        self.close()
        return GLib.SOURCE_REMOVE

    # ── Manual route ─────────────────────────────────────────────────────

    def _on_open_mgr(self, _btn):
        # Import lazily so the welcome window doesn't pull the whole
        # module-manager dependency chain on the no-op path.
        from module_manager import ModuleManagerWindow

        # transient_for + modal so tiling compositors (Hyprland) keep the
        # picker attached to the welcome window rather than spawning a
        # separate tile, and Mutter stacks it above its parent.
        win = ModuleManagerWindow(
            application=self.get_application(),
            transient_for=self,
            modal=True,
        )
        win.connect('close-request', self._on_mgr_closed)
        win.present()

    def _on_mgr_closed(self, _win):
        # User may have installed modules manually; re-check and hand off
        # to the real window if so. Otherwise stay on welcome.
        if sword_bridge.module_names():
            self._handoff()
        return False
