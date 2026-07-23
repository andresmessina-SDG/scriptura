# How SWORD's Python bindings actually build

Knowledge base from reading the authoritative distro packages.
Recorded because we spent a session iterating wrong CMake flags
before discovering the real recipe.

## TL;DR

Three things must be true to get `Sword.py` + `_Sword*.so` from a
SWORD 1.9.0 source tarball on modern Python:

1. CMake flag is **`SWORD_PYTHON_3:BOOL=TRUE`**. Not
   `SWORD_BINDINGS=Python3`. Not autotools' `--with-bindings=python3`
   either — at least not cleanly on every platform.

2. Apply Fedora's **`migrate-to-setuptools.diff`** patch. SWORD's
   build generates a `setup.py` that imports from `distutils`,
   which Python 3.12+ removed. Without the patch, the binding
   build's `setup.py` raises ModuleNotFoundError silently and no
   files get produced.

3. Set **`SWORD_PYTHON_INSTALL_DIR`** to the install prefix
   (`/app` in Flatpak, `/usr` for a distro build). Otherwise the
   generated Python module lands somewhere Python can't find.

Plus the usual peers:
- SWIG must be on PATH (build dep).
- libcurl must be installed and findable.
- `CMAKE_POLICY_VERSION_MINIMUM=3.5` because SWORD's CMakeLists
  declares `cmake_minimum_required` against a very old version
  that modern CMake refuses.

## Authoritative sources

- **Fedora**: `https://src.fedoraproject.org/rpms/sword` —
  `sword.spec` + `migrate-to-setuptools.diff` are the canonical
  recipe.
- **SWORD source**: `bindings/swig/python/CMakeLists.txt` in the
  1.9.0 tarball. References `SWORD_PYTHON_3` and friends. Note
  the path is `python/` not `python3/` — there isn't a separate
  py3 subdir.
- **BibleTime's Flatpak manifest** (`flathub/info.bibletime.BibleTime`)
  is useful for the C++ libsword build settings but DOESN'T cover
  Python bindings — BibleTime is Qt/C++ and doesn't ship them.

## What the bindings build actually does

Conceptually:

1. CMake's `bindings/swig/python/CMakeLists.txt` runs SWIG against
   the `.i` interface file to generate a C++ wrapper.
2. CMake writes out a `setup.py` template that calls
   `Extension(...)` linking the wrapper against libsword.
3. The generated `setup.py` is invoked at install time:
   `python3 setup.py install --root=$ROOT --prefix=$DIR`.
4. That produces `Sword.py` and `_Sword.cpython-*.so` under
   `$ROOT/$DIR/lib/python*/site-packages/`.

The setup.py imports `from distutils.core import setup, Extension`.
Python 3.12 removed `distutils`. So on any modern runtime (Fedora
40+, GNOME Platform 48+), step 3 fails silently. CMake doesn't
notice because the install step is wrapped in a way that swallows
the error — the build "succeeds" but ships only `libsword.so`.

## Patch details

`migrate-to-setuptools.diff` rewrites four lines across three
files:

- `bindings/swig/oldmake/Makefile.am`
- `bindings/swig/package/Makefile.am`
- `bindings/swig/package/Makefile.in`
- `bindings/swig/python/CMakeLists.txt`

Each change replaces `from distutils.core import setup` (and the
`distutils.extension` import) with `from setuptools import setup,
Extension`. setuptools provides API-compatible drop-ins for both.

Author: Aaron Rainbolt (Fedora maintainer). Sent upstream but
not yet merged at the time Fedora ships it.

## Fedora's full CMake invocation (annotated)

```
%cmake -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
       -DINCLUDE_INSTALL_DIR:PATH=/usr/include \
       -DLIB_INSTALL_DIR:PATH=/usr/lib64 \
       -DSYSCONF_INSTALL_DIR:PATH=/etc \
       -DSHARE_INSTALL_PREFIX:PATH=/usr/share \
       -DLIBSWORD_LIBRARY_TYPE=Shared \
       -DSWORD_PYTHON_3:BOOL=TRUE \        # ← bindings flag
       -DSWORD_PERL:BOOL=TRUE \            # ← perl flag (same pattern)
       -DSWORD_BUILD_UTILS="Yes" \
       -DLIBSWORD_SOVERSION=1.9 \
       -DSWORD_BUILD_TESTS=Yes \
       -DSWORD_PYTHON_INSTALL_ROOT=$buildroot \   # DESTDIR-like
       -DSWORD_PYTHON_INSTALL_DIR=/usr            # prefix
```

For Flatpak we drop the install-root override (Flatpak's
`cmake-ninja` buildsystem applies DESTDIR via FLATPAK_DEST) and
set `SWORD_PYTHON_INSTALL_DIR=/app`.

## Other gotchas (for future sessions)

- `LIBSWORD_LIBRARY_TYPE=Shared` is needed; the default sometimes
  builds static. Distros want shared for ABI compatibility.
- `SWORD_BUILD_TESTS=OFF` skips the `buildtest.cpp` target — saves
  build time AND avoids the `-Wl,--as-needed` linker error
  about unresolved curl symbols (because the tests don't carry
  the curl dependency through correctly).
- libcurl must be in the link path. The GNOME runtimes don't
  always ship it where SWORD's `find_package(CURL)` looks; we
  build it as a separate Flatpak module to be safe.
- SWIG must be present at build time. Not in the GNOME SDK by
  default; we build it as a `cleanup: ['*']` module.

## If you need to verify the bindings landed

```sh
flatpak run --command=find io.github.andresmessina_SDG.Scriptura \
    /app -iname "Sword*" -o -iname "_Sword*"
```

Expected:
- `/app/lib/python3.X/site-packages/Sword.py`
- `/app/lib/python3.X/site-packages/_Sword.cpython-*.so`

Plus the existing `/app/lib/libsword.so` and friends.
