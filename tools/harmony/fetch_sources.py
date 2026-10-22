"""Fetch what build_harmony.py reads into src/. All public domain.

They are not kept in the repository. Run once before a rebuild:
  python3 tools/harmony/fetch_sources.py

  robertson.txt  A. T. Robertson, A Harmony of the Gospels (1922), Gutenberg #36264
  sword/         INTF Eusebian_vs and Eusebian_num, and McGarvey's TFG (CrossWire)
  texts/         the pages the opening quotes, as plain text
"""
import html
import os
import re
import subprocess
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
ROBERTSON = 'https://www.gutenberg.org/cache/epub/36264/pg36264.txt'
CROSSWIRE = 'https://crosswire.org/ftpmirror/pub/sword/packages/rawzip/{}.zip'
MODULES = ('Eusebian_vs', 'Eusebian_num', 'TFG')
#: file name → address. ANF (1885) and DelCogliano's translation (released
#: by him to the public domain).
TEXTS = {
    'irenaeus': 'https://www.newadvent.org/fathers/0103311.htm',
    'carpianus': 'https://www.tertullian.org/fathers/eusebius_letter_to_carpianus.htm',
}


def fetch(url: str, path: str) -> None:
    subprocess.run(['curl', '-sSfL', '-m', '120', '-o', path, url], check=True)


if __name__ == '__main__':
    os.makedirs(os.path.join(SRC, 'sword'), exist_ok=True)
    fetch(ROBERTSON, os.path.join(SRC, 'robertson.txt'))
    print('robertson.txt')
    for name in MODULES:
        z = os.path.join(SRC, name + '.zip')
        fetch(CROSSWIRE.format(name), z)
        with zipfile.ZipFile(z) as f:
            f.extractall(os.path.join(SRC, 'sword'))
        os.remove(z)
        print(name)
    os.makedirs(os.path.join(SRC, 'texts'), exist_ok=True)
    for name, url in TEXTS.items():
        path = os.path.join(SRC, 'texts', name + '.txt')
        fetch(url, path)
        with open(path, encoding='utf-8', errors='replace') as f:
            page = re.sub(r'(?is)<(script|style).*?</\1>', '', f.read())
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html.unescape(re.sub(r'<[^>]+>', ' ', page)))
        print(name)
