# Flatpak packaging — research notes

Working document. Records findings, open questions, and decisions made
while planning Phase 2 (B2: Flatpak manifest) of the release checklist.
Not user-facing — internal planning only.

Last update: 2026-05-22.

---

## Decisions made

- **Migration of existing source-install users: not a goal.** Current
  users are testers; a clean fresh install under Flatpak is acceptable.
  No code or UX work for legacy-data import. The B1+S1 XDG-paths work
  was still right for correctness, but no migration UI is required.
- **`--persist=.sword`** is the canonical SWORD-app pattern on Flathub.
  Both Xiphos and BibleTime use it. We follow.
- **No `--filesystem=home`** by default. Users wanting host SWORD-module
  sharing can opt in via `flatpak override --filesystem=home <app-id>`.
- **CLucene is droppable** — we use Whoosh for full-text search. Set
  `-DSWORD_NO_CLUCENE=Yes` to skip even if libclucene is present.
- **Runtime target: `org.gnome.Platform//50`** (current stable, released
  2026-03-18). Branch 48 EOL'd 2026-03-24. Branch 49 is also valid but
  50 buys us another ~9 months of support window before next EOL.
- **Build approach: single CMake module**, not the two-step
  CMake-then-setup.py the CrossWire wiki describes. Debian's packaging
  proves the single-step path works.

---

## The known-good CMake recipe (from Debian sword 1.9.0+dfsg-8)

Verbatim from `salsa.debian.org/pkg-crosswire-team/sword`'s `debian/rules`:

```makefile
%:
	dh $@ --with python3 -Scmake

override_dh_auto_configure:
	dh_auto_configure -- \
		-DLIB_INSTALL_DIR="/usr/lib/$(DEB_HOST_MULTIARCH)" \
		-DSYSCONF_INSTALL_DIR=/etc \
		-DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
		-DSWORD_PYTHON_3:BOOL=TRUE
```

**Translated to a Flatpak module:**

```yaml
- name: sword
  buildsystem: cmake-ninja
  config-opts:
    - -DCMAKE_BUILD_TYPE=Release
    - -DCMAKE_INSTALL_PREFIX=/app
    - -DLIB_INSTALL_DIR=/app/lib
    - -DSYSCONF_INSTALL_DIR=/app/etc
    - -DCMAKE_POLICY_VERSION_MINIMUM=3.5
    - -DSWORD_PYTHON_3:BOOL=TRUE
    - -DSWORD_NO_CLUCENE=Yes
  sources:
    - type: archive
      url: http://crosswire.org/ftpmirror/pub/sword/source/v1.9/sword-1.9.0.tar.gz
      sha256: <pin>
```

**The flag name is `SWORD_PYTHON_3:BOOL=TRUE`, NOT `SWORD_BINDINGS=Python`**
as the CrossWire wiki suggests. Wiki is older; the modern flag is what
Debian uses and what's known to work on toolchains as recent as
Debian sid (GCC 14, Python 3.13, SWIG 4.x).

### Debian's Build-Depends (everything sword needs at build time)

- `cmake`
- `swig`
- `python3-dev`, `python3-setuptools`
- `libbz2-dev`, `liblzma-dev`, `libz-dev`
- `libcurl4-gnutls-dev`
- `libclucene-dev` (skip — `-DSWORD_NO_CLUCENE=Yes`)
- `libicu-dev`
- `chrpath` (only for Debian's strip-RPATH step; Flatpak doesn't need this)

The GNOME 50 SDK provides: GCC, glibc, ICU, libxml2, glib, GTK4,
libadwaita, PyGObject. Open question: does the SDK ship SWIG, bz2,
xz/lzma, zlib, curl development headers? bz2/xz/zlib/curl almost
certainly yes (freedesktop base). **SWIG is the one to verify.** If
not in SDK, add as a small build-only manifest module (cleanup="*"
after build).

---

## Canonical SWORD-on-Flathub pattern (BibleTime + Xiphos)

Both apps use this `finish-args` baseline:

```
--share=ipc
--share=network
--socket=wayland
--socket=fallback-x11
--device=dri
--persist=.sword
--persist=.<appname>   # e.g. .bibletime, .xiphos
```

`--persist=.sword` bind-mounts `~/.sword/` *inside* the sandbox to
`~/.var/app/<app-id>/.sword/` *on* the host. Total isolation from host
`~/.sword/` unless user adds `--filesystem=home`.

### BibleTime's libsword build (autotools, no Python bindings)

```json
{
  "name": "sword",
  "sources": [{"type":"archive","url":"http://crosswire.org/ftpmirror/pub/sword/source/v1.9/sword-1.9.0.tar.gz"}],
  "config-opts": ["--disable-static"],
  "cleanup": ["/lib/pkgconfig","/lib/*.la","/include"]
}
```

Minimal — they don't need Python bindings, and they accept the runtime's
CLucene transitive dep. **Not directly applicable to us** because we
need Python bindings, which the autotools build does not produce
reliably on modern systems (per CrossWire wiki — and Debian only ships
the CMake-built bindings).

### Xiphos differences

Same libsword module as BibleTime + `biblesync`, `dbus-glib`, `minizip`,
`appstream`. No Python.

---

## Our manifest skeleton (proposed)

```yaml
app-id: io.codeberg.andresmessina.BibleReader  # TBD; see App-ID section
runtime: org.gnome.Platform
runtime-version: '50'
sdk: org.gnome.Sdk
command: bible-reader

finish-args:
  - --share=ipc
  - --share=network
  - --socket=wayland
  - --socket=fallback-x11
  - --device=dri
  - --persist=.sword

modules:
  # Whoosh (pure Python; generate via flatpak-pip-generator)
  - python3-whoosh.yaml

  # SWORD + Python bindings (single CMake module — see Debian recipe)
  - name: sword
    buildsystem: cmake-ninja
    config-opts:
      - -DCMAKE_BUILD_TYPE=Release
      - -DLIB_INSTALL_DIR=/app/lib
      - -DSYSCONF_INSTALL_DIR=/app/etc
      - -DCMAKE_POLICY_VERSION_MINIMUM=3.5
      - -DSWORD_PYTHON_3:BOOL=TRUE
      - -DSWORD_NO_CLUCENE=Yes
    sources:
      - type: archive
        url: http://crosswire.org/ftpmirror/pub/sword/source/v1.9/sword-1.9.0.tar.gz
        sha256: <pin at manifest-write time>
    cleanup:
      - /lib/pkgconfig
      - /lib/*.la
      - /include

  # Bible Reader itself (simple manifest copying source into /app)
  - name: bible-reader
    buildsystem: simple
    build-commands:
      - install -Dm755 main.py /app/share/bible-reader/main.py
      - cp -r *.py data icons /app/share/bible-reader/
      - install -Dm755 bible-reader.sh /app/bin/bible-reader
      - install -Dm644 io.codeberg.andresmessina.BibleReader.desktop -t /app/share/applications/
      - install -Dm644 io.codeberg.andresmessina.BibleReader.metainfo.xml -t /app/share/metainfo/
      - install -Dm644 icons/io.codeberg.andresmessina.BibleReader.svg -t /app/share/icons/hicolor/scalable/apps/
    sources:
      - type: dir
        path: .
```

Where `bible-reader.sh` is a small launcher:

```sh
#!/bin/sh
exec python3 /app/share/bible-reader/main.py "$@"
```

---

## Things flatpak-builder-lint will check (and that will block submission)

### Manifest check
- `appid-not-defined` — must declare app-id
- `appid-filename-mismatch` — manifest filename = app-id (so the file
  must be named `io.codeberg.andresmessina.BibleReader.yaml`)
- `appid-less-than-3-components` — reverse-DNS required
- `toplevel-no-command` — must set `command:`
- `finish-args-host-filesystem-access` — `--filesystem=host` blocks
- `finish-args-arbitrary-dbus-access` — `--socket=session-bus` blocks

### AppStream check (appstreamcli validate + Flathub overrides)
- `appstream-metainfo-missing` — must ship `<app-id>.metainfo.xml`
- `appstream-id-mismatch-flatpak-id` — ID in XML = app-id
- `content-rating-missing` — OARS rating required
- `desktop-app-launchable-omitted` — `<launchable>` tag required
- `appstream-missing-screenshots` — ≥ 1 screenshot
- `releases-info-missing` — `<releases>` with version + date

### Builddir check
- `no-exportable-icon-installed` — icon must match `$FLATPAK_ID`
- `desktop-file-icon-key-absent` — `Icon=` in .desktop
- `desktop-file-not-installed` — file must be at
  `/app/share/applications/$FLATPAK_ID.desktop`
- `desktop-file-exec-key-absent` — must have `Exec=`

**All errors AND warnings are fatal.** Run locally before submission:

```sh
flatpak run --command=flatpak-builder-lint org.flatpak.Builder \
  appstream io.codeberg.andresmessina.BibleReader.metainfo.xml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder \
  manifest io.codeberg.andresmessina.BibleReader.yaml
```

---

## MetaInfo XML — mandatory fields

```xml
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>io.codeberg.andresmessina.BibleReader</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>

  <name>Bible Reader</name>
  <summary>GNOME-native Bible study with SWORD modules</summary>

  <description>
    <p>A GNOME-native Bible study app...</p>
    <p>Features:</p>
    <ul>
      <li>Two-pane layout with independent module selectors</li>
      <li>SWORD modules and eBible.org translations</li>
      <li>Strong's lexicon with hover word-study</li>
      <li>Full-text search per module</li>
      ...
    </ul>
  </description>

  <developer id="info.codeberg.andresmessina">
    <name>Andres Messina</name>
  </developer>

  <url type="homepage">https://codeberg.org/andresmessina/bible-reader</url>
  <url type="bugtracker">https://codeberg.org/andresmessina/bible-reader/issues</url>
  <url type="vcs-browser">https://codeberg.org/andresmessina/bible-reader</url>

  <launchable type="desktop-id">io.codeberg.andresmessina.BibleReader.desktop</launchable>

  <screenshots>
    <screenshot type="default">
      <image>https://codeberg.org/andresmessina/bible-reader/raw/branch/main/screenshots/two-pane.png</image>
      <caption>Two-pane layout with KJVA and MHCC</caption>
    </screenshot>
    <!-- More screenshots... -->
  </screenshots>

  <releases>
    <release version="1.0.0" date="2026-XX-XX">
      <description><p>Initial release.</p></description>
    </release>
  </releases>

  <content_rating type="oars-1.1" />

  <branding>
    <color type="primary" scheme_preference="light">#9b8df0</color>
    <color type="primary" scheme_preference="dark">#5b4cb8</color>
  </branding>

  <categories>
    <category>Education</category>
    <category>Literature</category>
  </categories>
</component>
```

Screenshot rules:
- HTTPS URLs only
- If hosted in git, use a commit SHA or tag, not a branch (Codeberg's
  `raw/commit/<sha>/...` pattern works)
- At least one required

Category rules:
- No generic "GTK", "Qt", "GUI"
- Use freedesktop Menu spec categories (Education, Literature, Office)

---

## App-ID — conflicting evidence on Codeberg prefix

Two patterns documented; policy may have evolved:

| Candidate | Source | Status |
|---|---|---|
| `org.codeberg.andresmessina.BibleReader` | GNOME Discourse t/23517 — a maintainer endorsed "org.codeberg.USER.APP" | Older guidance; may be deprecated |
| `page.codeberg.andresmessina.BibleReader` | Real-world: galaxyflasher (`page.codeberg.ethicalhaquer.galaxyflasher`); Imaginer migrated TO `page.codeberg.Imaginer.Imaginer` | Appears to be current Flathub-blessed form |
| `io.github.andresmessina.BibleReader` | Standard Flathub pattern, requires GitHub mirror | Always works but needs mirror |

**Action:** Verify by grepping the current Flathub org for `org.codeberg.*`
vs `page.codeberg.*` — whichever has more recent activity is the
current pattern. If both exist, lean toward `page.codeberg.*` (the
later-migrated form).

**Working recommendation:** `page.codeberg.andresmessina.BibleReader`

---

## What we drop / inherit

| Dep | Where | Notes |
|---|---|---|
| GTK4, libadwaita, PyGObject | GNOME 50 runtime | Already present. |
| ICU | GNOME 50 runtime | libsword links against it. |
| GLib, GObject, GIO | GNOME 50 runtime | Standard. |
| Python 3.x | GNOME 50 runtime | Version TBD — likely 3.13 in branch 50. |
| SQLite | GNOME 50 runtime | Used by ebible_bridge. |
| zlib, bz2, xz, libcurl | freedesktop base | Sword build needs headers — should be in Sdk. |
| **SWIG** | **Probably needs verification.** | If not in Sdk, add as build-only module. |
| **CLucene** | **drop** | `-DSWORD_NO_CLUCENE=Yes`; we use Whoosh. |
| **Whoosh** | **bundle** | Pure Python; flatpak-pip-generator. |

---

## Network behavior under sandbox

`--share=network` gives full TCP/UDP egress. Our app needs network for:

- **Module Manager** — HTTP/FTP to crosswire.org and mirrors
- **eBible bridge** — HTTPS to ebible.org
- **Open data** — HTTPS to openbible.info and Dodson lexicon mirror

All work. No portal needed for these because they're our own outbound
HTTP. The only portal we exercise is `xdg-desktop-portal` for
`Gtk.FileDialog` (export Study Journal), which works without any
`finish-args` setting — portals don't require static permission.

---

## Open questions remaining

1. **Does GNOME 50 SDK ship SWIG?** Unverified but freedesktop-sdk has
   a swig mirror at `gitlab.com/freedesktop-sdk/mirrors/github/swig`
   suggesting it's built upstream. If absent at runtime, add a small
   build-only `swig` module (cleanup=`["*"]`). Confirm by running
   `flatpak run --command=which org.gnome.Sdk//50 swig`.
2. **Confirmed Python version**: freedesktop-sdk 25.08 ships Python
   3.13.11; GNOME 50 Sdk uses freedesktop-sdk-25.08 base, so we expect
   Python 3.13.x. SWORD's CMake `find_package(Python3)` should resolve
   dynamically — don't hardcode.
3. **Codeberg prefix policy** — see App-ID section. Real-world apps
   are using `page.codeberg.*`. Verify before manifest commit.
4. **Brand colors** — placeholders only (`#9b8df0` / `#5b4cb8`).
5. **CA certificate handling under sandbox** — known issue: Flatpak
   apps sometimes fail SSL on custom-CA distros. Affects Module
   Manager + eBible + open-data downloads. Bundled SDK CA bundle
   normally works; document the workaround (`flatpak override
   --filesystem=/etc/ssl/certs:ro`) in README.
6. **Sword InstallMgr sample modules**: bibref's manifest moves the
   sample/test sword data SWORD installs to `/app/share/sword`. Check
   whether SWORD 1.9.0's CMake install creates such artifacts and
   whether they interfere with our per-user `~/.sword/` discovery.

---

## Validation plan (before manifest commit)

1. **Smoke test SWORD CMake Python build outside Flatpak.** On
   the dev machine, run:
   ```sh
   wget http://crosswire.org/ftpmirror/pub/sword/source/v1.9/sword-1.9.0.tar.gz
   tar xf sword-1.9.0.tar.gz
   cd sword-1.9.0
   cmake -B build -DSWORD_PYTHON_3:BOOL=TRUE -DSWORD_NO_CLUCENE=Yes \
                  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
                  -DCMAKE_INSTALL_PREFIX=/tmp/sword-test
   cmake --build build && cmake --install build
   python3 -c "import sys; sys.path.insert(0, '/tmp/sword-test/lib/python3*/site-packages'); import Sword; print(Sword.SWMgr())"
   ```
   If this works, the Flatpak manifest will work.

2. **Install `org.flatpak.Builder` from Flathub**, run a partial build
   of just the `sword` module to confirm SDK has SWIG.

3. **Run `flatpak-builder-lint`** against the draft manifest before
   submitting any PR to Flathub.

---

## Third precedent: bibref (`io.github.kovzol.bibref`)

KDE/Qt SWORD app. Manifest details:

- Runtime: `org.kde.Platform//6.10` (uses Qt base + WebEngine)
- libsword built with cmake-ninja, utilities and examples disabled,
  linked to curl
- Post-install moves sword DB files from `/app/tmp/.sword` to
  `/app/share/sword` — implication: SWORD's default install creates
  files in a `.sword` subdir under the install prefix that we may need
  to handle.
- Boost 1.90.0, Graphviz 14.1.3 as siblings (bibref's specific needs;
  not relevant to us)
- No Python bindings — third confirmation that **no existing Flathub
  app builds SWORD Python bindings.**

## Cross-cutting risks identified

### CA certificate handling (rated: medium risk)

Flatpak apps occasionally fail SSL handshake because the SDK's bundled
CA store doesn't match the host's. Affects:
- Module Manager (HTTPS to crosswire.org and mirrors)
- eBible bridge (HTTPS to ebible.org)
- OpenBible / Dodson downloads

The Flatpak `--filesystem=/etc/ssl/certs:ro` override is the documented
workaround. Most apps work fine with the SDK's bundled CA bundle —
this only bites on custom-CA enterprise distros. We should test in
the VM and document the workaround in README if needed.

GNOME 50 / freedesktop-sdk-25.08 bundle libcurl with the up-to-date
ca-certificates, so default-case should work.

### SWORD's "sample modules" install (rated: low risk, needs check)

The bibref manifest does `mv /app/tmp/.sword /app/share/sword`. SWORD's
CMake install creates sample modules at the prefix. With our
`--persist=.sword` setup, those don't conflict with the user's modules
in `~/.sword/`, but they're dead weight in the runtime. Add a cleanup
step:
```yaml
cleanup:
  - /share/sword
```
or move them as bibref does.

### CrossWire wiki out-of-date risk (rated: addressed)

The wiki says use `-DSWORD_BINDINGS=Python` but Debian uses
`-DSWORD_PYTHON_3:BOOL=TRUE`. Debian is authoritative — they ship the
binding in current testing.

### Python.h header availability (rated: addressed)

Confirmed available in GNOME SDK at `/usr/include/python3.X` (per
Flathub Discourse pybind11 thread). Modern CMake's
`find_package(Python3 COMPONENTS Development)` resolves it correctly.

### Whoosh transitive dependencies (rated: low risk)

Whoosh is pure Python with no compiled extensions. Generate via:
```sh
flatpak-pip-generator whoosh
```
Output is a small JSON. Pin SHA-256 hashes at generation time.

---

## Validation plan (updated)

1. **5-min smoke test (deferred):** Build SWORD 1.9.0 with
   `-DSWORD_PYTHON_3:BOOL=TRUE` on the dev machine; verify `import
   Sword` works in plain Python 3.13.
2. **Verify SWIG presence in SDK:**
   ```sh
   flatpak install --user -y flathub org.gnome.Sdk//50
   flatpak run --command=which org.gnome.Sdk//50 swig
   ```
3. **Verify Python version in runtime:**
   ```sh
   flatpak run --command=python3 org.gnome.Sdk//50 --version
   ```
4. **Verify Codeberg app-id prefix policy:**
   ```sh
   # Find recent Flathub apps using both prefixes
   gh search repos 'org.codeberg' --owner=flathub --limit 5
   gh search repos 'page.codeberg' --owner=flathub --limit 5
   ```
5. **Draft manifest + run `flatpak-builder-lint`** locally.
6. **Test SSL/CA path** by running Module Manager from inside a
   built-but-not-published flatpak.

---

## Sources

- [BibleTime Flathub manifest](https://github.com/flathub/info.bibletime.BibleTime/blob/master/info.bibletime.BibleTime.json)
- [Xiphos Flathub manifest](https://github.com/flathub/org.xiphos.Xiphos/blob/master/org.xiphos.Xiphos.json)
- [bibref Flathub manifest](https://github.com/flathub/io.github.kovzol.bibref)
- [GNOME Discourse — Codeberg app-id question](https://discourse.gnome.org/t/can-i-use-org-codeberg-for-an-application-id/23517)
- [Flathub Discourse — pybind11 Python.h](https://discourse.flathub.org/t/pybind11-does-not-build-no-python-h-header/7642)
- [Flathub Discourse — Remapping host directories](https://discourse.flathub.org/t/remapping-host-directories-into-the-sandbox/6991)
- [Imaginer commit migrating to page.codeberg](https://git.projectsegfau.lt/0xMRTT/Imaginer/commit/c5090298a93113035dccacbacfcd2d801b8e15f4)
- [Flatpak issue #2721 — host CA certs](https://github.com/flatpak/flatpak/issues/2721)
- [Flatpak issue #4314 — --persist semantics](https://github.com/flatpak/flatpak/issues/4314)
- [freedesktop-sdk swig mirror](https://gitlab.com/freedesktop-sdk/mirrors/github/swig/swig)
- [pysword (alternative path, not chosen)](https://pypi.org/project/pysword/)
- [CrossWire DevTools:CMake](https://wiki.crosswire.org/DevTools:CMake)
- [Debian sword 1.9.0+dfsg-8 rules](https://sources.debian.org/src/sword/1.9.0+dfsg-8/debian/rules/)
- [Debian sword control](https://sources.debian.org/src/sword/1.9.0+dfsg-8/debian/control/)
- [Flatpak Sandbox Permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html)
- [Flatpak Conventions](https://docs.flatpak.org/en/latest/conventions.html)
- [Flatpak Python guide](https://docs.flatpak.org/en/latest/python.html)
- [Flathub MetaInfo Guidelines](https://docs.flathub.org/docs/for-app-authors/metainfo-guidelines)
- [Flathub Requirements](https://docs.flathub.org/docs/for-app-authors/requirements)
- [flatpak-builder-lint README](https://github.com/flathub-infra/flatpak-builder-lint/blob/master/README.md)
- [GNOME 50 release notes](https://release.gnome.org/50/)
- [Available Runtimes](https://docs.flatpak.org/en/latest/available-runtimes.html)
- [Freedesktop SDK 25.08 deep dive (Python 3.13.11)](https://www.oreateai.com/blog/freedesktop-sdk-2508-a-deep-dive-into-the-latest-updates-and-what-they-mean/f52097886c91465b4c78a994a409fba5)
- [KDE PySide Flatpak guide](https://develop.kde.org/docs/getting-started/python/python-flatpak/)
- [sword-devel: SWIG bindings discussion](https://sword-devel.crosswire.narkive.com/3oSBs3m2/swig-bindings-was-re-what-is-a-sword-module)
