"""The player that floats over the reading pane while a chapter is read aloud.

Cast from the reader's own page rather than from the platform. Every audio
player in every app is a dark slab, because players normally float over media
that is already dark; this one floats over paper whose colour the reader
chose, where a dark slab is the only object on the surface that did not come
from the page — the mistake the Today page's listen disc was rebuilt to
correct. So the pill takes the live paper, mixed a little toward its own ink,
with a hairline of that ink and the house floating-card shadow. Sepia paper
gives a sepia pill; the Night Light dusk blend carries into it for free. The
colours are written by the pane's own provider (`BiblePane._update_font_css`),
because only the pane knows what paper is on screen.

Five slots, and the discipline is in what is absent:

    back fifteen · play/pause · what is sounding and how long it runs ·
    speed · close

No scrubber (three pixels cannot be dragged accurately, and back-fifteen is
the need that actually arises — "I missed that", never "get on with it"), no
forward skip for the same reason, no volume, no chapter list. The pane *is*
the chapter list. Volume and remote control belong on the desktop's media bus
rather than on a reading surface.

A sixth slot exists in one state only: while the reading that is sounding and
the chapter on screen have parted company, a switch naming the chapter on
screen appears between the two. It is the one control here that does not act
on what is sounding — every other player puts that control on the item rather
than on the transport (tapping a podcast episode replaces what is playing;
the now-playing bar never retargets itself), and this app has no list of
items to put it on. So it comes to the pill, named after its target, and only
while there is a second reading to name.

Speed is here, and it is not a media-player luxury: the narrator reads near
150 words a minute while silent reading runs at 200-300, so a reader
following the text at a fixed 1x is being dragged. It is the control that
decides whether reading along works at all.

The length is stated once and does not count down. It answers the question
that is actually asked — is this four minutes or fifteen — which is asked
before pressing play and never again. A running clock is what turns a reading
surface into a media player, and makes a reader watch it instead of listen.

Not a Gtk.Revealer, despite being a thing that appears and leaves: a Revealer
clips its child, which shears the shadow off a floating surface (see the CSS
quirks note at the top of data/style.css). It rises on an Adw.TimedAnimation
instead, which also collapses to its end state under reduced motion.
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk

import motion
from a11y import set_accessible_label
from gtk_utils import DelayedPulse
from i18n import _

#: How far the pill travels as it arrives, in px. Small enough to read as
#: settling rather than flying in.
TRAVEL_PX = 8

#: Clear of the reading card's foot, matching the 16px the progress line was
#: inset by — the pill lines up with the card's straight edge, not its curve.
FOOT_MARGIN = 16

#: The pill's paper-cast colours, for the whole display rather than per
#: widget. A provider added to a widget's style context reaches that widget's
#: own node and stops there — it never gets inside, so the thread's
#: `> trough > progress` kept Adwaita's accent blue and the pill grew the one
#: colour the two-accent law says it must not have. One provider is honest
#: here because paper and ink are app-wide settings: both panes always read
#: the same page.
_paper_css = None
_paper_applied = None

#: The speeds offered. Bounded and few: a list long enough to scroll turns a
#: choice into a settings page, and past 2x a reading stops being read aloud
#: and starts being skimmed. 0.75 is here for the reader following in a second
#: language, who needs the narrator slower rather than faster.
RATES = (0.75, 1.0, 1.25, 1.5, 1.75, 2.0)


def sane_rate(rate):
    """The nearest offered speed. A stored setting is only ever written by the
    pill, but it is a plain number in a file a reader can edit, and 6x is not
    a reading."""
    return rate if rate in RATES else 1.0


def format_rate(rate):
    """`1×`, `1.25×` — no trailing zeros, and a true multiplication sign."""
    return f'{rate:g}×'


def format_length(seconds):
    """`4:33` for a duration in seconds, or '' when it cannot be known.

    Stated once when the file opens, and never counted down: the question a
    reader actually asks is whether this is four minutes or fifteen, and it is
    asked before pressing play. A clock that keeps moving invites watching it.
    """
    if not seconds or seconds <= 0:
        return ''
    minutes, rest = divmod(int(round(seconds)), 60)
    return f'{minutes}:{rest:02d}'


class AudioPill(Gtk.Box):
    """The floating player. Owns its own look and its own waiting; the pane
    tells it what is happening and reads nothing back."""

    def __init__(self, on_play_pause, on_back, on_close, on_rate=None,
                 on_switch=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.add_css_class('audio-pill')
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.END)
        self.set_margin_bottom(FOOT_MARGIN)
        self.set_visible(False)
        self.set_opacity(0.0)
        self._state = 'idle'
        self._anim = None
        # Whether the pill is *meant* to be up. Not the same as get_visible():
        # visibility only drops at the end of the leaving animation, so asking
        # the widget swallowed a reopen pressed during those 150ms.
        self._shown = False

        self._back_btn = self._button(
            'scriptura-back-fifteen-symbolic', _('Back fifteen seconds'),
            on_back)
        self._play_btn = self._button(
            'media-playback-start-symbolic', _('Play'), on_play_pause)
        self._close_btn = self._button(
            'window-close-symbolic', _('Close the player'), on_close)
        self._close_btn.add_css_class('audio-pill-close')

        # Speed, named by its own value rather than by an icon: no glyph says
        # "one and a quarter times", and the number is the shortest possible
        # label for it.
        self._on_rate = on_rate
        self._rate = 1.0
        self._setting_rate = False
        self._rate_lbl = Gtk.Label(label=format_rate(1.0))
        self._rate_btn = Gtk.MenuButton()
        self._rate_btn.set_child(self._rate_lbl)
        self._rate_btn.set_valign(Gtk.Align.CENTER)   # as the actions, above
        self._rate_btn.add_css_class('flat')
        self._rate_btn.add_css_class('audio-pill-rate')
        self._rate_btn.set_tooltip_text(_('Reading speed'))
        set_accessible_label(self._rate_btn, _('Reading speed'))
        self._rate_btn.set_popover(self._build_rate_popover())
        # Pinned once the widget has a font to measure with: 1.25x is wider
        # than 1x, and letting the button size to its label made choosing a
        # speed nudge everything beside it sideways.
        self.connect('realize', lambda _w: self._pin_rate_width())

        # What is sounding, and how long it runs — one line, with the length
        # in the quieter voice because it is context, not the subject.
        self._ref_lbl = Gtk.Label(xalign=0.0)
        self._ref_lbl.add_css_class('audio-pill-ref')
        self._len_lbl = Gtk.Label(xalign=0.0)
        self._len_lbl.add_css_class('audio-pill-length')
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        line.append(self._ref_lbl)
        line.append(self._len_lbl)

        self._thread = Gtk.ProgressBar()
        self._thread.add_css_class('audio-pill-thread')
        # Tight: the thread belongs to the line above it, and a two-row column
        # centred in the pill hangs its text above the centre line every glyph
        # beside it sits on — 6px of gap put the reference 4.5px high.
        now = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        now.add_css_class('audio-pill-now')
        now.set_valign(Gtk.Align.CENTER)
        now.append(line)
        now.append(self._thread)

        # "Read this one instead", named after the chapter it would start.
        # A play triangle and a reference, which is how the item's own control
        # is written everywhere it exists; a bare glyph here would leave the
        # reader to guess which of the two chapters it meant, and a bare
        # reference beside the sounding one would read as a second statement
        # rather than as a control.
        self._on_switch = on_switch
        self._switch_content = Adw.ButtonContent(
            icon_name='media-playback-start-symbolic')
        # A second reference is 60px on the pill, and 125px for "1 Chronicles
        # 13". The pill is an overlay child, so it never widens the pane — it
        # would simply run past its edge in a narrow split. Let the reference
        # give way instead; the triangle beside it still says what it does.
        self._switch_content.set_can_shrink(True)
        self._switch_btn = Gtk.Button(child=self._switch_content)
        self._switch_btn.set_valign(Gtk.Align.CENTER)
        self._switch_btn.add_css_class('flat')
        self._switch_btn.add_css_class('audio-pill-switch')
        self._switch_btn.set_visible(False)
        self._switch_btn.connect('clicked', lambda _b: self._on_switch())

        self.append(self._back_btn)
        self.append(self._play_btn)
        self.append(now)
        self.append(self._switch_btn)
        self.append(self._rate_btn)
        self.append(self._close_btn)

        # The fetch shows itself here rather than on the toolbar, on the same
        # threshold every other busy indicator in the app waits out. Nothing
        # to show or hide: the thread is always on the pill, and clearing it
        # is set_state's business — it must happen when a *fetch* ends and
        # never when playback merely pauses.
        self._wait = DelayedPulse(show=lambda: None,
                                  tick=self._thread.pulse,
                                  hide=lambda: None)

    def _build_rate_popover(self):
        """A row of the speeds, one pressed.

        Toggles in a group rather than a menu: they carry radio semantics to
        AT for free, and six values read faster side by side than stacked.
        Spaced rather than linked — the group is what makes them one choice,
        and linking only cost the pressed one its corners.
        """
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self._rate_choices = {}
        group = None
        for rate in RATES:
            # Bare numerals here: the trigger has to mean something on its
            # own, but inside the popover the context is already set, and six
            # multiplication signs in one row is noise.
            choice = Gtk.ToggleButton(label=f'{rate:g}')
            choice.add_css_class('audio-rate-choice')
            set_accessible_label(choice, format_rate(rate))
            if group is None:
                group = choice
            else:
                choice.set_group(group)
            choice.set_active(rate == 1.0)
            choice.connect('toggled', self._on_rate_chosen, rate)
            row.append(choice)
            self._rate_choices[rate] = choice
        popover = Gtk.Popover()
        popover.add_css_class('audio-rate-popover')
        popover.set_child(row)
        return popover

    def _pin_rate_width(self):
        """Hold the speed at the width of its widest possible label.

        Measured rather than written down as a number of pixels, so it stays
        right under a different UI font or text scale — the widest label is
        not always the same string once the digits change width.
        """
        showing = self._rate_lbl.get_text()
        widest = 0
        for rate in RATES:
            self._rate_lbl.set_text(format_rate(rate))
            widest = max(widest, self._rate_lbl.measure(
                Gtk.Orientation.HORIZONTAL, -1)[1])
        self._rate_lbl.set_text(showing)
        self._rate_lbl.set_size_request(widest, -1)

    def _on_rate_chosen(self, choice, rate):
        # set_active() during set_rate() must not report a choice back as if
        # the reader had made it.
        if self._setting_rate or not choice.get_active():
            return
        self._rate = rate
        self._rate_lbl.set_text(format_rate(rate))
        self._rate_btn.get_popover().popdown()
        if self._on_rate is not None:
            self._on_rate(rate)

    def set_rate(self, rate):
        """Show a speed without reporting it back — for restoring the stored
        preference when the pill is built."""
        rate = sane_rate(rate)
        self._setting_rate = True
        self._rate = rate
        self._rate_lbl.set_text(format_rate(rate))
        self._rate_choices[rate].set_active(True)
        self._setting_rate = False

    def _button(self, icon, label, handler):
        btn = Gtk.Button(icon_name=icon)
        # Centred, not filled: a button left to stretch takes the pill's whole
        # 48px height, and a 32px-wide background with a capsule radius then
        # paints as a tall oval touching both edges — the outermost one cut by
        # the pill's own corner. Centring is what makes the 32px disc the CSS
        # asks for, with the pill's rim clear of it.
        btn.set_valign(Gtk.Align.CENTER)
        btn.add_css_class('flat')
        btn.add_css_class('audio-pill-action')
        btn.set_tooltip_text(label)
        set_accessible_label(btn, label)
        btn.connect('clicked', lambda _b: handler())
        return btn

    # ── Cast from the reader's paper ─────────────────────────────────────
    def set_appearance(self, paper, ink):
        """Recolour from the pane's live paper and ink.

        Mixed a fourteenth of the way toward the ink, which is enough to lift
        the pill off the page at any paper lightness without ever reading as
        a different material. Everything else on it is that same ink at
        descending strengths — no accent: this control neither goes to the
        Bible nor leaves the surface, which is what the two chrome colours
        mean.

        The popover is cast from the same paper. It is the larger of the two
        surfaces and it opens directly over the reading, so a stock grey sheet
        there would undo the whole argument for casting the pill at all.
        """
        global _paper_css, _paper_applied
        if _paper_css is None:
            _paper_css = Gtk.CssProvider()
        display = self.get_display()
        if display is not None and _paper_applied is not display:
            Gtk.StyleContext.add_provider_for_display(
                display, _paper_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            _paper_applied = display
        _paper_css.load_from_data((
            f'.audio-pill {{'
            f' background-color: mix({paper}, {ink}, 0.07);'
            f' border: 1px solid alpha({ink}, 0.11);'
            f' color: alpha({ink}, 0.86); }}'
            f'.audio-pill-ref {{ color: alpha({ink}, 0.80); }}'
            f'.audio-pill-length {{ color: alpha({ink}, 0.80); }}'
            f'button.audio-pill-action:hover,'
            f'button.audio-pill-switch:hover {{'
            f' background-color: alpha({ink}, 0.07); }}'
            # A shade back from the reference it stands beside: it is an offer
            # the reader may take, and the reading in hand is the subject.
            f'button.audio-pill-switch {{ color: alpha({ink}, 0.72); }}'
            f'progressbar.audio-pill-thread > trough {{'
            f' background-color: alpha({ink}, 0.11); }}'
            f'progressbar.audio-pill-thread > trough > progress {{'
            f' background-color: alpha({ink}, 0.38); }}'
            # `menubutton > button`, not `button.audio-pill-rate`: the class
            # sits on the GtkMenuButton, whose node is not a button at all.
            f'menubutton.audio-pill-rate > button {{'
            f' color: alpha({ink}, 0.86); }}'
            f'menubutton.audio-pill-rate > button:hover {{'
            f' background-color: alpha({ink}, 0.07); }}'
            # While its popover is open the button is `checked`, and Adwaita
            # fills a checked button with a theme colour — which put the one
            # surface on the pill that had not come from the paper.
            f'menubutton.audio-pill-rate > button:checked {{'
            f' background-color: alpha({ink}, 0.10); }}'
            f'.audio-rate-popover > contents {{'
            f' background-color: mix({paper}, {ink}, 0.07);'
            f' color: alpha({ink}, 0.86);'
            f' border: 1px solid alpha({ink}, 0.11);'
            f' box-shadow: 0 8px 24px alpha(black, 0.13); }}'
            f'.audio-rate-popover > arrow {{'
            f' background-color: mix({paper}, {ink}, 0.07);'
            f' border: 1px solid alpha({ink}, 0.11); }}'
            # No rim: the cells sat in a linked row, where the border was the
            # divider between them. Spaced apart, a rim on each one turns the
            # row into six outlined boxes and the chosen speed's fill stops
            # being the only mark that means anything.
            f'button.audio-rate-choice {{'
            f' color: alpha({ink}, 0.86);'
            f' background-image: none;'
            f' background-color: transparent;'
            f' border-color: transparent; }}'
            f'button.audio-rate-choice:hover {{'
            f' background-color: alpha({ink}, 0.07); }}'
            f'button.audio-rate-choice:checked {{'
            f' background-color: alpha({ink}, 0.15); }}'
        ).encode())

    # ── What the pane tells it ───────────────────────────────────────────
    def set_reading(self, reference, length=''):
        """Name what is on the pill: the chapter, and how long it runs."""
        self._ref_lbl.set_text(reference or '')
        self._len_lbl.set_text(length or '')
        self._len_lbl.set_visible(bool(length))

    def set_switch(self, reference):
        """Offer to start `reference` instead, or withdraw the offer.

        The pane decides when this applies — it is the only thing that knows
        what is on screen — and it passes '' for the ordinary case, where the
        reader is looking at the chapter they are listening to and there is
        nothing to switch to.
        """
        if not reference or self._on_switch is None:
            self._switch_btn.set_visible(False)
            return
        self._switch_content.set_label(reference)
        label = _('Read {reference} aloud instead').format(reference=reference)
        self._switch_btn.set_tooltip_text(label)
        set_accessible_label(self._switch_btn, label)
        self._switch_btn.set_visible(True)

    def set_state(self, state):
        """One of 'idle', 'fetching', 'playing'.

        The pause icon appears for 'playing' and nothing else — while the
        chapter is still being fetched there is silence, and a pause icon over
        silence is a claim the app cannot keep.
        """
        if state == self._state:
            return
        was_fetching = self._state == 'fetching'
        self._state = state
        if state == 'fetching':
            self._play_btn.set_icon_name('media-playback-stop-symbolic')
            self._label_play(_('Stop fetching the reading'))
            self._wait.start()
            return
        self._wait.stop()
        if was_fetching:
            # A pulsing bar holds no fraction, so it has to be put back to
            # zero on the way out. Only on the way out of a FETCH, though:
            # doing it on every state change wiped the reader's position off
            # the thread each time they pressed pause.
            self._thread.set_fraction(0.0)
        if state == 'playing':
            self._play_btn.set_icon_name('media-playback-pause-symbolic')
            self._label_play(_('Pause'))
        else:
            self._play_btn.set_icon_name('media-playback-start-symbolic')
            self._label_play(_('Play'))

    def _label_play(self, label):
        self._play_btn.set_tooltip_text(label)
        set_accessible_label(self._play_btn, label)

    def set_progress(self, fraction):
        if self._state != 'fetching':
            self._thread.set_fraction(fraction)

    def set_can_seek(self, can_seek):
        """Back-fifteen is offered only where it means something — a devotional
        that has not started has nothing to go back to."""
        self._back_btn.set_sensitive(can_seek)

    # ── Arriving and leaving ─────────────────────────────────────────────
    def is_shown(self):
        """Whether the pill is up, including while it is still arriving or
        leaving. Ask this rather than get_visible()."""
        return self._shown

    def present(self):
        if self._shown:
            return
        self._shown = True
        self.set_visible(True)
        # From wherever it currently is, so reopening mid-dismiss picks the
        # fade up rather than snapping it back to nothing first.
        self._animate(self.get_opacity(), 1.0,
                      motion.DURATION_STANDARD, motion.EASE_ENTER)

    def dismiss(self):
        if not self._shown:
            return
        self._shown = False
        self.set_state('idle')
        self._animate(self.get_opacity(), 0.0,
                      motion.DURATION_SHORT, motion.EASE_EXIT,
                      done=lambda: self.set_visible(False))

    def _animate(self, start, end, duration, easing, done=None):
        if self._anim is not None:
            self._anim.pause()
            self._anim = None

        def frame(value):
            self.set_opacity(value)
            # Rises as it fades in, sinks as it goes: the travel is tied to
            # the opacity so the two can never disagree.
            self.set_margin_bottom(
                round(FOOT_MARGIN - TRAVEL_PX * (1.0 - value)))

        def finished(_a):
            self._anim = None
            if done is not None:
                done()

        target = Adw.CallbackAnimationTarget.new(frame)
        self._anim = Adw.TimedAnimation.new(self, start, end, duration, target)
        self._anim.set_easing(easing)
        self._anim.connect('done', finished)
        self._anim.play()
