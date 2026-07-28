"""AudioSurfaces — the pane's two spoken-reading surfaces, extracted from
BiblePane (BACKLOG.md item 24b).

The pane grew 546 lines of audio wiring across 29 methods while the players
themselves lived elsewhere (devotional_audio / bible_audio / audio_pill): the
logic had a home, the wiring did not, because only the pane held the book,
chapter and module every surface needs. This module gives the wiring a home
too.

Two surfaces, one player type. `DevotionalAudio` owns the date-row reading of
the day; `ReadingAudio` owns the chapter/psalm reading and the listening pill.
Both run on `devotional_audio.Player` and both reach the desktop through
`mpris.Reading` — item 23a had already unified them there, and this extends
that same seam down into the pane.

Each surface owns its own widgets and its own state outright; what stays with
the pane is placement (the toolbar box, the date-nav row, the overlay) and the
two public entry points the window calls, `stop_audio` / `set_show_audio`.
What the surfaces still need FROM the pane — the open module, book, chapter,
and the toast channel — arrives through the small proxy properties below, so
every method body is the inline original unchanged (the ScrollKeeper /
ChromeController pattern, STRUCTURAL_ANALYSIS.md §5.4).
"""
import datetime

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk

import a11y
import bible_audio
import devotional_audio
import mpris
import settings
import tasks
from a11y import set_accessible_label
from audio_pill import AudioPill, format_length, sane_rate
from gtk_utils import DelayedPulse


class _Surface:
    """What both spoken-reading surfaces share: a back-reference to the pane,
    read-only proxies onto the pane state they address, and the one moment
    either of them has to speak."""

    def __init__(self, pane):
        self._pane = pane

    # ── Proxies onto pane-owned state ───────────────────────────────────────

    @property
    def _module(self):
        return self._pane._module

    @property
    def _book(self):
        return self._pane._book

    @property
    def _chapter(self):
        return self._pane._chapter

    @property
    def _on_toast(self):
        return self._pane._on_toast

    def _is_verse_navigable(self):
        return self._pane._is_verse_navigable()

    def _report_audio_failure(self, button, message):
        """Say what went wrong — for either of the pane's two players.

        The icon returning to play is not an explanation: it is the same
        thing the reader sees when a reading ends, and it leaves them to
        guess whether the app, the network or the recording is at fault.
        This is the one moment these controls have to speak.
        """
        a11y.announce(button, message, urgent=True)
        if self._on_toast:
            self._on_toast(message)


class DevotionalAudio(_Surface):
    """A published reading of the day's devotional, played from the chrome row
    the date navigation already occupies. Two rules shape it:

      * the clock decides which half of the day is meant, exactly as the
        Today page's epigraph does — pressing play in the morning plays the
        morning reading, and nobody has to choose;
      * the other half is reachable but not advertised — it appears on hover
        or on keyboard focus, so the row stays a date navigator with a play
        button rather than becoming a media bar.

    The control is built only if the feature is on AND the day actually has a
    reading: an absent episode leaves no button, never a dead one.

    Its widgets are built into the row the pane hands it; the pane keeps only
    the progress bar's placement, because that hairline sits under the row
    rather than in it.
    """

    @property
    def progress(self):
        """The hairline under the date row. The pane places it in the date-nav
        stack; everything that fills it lives here."""
        return self._devot_progress

    @property
    def _devotional_date(self):
        return self._pane._devotional_date

    def build(self, row):
        self._devot_player = None
        # What the desktop's media bus shows for this reading, while it holds
        # the bus. Both of the pane's players can reach it; the last to start
        # owns it, as on any desktop.
        self._devot_media = None
        self._devot_play_btn = Gtk.Button(icon_name='media-playback-start-symbolic')
        self._devot_play_btn.add_css_class('flat')
        self._devot_play_btn.add_css_class('devotional-play')
        self._devot_play_btn.connect('clicked', self._on_devot_play)
        self._devot_alt_btn = Gtk.Button()
        self._devot_alt_btn.add_css_class('flat')
        self._devot_alt_btn.add_css_class('devotional-alt')
        self._devot_alt_btn.connect('clicked', self._on_devot_alt)
        # Hidden until the row is pointed at or focused — see the CSS; the
        # widget stays in the layout so revealing it never shifts the row.
        audio = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        audio.add_css_class('devotional-audio')
        # A hairline of its own: listening and moving between days are two
        # different things, and undivided they read as one undifferentiated
        # strip with the back arrow pushed out of the place the eye expects.
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.add_css_class('devotional-audio-rule')
        audio.append(sep)
        # The reading in hand is named plainly and always. Without it the
        # alternate's label was the only word in the row, so "Evening" beside
        # a pause icon read as what was playing rather than as what was on
        # offer — the opposite of the truth.
        self._devot_cur_lbl = Gtk.Label()
        self._devot_cur_lbl.add_css_class('devotional-current')
        audio.append(self._devot_play_btn)
        audio.append(self._devot_cur_lbl)
        audio.append(self._devot_alt_btn)
        audio.set_visible(False)
        row.append(audio)
        self._devot_audio_row = audio
        # Where the reading has got to: a hairline under the row, filling as
        # it plays. No elapsed time and no scrubber — the page counts nothing
        # else either (see today_page.progress_whisper).
        self._devot_progress = Gtk.ProgressBar()
        self._devot_progress.add_css_class('reading-progress')
        self._devot_progress.set_visible(False)
        self._devot_session = None
        self._devot_tick = None
        # The fetch, on the same terms as the chapter reading's: shown on the
        # hairline once the wait outlasts the threshold, never as a pause.
        self._devot_fetching = False
        self._devot_key = f'devot-audio:{id(self)}'
        self._devot_wait = DelayedPulse(
            show=lambda: self._devot_progress.set_visible(True),
            tick=self._devot_progress.pulse,
            hide=self._clear_devot_band)

    def _sync_devotional_audio(self, date_obj):
        """Offer the player for this day, or withdraw it entirely.

        Absent the Advanced ▸ audio opt-out, the control appears when the open
        module is a devotional this feed actually reads AND the feed has
        published that day's reading — otherwise there is simply nothing
        there, which is the honest state and never a dead button.
        """
        if self._devot_audio_row is None:
            return
        self._stop_devotional_audio()
        if not settings.get('show_audio'):
            self._devot_audio_row.set_visible(False)
            return
        if date_obj is None or not devotional_audio.covers_module(self._module):
            self._devot_audio_row.set_visible(False)
            return
        session = devotional_audio.session_for_hour(
            datetime.datetime.now().hour)
        if devotional_audio.episode_url(date_obj, session) is None:
            # No index yet (or it has aged out). Fetch it off the UI thread
            # and come back — the control stays absent until it is known to
            # work, rather than appearing and then failing.
            self._devot_audio_row.set_visible(False)
            tasks.submit(
                key=f'devot-index:{id(self)}',
                work=lambda _t: devotional_audio.refresh_index(),
                apply=lambda _idx: self._on_devot_index(date_obj),
                on_error=lambda _e: None)
            return
        self._show_devotional_audio(date_obj, session)

    def _on_devot_index(self, date_obj):
        """The feed index has arrived; offer the control if it helps."""
        if self._devot_audio_row is None or self._devotional_date != date_obj:
            return
        session = devotional_audio.session_for_hour(
            datetime.datetime.now().hour)
        if devotional_audio.episode_url(date_obj, session) is not None:
            self._show_devotional_audio(date_obj, session)

    def _show_devotional_audio(self, date_obj, session):
        self._devot_audio_row.set_visible(True)
        self._devot_session = session
        self._devot_date = date_obj
        self._refresh_devot_labels()

    def _on_devot_alt(self, _btn):
        """Switch to the other reading of this day and start it.

        The alternate always names what it will switch TO, never what is
        playing — so it has to be relabelled the moment it is used, or it goes
        on offering the reading you just chose.
        """
        self._devot_session = ('evening' if self._devot_session == 'morning'
                               else 'morning')
        self._stop_devotional_audio()
        self._refresh_devot_labels()
        self._on_devot_play(None)

    def _refresh_devot_labels(self):
        """Name the current reading on the play button and the other one on
        the alternate. The play button carries the only statement of which
        reading is in hand — there is no second line of chrome saying so."""
        session = self._devot_session
        other = 'evening' if session == 'morning' else 'morning'
        current_name = _('Evening') if session == 'evening' else _('Morning')
        other_name = _('Evening') if other == 'evening' else _('Morning')
        self._devot_cur_lbl.set_text(current_name)
        self._devot_alt_btn.set_label(other_name)
        self._devot_alt_btn.set_visible(
            devotional_audio.episode_url(self._devot_date, other) is not None)
        self._devot_play_btn.set_tooltip_text(current_name)
        self._devot_alt_btn.set_tooltip_text(other_name)
        set_accessible_label(
            self._devot_play_btn,
            _('Play the evening reading') if session == 'evening'
            else _('Play the morning reading'))
        set_accessible_label(
            self._devot_alt_btn,
            _('Switch to the morning reading') if other == 'morning'
            else _('Switch to the evening reading'))

    def _on_devot_play(self, _btn):
        if self._devot_fetching:
            self._end_devot_fetch()
            tasks.cancel(self._devot_key)
            return
        if self._devot_player is not None and self._devot_player.playing:
            self._devot_player.pause()
            self._devot_play_btn.set_icon_name('media-playback-start-symbolic')
            mpris.update(self._devot_media)
            return
        url = devotional_audio.episode_url(self._devot_date,
                                           self._devot_session)
        if not url:
            return
        cached = devotional_audio.cached_episode(url)
        if cached:
            self._start_devotional_audio(cached)
            return
        # Fetched once, then kept: the reading is ~5 MB and this is the only
        # moment the feature touches the network. Until it is here there is
        # nothing to hear, so the button shows the fetch rather than claiming
        # a playback that has not started.
        self._begin_devot_fetch()
        tasks.submit(
            key=self._devot_key,
            work=lambda _t: devotional_audio.fetch_episode(url),
            apply=self._finish_devot_fetch,
            on_error=lambda _e: self._finish_devot_fetch(None))

    def _begin_devot_fetch(self):
        self._devot_fetching = True
        stop = _('Stop fetching the reading')
        self._devot_play_btn.set_icon_name('media-playback-stop-symbolic')
        self._devot_play_btn.set_tooltip_text(stop)
        set_accessible_label(self._devot_play_btn, stop)
        a11y.announce(self._devot_play_btn, _('Fetching the reading'))
        self._devot_wait.start()

    def _clear_devot_band(self):
        self._devot_progress.set_fraction(0.0)
        self._devot_progress.set_visible(False)

    def _end_devot_fetch(self):
        if not getattr(self, '_devot_fetching', False):
            return
        self._devot_fetching = False
        self._devot_wait.stop()
        self._devot_play_btn.set_icon_name('media-playback-start-symbolic')
        # The button's own wording is Morning or Evening, which is a fact
        # about the day rather than about this control — so it is restated
        # from the day, not remembered here.
        self._refresh_devot_labels()

    def _finish_devot_fetch(self, path):
        self._end_devot_fetch()
        if not path:
            self._report_audio_failure(
                self._devot_play_btn, _('Could not fetch the reading'))
            return
        self._start_devotional_audio(path)

    def _start_devotional_audio(self, path):
        if not path:
            self._devot_play_btn.set_icon_name('media-playback-start-symbolic')
            return
        if self._devot_player is None:
            self._devot_player = devotional_audio.Player()
        if not self._devot_player.play(path):
            self._devot_play_btn.set_icon_name('media-playback-start-symbolic')
            self._report_audio_failure(
                self._devot_play_btn, _('Could not play the reading'))
            return
        self._devot_play_btn.set_icon_name('media-playback-pause-symbolic')
        self._publish_devot_media()
        # Straight from the fetch's pulse to the reading's position, so the
        # hairline never blinks out between the two.
        self._devot_progress.set_fraction(self._devot_player.progress())
        self._devot_progress.set_visible(True)
        if self._devot_tick is None:
            self._devot_tick = GLib.timeout_add(
                500, self._on_devotional_audio_tick)

    def _publish_devot_media(self):
        """Hand the devotional to the desktop. Titled by the half of the day
        it belongs to, which is the whole of what this reading is — the book
        beside it says the rest."""
        title = (_('Evening') if self._devot_session == 'evening'
                 else _('Morning'))
        if self._devot_media is None or self._devot_media.title != title:
            self._devot_media = mpris.Reading(
                title, devotional_audio.MORNING_EVENING_SERIES,
                player=self._devot_player,
                on_play=lambda: self._on_devot_play(None),
                on_pause=lambda: self._on_devot_play(None),
                on_stop=self._stop_devotional_audio)
            mpris.publish(self._devot_media)
            return
        self._devot_media.player = self._devot_player
        mpris.update(self._devot_media)

    def _on_devotional_audio_tick(self):
        if self._devot_player is None:
            self._devot_tick = None
            return GLib.SOURCE_REMOVE
        if self._devot_player.ended():
            self._stop_devotional_audio()
            return GLib.SOURCE_REMOVE
        self._devot_progress.set_fraction(self._devot_player.progress())
        self._devot_progress.set_visible(True)
        return GLib.SOURCE_CONTINUE

    def _stop_devotional_audio(self):
        # A fetch still in flight belongs to the day and session that were on
        # screen when play was pressed, and would start playing after the
        # reader had moved on.
        tasks.cancel(getattr(self, '_devot_key', ''))
        self._end_devot_fetch()
        if self._devot_tick is not None:
            GLib.source_remove(self._devot_tick)
            self._devot_tick = None
        if self._devot_player is not None:
            self._devot_player.stop()
            self._devot_player = None
        mpris.withdraw(self._devot_media)
        self._devot_media = None
        if self._devot_audio_row is not None:
            self._devot_play_btn.set_icon_name('media-playback-start-symbolic')
            self._devot_progress.set_fraction(0.0)
            self._devot_progress.set_visible(False)

class ReadingAudio(_Surface):
    """The chapter (or psalm) read aloud, and the listening pill that governs
    it.

    The pill outlives navigation — a reading plays on while the reader pages
    through the text — so this surface holds two references at once: the
    reading that is sounding, and the chapter on screen. Keeping them apart is
    most of what the class does.
    """

    def __init__(self, pane, toolbar):
        super().__init__(pane)
        self._reading_audio = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                      spacing=2)
        self._reading_audio.add_css_class('devotional-audio')
        # Headphones, not a play glyph: this opens the listening surface, and
        # the play control lives on that surface. It is the split Kindle and
        # Substack both make — headphones mean "there is a reading of this",
        # play means "start it" — and it keeps the toolbar honest, because
        # one press can no longer both summon a player and claim playback.
        # The app's own headphones, not the stock audio-headphones-symbolic:
        # that one lives in the DEVICES category, so it is whatever the
        # reader's icon theme says it is — Zorin's copy has no viewBox and a
        # hardcoded fill, and GTK's recolour of it drew a solid block in the
        # toolbar.
        self._reading_play_btn = Gtk.Button(
            icon_name='scriptura-headphones-symbolic')
        self._reading_play_btn.add_css_class('flat')
        self._reading_play_btn.add_css_class('pane-action')
        self._reading_play_btn.connect('clicked', self._on_reading_listen)
        self._reading_audio.append(self._reading_play_btn)
        self._reading_audio.set_visible(False)
        toolbar.append(self._reading_audio)
        self._reading_player = None
        self._reading_tick = None
        self._reading_url = None
        # Which source the offered reading came from — it decides which cache
        # the file is fetched into and looked for.
        self._reading_scripture = False
        # The fetch that stands between pressing play and hearing anything:
        # whether one is running, and the button's own idle wording, which
        # the fetch borrows and gives back. What shows the wait is built with
        # the progress band, below.
        self._reading_fetching = False
        # What the pill names while it plays. Audio outlives navigation, so
        # this is the only thing on screen that can say what is sounding once
        # the reader has moved on to another chapter.
        self._reading_reference = ''
        self._reading_length = ''
        self._reading_key = f'reading-audio:{id(self)}'
        # What the player holds, as (path, reference) — the reading that is
        # sounding, which is not the chapter on screen once the reader pages
        # on. None when nothing is open. The pill names this in preference to
        # the offer, and while it is set the pill may not be put away: it
        # carries the only pause and the only stop there is.
        self._sounding = None
        # The reference of a fetch in flight. The pill's controls act on it
        # exactly as they act on a sounding reading — the reader pressed play
        # on that chapter — so it has to be nameable while the file is still
        # on its way and there is nothing open to ask.
        self._pending = None
        # What the desktop's media bus is showing for this pane's reading,
        # while it is the reading that holds the bus.
        self._reading_media = None
        # A progress line and a player are two answers to one question, and
        # the pill is the better one. It floats at the foot of the reading
        # area — the pane adds it to the chrome overlay, which is the only
        # thing about it the pane knows.
        self._pill = AudioPill(on_play_pause=self._on_reading_play,
                               on_back=self._on_reading_back,
                               on_close=self._on_reading_close,
                               on_rate=self._on_reading_rate,
                               on_switch=self._on_reading_switch)
        self._pill.set_rate(settings.get('reading_rate'))

    @property
    def pill(self):
        """The listening surface. The pane adds it to the chrome overlay and
        casts it in the reading paper; it is governed from here."""
        return self._pill

    def _sync_reading_audio(self):
        """Offer a reading of the chapter on screen, or withdraw the control.

        Same rule as the devotional: the control exists when there is
        something behind it and not otherwise.

        Two sources, in this order. The Berean Standard Bible's own reading is
        preferred wherever it applies, because it is the very text on the page
        spoken aloud, and because its address is computed rather than looked
        up — no index, no network, and no chance of offering the wrong
        chapter. Crossway's psalm episodes cover the Psalms in every other
        translation; their index is fetched off the UI thread the first time a
        psalm is opened, so a cold start shows nothing for a moment rather
        than a button that cannot yet work.

        This changes the offer and never what is sounding. A reading plays on
        while the reader pages through the text — that is most of the point of
        naming the chapter on the pill — so the only thing paging does here is
        re-address the play button. The reader's own "no spoken readings" is
        different, and does silence it.
        """
        self._reading_url = None
        self._reading_audio.set_visible(False)
        if not settings.get('show_audio'):
            self._stop_reading_audio()
            self._pill.dismiss()
            return
        if not self._is_verse_navigable():
            self._dismiss_pill_if_idle()
            return
        if bible_audio.covers_module(self._module):
            url = bible_audio.chapter_url(self._book, self._chapter)
            if url is not None:
                self._offer_reading_audio(
                    url, _('Listen to this chapter'), scripture=True,
                    reference=f'{book_label(self._book)} {self._chapter}')
                return
        if self._book != 'Psalms':
            self._dismiss_pill_if_idle()
            return
        got = devotional_audio.psalm_episode_url(self._chapter)
        if got is None:
            chapter = self._chapter
            tasks.submit(
                key=f'psalm-index:{id(self)}',
                work=lambda _t: devotional_audio.refresh_index(
                    feed=devotional_audio.PSALMS_FEED_URL),
                apply=lambda _i: self._on_psalm_index(chapter),
                on_error=lambda _e: None)
            self._dismiss_pill_if_idle()
            return
        self._offer_psalm_audio(got)

    def _reading_is_live(self):
        """Whether a reading is sounding or on its way to being heard. The
        pill stays up for as long as this is true, wherever the reader has
        navigated to: it holds the pause, and closing it is the stop."""
        return self._sounding is not None or self._reading_fetching

    def _dismiss_pill_if_idle(self):
        """Put the pill away only if it is not governing a reading. A chapter
        with nothing to listen to withdraws the toolbar's headphones, but it
        cannot take the controls of a reading already under way with it."""
        if not self._reading_is_live():
            self._pill.dismiss()

    def _live_reference(self):
        """What the pill's controls are acting on — the reading that is
        sounding, or the one being fetched — and None when they govern
        nothing, which is when the chapter on screen is all there is to
        name."""
        if self._sounding is not None:
            return self._sounding[1]
        return self._pending

    def _restate_pill_reading(self):
        """Name what the pill governs, and the chapter on screen only when it
        governs nothing. The two part company the moment the reader pages on,
        and the live one wins — it is what the controls beside it act on.

        Where they have parted company, the switch appears naming the chapter
        on screen: it is the only way to start that chapter without first
        stopping the reading in hand, and it exists in no other state.
        """
        live = self._live_reference()
        if live is not None:
            self._pill.set_reading(live, self._reading_length)
        else:
            self._pill.set_reading(self._reading_reference)
        on_screen = self._reading_reference if self._reading_url else ''
        if live is not None and on_screen and on_screen != live:
            self._pill.set_switch(on_screen)
        else:
            self._pill.set_switch('')

    def _on_psalm_index(self, chapter):
        if self._book != 'Psalms' or self._chapter != chapter:
            return
        # The scripture reading may have claimed the control while the index
        # was in flight (a translation switch), and it outranks this one.
        if self._reading_url is not None:
            return
        got = devotional_audio.psalm_episode_url(chapter)
        if got is not None:
            self._offer_psalm_audio(got)

    def _offer_psalm_audio(self, got):
        url, subtitle = got
        # The publisher's own title for the psalm, which says more than
        # "play" ever could.
        self._offer_reading_audio(url, subtitle or _('Listen to this psalm'),
                                  scripture=False,
                                  label=_('Listen to this psalm'),
                                  reference=f'{book_label("Psalms")} '
                                            f'{self._chapter}')

    def _offer_reading_audio(self, url, tooltip, scripture, label=None,
                             reference=None):
        self._reading_url = url
        self._reading_scripture = scripture
        self._reading_audio.set_visible(True)
        self._reading_reference = reference or tooltip
        if not self._reading_is_live():
            # The length belongs to the open file, so it may only be cleared
            # when there is no open file. Clearing it on navigation used to be
            # safe because navigation stopped the reading.
            self._reading_length = ''
        self._reading_play_btn.set_tooltip_text(tooltip)
        set_accessible_label(self._reading_play_btn, label or tooltip)
        self._restate_pill_reading()

    def _cached_reading(self, url):
        return (bible_audio.cached_chapter(url) if self._reading_scripture
                else devotional_audio.cached_episode(url))

    def _on_reading_listen(self, _btn):
        """The headphone button: summon the listening surface, or put it away.

        It does not start anything. The pill carries the play control, so a
        reader who opens it and changes their mind has closed a player rather
        than stopped a reading they never wanted.
        """
        if self._pill.is_shown():
            self._on_reading_close()
            return
        self._restate_pill_reading()
        self._pill.set_can_seek(self._reading_player is not None)
        self._pill.present()

    def _on_reading_close(self):
        """Dismiss the pill, and with it whatever it was controlling. Closing
        a player that is still sounding and leaving the sound running would be
        a control the reader can no longer reach."""
        self._stop_reading_audio()
        self._pill.dismiss()

    def _on_reading_rate(self, rate):
        """Remember the speed, and apply it to whatever is sounding now.

        Stored for the app rather than for this chapter: a reader who has
        found the pace they follow the text at has found it for good. The
        Today page's devotional and the date-row player keep the narrator's
        own pace — the control that sets this lives on the pill, and a speed
        chosen there should not silently reach surfaces that do not show it.
        """
        settings.put('reading_rate', rate)
        # The pane owns the stored speed, so it also owns what the pill says:
        # restating it here means the label can never drift from what is
        # actually playing, whoever asked for the change.
        self._pill.set_rate(rate)
        if self._reading_player is not None:
            self._reading_player.set_rate(rate)
        mpris.update(self._reading_media)

    def _on_reading_back(self):
        """Fifteen seconds back. Backward only, because the need that arises
        while reading along is "I missed that" and never "get on with it"."""
        if self._reading_player is not None:
            self._reading_player.seek_relative(-15)

    def _on_reading_switch(self):
        """Read the chapter on screen instead of the one in hand.

        The reading in hand is not paused and set aside: it is stopped, and
        the reader's place in it is not kept. That is what every player does
        when a second item is started — the one that was playing is replaced,
        with no question asked and no queue behind it — and keeping a place
        the pill has no way to name or return to would be a promise this
        surface cannot show, let alone honour.

        Stopping first is also what makes this one press rather than two: the
        play button beside it belongs to what is sounding, and it says so, so
        it can never be the control that starts something else.
        """
        if not self._reading_url:
            return
        self._stop_reading_audio()
        self._on_reading_play()

    def _on_reading_play(self):
        if self._reading_fetching:
            # A chapter is six megabytes and can be twenty; a reader who
            # changes their mind must not have to wait the fetch out, and the
            # button they pressed is where they will look to say so.
            self._end_reading_fetch()
            tasks.cancel(self._reading_key)
            return
        if self._reading_player is not None and self._reading_player.playing:
            self._reading_player.pause()
            self._pill.set_state('idle')
            mpris.update(self._reading_media)
            return
        if self._sounding is not None:
            # Paused, and the reader has since paged on: this button belongs to
            # the reading it has been showing all along, so it resumes that and
            # not the chapter that happens to be on screen now. Starting the
            # new one here would be the pill doing something other than what it
            # says, and it would lose the reader's place in the old one.
            path, reference = self._sounding
            self._start_reading_audio(path, reference)
            return
        if not self._reading_url:
            return
        cached = self._cached_reading(self._reading_url)
        if cached:
            self._start_reading_audio(cached, self._reading_reference,
                                      self._reading_series())
            return
        # Nothing can be heard until the file is here, so the pause icon at
        # this point would claim playback of a silence — and on a slow line
        # it would claim it for half a minute before flipping back with no
        # word of why. The control shows the fetch as a fetch instead, and
        # turns to pause only when sound actually starts.
        url = self._reading_url
        fetch = (bible_audio.fetch_chapter if self._reading_scripture
                 else devotional_audio.fetch_episode)
        # Carried, not read again when it lands: the reader may well have paged
        # on during a twenty-megabyte fetch, and what arrives is the chapter
        # they pressed play on.
        reference = self._reading_reference
        series = self._reading_series()
        self._begin_reading_fetch(reference)
        tasks.submit(
            key=self._reading_key,
            work=lambda _t: fetch(url),
            apply=lambda path: self._finish_reading_fetch(
                path, reference, series),
            on_error=lambda _e: self._finish_reading_fetch(
                None, reference, series))

    def _reading_series(self):
        """What the reading on offer is a reading OF — the translation for a
        chapter, the publisher's series for a psalm episode. Read at the
        moment play is pressed and carried from there: by the time a
        twenty-megabyte fetch lands, the pane may be showing the other one.
        """
        return (bible_audio.TRANSLATION if self._reading_scripture
                else devotional_audio.PSALMS_SERIES)

    def _begin_reading_fetch(self, reference=None):
        """Dress the pill for the wait: a stop, not a playback state. The
        thread pulses once the wait outlasts the threshold — the pill owns
        that timing itself.

        `reference` is the chapter being fetched, and the pill names it for as
        long as the fetch runs: paging on during a twenty-megabyte wait used
        to leave the pill naming the chapter that had just come on screen
        while the controls beside it still belonged to the one being fetched.
        """
        self._reading_fetching = True
        self._pending = reference
        self._pill.set_state('fetching')
        self._restate_pill_reading()
        a11y.announce(self._pill, _('Fetching the reading'))

    def _end_reading_fetch(self):
        """Return the control to rest — success, failure and cancel alike."""
        if not getattr(self, '_reading_fetching', False):
            return
        self._reading_fetching = False
        self._pending = None
        self._pill.set_state('idle')
        self._restate_pill_reading()

    def _finish_reading_fetch(self, path, reference=None, series=''):
        self._end_reading_fetch()
        if not path:
            # Named no closer than this on purpose: fetch_episode answers
            # every failure with None, so a connection, a DNS miss and a
            # publisher's 404 arrive here indistinguishable, and naming the
            # likeliest would send half the readers who see it to fix the
            # wrong thing.
            self._report_audio_failure(
                self._pill, _('Could not fetch the reading'))
            return
        self._start_reading_audio(path, reference, series)

    def _start_reading_audio(self, path, reference=None, series=''):
        """Play `path`, or resume it where the player already holds it.

        `reference` is what the pill will name until this reading stops, and
        it is passed in rather than read off the pane: by the time a fetch
        lands, or a paused reading is resumed, the chapter on screen may be a
        different one entirely. `series` names what it is a reading of, for
        the desktop; a resume carries none, because the bus already holds it.
        """
        if not path:
            self._pill.set_state('idle')
            return
        if self._reading_player is None:
            self._reading_player = devotional_audio.Player()
        if not self._reading_player.play(path):
            self._pill.set_state('idle')
            self._report_audio_failure(
                self._pill, _('Could not play the reading'))
            return
        self._reading_player.set_rate(sane_rate(settings.get('reading_rate')))
        if self._sounding is None or self._sounding[0] != path:
            # A different file: its length is not the last one's, and is not
            # answerable yet either.
            self._reading_length = ''
        self._sounding = (path, reference or self._reading_reference)
        self._publish_reading_media(self._sounding[1], series)
        self._restate_pill_reading()
        self._pill.set_state('playing')
        self._pill.set_can_seek(True)
        # The thread takes over from the fetch's pulse here rather than at the
        # first tick, so it never blinks out between the two. The length is
        # stated once, now that the file is open and can be asked.
        self._pill.set_progress(self._reading_player.progress())
        self._show_reading_length()
        if self._reading_tick is None:
            self._reading_tick = GLib.timeout_add(500, self._on_reading_tick)

    def _publish_reading_media(self, title, series=''):
        """Hand the sounding reading to the desktop, or restate it.

        Replaced rather than restated only when the reading itself has
        changed: a resume after a pause is the same track, and republishing
        it would tell every remote a new one had begun.

        The handlers are the pill's own, so the lock screen and the pill can
        never disagree — a pause from either leaves both showing paused.
        `on_stop` is the close, which is what the stop means here: the pill
        carries the only controls there are, so silencing a reading while
        leaving it up would strand them.
        """
        if self._reading_media is None or self._reading_media.title != title:
            self._reading_media = mpris.Reading(
                title, series, player=self._reading_player,
                on_play=self._on_reading_play,
                on_pause=self._on_reading_play,
                on_stop=self._on_reading_close,
                on_rate=self._on_reading_rate)
            mpris.publish(self._reading_media)
            return
        self._reading_media.player = self._reading_player
        mpris.update(self._reading_media)

    def _show_reading_length(self):
        """State how long the reading runs, once that can be known.

        Playback starts without waiting for the pipeline to preroll, so the
        file's length is usually not answerable at the instant play is
        pressed. It is asked again on each tick until it is, and then left
        alone — a file that never answers (a stream, an encode with no
        header) simply has no length stated.
        """
        if self._reading_length or self._reading_player is None:
            return
        self._reading_length = format_length(self._reading_player.duration())
        if self._reading_length:
            self._restate_pill_reading()
            # The desktop states the length as a number rather than as text,
            # and it could not be asked for until now either.
            mpris.update(self._reading_media)

    def _on_reading_tick(self):
        if self._reading_player is None:
            self._reading_tick = None
            return GLib.SOURCE_REMOVE
        if self._reading_player.ended():
            # The reading stops at the end of the chapter and does not read
            # on. Turning the page under a reader is the app moving the text
            # without being asked.
            self._stop_reading_audio()
            return GLib.SOURCE_REMOVE
        self._pill.set_progress(self._reading_player.progress())
        self._show_reading_length()
        return GLib.SOURCE_CONTINUE

    def _stop_reading_audio(self):
        """Silence the reading and forget it. This is the stop, so it is only
        ever reached deliberately: closing the pill, hiding the pane, turning
        spoken readings off, and a chapter running to its end. Paging through
        the text does not come here.

        A fetch still in flight is cancelled with it — a reader who has just
        stopped a reading is not waiting to have one start.
        """
        tasks.cancel(getattr(self, '_reading_key', ''))
        self._end_reading_fetch()
        if self._reading_tick is not None:
            GLib.source_remove(self._reading_tick)
            self._reading_tick = None
        if self._reading_player is not None:
            self._reading_player.stop()
            self._reading_player = None
        self._sounding = None
        mpris.withdraw(self._reading_media)
        self._reading_media = None
        self._reading_length = ''
        # Nothing is sounding now, so the pill falls back to naming the chapter
        # on screen, with no fill left behind on the thread — it is shared by
        # every module this pane opens.
        if getattr(self, '_pill', None) is not None:
            self._restate_pill_reading()
            self._pill.set_state('idle')
            self._pill.set_progress(0.0)
            self._pill.set_can_seek(False)

