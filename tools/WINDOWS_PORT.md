# Windows Port — Recommended Path

A starting brief for a future Windows build of Scriptura. Advisory; nothing here
is started yet. Written 2026-06-03.

## Verdict in one line

Possible and not even that far off in *code* terms — the hard part is packaging
and polish, not porting. Target **"coherent and polished," not "native."**

## The one architectural fact that decides everything

**libadwaita is deliberately un-themeable.** GNOME hardcodes the Adwaita look and
resists restyling it. Building on `Adw.*` widgets means the app *looks like a GNOME
app wherever it runs*. You cannot CSS your way to a native Windows look while on
libadwaita. So "native Windows aesthetic" is not a setting — it's a fork:

| Option | Cost | Result |
|--------|------|--------|
| 1. Ship as-is (GTK4 + libadwaita) | Low | Clean but visibly GNOME on Windows (like GIMP/Inkscape) |
| 2. Drop libadwaita → plain GTK4 + custom CSS | Med-High | Rebuild every `Adw.*` surface; *some* native room, still not truly native (GTK4 Windows theming is weak) |
| 3. Native UI layer (WinUI/WPF/Qt) | Total rewrite | Genuinely native; not realistic for a one-dev project |

## Why Option 1 is the right call

Scriptura's identity lives in surfaces **you already own**, not in Adwaita widgets:
the reading view is custom typography + Cairo painting (verse/search/flash bands,
the archaeology map + timeline, imagery). That's ~95% of what users look at, and
it's already "yours." The GNOME-ness is concentrated in the *chrome* (header bar,
dialogs, switches, popovers).

The real bar isn't "indistinguishable from a WinUI app." It's the **Obsidian/Spotify
standard**: a polished app with its own coherent identity that feels at home without
being native. A content-first reading app earns that permission — and it's
consistent with the "Apple Books for Scripture" instinct (Apple Books isn't
native-chrome-heavy either; it's a clean custom reading surface). Don't chase
native. Chase coherent.

## The recommended path

### Step 0 — the only real *code* blocker (do this first, it's cheap)
`sword_bridge.py` hardcodes Linux SWORD locations:
- `_SWORD_PATH = os.path.expanduser('~/.sword')`  (line ~951)
- `/usr/share/sword`  (lines ~1110, ~1191, ~1204)

SWORD on Windows lives at `%APPDATA%\Sword`. Abstract these behind an OS-aware
resolver (a few lines). Everything else in the app already uses
`GLib.get_user_{config,data,cache}_dir()` (see `paths.py`), which GLib maps to the
correct native Windows location (`%LOCALAPPDATA%`) automatically — so the app's own
data/config/cache are *already* cross-platform-correct. SWORD is the lone Linux-ism.
(Also check for any Wayland-specific clipboard workarounds.)

### Step 1 — build the dependency stack on Windows (the fiddly part)
- **python-libsword**: SWORD is C++ with SWIG/Python bindings. Compiling SWORD +
  bindings for Windows and bundling them is the single hardest piece. (Same family
  of pain as the SWORD CMake bug already hit on Linux — see
  `reference_sword_cmake_bug` memory.) BibleTime proves SWORD runs on Windows, so
  it's a known-good target, just laborious.
- **GTK4 + libadwaita + PyGObject runtime**: use the **MSYS2** toolchain
  (mature; libadwaita is packaged there) or **gvsbuild**. This is well-trodden;
  several GTK4 apps ship this way.

### Step 2 — package an installer
Bundle Python + GTK runtime + app into an MSI/NSIS installer. Expect a large
bundle (~100–200 MB). A code-signing cert is worth it to avoid SmartScreen warnings.

### Step 3 — the Windows-seam polish (turns "Linuxy" into "at home enough")
These are the specific tells worth fixing under Option 1:
- **Native window frame** instead of GTK client-side decorations (GTK4 supports the
  native frame on Windows).
- **Default font → Segoe UI** (and confirm the serif reading face ships/loads), so
  text doesn't fall back to something off.
- **Optional menu bar** — Windows users expect one; the hamburger menu reads as
  foreign. Consider surfacing a real menu bar on Windows.
- **Scrollbars / switches** — overlay scrollbars and Adwaita switches read as
  foreign; minor but cumulative.

## Performance notes (the good-news column)
- GTK4's GPU renderer is fast on normal hardware. The real risk is older/odd GPUs
  or bad drivers forcing the **Cairo software fallback**, which is slow for heavy
  redraws — your custom-painted views (map pulse animation, timeline) are where a
  weak machine would feel it. Rare on modern hardware; mitigatable.
- **Startup latency** is the honest cost: Python + GTK + libadwaita cold-load is
  seconds, not instant. Smooth once running.

## Sequencing across platforms
Linux/Flathub first (in flight) → **Windows** if there's demand (most tractable,
biggest audience, code is nearly ready) → macOS last and only if there's real pull
(hardest backend, worst native fit, Apple signing/notarization overhead).

## The honest ongoing cost
The port is a one-time effort; the **maintenance multiplier** is forever. Each OS
is its own build, CI, testing, and signing. For a one-developer project that's the
bigger long-term commitment than the port itself. Worth doing only with real
Windows demand to justify it.

## First concrete action when you pick this up
Do Step 0 (the SWORD path abstraction). It's small, it's the only code blocker, and
it makes the codebase stop assuming Linux — useful even before any Windows work
ships.
