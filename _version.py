"""Single source of truth for the app version.

Imported by:
  - main.py / window.py (About dialog)
  - paths consumers if they ever need to detect a schema migration
  - the Flatpak manifest's `<release>` declaration in metainfo.xml
    (kept in sync manually until a build step automates it)

Versioning is semver-ish: bump MINOR for new features, PATCH for
bugfixes.
"""

__version__ = '1.8.3'

# Sent with every request. It names the app and where to read about it, and
# nothing about the reader: no address, ever. eBible refuses urllib's own
# `Python-urllib/3.x` with a 403, which is why it once sent a browser's name.
USER_AGENT = (f'Scriptura/{__version__} '
              '(+https://andresmessina-sdg.github.io/scriptura/)')
