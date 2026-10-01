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

ARCHIVE = 'https://archive.org/download/'
#: Wikipedia refuses a client that does not say what it is.
AGENT = 'ScripturaBuild/1.0 (Bible study app; quotation check)'

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
    # J. H. Breasted, Ancient Records of Egypt III and IV (1906).
    'breasted3': ARCHIVE + 'dli.ernet.19796/19796-Ancient%20Records%20Of%20Egypt%20Vol-iii_djvu.txt',
    'breasted4': ARCHIVE + 'in.ernet.dli.2015.231361/2015.231361.Ancient-Records_djvu.txt',
    # S. R. Driver, Notes on the Hebrew Text of the Books of Samuel (1890).
    'driver1890': ARCHIVE + 'notesonhebrewte01drivgoog/notesonhebrewte01drivgoog_djvu.txt',
    # L. W. King and R. C. Thompson, The Sculptures and Inscription of Darius
    # the Great on the Rock of Behistûn (1907).
    'behistun': ARCHIVE + 'sculpturesinscri00brituoft/sculpturesinscri00brituoft_djvu.txt',
    # A. Deissmann, Light from the Ancient East (1910).
    'deissmann': ARCHIVE + 'cu31924029303538/cu31924029303538_djvu.txt',
    # R. A. S. Macalister, The Excavation of Gezer II (1912).
    'macalister2': ARCHIVE + 'in.ernet.dli.2015.107176/2015.107176.Excavation-Of-Gezer-Vol2_djvu.txt',
    # The Library of the Palestine Pilgrims' Text Society I (1896): the
    # Bordeaux Pilgrim of 333, tr. Aubrey Stewart.
    'ppts1': ARCHIVE + 'libraryofpalesti01paleuoft/libraryofpalesti01paleuoft_djvu.txt',
    # Josephus, tr. William Whiston (1737).
    'josephus_ant': 'https://www.gutenberg.org/cache/epub/2848/pg2848.txt',
    'josephus_war': 'https://www.gutenberg.org/cache/epub/2850/pg2850.txt',
    # Pausanias, tr. W. H. S. Jones (1918); Pliny, tr. Bostock and Riley (1855).
    'pausanias1': 'https://www.theoi.com/Text/Pausanias1B.html',
    'pliny36': 'https://www.perseus.tufts.edu/hopper/text?doc=Perseus:text:1999.02.0137:book=36:chapter=21',
    # Short inscriptions, as transcribed and glossed.
    'wikipedia_hezekiah_seal': 'https://en.wikipedia.org/wiki/Hezekiah%27s_seal',
    'wikipedia_caiaphas': 'https://en.wikipedia.org/wiki/Caiaphas_ossuary',
    'wikipedia_hyrcanus': 'https://en.wikipedia.org/wiki/John_Hyrcanus',
    'wikipedia_judaea_capta': 'https://en.wikipedia.org/wiki/Judaea_Capta_coinage',
    'wikipedia_arch_titus': 'https://en.wikipedia.org/wiki/Arch_of_Titus',
    'wikipedia_lmlk': 'https://en.wikipedia.org/wiki/LMLK_seal',
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
    elif name in ('breasted3', 'breasted4', 'driver1890', 'behistun', 'deissmann',
                  'macalister2', 'ppts1'):
        # The scans' OCR: words broken at line ends, footnote marks, slips.
        text = re.sub(r'(\w)[-¬]\s*\n+\s*(\w)', r'\1\2', text)
        text = re.sub(r'\(\s?\d+\s?\)', ' ', text)
        text = text.replace('Eg)rpt', 'Egypt').replace('*®', '')
        text = text.replace('pick gainst pick', 'pick against pick')
    return text


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for name, url in TEXTS.items():
        raw = subprocess.run(['curl', '-sSL', '-A', AGENT, '-m', '300', url], check=True,
                             capture_output=True).stdout.decode('utf-8', 'replace')
        text = raw if url.endswith('.txt') else to_text(raw)
        with open(os.path.join(OUT, name + '.txt'), 'w', encoding='utf-8') as f:
            f.write(unlayout(name, text))
        print(name)
