#!/usr/bin/env python3
import os
import subprocess
import sys

destdir = os.environ.get('DESTDIR', '')
prefix = os.environ.get('MESON_INSTALL_PREFIX', '/usr/local')
pkgdatadir = os.path.join(destdir + prefix, 'share', 'scriptura')

if os.path.isdir(pkgdatadir):
    subprocess.run([sys.executable, '-m', 'compileall', '-q', pkgdatadir],
                   check=False)
