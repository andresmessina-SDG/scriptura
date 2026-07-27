# Flatpak packaging status

What `io.github.andresmessina_SDG.Scriptura.yml` builds, what is verified,
and what was ruled out. The release/publish procedure is a separate,
gitignored ops note (`FLATPAK_RELEASE.md`); this file is about the package.

> Rewritten 2026-07-27. The previous version described a **Flathub
> submission** under the old `page.codeberg.andresmessina.Scriptura` ID,
> against runtime 49, with an unresolved `sha256: TODO` — none of which is
> still true. See "How it ships" and "History" below.

## How it ships

Not through Flathub. Scriptura is distributed as a **self-hosted, GPG-signed
ostree repo** on GitHub Pages, installed in one click from
`https://andresmessina-sdg.github.io/scriptura-flatpak/scriptura.flatpakref`.
Users still need the Flathub *remote* for `org.gnome.Platform//50`, which the
ref's `RuntimeRepo` line adds automatically — that is a runtime dependency,
not a submission.

The submission gates the old version of this file tracked (screenshots,
`flatpak-builder-lint`, a PR to flathub/flathub) are therefore not live work.
The reason the Flathub track was set aside is not recorded in this repo; if it
matters later, it should be written down here rather than remembered.

## What the manifest builds

App ID `io.github.andresmessina_SDG.Scriptura`, on `org.gnome.Platform//50`
with `org.gnome.Sdk//50`. Four modules, in order:

| Module | Source | Produces |
|---|---|---|
| `libcurl` | `curl-8.10.0.tar.gz` | libsword's configure would not find a usable curl in the runtime cleanly |
| `libsword` | `sword-1.9.0.tar.gz` (CrossWire) | `/app/lib/libsword.so`, `sword.pc` — C++ only, no bindings target |
| `python-libsword` | greg-hellings, tag `1.9.0.post1` | `/app/lib/python3.13/site-packages/Sword.py` + `_Sword*.so` |
| `scriptura` | `type: dir`, meson | `/app/share/scriptura/*.py`, wrapper at `/app/bin/io.github.andresmessina_SDG.Scriptura` |

SWIG is **no longer a module**. It existed only to generate bindings we now
take pre-generated; nothing in the build needs it.

`libsword` carries two local adjustments worth knowing:

- `flatpak/patches/sword-curl-libraries.patch` plus `-lcurl` in all three
  linker-flag variables, because the CMake build does not propagate curl.
- The tarball has `mirror-urls` alongside the CrossWire URL. CrossWire's web
  server and FTP daemon share one host and fail independently — in July 2026
  the web tier was down for a day. Without the mirror a clean build cannot
  fetch libsword at all. Same tarball, same `sha256`, so the checksum still
  gates both.

Full-text search is SQLite FTS5 through the runtime's own `sqlite3`. No
vendored search dependency.

## Current binding strategy

SWORD's own bindings target was abandoned. `python-libsword` ships
**pre-generated SWIG output** — `Sword.cxx` and `Sword.py` are checked into
its repo — so its build just runs `pkg-config --cflags --libs sword` against
our just-built libsword, compiles the `.cxx`, and installs both files. No SWIG
run, no `Makefile.am` macros, no silent skip paths.

The `sha256: TODO_FILL_BEFORE_BUILD` the old file warned about is long
resolved; the manifest pins a real digest.

For *why* the bindings behave this way, see `SWORD-PYTHON-BUILD.md` in this
directory — it is the knowledge base built from reading the distro packages,
and it is the file to read before touching this area.

## What's been ruled out (do not retry)

All of these silently failed to produce `Sword.py` / `_Sword.so`:

| # | Tried | Outcome |
|---|---|---|
| 1 | `cmake-ninja` + `-DSWORD_BINDINGS=Python` | bindings dir silently skipped |
| 2 | `cmake-ninja` + `-DSWORD_BINDINGS=Python3` | same |
| 3 | as 2, plus `-DPython3_EXECUTABLE=…` and `-DSWIG_EXECUTABLE=/app/bin/swig` | same |
| 4 | autotools `--with-bindings=python3` (BibleTime's pattern) | libsword.so built; no bindings |
| 5 | `cmake-ninja` + `-DSWORD_PYTHON_3:BOOL=TRUE` + a setuptools migration patch | libsword.so built; no bindings |

The setuptools patch from attempt 5 is gone from the tree; the only patch
left is the curl one described above.

## Sandbox

Every permission and the reason it is there — this list is the thing to audit
when adding a feature, and a permission with no reason is one to remove:

| Permission | Why |
|---|---|
| `--socket=wayland`, `--socket=fallback-x11`, `--share=ipc`, `--device=dri` | ordinary GTK 4 app |
| `--share=network` | module downloads from CrossWire, data packs, audio feeds |
| `--persist=.sword` | installed SWORD modules live in `~/.sword` |
| `--socket=pulseaudio` | spoken devotionals and chapter audio. **Playback only** — nothing is recorded, no microphone is requested |
| `--talk-name=org.gnome.SettingsDaemon.Color` | evening paper follows GNOME Night Light; without it the monitor is silently inert in the sandbox |

No `--filesystem=host`. File save/open goes through `xdg-desktop-portal`, and
printing through the Print portal (verified present in-sandbox, version 4, so
no manifest permission was needed).

## Verified

**2026-07-27, on the 1.4.0 build**, checked against the built artifact rather
than the source tree:

- all **67** shipped modules import inside the sandbox
  (`flatpak-builder --run … python3 -c "import …"`)
- `Sword.py` and `_Sword.cpython-313-*.so` land in site-packages; libsword
  reports 1.9.0
- the About dialog reports the version meson built (guarded now by
  `tests/test_version_sync.py`, after a build shipped 1.3.0 in About while
  everything else said 1.4.0)
- `appstreamcli compose` keeps all 6 screenshots — it drops 404ing URLs
  silently, and they resolve to `raw.githubusercontent.com` on `main`, so
  `main` must be pushed before building
- the signed repo installs and the live remote serves the expected commit

**2026-05-22**, in a clean Zorin OS 18 VM (the architecture question, still
settled): `import Sword` resolves; Welcome → Install essentials lands modules
in the sandboxed `.sword`; chapters, annotations and the file portal all work.

A green test suite says nothing about any of this. Meson's `py_sources` list
is a second manifest, and a module missing from it simply is not shipped —
`tests/test_meson_manifest.py` guards the list, but only running the built
sandbox proves the result.

## Reference manifests studied

No Flathub app combines Python and SWORD, which is why the pivot above was
needed. These were read for the libsword build skeleton only:

- **BibleTime** (`info.bibletime.BibleTime`) — Qt/C++, no Python
- **Xiphos** (`org.xiphos.Xiphos`) — GTK/C, no Python
- **bibref** (`io.github.kovzol.bibref`) — Qt/C++, no Python
- **Sonofman** (`org.hlwd.sonofman`) — Python, but its own SQLite data, not SWORD
- **bible_gui** (`net.lugsole.bible_gui`) — Python, but SPB/SQLite/tsv/xml, not SWORD

## History

The app ID moved twice: `org.codeberg.*` → `page.codeberg.andresmessina.Scriptura`
→ `io.github.andresmessina_SDG.Scriptura` when hosting moved to GitHub
(`cc61259`, 2026-07-23). Anything still naming a `codeberg` app ID, path or
URL is stale by definition — Codeberg is now only a read-only push mirror.
