"""Fetch the old texts the page quotes into src/texts/, as plain text.

They are not kept in the repository; build_creeds.py checks every quotation
in quotes.py against them, word for word, when they are here. Run once before
a rebuild:  python3 tools/creeds/fetch_texts.py

An Orthodox Creed (1679) comes from a PDF; see witnesses.py for how to make
src/oc.txt, which is read from there.
"""
import html
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'src', 'texts')

#: file name → address. NPNF (1890s) and Schaff (1877) are public domain.
TEXTS = {
    'cyril04': 'https://www.newadvent.org/fathers/310104.htm',
    'cyril05': 'https://www.newadvent.org/fathers/310105.htm',
    'cyril11': 'https://www.newadvent.org/fathers/310111.htm',
    'cyril14': 'https://www.newadvent.org/fathers/310114.htm',
    'cyril15': 'https://www.newadvent.org/fathers/310115.htm',
    'cyril18': 'https://www.newadvent.org/fathers/310118.htm',
    'rufinus': 'https://www.newadvent.org/fathers/2711.htm',
    'athanasius_decretis': 'https://www.newadvent.org/fathers/2809.htm',
    'augustine_trinity5': 'https://www.newadvent.org/fathers/130105.htm',
    'tertullian_praxeas': 'https://www.newadvent.org/fathers/0317.htm',
    'schaff_apostles': 'https://ccel.org/ccel/schaff/creeds1/creeds1.iv.ii.html',
    'schaff_nicene': 'https://ccel.org/ccel/schaff/creeds1/creeds1.iv.iii.html',
    'schaff_athanasian': 'https://ccel.org/ccel/schaff/creeds1/creeds1.iv.v.html',
    'heidelberg': 'https://ccel.org/ccel/schaff/creeds3/creeds3.iv.vi.html',
    'philaret': 'https://www.pravoslavieto.com/docs/eng/Orthodox_Catechism_of_Philaret.htm',
}


def to_text(page: str) -> str:
    page = re.sub(r'(?is)<(script|style).*?</\1>', '', page)
    page = re.sub(r'(?i)</p>|<br\s*/?>|</h\d>', '\n\n', page)
    return html.unescape(re.sub(r'<[^>]+>', '', page))


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for name, url in TEXTS.items():
        raw = subprocess.run(['curl', '-sS', '-m', '60', url], check=True,
                             capture_output=True).stdout.decode('utf-8', 'replace')
        with open(os.path.join(OUT, name + '.txt'), 'w', encoding='utf-8') as f:
            f.write(to_text(raw))
        print(name)
