"""Single source of truth for the app version.

Imported by:
  - main.py / window.py (About dialog)
  - paths consumers if they ever need to detect a schema migration
  - the Flatpak manifest's `<release>` declaration in metainfo.xml
    (kept in sync manually until a build step automates it)

Versioning is semver-ish: bump MINOR for new features, PATCH for
bugfixes.
"""

__version__ = '1.0.1'
