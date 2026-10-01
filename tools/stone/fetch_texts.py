"""Fetch the texts Scripture in Stone quotes into src/texts/, as plain text.

They are not kept in the repository; build_stone.py checks every quotation in
data/archaeology/scripture_in_stone.toml against them, word for word, when
they are here. Run once before a build:  python3 tools/stone/fetch_texts.py

Each source's own layout is undone here, never in the quotation: Compston
prints the stele's line numbers inside the words ("ʿOmr-5-î"), Rogers his
line numbers in brackets and the page's running head between the lines.
An Orthodox Creed (1679) is read from tools/creeds/src/oc.txt.
"""
import html
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'src', 'texts')

#: file name → address. All public domain, or (Wikipedia) the stones' own
#: words as printed there, which are facts.
TEXTS = {
    # H. F. B. Compston, The Inscription on the Stele of Méšaʿ (SPCK, 1919).
    'compston_mesha': 'https://en.wikisource.org/wiki/The_Inscription_on_the_Stele_of_M%C3%A9%C5%A1a%CA%BF/Translation',
    # R. W. Rogers, Cuneiform Parallels to the Old Testament (1912).
    'rogers': 'https://archive.org/download/cuneiformparalle00rogeuoft/cuneiformparalle00rogeuoft_djvu.txt',
    # The stones' own words, transcribed.
    'wikipedia_pilate': 'https://en.wikipedia.org/wiki/Pilate_stone',
    'wikipedia_tel_dan': 'https://en.wikipedia.org/wiki/Tel_Dan_stele',
    # Schaff, Creeds of Christendom III (1877): the Thirty-nine Articles.
    'schaff_39_articles': 'https://ccel.org/ccel/schaff/creeds3/creeds3.iv.xi.html',
}


def to_text(page: str) -> str:
    page = re.sub(r'(?is)<(script|style).*?</\1>', '', page)
    page = re.sub(r'(?i)</p>|<br\s*/?>|</h\d>|</li>|</dd>', '\n\n', page)
    return html.unescape(re.sub(r'<[^>]+>', '', page))


def unlayout(name: str, text: str) -> str:
    if name == 'compston_mesha':
        text = re.sub(r'-\d+-', '', text)                  # "ʿOmr-5-î"
        text = re.sub(r'(?<=\s)\d+-(?=\w)', '', text)      # "18-sels"
        text = re.sub(r'(?<=[\s.\]])\d{1,2}(?=[^\d\s.,])', '', text)  # "7and"
    elif name == 'rogers':
        text = re.sub(r'\(\d+\)', ' ', text)                # "(20)"
        text = re.sub(r'(?m)^\s*\d*\s*[A-Z][A-Z ]{8,}\d*\s*$', '', text)  # running heads
        text = re.sub(r'(\w)-\s*\n+\s*(\w)', r'\1\2', text)  # "thou-\nsand"
    return text


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for name, url in TEXTS.items():
        raw = subprocess.run(['curl', '-sSL', '-m', '120', url], check=True,
                             capture_output=True).stdout.decode('utf-8', 'replace')
        text = raw if url.endswith('.txt') else to_text(raw)
        with open(os.path.join(OUT, name + '.txt'), 'w', encoding='utf-8') as f:
            f.write(unlayout(name, text))
        print(name)
