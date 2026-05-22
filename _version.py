"""Single source of truth for the app version.

Imported by:
  - main.py / window.py (About dialog)
  - paths consumers if they ever need to detect a schema migration
  - the Flatpak manifest's `<release>` declaration in metainfo.xml
    (kept in sync manually until a build step automates it)

Versioning is semver-ish: bump MINOR for new features, PATCH for
bugfixes. 0.x is the pre-1.0 testing track; bump to 1.0.0 when the
Flathub submission is accepted.
"""

__version__ = '0.9.0'
