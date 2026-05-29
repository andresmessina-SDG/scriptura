# Scriptura — Architecture Brief

Internal architecture and design notes for anyone working on the
codebase. For the user-facing introduction, see [README.md](README.md).

## What we're building

A GNOME-native Bible study app for Linux. The goal is something like Logos Bible
Software but simpler: multiple resource panes (translations, commentaries,
lexicons, concordances, devotionals) navigable to a shared verse reference, with
a clean GNOME look and feel and an emphasis on quiet, distraction-free reading.

## Tech stack

- **Language:** Python 3 with PyGObject (GTK4 bindings)
- **UI toolkit:** GTK4 + libadwaita
- **Primary data layer:** SWORD Project library (`python3-sword` / `libsword`)
- **Secondary data layer:** eBible.org SQLite catalog (modern translations not
  available as SWORD modules — e.g. LEB, BSB)
- **Open data:** OpenBible.info cross-references + topics (CC-BY); Dodson Greek
  Lexicon (CC-BY). Downloaded on demand via Module Manager.
- **Text rendering:** Native `Gtk.TextView` + Pango markup (WebKitGTK was tried
  and reverted — do not suggest switching back)
- **Search:** Whoosh full-text indexing (per-module, lazy-built)
- **Build:** No build step; plain Python scripts
- **Platform:** Fedora Linux, GNOME desktop (Zorin Blue-Dark theme on this
  development machine; should work on any GNOME)

**Why native GtkTextView over WebKitGTK:** WebKit was implemented and replaced
by the user. Native GtkTextView starts faster, uses less memory, scrolls
smoothly, and inherits system fonts and theme colors without hardcoded values.

**Why SWORD:** CrossWire's SWORD Project provides a standardized module format
with thousands of free resources and a stable verse-reference data model.

## Architecture

Multi-pane layout. All panes can share an active verse reference; per-pane
sync toggles let the user lock a pane to its own location. Each pane has its
own module selector dropdown.

```
+----------------------------------------------------------------------------+
| HeaderBar  [menu] [back] [fwd]  [Book N v]  [Heb/Grk]  ...  [view] [srch] [bm] |
+----------------------------------+-----------------------------------------+
| [Module v] [lock][note][search]  | [Module v] [lock][note][search]         |
| Pane 1 — Bible / Commentary      | Pane 2 — Bible / Commentary /           |
| (Bibles render with chapter      |          Devotional                     |
| heading + drop-cap on v1)        |                                         |
|                                  |                                         |
+----------------------------------+-----------------------------------------+
| [Verse N:V]  cross-ref pills...                                       [x]  |
+----------------------------------------------------------------------------+

  Per-pane (below the Bible text): Lexicon panel
    [Definition view + clickable cross-numbers]  |  [Word study list]

  Overlays:  menu panel (left slide-in)   search panel (right slide-in)
             quick-jump bar (top, Ctrl+L)  F11 reading mode (hides chrome)
             dictionary popup on double-click of a plain word
```

## File layout

```
scriptura/
+-- ARCHITECTURE.md       # this file
+-- README.md             # user-facing overview, install, credits, license
+-- LICENSE               # GPL-3.0-or-later (canonical text)
+-- SEARCH_RESEARCH.md    # early design notes (kept for reference)
+-- pytest.ini            # testpaths + pythonpath config
+-- requirements-dev.txt  # pytest + dev tools
+-- main.py               # app entry, Adw.Application (page.codeberg.andresmessina.Scriptura)
+-- window.py             # BibleWindow — header, panes, navigation funnels, About dialog
+-- pane.py               # BiblePane — text rendering, annotations, click handling
+-- genbook_reader.py     # GenbookReader — Generic Books (TreeKey) subsystem extracted from pane.py
+-- styles.py             # Loads data/style.css once at startup; per-pane dynamic CSS stays in pane.py
+-- lexicon_panel.py      # LexiconPanel — definition view + word study (own class)
+-- annotation_dialogs.py # Right-click study menu, note editor, chapter note, compare translations
+-- devotional.py         # Devotional OSIS rendering (Spurgeon-style multi-section labels)
+-- sword_bridge.py       # SWORD library wrapper + Whoosh indexing
+-- ebible_bridge.py      # eBible.org SQLite translation backend
+-- open_data.py          # OpenBible refs/topics + Dodson Greek (CC-BY)
+-- annotations.py        # Per-verse JSON persistence
+-- bookmarks.py          # Bookmark list
+-- settings.py           # User preferences
+-- reading_plans.py      # Built-in plans + progress
+-- search_panel.py       # Search overlay (right-side revealer)
+-- study_journal.py      # Study Journal window (master-detail) + TagManagerWindow
+-- crossref_panel.py     # Cross-reference bar (slim single row)
+-- module_manager.py     # Module Manager (3 tabs: SWORD, Open Databases, eBible)
+-- welcome.py            # First-run welcome window (essentials bundle download)
+-- tests/                # Pytest suite for the pure-Python bridges (227 tests)
|   +-- test_open_data.py
|   +-- test_annotations.py
|   +-- test_reading_plans.py
|   +-- test_sword_bridge.py
|   +-- test_paths.py
|   +-- test_bookmarks.py
|   +-- test_settings.py
|   +-- test_ebible_bridge.py
|   +-- test_module_positions.py
+-- data/
|   +-- icons/hicolor/scalable/apps/page.codeberg.andresmessina.Scriptura.svg
|   +-- page.codeberg.andresmessina.Scriptura.desktop
|   +-- style.css              # Centralised application stylesheet (loaded by styles.py)
|   +-- cross_references.txt   # gitignored — OpenBible download
|   +-- topic-scores.txt       # gitignored — OpenBible download
|   +-- dodson.csv             # gitignored — Dodson Greek download
+-- *.json                # User runtime data (annotations, settings, bookmarks, reading_plans, search_history) — gitignored
+-- ebible.db             # eBible SQLite — gitignored
```

### Naming convention: `Bible*` vs `Scriptura`

Internal class names use `Bible*` (`BibleApp`, `BibleWindow`,
`BiblePane`); the user-facing brand is "Scriptura". This split is
deliberate — `Bible` describes the *domain* (what the objects work
on), `Scriptura` is the *product name*. Same pattern most apps
follow (Firefox's classes aren't `Firefox*`). The app-ID, window
title, About dialog, desktop entry, and `.flatpak` all use
Scriptura; the class hierarchy stays domain-named so it remains
accurate if the product is ever rebranded again.

If you're grepping for the main application class and expected
`ScripturaApp`, it's `BibleApp` in `main.py`.

## pane.py — key internals

### Rendering pipeline

- `_html_to_markup(html, dark, strip=True)` — converts SWORD `renderText()`
  output to Pango markup. Pipeline: map known tags to placeholder tokens →
  strip remaining HTML → `GLib.markup_escape_text()` → swap tokens back to
  Pango spans. Annotation styling (highlight/underline/note) is **not** baked
  in here — those are named buffer tags applied after insertion (see "in-place
  annotations" below). `strip=False` keeps inter-segment whitespace for the
  commentary reference-splitting path.

- `_extract_segments(html)` → `[(text, strong_num, morph)]` for per-word
  Strong's tagging. Captures both `lemma="strong:..."` and `savlm="strong:..."`
  plus `morph="robinson:..."`.

- `_make_verse_markup(html, target_strong)` — verse markup with words matching
  `target_strong` rendered bold. Used by the word study panel.

### Per-verse tagging

- Each verse range gets a named TextTag `vnum_N` (covers verse number + text).
- Verse text range (excluding the gray number prefix) is targeted by the
  annotation helpers via `_verse_ranges(N)` which returns
  `(vnum_start, vtext_start, vtext_end)`. `vtext_start = vnum_start +
  len(str(N)) + 2 chars` (the " N " prefix).

### In-place annotations (recent, important)

Highlights, underlines, and note indicators are applied as **named buffer
tags**, not baked into Pango markup. This means right-click annotation changes
are pure tag-application — no `set_text` / re-render / scroll restoration.
Scroll position is genuinely untouched.

- `hl_<rendered_color>` tag — `background=color, foreground=black`. Applied
  to the verse text range. Soft palette via `_HIGHLIGHT_RENDER` (stored
  colors map to softer rendered colors; existing JSON data unchanged).
- `_ul_text` tag — `underline=Pango.Underline.DOUBLE`. Applied to verse text.
- `_note_marker` tag — `foreground=#5b8def, weight=BOLD`. Applied to verse
  *number* only — gives notes a subtle accent-colored number instead of the
  old 📝 emoji at end of verse.

`_apply_anno_tags(verse_num, anno)` — idempotent: clears any prior annotation
tags from the verse's ranges, then applies new ones from the anno dict. Bumps
each tag's priority to `table.get_size() - 1` on every apply, so subsequent
chapter renders don't out-prioritize the persistent tags via newly-created
anonymous insert_markup tags.

`_refresh_verse_annotation(verse_num)` — re-reads `annotations.get_annotations`
and calls `_apply_anno_tags`. Called from `_apply_highlight`,
`_toggle_underline`, and `_save_note_window` instead of any `_fetch_and_render`.

### Strong's hover model

- Strong's-tagged words no longer carry a static underline (the wall of
  underlines made every page look like a contract).
- A `Gtk.EventControllerMotion` on the textview tracks the cursor. When over
  a `strg:`-tagged word, a transient `_strg_hover` tag (single underline +
  soft accent foreground) is applied to that word's range. Removed when the
  cursor leaves the word or the view.
- Word boundaries detected with `iter.backward_word_start()` /
  `forward_word_end()` (same pattern as the dict popup).
- Motion handler bails when `_lexicon_enabled` is False so non-Strong's
  Bibles aren't affected.

### Other notable bits

- **Chapter heading** — muted `[Book Chapter]` rendered at top of buffer for
  Bibles (not commentaries). Scrolls with the text.
- **Drop-cap on v1** — first letter rendered at `size="200%" weight="bold"
  rise="-2000"` via a regex that skips leading Pango span tags. Suppressed
  when v1 is highlighted.
- **Soft highlight palette** — `_HIGHLIGHT_RENDER` maps the four stored
  highlight colors to muted pastels for rendering. Storage values unchanged
  so legacy annotations.json data still loads.
- **Flash highlight** — `_flash_verse(N)` applies a `_flash` tag (pale yellow
  bg / black fg in both light and dark mode), priority bumped to top, with
  per-flash independent timers held in `self._flash_timers: set[int]` so
  rapid clicks don't cancel each other. `_cancel_all_flashes()` runs before
  `set_text('')` in `_display` / `_display_devotional` to clear stale flashes.
- **Scroll** — `_scroll_to_verse(N)` uses `scroll_to_mark` (not
  `scroll_to_iter`) because line heights are stale right after a chapter
  render. Defers `_flash_verse` by 150ms so the scroll fully settles before
  the flash applies (verses deep in long chapters would otherwise flash off
  screen).
- **Right-click menu** — 4 highlight colors (yellow/green/blue/orange),
  underline, note editor (Adw.Window, not popover — see "popover lifecycle"
  below), copy verse, compare translations. Multi-verse selection supported
  (highlight/underline/copy all selected verses).
- **Dictionary popup** — double-click any word opens an Adw.Window with
  tabbed Easton's/Smith's results. Strong's-tagged words also trigger this
  on double-click (the lexicon panel opens on the first click of the same
  double-click).
- **Devotional support** — `_is_devotional` detected on construction;
  separate render path `_render_devotional_osis` with date navigation.
  Detects multi-section devotionals (SME — Spurgeon Morning & Evening) and
  labels them.
- **Sync** — per-pane lock button. When a pane is locked, it ignores
  window-level navigation (sync_btn `active=True` returns from
  `load_reference*`). On unlock, `_on_sync_toggled` catches up to the
  window's current location. Auto-unlocks when switching from a devotional
  module to a Bible.
- **Reading column cap** — TextView is a direct child of a custom
  `_ReadingScrolledWindow` subclass that pushes symmetric
  `left_margin`/`right_margin` onto the view on every `size_allocate`,
  so the column stays centered and the scrollbar sits at the pane's
  outer edge (not inside the column). User-tunable via the Width slider
  in the Text Appearance card (range 540–1600 px, default 720, stored
  in `settings.reading_width`). **Earlier `Adw.Clamp(ScrolledWindow)` is
  gone** — it kept TextView a Gtk.Scrollable direct child but forced
  the scrollbar inside the reading column, which the user disliked.
  Clamping the TextView itself still forces a Viewport that breaks
  `scroll_to_iter` — don't go back to that path.
- **Module picker** — `pane.module_drop` is a `Gtk.MenuButton` (was
  `Gtk.DropDown`) opening a popover with a two-page `Gtk.Stack`: a list
  page (SearchEntry + language chip row + scrollable module list, each
  row with an ⓘ button) and an info page (description / language /
  version / type / copyright / license / about). `_apply_module_change
  (name)` takes a module name string and applies all the side effects;
  the picker row activation drives it. `_module_lang_cache` is a
  class-level memoization so the picker doesn't probe SWORD or eBible
  on every keystroke.

## window.py — key internals

- `_go_to(book, chapter, verse, record)` — central navigation. Updates the
  hidden book/chapter dropdowns and the visible "Book N" ref button, then
  calls `pane.load_reference(_at_verse)` on both panes.
- `book_drop` / `chapter_drop` — kept alive as state holders but `set_visible(False)`.
  Navigation flows through `_go_to`, the combined Book+Chapter popover, the
  quick-jump bar, or Alt+arrows — never via direct user manipulation of
  the dropdowns. The old `_on_book_changed` / `_on_chapter_changed` handlers
  have been removed.
- **Combined Book + Chapter popover** (`_ref_btn`, `_build_ref_popover_content`)
  — 420×360 popover with `Gtk.ListBox` of 66 books on the left, `Gtk.FlowBox`
  of chapter buttons (4-per-row) on the right. Clicking a chapter calls
  `_go_to(book, ch)` directly.
- **Toast overlay** — `self._toast_overlay = Adw.ToastOverlay()` wraps the
  main content. `self._toast(msg)` helper emits transient toasts (2s) for
  bookmark add/remove, copy-verse, etc.
- **Reading mode** — F11 toggles `self._reading_mode`. On entry: hides
  `Adw.HeaderBar`, both pane toolbars (`pane._toolbar` references), dismisses
  any open overlay panels. Exit affordance: a circular `window-close-symbolic`
  button in a SLIDE_DOWN revealer at top-center reveals after the cursor
  sits in the top 12px hot zone for 2s, stays visible while the cursor is
  within 80px of the top, hides on cursor-out / leave / mode-exit. Motion
  controller attached to `self` (the window), not the overlay, so events
  reach us regardless of which child widget has the cursor.
- **Recent passages** — `document-open-recent-symbolic` button between
  forward and the title button. Popover shows the last 10 distinct
  `(book, chapter)` pairs (`settings.recent_passages`), deduped, with a
  trash icon to clear. `_push_recent` called from `_go_to` only when
  `record=True` (back/forward stack moves and initial restore don't push).
- **Cross-ref clicks** target pane 2 in split mode, pane 1 in single-pane mode
  (with fallback if pane 2 is on a devotional / sync-locked).
- **Key controller phase = CAPTURE.** Without this, focus drift onto
  TextView/Entry/DropDown after extended use could silently swallow
  Alt+arrows, F-keys, Esc, font-size shortcuts. CAPTURE makes the
  window-level handler the first responder; it still returns False for
  unhandled keys so normal typing in entries works.
- **Keyboard shortcuts:**
  - `Ctrl+=` / `Ctrl+-` — font size (also `Ctrl+scroll` and touchpad
    pinch — see `BiblePane._on_zoom_scroll` / `_on_zoom_gesture`)
  - `Ctrl+L` — quick jump bar
  - `Ctrl+F` — open / close window search panel
  - `F3` / `Shift+F3` — next / previous search result. Routes to whichever
    surface has cached results (window panel preferred; falls back to
    re-revealing a closed panel if results are still in memory).
  - `Alt+←/→` — prev/next chapter (wraps across books)
  - `Alt+↑/↓` — prev/next book
  - `Home` / `End` — first / last verse of current chapter (gated on
    `_focus_is_text_input()` so typing in entries still works)
  - `Ctrl+1` / `Ctrl+2` / `Ctrl+Tab` — focus pane / cycle panes
  - Mouse wheel over the Book/Chapter title button — cycle chapters
  - `Esc` — dismiss jump bar, search panel, menu panel, or exit reading mode
  - `F11` — reading mode
- **Book/Chapter popover** with right-click verse picker. The right
  column is a `Gtk.Stack(SLIDE_LEFT_RIGHT, 180ms)` flipping between a
  chapter FlowBox and a verse FlowBox. Left-click on a chapter still
  navigates immediately; right-click slides over to the verse picker for
  that chapter. Title flips from "Chapter" to "Chapter N Verse"; a back
  button appears in the verse view. Uses `sword_bridge.verse_count`
  (wraps `VerseKey.getVerseMax()`).
- **Menu panel (left overlay)** — burger button opens. Contains: Study
  Journal button, Modules button, Text Appearance toggle (font family, size,
  line spacing, bold, justify, color, **reading column width**),
  Hotkeys reference, Reading Plan selector + day list with progress.

## sword_bridge.py — key internals

- `load_chapter(module, book, chapter)` — thread-safe (RLock), in-memory
  cache, returns `[(verse_num, rendered_html)]`. Falls back to `ebible_bridge`
  for eBible modules.
- `get_cross_refs(book, chapter, verse)` — tries `open_data.get_cross_refs()`
  first; falls back to the SWORD TSK module. OpenBible has ~5× more refs
  than TSK.
- `lookup_strong(strong_num)` — tries `open_data.lookup_dodson()` first for
  Greek; falls back to SWORD `StrongsHebrew` / `StrongsGreek` modules. Uses
  `mod.setKeyText()` + `mod.getRawEntry()` (NOT `setKey/renderText` — see
  SWORD quirks).
- `lookup_dict_word(word)` — looks up English dictionaries (Easton, Smith).
  Creates a fresh `Sword.SWMgr()` per call because a failed `setKeyText`
  corrupts subsequent lookups. Calls `getRawEntry()` unconditionally to clear
  the internal error state.
- `lookup_morph_for_strong(book, ch, v, strong)` — MorphGNT lookup for Greek
  morphology. Pairs with `decode_robinson(morph)` which converts
  `robinson:V-2AAI-3S` to readable strings.
- `lookup_morph_for_strong_heb(...)` + `decode_hebrew_morph(...)` — OSHB
  morphology for Hebrew.
- `search_module(module, query)` — Whoosh full-text search. Lazy-builds
  per-module index on first use (background thread). Max 5000 results.
- `get_devotional_raw(module, date)` / `load_devotional(...)` — fresh SWMgr
  per call for the same reason as dict lookup.
- `parse_devotional_refs(raw_osis)` — extracts the first `osisRef` from a
  devotional entry. Used to navigate pane 1 to the day's passage on startup.
- `_OSIS_BOOKS` — book-abbreviation map used by `parse_osis_ref()`.
- `_parse_conf(path)` — reads a SWORD `.conf` file with `utf-8-sig`
  (BOM-safe) and backslash line-continuation handling. The actual
  parsing lives in `_parse_conf_lines(lines)` so the same logic works on
  `.conf` text pulled straight from a zip in memory.
- **Module sideload** (import a `.zip` you already have, no network):
  `inspect_module_zip(bytes)` validates the archive and returns one dict
  per module (name, type, lang, version, size, locked, installed,
  installed_version) without writing anything; `install_module_from_zip`
  extracts only the chosen modules' conf + datapath, guarded by
  `_safe_extract` against zip-slip paths. `cmp_version` drives the
  install/update/reinstall/replace label. The UI side is the import
  button + drag-target + preview sheet in `module_manager.py`.
- **Cipher-locked modules:** `is_encrypted_module(name)` reports whether
  a conf declares a `CipherKey`; `set_cipher_key(name, key)` writes the
  key and resets. A wrong key decrypts to garbage, which the pane catches
  on render (see `_printable_ratio` / `_display_cipher_locked`) and the
  window turns into an "Edit Key" toast.

## open_data.py — key internals

- `_OSIS_BOOKS` — local copy of book abbreviations (to avoid circular import
  from sword_bridge).
- `_osis_to_vids(s)` — converts `Gen.1.1` or `Exod.20.1-Exod.20.26` to
  8-digit numeric verse IDs. Expands single-chapter ranges; clips
  cross-chapter / cross-book ranges to the start verse.
- `get_cross_refs(book, ch, v)` → `[(book, ch, v, label), ...]` or `None` if
  the file isn't downloaded.
- `get_topics(book, ch, v)` → list of CC-BY topic tags. Used by the
  annotation "Suggested topics" chip row in the note editor.
- `lookup_dodson(strong_num)` → readable NT Greek definition.
- `download_source(id)` — fetches + extracts OpenBible cross-references ZIP,
  topics ZIP, or Dodson CSV into `data/`.

## Logging

App-wide logging lives on the `scriptura.*` logger tree. `main.py` calls
`_setup_logging()` before any module import, which:

- reads `SCRIPTURA_LOG_LEVEL` (default `WARNING`),
- attaches one `StreamHandler` to the `scriptura` logger with format
  `name [LEVEL] message`,
- sets `propagate = False` so we don't double-print through the root logger.

Each module declares its own logger near the top of the file, e.g.
`_log = logging.getLogger('scriptura.sword')`. Component names preserve
the historical `[tag]` prefixes used before the migration — including
the deliberate split inside `sword_bridge.py`, which carries both
`scriptura.sword` (module load / verse keys / genbook walks) and
`scriptura.search` (index build / Whoosh query path).

Convention: `_log.exception(msg)` inside `except` blocks (logs at ERROR
with the traceback — the main reason this exists is debugging weird
SWORD setups from user reports), `_log.info(msg)` for one-shot
informational events like the legacy-file migrations in `paths.py`.
There are no `_log.debug()` sites yet; they're available when a tricky
bug needs them.

To debug a user report: `SCRIPTURA_LOG_LEVEL=DEBUG python3 main.py`.
The Flatpak install writes the same stream to the journal — viewable
with `journalctl --user -f` while the app runs.

## Type hints (gradual)

Scriptura uses gradual typing. The persistence layer is fully
annotated and mypy-clean: `paths`, `bookmarks`, `settings`,
`annotations`, `module_positions`, `reading_plans`. TypedDicts capture
the on-disk shapes (`Bookmark`, `Plan`, `ChapterNoteData`,
`PlanSummary`).

Conventions:

- **Modern syntax.** PEP 585 (`list[str]`, `dict[str, Any]`) and
  PEP 604 (`str | None`). No `from typing import List, Optional`
  in new code. `python_version = 3.10` in `mypy.ini`.
- **`dict[str, Any]` at the JSON I/O boundary.** Real on-disk data is
  schemaless across versions; helpers narrow via `isinstance()` once
  inside. Using `cast()` at the I/O boundary is preferred over
  `# type: ignore`.
- **mypy scope widens module-by-module.** `mypy.ini` enforces
  `disallow_untyped_defs` only on already-typed modules. Other
  modules are listed in the `[mypy-…] ignore_errors = True` section
  at the bottom; when you finish typing a file, move it from the
  ignore list to the strict list.

Run: `mypy .` (uses `mypy.ini`; excludes `build-dir/`).

## annotations.py

Per-verse study data persisted in `annotations.json`. Key format:
`"{module}/{book}/{chapter}"` → `{"{verse}": {...}, "chapter_note": {...}}`.

Per-verse value shape:
```
{
  "highlight": "#ffff00" | null,   # stored colors (mapped to soft tints at render time)
  "underline": bool,
  "note": "text" | null,
  "tags": ["topic1", "topic2", ...]
}
```

Chapter note: same shape (note + tags) under the `"chapter_note"` key.
Includes migration logic for old single-color string format.

## Critical SWORD Python binding quirks

- **Dict modules** (Strongs, Easton, Smith): use `mod.setKeyText(key)` +
  `mod.getRawEntry()`. NOT `setKey/renderText/stripText` (broken).
- `setKeyText()` with a non-existent key corrupts module key state for
  subsequent calls. **Fix:** create a fresh `Sword.SWMgr()` per dict lookup.
- After a failed `setKeyText`, call `getRawEntry()` unconditionally — it
  clears the internal error state so the next `setKeyText` variant works.
- Validate matches: `mod.getKeyText().lstrip('0') == num_bare` (SWORD snaps
  to the last entry on miss).
- **StrongsHebrew key:** 5-digit zero-padded, no `H` prefix (`"00430"`).
- **Easton/Smith keys:** ALL CAPS (`"CHRIST"`, `"ADAM"`).
- **KJVA `<w>` attribute:** uses `savlm="strong:..."` not `lemma=` —
  `_extract_segments()` handles both.
- **Commentary modules** (TSK, MHC, MHCC): use `mod.setKey(VerseKey)` +
  `mod.renderText()` (the dict-module quirks above don't apply).
- **Plain KJV** has no `<w>` tags → Strong's doesn't work; recommend KJVA.
- **Non-UTF-8 dict data:** some SWORD dict modules contain lone surrogates;
  strip them in `_html_to_markup()` before `GLib.markup_escape_text()`.

## Critical GTK4 / Wayland quirks

- **`Adw.Clamp` around a `Gtk.TextView`** forces GTK to inject a Viewport
  (Clamp isn't `Gtk.Scrollable`), and `TextView.scroll_to_iter()` doesn't
  propagate through it. Always clamp the `ScrolledWindow`, not the TextView.
- **`scroll_to_iter` uses currently-computed line heights**, which are stale
  right after a `set_text` / `insert_markup`. Always use `scroll_to_mark`
  with a temporary `TextMark` for post-render scrolling.
- **Tag-priority decay:** tags created earlier have lower priority. Anonymous
  tags from `insert_markup` get created on every chapter render — so any
  long-lived tag (flash, annotation, note marker) needs its priority bumped
  to `table.get_size() - 1` before each apply.
- **`get_iter_at_location` returns False** for points inside the textview's
  `left_margin`. Always probe at `rect.x + max(40, rect.width // 2)`.
- **Popover-inside-popover on Wayland:** the parent's `closed` signal can
  fire synchronously inside `popdown()`, and the standard
  `lambda p: p.unparent()` cleanup races with the new popover's surface
  creation → use-after-free + segfault. **Workaround:** use `Adw.Window` for
  dialogs that originate from inside a popover (note editor, dict popup),
  not nested popovers.
- **`Pango.Underline`** has no DOTTED variant. Use `SINGLE` with a soft
  foreground color for subtle underlines, or no underline at all for
  hover-only schemes.
- **Buffer marks** are deleted by `Gtk.TextBuffer.set_text('')`. Don't try
  to preserve scroll position by saving a mark across a set_text.
- **`set_text('')` does NOT remove tags from the tag table**, only
  unapplies them from now-removed content. The tag table grows
  unbounded if you create named tags per chapter render — `vnum_N`,
  `strg:G…`, `morph:…`, `phrase:…`, `devref:…` all accumulate.
  `_clear_chapter_scoped_tags()` (called in every render path right
  after `set_text('')`) walks the table via `foreach` and removes
  tags matching `_CHAPTER_SCOPED_TAG_PREFIXES`. Two-pass: collect into
  a list, then remove — don't mutate the table during iteration.
- **`Gtk.EventControllerKey` default phase is BUBBLE**, which lets the
  focused widget swallow keys before window-level handlers see them.
  Use `set_propagation_phase(Gtk.PropagationPhase.CAPTURE)` for global
  shortcuts; return False for keys you don't care about so normal
  typing in entries still propagates.
- **`Adw.ToolbarView` top bars + `Adw.Window` overlay handling on
  Wayland:** dismissing the panel via row activation auto-closes the
  panel. F3 step-through must therefore tolerate a closed panel —
  re-reveal it if `_results` is still cached rather than refusing to
  step. Same applies to any "stepping through results" UI pattern.
- **`Gtk.EventControllerScroll` with Ctrl modifier** for zoom: check
  `controller.get_current_event().get_modifier_state() &
  Gdk.ModifierType.CONTROL_MASK` and return False when Ctrl isn't held
  so normal scroll passes through to the ScrolledWindow. CAPTURE phase
  on the TextView keeps the zoom shortcut from being shadowed by the
  scroll bubble.
- **`Gtk.GestureZoom` `'begin'` resets cumulative scale to 1.0.** Track
  your own `_accum` ratio and reset on `'begin'` — otherwise a fresh
  pinch's first scale-changed signal triggers a spurious zoom-out
  because the ratio jumps from the previous gesture's final scale to
  1.0.
- **Wayland compositors report raw, unsmoothed pointer motion.** Mutter
  (and X11) apply pointer acceleration / smoothing, so a stationary
  finger on a trackpad delivers a tidy stream of "no motion" events.
  Hyprland (and most wlroots-based compositors) hand you the device's
  raw deltas — a "still" cursor still emits sub-pixel wobbles that
  cross any narrow Y-band. Any "must hover inside an N-px zone for T
  seconds" gesture needs **two thresholds**: a narrow trigger zone to
  arm the timer, and a wider tolerance zone within which the timer
  survives jitter. Only cursor motion past the wider zone should
  cancel. See `_on_reading_mouse_motion` for the F11 exit affordance,
  which uses `_READING_TRIGGER_ZONE_PX = 12` to arm and
  `_READING_KEEP_ZONE_PX = 80` as the cancel boundary.
- **Floating overlays + `.card` CSS class:** `@card_bg_color` is
  semi-transparent in libadwaita's dark palette (designed to layer over
  a solid window bg). Overlays mounted via `Gtk.Overlay.add_overlay`
  need an opaque background — apply your own class with
  `background-color: @view_bg_color`. Hit this with the menu panel
  (fixed earlier) and the Ctrl+L jump bar.
- **`sqlite3.connect` default `check_same_thread=True`** raises when a
  connection is used from a different thread. For app-wide reuse,
  thread-local storage (`threading.local()`) is the simplest correct
  shape; one connection per thread, schema initialised lazily on first
  call per thread. Avoids both the threading error and the
  open/PRAGMA/CREATE churn that "open per call" introduces.

## Known working modules

- **KJVA** — Hebrew/Greek OT+NT with Strong's; `savlm` attribute; hover-only
  underlines on words; clickable for Strong's lookup.
- **LEB / BSB** — via eBible.org SQLite backend.
- **StrongsHebrew + StrongsGreek** — required for the lexicon panel.
- **TSK** — Treasury of Scripture Knowledge; SWORD-side fallback for cross-refs.
- **MHCC** — Matthew Henry's Concise Commentary; commentary mode.
- **SME** — Spurgeon's Morning & Evening; devotional mode with morning/evening
  section split.
- **MorphGNT** — Greek morphology lookup.
- **Open data** (downloadable via Module Manager): OpenBible cross-references
  (340k refs, ~5× TSK), OpenBible topics, Dodson Greek Lexicon.

