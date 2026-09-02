# Changelog

All notable changes to Scriptura. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/). Versioning is
semver-ish — 0.x was the pre-Flathub testing track.

## [1.6.0] — 2026-09-02

### Added

- **The Book of Generations.** Scripture keeps lists of names and readers
  skip them, so Scriptura draws them, and binds them as a book: one genealogy
  to a page, turned by the arrows in the running foot, from Adam to Noah
  through to Matthew and Luke laid side by side, with the ten lifespans of
  Genesis 5 on one axis so you can see that Methuselah's years run out in the
  flood year. A table of contents lists the eight pages and marks the one you
  are on, and each page keeps its place, so turning away and back returns you
  to the line you left. The charts are live, not pictures — a folded run of
  ten generations opens in place, a name opens the person, a chip opens the
  verse — and the same
  geometry writes printable plates, so what prints and what is on screen
  cannot disagree. Where a genealogy leaves generations out the gap is drawn
  as a gap, says how many, and cites who does name them. Where Matthew and
  Luke disagree both are shown as their writers give them, with the three
  classical answers set out below and attributed, and none of them chosen.
  Every one of the 165 lines carries the verse it comes from; the build reads
  all 186 citations back against the text and fails if one of them does not
  name the people it is drawn from. In English, Spanish and Russian, with the
  names in each read off the Bibles themselves.

- **Scriptura reads in Russian.** The whole interface — 1,134 strings,
  every one of them, with the three plural forms Russian needs — plus the
  Synodal book names it expects: 1 Kings is 3-я Царств. Names are said the
  way Russian Bible software says them: the references beside a verse are
  «Параллельные места», the interlinear is «Подстрочник», and a module is
  named in its own language to the reader running the app in it. Two fonts
  were set in the wrong voice, because the reading serif carries no Cyrillic
  and nobody had asked it to; the verse card and the printed handout now fall
  through to one that does.
- **A modern Russian Bible, and the first Russian dictionary.** Every
  Russian Bible anyone distributes is the 1876 Synodal or a revision of it,
  and the four Russian lexicons in the SWORD repositories are glossaries of
  the Central Asian translations' own terms — so a Russian reader had
  archaic prose and nothing at all behind the double-click. Scriptura now
  builds two modules and serves them from its own release. The Russian Open
  Bible is a modern text from the Door43 community, complete in 66 books, and
  23 of them — the Gospels, Acts, most of Paul, Genesis and Exodus among them
  — carry a Strong's number, lemma and morphological parse on every word,
  167,212 in all, so word study works in Russian for the first time. The
  Bible dictionary holds 1,018 articles on the terms, names and ideas of
  Scripture. Russian's first run now offers two collections instead of one,
  and the reading window opens on the modern text with the Synodal beside
  it.
- **A Spanish dictionary, where there was none.** Every one of the 168
  dictionaries the SWORD repositories distribute is English, French,
  Russian or Portuguese, so for a reader of the Spanish Bibles the
  double-click this app teaches on first run did nothing. Scriptura now
  builds one and serves it from its own release: a million keys from the
  Spanish Wiktionary, with the 2,691 entries of W. W. Rand's
  *Diccionario de la Santa Biblia* of 1890 laid over them, so *Moisés*
  opens on the prophet rather than on a wicker carrycot and
  *circuncisión* on the covenant rather than the surgery. Looking a word
  up follows Spanish too: the accents the 1909 spellings do not carry
  are ignored, and *alegróse* reaches *alegrar*.
- **First run asks which language you read in, and the answer leads.**
  Spanish used to be a fourth card beside three English ones, which made
  a language a kind of collection rather than the question above them: a
  Spanish reader met four choices of which three were the wrong
  language, with the interface in whatever the desktop had decided. The
  first screen now asks the language and sets both the interface and the
  library offered on the second, where the same three collections are
  filled from what that language actually has — and each card counts its
  own contents, so it can no longer promise a commentary the language
  has none of.

### Changed

- **The language cards say what each language holds**, counted from that
  language's own catalogue and written in that language — "3 Biblias · notas
  · diccionario" under Español whatever language the interface is in. The one
  your desktop already asked for is marked, so the screen shows you its answer
  rather than making you find it.
- **The dictionary peek stopped describing dictionaries and started naming
  yours.** Where a word has no entry it used to say that Bible dictionaries
  index proper nouns and key terms and suggest trying "covenant" or
  "atonement" — advice written when the only dictionaries were English Bible
  dictionaries, and false for the Spanish reader whose dictionary answers
  ordinary vocabulary. It now says which dictionaries were searched.
- **Scripture in Stone opens as soon as you ask for it.** The gallery
  decoded all 56 of its photographs before it would appear — 485ms of
  waiting, and 126MB of texture held for as long as it stayed open, to
  show you the two plates that fit on screen. The pictures now load as
  they come into view and are dropped once they are well past it: 102ms
  to open, 31MB held, and nothing moves under you as they arrive.

### Fixed

- **Jumping to a reference took English book names only.** Typing
  «Бытие 3» — the name the book picker two inches away was showing —
  flashed the box red, and had done the same to *Génesis 3* since Spanish
  shipped. The jump bar now takes the name you are reading as well as the
  canonical one, including the part of it you would actually type: Russian
  calls the Gospel «От Иоанна» and a reader types «Иоанна».
- **Book names sat in English inside a translated interface.** The
  cross-reference chips under a verse, and the per-book bars inside a
  search result's chart, were built where the English name is the key and
  never translated on the way out — so «Большие пророки» opened onto
  "Isaiah / Jeremiah / Ezekiel" with «Исаия 1:2» in the results beneath.
- **Scripture in Stone was English in every language.** The gallery is
  curated in TOML, which the string extractor cannot read, so none of its
  342 strings had ever reached a catalogue: a Russian reader opened
  «Писание в камне» onto a page headed "Scripture in Stone" and read 62
  captions, 11 introductions and a 15-entry glossary in a language they
  had not chosen. They are translated now at the one place every display
  site reads from, which covers the page, the artifact dialog and the
  search index together. Three things stay as printed, because a
  photographer's credit, a library catalogue and a verse chip each need
  the words they were given. Two Spanish cards also quoted a Bible no
  Spanish collection installs — every Spanish Bible here has «¡Grande es
  Diana de los efesios!» where the cards said «Artemisa», so the chip
  beside the sentence opened a verse naming someone else.
- **Translated labels overflowed the places that hold them.** A paper
  chip draws its name inside a fixed 56px ring, so «Грифельный» ran
  through it and lost its Г — and the Spanish *Personalizado* had been
  spilling since Spanish shipped. The Module Manager's four tabs share
  one header, and both translations were cut mid-word in the one place
  you are choosing between four of them. The names are shorter now, and
  two tests measure every one of them in every catalogue, in pixels.
- **The menu's cards lost their right-hand corners.** The panel reserves a
  gutter for its scrollbar, and the content underneath it had a minimum
  width equal to the whole panel — one long font name in the appearance
  card was setting it — so the overflow came off the right edge in every
  language. Opening Advanced made the whole panel jump wider, too.
- **A first-run download that failed for a module that exists.** The
  list of available modules is cached and nothing aged it out, so a
  profile that had read the list before a module was published had no
  row for it; the install fell back to a repository that module had
  never been in, and the download 404'd. Every profile that had ever
  opened the Module Manager was in that state when the Spanish
  dictionary shipped — the collection installed, reported a warning, and
  opened a reading window with nothing behind the double-click the same
  screen had just taught. The list is refetched now whenever it has no
  row for something the collection asks for.
- **Closing the first-run window mid-download left part of a library.**
  The install runs in the background and the titlebar close button stayed
  live through all of it, so closing at the fourth module of eight ended
  the app with some of the collection on disk, no record of what to open
  on, and nothing said about either. It asks now: whatever has arrived is
  kept, and it says where the rest can be downloaded later.
- **Russian was set in whichever serif the machine happened to own.** The
  app's reading serif carries no Cyrillic, so every Russian word fell out
  of the chain to a face nobody chose: Georgia on one machine, DejaVu
  Serif on the next. The widest of them was struck through by the
  genealogy charts' own column rails, which broke around a name by the
  size of the type rather than the size of the ink. Russian now sets in a
  serif the app ships with, the same one everywhere, and a rail breaks
  around what is actually on the paper.

### Internal

- Flatpak packaging: the catalogues ship with the app rather than in a
  locale extension that arrives empty on a host set to another language,
  and the icon is one flatpak will export past a validator that can read
  SVG.

## [1.5.0] — 2026-08-19

Scriptura in Spanish, and the books it would not open.

### Added

- **Scriptura speaks Spanish.** The whole application — menus, dialogs,
  the Module Manager, first run, the reading plans, the liturgical
  calendar and all 66 book names. A picker sits in the header of the
  first screen you meet and in the menu thereafter, each language listed
  in its own name.
- **Spanish Bibles, and a Spanish reading.** La Biblia de las Américas
  and the Nueva Biblia de las Américas (Lockman), the Versión Biblia
  Libre, and Straubinger's, whose 13,099 footnotes are paragraph-length
  commentary. La Biblia en Español Sencillo brings text and narration
  from one publisher, all 1,189 chapters.
- **The deuterocanonical books.** A translation that carries them shows
  them in an appendix after Revelation. They were unreachable before:
  the navigation stopped at 66 books, and asking a versification for a
  book it has never heard of clamps to its last one, so Tobit read back
  Revelation without anything looking wrong.
- **Every dictionary you install now appears**, whatever language it is
  in. The list had been filtered to English, which hid a dictionary the
  reader had gone to the Module Manager and installed on purpose.
- **The app draws its own icons.** The toolbar is the same line art on
  every desktop instead of whatever the local icon theme supplies — a
  KDE reader was meeting colour cartoons. The window controls are still
  the desktop's own.
- **Nineteenth-century plates** join the imagery pack, and an installed
  pack that has fallen behind the published one now offers its update.
- **Letter spacing.** Appearance → Advanced now opens the space between
  letters, from the face's own metrics up to a fifth of the type size.
  Widening it is the best-supported thing typography can do for a reader
  who finds text hard going — better than any special typeface — and it
  is set as a proportion of the size, so it holds when you change how
  big the text is.
- **OpenDyslexic is bundled.** The typeface now sits at the top of
  Appearance → Font, so a reader who wants it does not have to go and
  install one. It is offered honestly: testing has found no gain in
  reading speed, and the app says so where you choose it — but readers
  who find it easier find it easier all the same. It reads noticeably
  wider than the serif, so expect a longer chapter.
- **Scriptura follows the desktop's high-contrast setting.** Turn on
  *Accessibility → Seeing → High Contrast* and the app's own outlines
  come with it: the chips, swatches, cards, buttons and panel edges it
  draws are all lifted over the 3:1 contrast the guidelines ask of a
  control's boundary, in both light and dark. Nothing moves and nothing
  changes size — only how clearly each edge is drawn.
- **Readings on the desktop's media controls.** Whatever the app is
  reading aloud — a chapter, a psalm, either devotional — now appears on
  the media keys, the lock screen and the Shell's media control, named by
  what it is: "John 3", from the Berean Standard Bible. Play, pause, stop,
  skip back, reading speed and volume all work from there. There is no
  next or previous, because a reading stops at the end of its chapter and
  does not read on.
- **Quiet the rest of the page.** An optional reading focus: the passage
  you are in stays on lit paper while the rest of the page is laid back
  under a veil of that same paper — its heading stays with it, and
  nothing moves. It follows your scrolling, not your cursor, and it
  needs a translation that marks its own section headings. Appearance →
  Advanced → *Quiet the rest of the page*, off until you ask for it.
- **First run opens on a Bible and a commentary** rather than the same
  text twice, installs the collection you choose for real, and hands you
  the gestures reference where the gestures are taught.

### Fixed

- **Strong's numbers were invisible in the Spanish texts that carry
  them.** SpaRV1909 writes `Strong:` and both copies of the renderer
  read `strong:`, so a fully tagged Bible showed none of its 31 tagged
  verses in Genesis 1 — while search, which ignored case all along,
  found what the page refused to mark.
- **Texts imported from eBible keep their Strong's numbers** instead of
  discarding them at import, and an eBible translation that has fallen
  behind its source now offers an Update — the button used to be there
  whether or not there was anything to update.
- **The page holds still.** Flipping the theme, showing footnote
  markers, switching to old-style figures and lighting the drop cap
  recolour the chapter instead of rebuilding it; where a rebuild remains,
  your reading place is held through it, including in poetry, where the
  probe used to land between lines and lose the position.
- **A settings file the app cannot read is set aside, not overwritten.**
  A backup that did not reach the disk now says so, and a module archive
  that tries to write through a symlink is refused.
- **The lexicon hint no longer fires where tapping a word does nothing** —
  it is now gated on the text actually carrying Strong's numbers.
- **A long footnote now opens.** Where a note runs to an essay rather
  than a line — Straubinger's Spanish Bible writes 2,400 characters of
  commentary on one verse of Psalm 51 — the note asked for a popover
  taller than the window, which GTK will not place, so the marker did
  nothing when clicked while a shorter note two lines below opened first
  time. The note now opens on whichever side of the marker has more room,
  and scrolls inside the peek when it is long. The lexicon's verse peek
  and the Strong's hovercard are held to the same rule, so a long verse
  or a wordy gloss can no longer be unopenable either.
- **Voices of the Church: numbers were losing their thousands.** Four
  quotes printed figures like "Hezekiah routed 185, of the enemy" — a
  parser upstream had been dropping the digits after the comma. Fixed at
  the source and carried in the rebuilt pack, along with Origen on
  Romans and Jeremiah (+914 quotes), two verses reattributed from Jerome
  to Pseudo-Jerome, and a commentary wrongly given to Pacian of
  Barcelona removed. Installed packs will offer the update.

## [1.4.0] — 2026-07-27

Chapters read aloud, and passages you can take with you.

### Added

- **Chapters read aloud.** With the Berean Standard Bible open, the
  headphones in the pane toolbar bring up a small player over the page —
  the whole canon, all 1189 chapters, narrated by Bob Souer and dedicated
  to the public domain by the translation's own publisher. It carries
  play, back fifteen seconds, how far through you are, how long the
  chapter runs, and a reading speed from 0.75× to 2× that holds the
  narrator's pitch — set it once and every chapter follows. The player is
  drawn from your own paper and ink, so it belongs to the page rather
  than sitting on it. Chapters are fetched one at a time as you press
  play and kept for later, so a chapter you have heard stays available
  offline; a fetch that fails now says so instead of quietly stopping.
  Turn it all off under Appearance → Advanced → *Spoken readings*.
- **Spoken devotionals** from their publishers' own feeds — Spurgeon's
  Morning and Evening, the Psalms read one at a time, and the day's
  Daily Strength reading on the Today page.
- **Take a passage with you.** Export it as a study worksheet in Markdown
  or plain text, carrying your own notes and highlights, with optional
  interlinear, textual-variant and church-fathers layers. Citations
  follow the SBTS/Turabian short form.
- **A verse as an image**, set in the app's own serif on its own paper —
  three shapes, saved to a file or copied straight to the clipboard.
- **Print a passage** as a study handout, paginated so no line is ever
  cut in half.
- **The section headings your translation ships.** Until now they were
  dropped altogether. Move a whole thought at a time with `[` and `]`,
  and see at a glance which sense-unit you are reading.
- **The reading pane from the keyboard, throughout.** Step between verses
  and words with the arrow keys, open the lexicon, a footnote or the
  dictionary with Enter, and hear every move announced by a screen
  reader.
- **More of the Roman calendar's collects**, and a steadier Today page.

### Fixed

- **Modules keep installing when CrossWire's server is down.** The app
  falls back to FTP, and then to a mirror of everything CrossWire's own
  licences allow anyone to redistribute.
- Every translation now gets its verse-one drop cap, and commentaries
  render the inline titles they carry.

## [1.3.0] — 2026-07-10

The original languages, word by word.

### Added

- **Two interlinear reading surfaces** — the Greek New Testament and the
  Hebrew Old Testament (Tyndale House data). Every word carries its
  English gloss and parsing, with transliteration and Strong's numbers a
  chip away and the lexicon a click away. A Hebrew Accents chip calms the
  cantillation marks.
- **A Scholar's Greek Lexicon pack.** Abbott-Smith becomes the brief
  Greek entry, with the full Liddell-Scott-Jones one click deeper.
  Scripture citations inside entries are live — click one to peek the
  verse in place, or send it to the other pane.
- **Presentation mode.** Press F5 to project the current passage
  full-screen for a projector or mirrored display, with paging through
  chapters, a verse-per-page toggle, live type-size control, and a
  side-by-side parallel view of two translations.
- **Passage chips on the maps.** A map in Scripture in Art carries its
  passage as a chip — click it to drive the partnered Bible pane there.
  The Historical Commentaries pane shows place chips for the verse under
  commentary: click one for the place's photo and identification, without
  displacing what you're reading.

### Fixed

- Greek in the reading panes now renders with correctly composed accents
  on systems where the default serif drew them detached.

## [1.2.0] — 2026-07-05

Getting started, made discoverable.

### Added

- **Tips & Gestures.** A guide in the menu gathering every reading
  gesture in one place.
- **Gentle one-time tips** point out a hidden gesture — tapping a verse
  for its cross-references — the first time it is useful, then never
  again. You can turn them off at any time.

## [1.1.0] — 2026-06-28

Customizable reading appearance.

### Added

- **A reading appearance you choose.** A new Appearance panel: pick the
  paper — Paper, White, Sepia, Green, or a colour of your own — with ink
  that adapts to the page, a warm one on sepia and so on.
- **Reading plans redesigned** around a Today view and a month calendar
  of your progress.
- **Historical Commentaries.** An optional church-history commentary
  pane: how the church read each verse across time — the ante-Nicene
  fathers, the medieval doctors, and the Reformers — as chronological
  cards grouped by era, synced to the verse you're studying. Download
  the pack from Module Manager → Open Databases (compiled from the
  public-domain HistoricalChristianFaith Commentaries Database).
- **Import your own SWORD modules.** A `.zip` you already have on disk
  (a commercial translation, a shared draft, anything CrossWire doesn't
  carry) installs via Module Manager — an import button plus drag-and-
  drop, with a preview sheet and support for cipher-locked modules.
- **Remove a module from the pane picker.** The picker's info page now
  has a "Remove module" action, behind a confirmation.
- **Manage search history.** Each recent search has a remove button, a
  "Clear" button wipes the list, and searching an empty field returns
  to the recent-searches view.
- **Guided first run.** The welcome screen now offers three curated
  starting points — *Just reading*, *Reading + study* (recommended), and
  *Full library* — framed by what you get rather than by SWORD module
  names, so a newcomer can pick one and start reading. Everything stays
  addable or removable later from the Module Manager.

### Fixed

- Faint text trails when scrolling the reading view under Flatpak.
- Wrong/missing cipher key on an encrypted module now shows a "the
  cipher key may be incorrect" message with an Edit Key action instead
  of rendering gibberish (or nothing).
- Global keyboard shortcuts now work reliably from launch and after the
  window loses and regains focus. They were dispatched through a
  focus-dependent key handler that went dead whenever no widget held
  focus on Wayland; they're now window actions with accelerators.
- The chapter-note editor now opens as a dialog instead of a popover, so
  its text field reliably accepts keyboard input on Wayland.
- Verse highlights (and the search-match and navigation-flash highlights)
  now render as uniform bands that hug the text — no more tall blocks on
  the drop-cap line, notches around verse numbers, or per-verse stepping
  — and stay aligned at any font size, line spacing, or margin.

### Changed

- Bold and justified move to compact controls beside the font, and the
  menu's sections gain a clearer, calmer layout.
- **Empty placeholders are now actionable.** The “can’t read this module
  here” and “passage isn’t in this module” pages offer a *Choose another
  module* button (it opens the module picker), and a locked module offers
  *Edit Key* — instead of only describing what to do.
- **UI polish pass.** Consistent transition timing across panels and menus,
  search-result bars that follow your GNOME accent colour, and the lexicon
  toggle regrouped with the reading-view controls rather than the
  navigation buttons.

### Internal

- **Shared empty-state widget** (`empty_state.py`) deduplicates the compact
  placeholder used by the search panel and study journal; `style.css` now
  documents the spacing / radius / motion scale as a convention.

- **`content.py` routing facade** over the SWORD / eBible / catena
  bridges, so source dispatch lives in one place rather than scattered
  `if/elif` chains.
- **`ModulePicker` extracted** from `pane.py` into `module_picker.py`
  (the module selector popover); plus a consolidated module-flag helper.
  From a whole-app code review.
- **Keyboard shortcuts as GActions.** Global shortcuts moved to window
  actions + `set_accels_for_action`; the Keyboard Shortcuts window is now
  an `Adw.Dialog` with `Gtk.ShortcutLabel` key-caps read back from the
  action map. Only Escape and Home/End remain on a key controller.
- **Modern dialog / widget pass.** Note editors and the module-import
  sheet converted from transient `Adw.Window` to `Adw.Dialog` (dropping
  their manual Escape handlers); journal export uses `Gtk.FileDialog`;
  the catena and "can't read this module" placeholders use
  `Adw.StatusPage`.
- **Highlights painted, not tag backgrounds.** `BibleTextView` draws the
  verse / search / flash highlights as uniform bands in `do_snapshot` (from
  zero-visual marker tags `hl_bg_<hex>` / `_search_hl` / `_flash`); GTK tag
  backgrounds hug line metrics and broke on the drop cap and small verse
  numbers. Anchored to the display-line start so adjacent bands can't drift.

## [1.0.1] — 2026-05-28

Packaging fixes.

### Changed

- The build moved to meson, for a cleaner Flatpak install.

### Fixed

- SWORD's CMake now links libcurl properly (upstream bug API-263). It
  had been substituting a deprecated singular variable that modern CMake
  no longer sets, so the link silently pulled in nothing.

### Internal (post-1.0 cleanup)

- **Logging migration.** Replaced ~25 `print('[tag] …')` sites across
  11 modules with the standard `logging` module, rooted at the
  `scriptura.*` logger tree. Exception handlers now use
  `_log.exception()` so caught errors include a traceback —
  invaluable for debugging user-reported SWORD setup issues.
  Verbosity is controlled with `SCRIPTURA_LOG_LEVEL` (default
  `WARNING`); README's "Reporting bugs" section asks users to attach
  the `DEBUG` output to issues.
- **`Adw.MessageDialog` → `Adw.AlertDialog`** in `study_journal.py`
  (rename / delete tag, export error). `MessageDialog` is deprecated
  in libadwaita 1.6 and emits runtime warnings.
- **Tests for the pure-Python bridges.** 91 new tests across
  `paths.py` (XDG resolution + legacy migration), `bookmarks.py`,
  `settings.py` (debounce + corrupt-file recovery), and
  `ebible_bridge.py` (USFM parsing + SQLite-backed verse storage).
  Total suite: 227 tests.
- **Type hints — persistence layer.** Annotated `paths`, `bookmarks`,
  `settings`, `annotations`, `module_positions`, `reading_plans` with
  modern syntax (PEP 585/604). Introduced TypedDicts for the
  on-disk shapes (`Bookmark`, `Plan`, `ChapterNoteData`). `mypy.ini`
  enforces `disallow_untyped_defs` on these six modules and runs
  clean (the rest of the tree remains `ignore_errors` for now,
  widening module-by-module). Tooling: `mypy>=1.10` added to
  `requirements-dev.txt`.
- **CSS centralised.** All static styling moved from five inline blocks
  (in `search_panel.py`, `annotation_dialogs.py`, `study_journal.py`,
  `window.py`) into `data/style.css`. A small `styles.py` loader calls
  `Gtk.CssProvider.load_from_path` once at startup. The per-pane dynamic
  CSS (font family, size, line spacing, user-chosen text color) stays
  in `pane.py` since it depends on runtime state. Saved ~160 lines of
  per-module CSS plumbing; one place to edit, with editor syntax
  highlighting and a clearer comment trail about Revealer-shadow and
  `@view_bg_color`-vs-`@card_bg_color` quirks. Flatpak manifest updated
  to install `data/style.css` and the previously-missing
  `genbook_reader.py` and `styles.py`.
- **Generic Books subsystem extracted from `pane.py`.** ~270 lines
  of TreeKey rendering, prev/next/TOC widgets, async fetch, and
  entry-path persistence moved into a new `GenbookReader` class in
  `genbook_reader.py`. `pane.py` drops from 2 681 → 2 381 lines;
  the new file is fully type-hinted and joins the strict mypy
  surface. Behavior is unchanged — same icons, same fallback
  heuristics, same TreeKey auto-scroll. The pane retains
  `_is_genbook` because it gates pane-level chrome and dispatches
  between verse-keyed / genbook / devotional render paths.

## [1.0.0] — 2026-05-23

First Flathub release. The app gets its proper name, a hardened
persistence layer, and the Flatpak packaging story closed.

### Name

- **Renamed from Bible Reader to Scriptura.** Latin for
  *Scripture* — distinctive, memorable, and aligned with the
  audience this app is built for. App-ID is now
  `page.codeberg.andresmessina.Scriptura`.

### New features

- **Pane-swap button** in the headerbar (alongside the single /
  split toggle) — flips the two panes' modules in one click,
  preserving scroll position via the new per-module memory.
- **`bible:` URI scheme** — `xdg-open 'bible:John+3:16'` opens
  Scriptura at the requested reference. Works for both `+`-
  encoded spaces and proper `%20`. Lets external apps
  (browsers, chat clients, notes) link directly into Scripture.
- **Current-verse indicator** — the active verse number wears a
  subtle accent (purple, bold). Persists across annotation saves;
  cleared on chapter change. Distinct from the click-flash and
  from annotation highlights.

### Persistence

- **Per-module position memory.** A single record per module
  tracks the last reading position (top verse for verse-keyed
  modules, entry path for Generic Books). Both panes consult the
  same store, so swapping modules between panes — or opening the
  same module in either pane on next launch — returns to the
  last place it was viewed.
- **Atomic writes** across every state file (annotations,
  bookmarks, settings, module positions). A crash mid-write
  leaves the original file intact instead of truncating it — your
  annotations are no longer at risk if the system loses power
  during a save.
- **Debounced + locked-down module-position writes.** A pane
  swap fires two module changes in quick succession; the
  debounce coalesces them into one disk write, and the lock is
  released before disk I/O so concurrent callers don't serialise.

### Performance

- **LRU caps on chapter and Strong's caches.** Reading the entire
  canon in one session previously grew memory by ~230 MB. The
  cap holds steady-state at ~175 MB. Re-rendering an evicted
  chapter costs one SWORD round-trip (~20–80 ms).
- **Lazy Whoosh import** — `sword_bridge` no longer pulls in the
  full-text search engine at startup. Cold-start of the bridge
  module dropped from ~102 ms to ~90 ms. Whoosh loads on first
  search.
- **Cheap module-presence probe.** The welcome-vs-main decision
  reads `~/.sword/mods.d/` directly instead of instantiating
  `Sword.SWMgr()` (105 ms → 0.09 ms). The full SWMgr init still
  happens — just after first paint instead of before it.
- **Stop caching Strong's misses.** A failed lookup is no longer
  permanently cached as `None`; subsequent clicks on the same
  Strong's number will retry, so installing the missing module
  takes effect immediately.

### Stability fixes

- **Pane-swap scroll preservation** for all common chapter
  positions, not just deep scrolls.
- **`bible:` URI** parses from `sys.argv` directly — Gio.File
  doesn't always round-trip custom URI schemes cleanly.
- **Welcome / panel UI:** shadows on overlay panels (menu,
  search, F11 exit button) no longer render with 90° artifacts
  on certain themes. Borders carry the visual weight; revealer
  clipping no longer fights the shadow.
- **Genbook position saved as a string,** not a list of
  characters. (A regression introduced during the per-module
  refactor that broke Concord / Westminster Confession startup
  briefly during testing.)

### Code health

- **Extract pane search into its own module** (`pane_search.py`,
  ~345 lines). `pane.py` shrank from 2 831 to 2 607 lines as a
  result; the external interface for window callers stayed
  identical via property delegators.
- **PROJECT.md → ARCHITECTURE.md.** The project brief is now a
  neutral architecture document; AI-assistance acknowledgement
  is consolidated into a single paragraph in the README.

### Packaging

- **Flatpak builds and runs end-to-end** in clean Zorin OS 18
  VM and on Fedora. The SWORD-Python binding integration is
  solved via `greg-hellings/python-libsword` 1.9.0.post1, which
  ships pre-generated SWIG output and links against the
  libsword built in the same manifest.
- **Bytecode precompiled at install** (`python3 -m compileall`)
  so first launch doesn't pay the compile cost.
- **Atomic-write tmp files** auto-clean — the rename pattern
  overwrites the same `.tmp` path on each save, so no orphan
  files accumulate.

### Tests

- 124 → 136 tests, all passing in under a second. The 12 new
  cases cover `module_positions` round-trip, kind discrimination,
  chapter/book scoping, legacy data recovery, debounce, and
  flush behaviour.

## [0.9.0] — 2026-05-21

First public testing release. Everything below is stable and
exercised in real reading sessions; the only thing standing between
this and a 1.0 tag is the Flathub submission round-trip.

### Reader

- Two-pane reading view with per-pane sync locks and an independent
  module selector on each pane.
- SWORD module support: Bibles, commentaries, devotionals, and
  Generic Books (tree-keyed reference works).
- eBible.org modern translations (LEB, BSB, etc.) via a SQLite
  backend, surfaced as just-another module in the picker.
- Greek and Hebrew Strong's lexicon with hover-only word underlines,
  a per-pane lexicon panel, word-study list across the current
  book, and Greek (Robinson via MorphGNT) + Hebrew (OSHB)
  morphology displayed in the header.
- Adjustable reading-column width via Text Appearance slider
  (540–1600 px); scrollbar sits at the pane's outer edge for a
  modern reader feel.
- F11 reading mode with a hover-to-reveal exit affordance at the
  top of the window for users who don't remember Esc/F11.

### Annotations

- Four highlight colors plus underlines plus per-verse and
  per-chapter notes with topical tags.
- All annotation actions are in-place tag mutations — the scroll
  position never moves on save.
- Soft pastel highlight palette at render time; underlying storage
  values unchanged for forward compatibility.
- Drag-select across verses works; Ctrl+C copies with the verse
  reference prepended.

### Cross-references and topics

- Slim single-row cross-reference bar at the bottom of the window.
- OpenBible.info's 340 000-reference database (CC-BY), with TSK as
  the fallback.
- OpenBible topical tags surfaced as Suggested chips inside the
  note editor.

### Search

- Whoosh full-text per-module search with a canon-distribution
  bar chart and click-to-navigate results.
- F3 / Shift+F3 step through results without re-opening the
  panel; tolerates a closed panel by re-revealing.
- Aa match-case toggle (Whoosh post-filter for SWORD modules;
  SQLite GLOB for eBible).
- Matched-word highlighting in the chapter on arrival from a
  search result (5-second amber highlight, distinct from the
  yellow verse flash).

### Study Journal

- Master-detail layout: sidebar with type / tag / module / book
  filters + free-text search; detail editor on the right with
  color swatches, underline toggle, tags entry, and a note
  TextView.
- Live-save for color and underline; explicit Save for note +
  tags so unsaved text isn't blown away by a swatch click.
- Clickable tag chips on rows filter by that tag.
- Tag Manager dialog (rename / merge / delete) launched from a
  header button.

### Reading plans

- Six built-in plans: Bible in a Year, Blended (4-stream
  OT+NT+Psalms+Proverbs), OT in a Year, NT in 90 Days, Psalms in
  30 Days, Proverbs in 31 Days.
- Day-by-day progress tracking with a today highlight; multi-passage
  days surface a small popover.

### Devotionals

- Spurgeon's Morning and Evening (SME) with morning/evening
  section split; other devotionals supported through the standard
  Daily Devotional SWORD convention.

### Generic Books

- Tree-keyed reference works (Didache, Westminster Confession,
  Book of Concord, Dark Night of the Soul, Apostolic Fathers)
  read via a TOC popover and prev/next entry buttons.
- Breadcrumb title above the entry body for deep hierarchies.
- Per-pane reading position persistence — switching modules and
  coming back returns to the last-read entry; same across app
  restarts.
- Section-heading entries (no body, only sub-entries) get a hint
  pointing the user to the TOC.

### Navigation

- Ctrl+L quick jump (`Goto: John 3:16`, abbreviations supported).
- Alt+←/→ for chapter; Alt+↑/↓ for book.
- Home / End for first / last verse of current chapter.
- Ctrl+1 / Ctrl+2 / Ctrl+Tab for pane focus.
- Ctrl++ / Ctrl+- for font size; Ctrl+scroll and touchpad pinch
  for the same.
- Mouse wheel over the title button cycles chapters.
- Right-click a chapter in the picker to slide over to a verse
  picker for that chapter.
- Recent-passages menu (header clock icon, 10 distinct passages,
  persistent across sessions).

### State

- Per-pane scroll position restored on next launch.
- Per-pane Generic Book reading position restored on next launch
  and across module switches.
- Window size, maximized state, split-pane mode, last book /
  chapter, and pane modules all persisted.
- All data lives under XDG locations
  (`$XDG_{CONFIG,DATA,CACHE}_HOME/bible-reader/`). One-shot
  migration moves legacy in-tree state out on first launch.

### Module Manager

- Three tabs: SWORD modules, Open Databases (OpenBible cross-refs
  + topics, Dodson Greek), eBible.org translations.
- Module picker has language chips, per-module info popover, and
  free-text filtering.

### Internals

- 124 pytest tests across `sword_bridge`, `open_data`,
  `annotations`, `reading_plans`. GTK-side code verified by
  running the app.
- Performance audit pass (release-blocker hot paths): eBible SQLite
  thread-local singleton, BiblePane module-language memoization,
  SearchPanel display cap at 500 rows, settings.put debounce,
  tag-table bounded per render.

### Packaging

- Flatpak manifest for `page.codeberg.andresmessina.Scriptura`
  is checked in but the SWORD-Python binding integration step is
  pending Flathub-maintainer help. See `flatpak/STATUS.md`.

### Known limitations

- Generic Books cannot be searched (Whoosh indexes verse-keyed
  modules).
- Annotations and bookmarks are not yet extendable to genbook
  entries.
- Some long-form dictionaries (Webster's 1913) ship HTML markup
  that renders fine but isn't perfectly typeset.
- Module Manager doesn't filter out Maps / Images or
  "Cults / Unorthodox / Questionable Material" categories — they
  can be installed but won't render in panes.
