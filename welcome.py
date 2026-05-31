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


# Each step is (kind, ident, label):
#   'sword'    → sword_bridge.install_module(ident)
#   'opendata' → open_data.download_source(ident)
#   'catena'   → catena_bridge.download_and_install()   (ident unused)
_BUNDLES = [
    {
        'id': 'reading',
        'title': 'Just reading',
        'tagline': 'Open a Bible and start reading right away.',
        'summary': '1 Bible',
        'size': 'Quick download',
        'recommended': False,
        'items': [
            ('sword', 'KJVA', 'King James Bible'),
        ],
    },
    {
        'id': 'study',
        'title': 'Reading + study',
        'tagline': 'A few translations, historical commentary, and '
                   'word-study tools.',
        'summary': '3 Bibles · commentary · lexicon · cross-references',
        'size': 'Small download',
        'recommended': True,
        'items': [
            ('sword',    'KJVA',          'King James Bible'),
            ('sword',    'ASV',           'American Standard Version'),
            ('sword',    'YLT',           "Young's Literal Translation"),
            ('catena',   '',              'Historical Commentaries'),
            ('sword',    'StrongsHebrew', "Strong's Hebrew Lexicon"),
            ('sword',    'StrongsGreek',  "Strong's Greek Lexicon"),
            ('opendata', 'dodson',        'Dodson Greek Lexicon'),
            ('sword',    'TSK',           'Treasury of Scripture Knowledge'),
        ],
    },
    {
        'id': 'full',
        'title': 'Full library',
        'tagline': 'The complete set — more translations and commentaries '
                   'from the start.',
        'summary': '5 Bibles · 3 commentaries · lexicon · 340k cross-references',
        'size': 'Larger download',
        'recommended': False,
        'items': [
            ('sword',    'KJVA',          'King James Bible'),
            ('sword',    'ASV',           'American Standard Version'),
            ('sword',    'YLT',           "Young's Literal Translation"),
            ('sword',    'Geneva1599',    'Geneva Bible (1599)'),
            ('sword',    'Webster',       "Webster's Bible"),
            ('catena',   '',              'Historical Commentaries'),
            ('sword',    'MHCC',          "Matthew Henry's Concise Commentary"),
            ('sword',    'JFB',           'Jamieson-Fausset-Brown Commentary'),
            ('sword',    'StrongsHebrew', "Strong's Hebrew Lexicon"),
            ('sword',    'StrongsGreek',  "Strong's Greek Lexicon"),
            ('opendata', 'dodson',        'Dodson Greek Lexicon'),
            ('opendata', 'cross_references', 'OpenBible Cross-References'),
            ('opendata', 'topics',        'OpenBible Topics'),
            ('sword',    'TSK',           'Treasury of Scripture Knowledge'),
        ],
    },
]


class WelcomeWindow(Adw.ApplicationWindow):
    def __init__(self, on_ready, **kwargs):
        super().__init__(**kwargs)
        self._on_ready = on_ready
        self._last_items = None
        self.set_title('Welcome to Scriptura')
        self.set_default_size(900, 600)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        self.set_content(toolbar_view)

        # Two pages: the bundle chooser, and the install-progress view.
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(150)
        self._stack.add_named(self._build_choose(), 'choose')
        self._stack.add_named(self._build_progress(), 'progress')
        toolbar_view.set_content(self._stack)

    # ── Chooser page ───────────────────────────────────────────────────────

    def _build_choose(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        outer.set_margin_top(20)
        outer.set_margin_bottom(24)
        outer.set_margin_start(28)
        outer.set_margin_end(28)
        outer.set_valign(Gtk.Align.CENTER)

        title = Gtk.Label(label='Welcome to Scriptura')
        title.add_css_class('title-1')
        outer.append(title)

        subtitle = Gtk.Label(
            label='Choose a starting point. Pick the shape that fits how '
                  'you want to work — this is just a head start.')
        subtitle.set_wrap(True)
        subtitle.set_wrap_mode(Pango.WrapMode.WORD)
        subtitle.set_justify(Gtk.Justification.CENTER)
        subtitle.add_css_class('dim-label')
        outer.append(subtitle)

        cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        cards.set_homogeneous(True)
        cards.set_margin_top(8)
        default_card = None
        for bundle in _BUNDLES:
            card = self._make_card(bundle)
            cards.append(card)
            if bundle['recommended']:
                default_card = card
        outer.append(cards)

        footnote = Gtk.Label(
            label='You can add or remove anything later from the '
                  'Module Manager.')
        footnote.add_css_class('caption')
        footnote.add_css_class('dim-label')
        footnote.set_margin_top(4)
        outer.append(footnote)

        mgr_btn = Gtk.Button(label='Choose individual modules instead')
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
            badge = Gtk.Label(label='★ Recommended')
            badge.add_css_class('welcome-badge')
            badge.set_halign(Gtk.Align.START)
            badge.set_margin_bottom(2)
            box.append(badge)

        title = Gtk.Label(label=bundle['title'])
        title.add_css_class('title-4')
        title.set_xalign(0)
        title.set_wrap(True)
        box.append(title)

        tagline = Gtk.Label(label=bundle['tagline'])
        tagline.set_wrap(True)
        tagline.set_wrap_mode(Pango.WrapMode.WORD)
        tagline.set_xalign(0)
        tagline.add_css_class('dim-label')
        box.append(tagline)

        summary = Gtk.Label(label=bundle['summary'])
        summary.set_wrap(True)
        summary.set_wrap_mode(Pango.WrapMode.WORD)
        summary.set_xalign(0)
        summary.add_css_class('caption')
        summary.set_margin_top(4)
        box.append(summary)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        box.append(spacer)

        size = Gtk.Label(label=bundle['size'])
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
        self._last_items = bundle['items']
        self._back_btn.set_visible(False)
        self._spinner.set_visible(True)
        self._spinner.start()
        self._status.set_text('Starting download…')
        self._stack.set_visible_child_name('progress')
        threading.Thread(
            target=self._install_worker, args=(bundle['items'],),
            daemon=True).start()

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

        self._back_btn = Gtk.Button(label='Back to options')
        self._back_btn.set_halign(Gtk.Align.CENTER)
        self._back_btn.set_visible(False)
        self._back_btn.connect('clicked', self._on_back)
        box.append(self._back_btn)
        return box

    def _on_back(self, _btn):
        self._stack.set_visible_child_name('choose')

    # ── Install flow ───────────────────────────────────────────────────────

    def _install_worker(self, items):
        failed = []
        total = len(items)
        for step, (kind, ident, label) in enumerate(items, start=1):
            base = f'({step}/{total}) Downloading {label}…'
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
            except Exception as e:
                failed.append((label, str(e)))
        GLib.idle_add(self._finish_install, failed)

    def _mk_progress(self, base):
        def _progress(done, total):
            if total > 0:
                pct = int(done * 100 / total)
                GLib.idle_add(
                    self._set_status,
                    f'{base} {pct}% ({done >> 20} of {total >> 20} MB)')
            else:
                GLib.idle_add(self._set_status, f'{base} {done >> 20} MB')
        return _progress

    def _set_status(self, msg):
        self._status.set_text(msg)
        return GLib.SOURCE_REMOVE

    def _finish_install(self, failed):
        # The one hard requirement: a Bible-text module must now exist, or the
        # main window has nothing to open. Everything else is recoverable from
        # the Module Manager later.
        installed = sword_bridge.module_names()
        has_bible = any(
            sword_bridge.module_type(m) == 'Biblical Texts' for m in installed
        )

        if not has_bible:
            details = '; '.join(f'{n}: {e}' for n, e in failed) or 'unknown error'
            self._spinner.stop()
            self._spinner.set_visible(False)
            self._status.set_text(
                f'Couldn’t download a Bible — please check your connection '
                f'and try again. ({details})')
            self._back_btn.set_visible(True)
            return GLib.SOURCE_REMOVE

        if failed:
            names = ', '.join(n for n, _ in failed)
            self._status.set_text(
                f'Installed with warnings — these can be retried later from '
                f'the Module Manager: {names}')
        else:
            self._status.set_text('Done. Opening Scriptura…')
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
