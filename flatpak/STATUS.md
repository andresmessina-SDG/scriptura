# Flatpak packaging status

Current state of `org.codeberg.andresmessina.BibleReader.yml` and what
the Flathub submission PR needs to resolve.

## What works (verified end-to-end 2026-05-22)

Flatpak builds, installs, and runs to the welcome window inside a
clean Zorin OS 18 VM. Confirmed working in that environment:

- `import Sword` resolves (the long-standing wall).
- Welcome → Install essentials → modules land in
  `~/.var/app/org.codeberg.andresmessina.BibleReader/.sword/`.
- Open a module and read — SWMgr discovery, chapter loads,
  annotations all work.
- File picker via `xdg-desktop-portal` (Study Journal → Export).
- Settings / bookmarks / annotations persist across relaunch
  in the sandboxed XDG dirs (B1+S1 work paying off).

The SWORD-in-Flatpak architecture question is closed.

Validated pieces from prior builds (unchanged by the latest pivot):

- **Runtime + SDK**: `org.gnome.Platform//49`, `org.gnome.Sdk//49`.
- **SWIG** (`swig-4.2.1`): builds as a build-time-only module
  (`cleanup: ['*']`). Kept as a safety net; may be removable.
- **libcurl** (`curl-8.10.0`): built explicitly because libsword's
  configure didn't find a usable curl in the runtime cleanly.
- **libsword** (`sword-1.9.0`): C++ shared library only, no Python
  bindings target. Installs `libsword.so` + `sword.pc`.
- **Whoosh** (`Whoosh-2.7.4`): pip-installs into
  `/app/lib/python3.13/site-packages/`.
- **Bible Reader app code**: all `.py` files installed to
  `/app/share/bible-reader/`. Wrapper at
  `/app/bin/org.codeberg.andresmessina.BibleReader`.
- **PNG icons**: 48/64/128/256 rendered by `rsvg-convert` from the
  source SVG.
- **Desktop file**: `Exec=org.codeberg.andresmessina.BibleReader %U`.
- **Sandbox**: wayland + fallback-x11 + network + dri + `~/.sword`
  persistence.

## Current binding strategy

We stopped trying to coax SWORD's own bindings target into producing
the `Sword.py` / `_Sword.so` pair. Instead the manifest now pulls in
**Greg Hellings' `python-libsword`** (`github.com/greg-hellings/
python-libsword`, tag `v1.9.0.post1`) as a separate module after
libsword:

| Layer | Source | What it produces |
|---|---|---|
| `libsword` | crosswire.org/...sword-1.9.0.tar.gz | `/app/lib/libsword.so`, `/app/lib/pkgconfig/sword.pc` |
| `python-libsword` | github.com/greg-hellings/python-libsword v1.9.0.post1 | `/app/lib/python3.X/site-packages/Sword.py` + `_Sword*.so` |

The python-libsword package ships **pre-generated SWIG output** —
`Sword.cxx` and `Sword.py` are checked into its repo. Its `setup.py`
just calls `pkg-config --cflags --libs sword` (resolves to our
just-built libsword in `/app/lib`), compiles the `.cxx` against
libsword + Python dev headers, and lands both files in
`site-packages`. No SWIG run, no Makefile.am macros, no silent skip
paths.

**Outstanding TODO**: the `python-libsword` source has
`sha256: TODO_FILL_BEFORE_BUILD`. Compute with:
```sh
wget https://github.com/greg-hellings/python-libsword/archive/refs/tags/v1.9.0.post1.tar.gz
sha256sum v1.9.0.post1.tar.gz
```
and paste into the manifest before the next `flatpak-builder` run.

## What's been ruled out (do not retry)

The following approaches were exhausted in earlier iterations. They
all silently failed to produce `Sword.py` / `_Sword.so`:

| Attempt | What we tried | Outcome |
| --- | --- | --- |
| 1 | `cmake-ninja` + `-DSWORD_BINDINGS=Python` | Bindings dir silently skipped. |
| 2 | `cmake-ninja` + `-DSWORD_BINDINGS=Python3` | Same. |
| 3 | Same + `-DPython3_EXECUTABLE=…` + `-DSWIG_EXECUTABLE=/app/bin/swig` | Same. |
| 4 | autotools + `--with-bindings=python3` (BibleTime pattern) | libsword.so builds; no Sword.py / _Sword.so. |
| 5 | `cmake-ninja` + `-DSWORD_PYTHON_3:BOOL=TRUE` + setuptools migration patch | libsword.so builds; bindings still missing. |

The patch `flatpak/patches/migrate-to-setuptools.diff` is no longer
referenced by the manifest. It can be deleted in a follow-up commit
or kept for historical reference.

## Reference manifests we studied

- **BibleTime** (`info.bibletime.BibleTime`) — Qt/C++, no Python.
  Useful only for the libsword build skeleton.
- **Xiphos** (`org.xiphos.Xiphos`) — GTK/C, no Python. Same.
- **bibref** (`io.github.kovzol.bibref`) — Qt/C++, no Python. Same.
- **Sonofman** (`org.hlwd.sonofman`) — Python, but uses its own SQLite
  data, *not* SWORD. Not directly relevant.
- **bible_gui** (`net.lugsole.bible_gui`) — Python, but uses SPB/
  SQLite/tsv/xml formats, *not* SWORD. Not directly relevant.

No existing Flathub app combines Python + SWORD. We're first; that's
why the manifest needed the python-libsword pivot above.

## Remaining work before Flathub submission

The Flatpak runs locally. Items below are submission gates:

1. **App-ID decision** — `org.codeberg.*` (current) vs
   `page.codeberg.*` (newer Flathub convention). Affects manifest,
   metainfo, .desktop, icon filenames, `main.py` constant. Decide
   before everything else so renames don't cascade.
2. **Restore metainfo install line** in manifest (currently
   commented out; Flathub's builder runs `appstreamcli compose`
   cleanly, unlike Zorin's).
3. **5 screenshots** captured from the running app, hosted at
   stable Codeberg `raw/commit/<sha>/...` URLs, referenced from
   `data/org.codeberg.andresmessina.BibleReader.metainfo.xml`'s
   `<screenshots>` block.
4. **`CHANGELOG.md`** with v1.0.0 entry.
5. **Local `flatpak-builder-lint` pass** against the manifest +
   metainfo.
6. **`git tag v1.0.0`** + push tag.
7. **PR to flathub/flathub** for new-app submission.

## App-ID note

Real-world Codeberg-hosted apps on Flathub now use the prefix
`page.codeberg.<user>.<App>` (e.g. `page.codeberg.ethicalhaquer.
galaxyflasher`). The current manifest still uses
`org.codeberg.andresmessina.BibleReader`, which a maintainer
endorsed on GNOME Discourse but predates the `page.codeberg.*`
convention. **Verify with Flathub before submission**; the change
ripples through manifest, metainfo, desktop file, icon filenames,
and source code constants.
