# Flatpak packaging

This directory holds the wrapper script for the Flatpak build. The
manifest lives at the repo root as
`org.codeberg.andresmessina.BibleReader.yml`.

## Prerequisites

```sh
# Fedora
sudo dnf install flatpak flatpak-builder

# Ubuntu / Debian / Zorin
sudo apt install flatpak flatpak-builder

# Arch
sudo pacman -S flatpak flatpak-builder
```

Add Flathub if you haven't, and install the matching runtime + SDK:

```sh
flatpak remote-add --if-not-exists --user flathub \
    https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub org.gnome.Platform//48 org.gnome.Sdk//48
```

## TODOs before the manifest will build

The first build will fail until you fill in:

1. **libsword sha256.** Download the source tarball, compute the hash,
   paste into the manifest:
   ```sh
   curl -LO https://crosswire.org/ftpmirror/pub/sword/source/v1.9/sword-1.9.0.tar.gz
   sha256sum sword-1.9.0.tar.gz
   ```
   Also confirm the version on CrossWire's downloads page is still
   `1.9.0`; bump if needed.

2. **Whoosh sha256.** Same drill:
   ```sh
   pip download --no-binary=:all: --no-deps whoosh==2.7.4
   sha256sum Whoosh-2.7.4.tar.gz
   ```

Both sha256 values get pasted into the `sha256:` lines that currently
hold `0000…0000` placeholders.

## Build + run locally

From the repo root:

```sh
flatpak-builder --user --install --force-clean build-dir \
    org.codeberg.andresmessina.BibleReader.yml
flatpak run org.codeberg.andresmessina.BibleReader
```

Iterate as needed. `--force-clean` wipes the build dir each run so
mistakes don't compound.

## Things that will break first and why

- **SWORD's CMake bindings flag.** `SWORD_BINDINGS=Python` is the
  name CrossWire's current CMake uses, but the bindings build step
  sometimes needs SWIG and a Python development header set the SDK
  may not provide. If you see `swig: command not found`, add `swig`
  as a build dependency to the libsword module via a
  `build-options.append-path` or a separate prep module.
- **Whoosh version conflict with newer pip.** Whoosh 2.7.4 is old
  enough that newer pip resolvers complain. The official Whoosh
  fork (`whoosh-reloaded`) ships 2.7.x with patches. If the build
  fails on Whoosh-2.7.4, switch the source to the reloaded fork:
  `https://files.pythonhosted.org/.../Whoosh_Reloaded-2.7.4.tar.gz`.
- **No SWORD modules on first launch.** The Flatpak sandbox has its
  own `~/.var/app/<id>/data/.sword/` — your existing host-level
  `~/.sword/` modules don't carry over. The welcome window's "Install
  essentials" flow will download them fresh on first run.
- **Screenshots missing in metainfo.** The metainfo references
  `data/screenshots/*.png` URLs that 404 until you commit + push
  real screenshots. Flathub will warn but the build itself works.

## Flathub submission

Once the manifest builds clean and the screenshots are in place:

1. Fork `flathub/flathub` on GitHub.
2. Create a branch named `new-pr/org.codeberg.andresmessina.BibleReader`.
3. Add the manifest + (optionally) a `flathub.json` config for
   long-term maintenance settings.
4. Open a PR. Flathub maintainers review.
