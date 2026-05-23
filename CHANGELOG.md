# Changelog

All notable changes to Scriptura. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/). Versioning is
semver-ish — 0.x was the pre-Flathub testing track.

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
