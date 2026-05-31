# Changelog

All notable changes to Scriptura. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/). Versioning is
semver-ish — 0.x was the pre-Flathub testing track.

## [Unreleased]

### Added

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

- **Empty placeholders are now actionable.** The “can’t read this module
  here” and “passage isn’t in this module” pages offer a *Choose another
  module* button (it opens the module picker), and a locked module offers
  *Edit Key* — instead of only describing what to do.
- **UI polish pass.** Consistent transition timing across panels and menus,
  search-result bars that follow your GNOME accent colour, and the lexicon
  toggle regrouped with the reading-view controls rather than the
  navigation buttons.

### Internal (v1.1)

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
