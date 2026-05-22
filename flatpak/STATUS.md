# Flatpak packaging status

Current state of `org.codeberg.andresmessina.BibleReader.yml` and what
the Flathub submission PR needs to resolve.

## What works

End-to-end local builds with `flatpak-builder` complete successfully
against `org.gnome.Platform//49`. The resulting Flatpak installs and
the app's wrapper script runs Python, but `import Sword` fails at
startup. Everything ELSE has been validated:

- **Runtime + SDK**: `org.gnome.Platform//49`, `org.gnome.Sdk//49`.
- **SWIG** (`swig-4.2.1`): builds as a build-time-only module
  (`cleanup: ['*']`).
- **libcurl** (`curl-8.10.0`): built explicitly because libsword's
  configure didn't find a usable curl in the runtime cleanly.
- **libsword** (`sword-1.9.0`): builds via autotools with
  `--disable-static --with-bindings=python3` (BibleTime's Flathub
  manifest pattern). `libsword.so` lands in `/app/lib/` correctly.
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

## What doesn't work

**SWORD's Python bindings are not built**, regardless of approach.
`flatpak run` dies with:

```
ModuleNotFoundError: No module named 'Sword'
```

We attempted both cmake-ninja and autotools paths:

| Attempt | What we tried | Outcome |
| --- | --- | --- |
| 1 | `cmake-ninja` + `-DSWORD_BINDINGS=Python` | Bindings dir silently skipped. |
| 2 | `cmake-ninja` + `-DSWORD_BINDINGS=Python3` | Same. |
| 3 | Same + `-DPython3_EXECUTABLE=…` + `-DSWIG_EXECUTABLE=/app/bin/swig` | Same. |
| 4 | autotools + `--with-bindings=python3` (BibleTime pattern) | libsword.so builds; no `Sword.py` / `_Sword.so` produced. |

In each case `libsword.so` itself ships, but the SWIG-generated
Python bridge does not. SWORD's build system appears to silently
skip the bindings target when something it requires isn't met — no
hard error, no useful diagnostic in the build log.

## What a Flathub maintainer would need to know

- BibleTime's manifest doesn't help directly because BibleTime is
  Qt/C++ and links libsword via C++ rather than Python. We need
  the equivalent of `python3-sword` (Fedora/Ubuntu's distro package)
  produced inside the Flatpak.
- Yetzirah (also on Flathub) is reportedly a Python+SWORD app —
  examining their manifest would likely resolve this in one read.
- The Python bindings on distro systems are typically built by:
  1. Running SWIG against `bindings/swig/sword.i` to generate
     a C++ wrapper.
  2. Building a Python extension module via `setup.py` linking
     against libsword + Python's dev headers.
  3. Installing both `Sword.py` and `_Sword*.so` into
     `site-packages`.
- We have SWIG built and available in the build environment
  (`/app/bin/swig`); we have libsword built and available
  (`/app/lib/libsword.so`); we have Python 3.13 in the runtime.
  The missing piece is the right manifest-level recipe to invoke
  step 2 and 3 above as part of the build.

## Suggested next iteration (for a maintainer)

A separate `python3-sword` build module after `libsword`, that uses
the same SWORD tarball, runs SWIG and `setup.py` against
`bindings/swig/`, and installs the resulting Python module to
`/app/lib/python3.13/site-packages/`. The exact `build-commands`
shape is what we couldn't figure out locally — a working example
from another Python+SWORD Flathub app would be the unblocker.

## Everything else for v1.0

Items that aren't blocked on the binding issue and can ship in
parallel:

- README + AboutDialog privacy statement.
- `CHANGELOG.md` with v0.9.0 entry.
- 5 screenshots in `data/screenshots/`.
- Restore the `<screenshots>` block in
  `data/org.codeberg.andresmessina.BibleReader.metainfo.xml`.
- Restore the metainfo `install` line in the manifest (commented
  out for now because Zorin's patched flatpak-builder couldn't run
  compose; Flathub's own builder should handle it).
- `git tag v0.9.0`.
