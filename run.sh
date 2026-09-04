#!/usr/bin/env bash
# Run Scriptura from this checkout, with the translations built first.
#
# `python3 main.py` works, but meson compiles the catalogues at install time,
# so a run straight from the tree has none: the language picker hides itself
# below two languages and the Spanish and Russian interfaces cannot be reached
# at all. This compiles po/*.po into locale/ (only what changed) and then runs
# the same main.py, so what you launch is the working tree, translations
# included.
#
# Everything else is already live — the tree is the app. Arguments pass
# through: ./run.sh --help
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
python3 tools/build-locale.py
exec python3 main.py "$@"
