#!/usr/bin/env python3
"""Generate tools/tissot_plates.toml from Wikimedia Commons.

James Tissot's *The Life of Our Lord Jesus Christ* (NT, ~1886–1894, Brooklyn
Museum, PD) and *The Old Testament* (OT, Phillip Medhurst color reproductions).
Tradition = 'watercolor' (gouache); the first colour-narrative source.

NT files have no scripture reference, so each scene title is mapped to a verse
here (NT_MAP). OT Medhurst filenames embed the reference, e.g.
`...Les filles de Lot (Genesis 19 30) • invenit...`, so those auto-map; the
rest of the OT scenes are mapped by hand (OT_MAP). Non-scene material
(topographic studies, ethnographic "types", apostle/evangelist portraits,
architectural reconstructions, non-canonical relics) is dropped.

Run:  python tools/gen_tissot.py   →  writes tools/tissot_plates.toml
It prints any Brooklyn scene that is neither mapped nor dropped, so the map can
be driven to full coverage.
"""
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

API = 'https://commons.wikimedia.org/w/api.php'
NT_CAT = 'Category:The Life of Jesus Christ by James Tissot'
OT_CAT = 'Category:Old Testament by James Tissot'
NT_CAT_URL = ('https://commons.wikimedia.org/wiki/'
              'Category:The_Life_of_Jesus_Christ_by_James_Tissot')
OT_CAT_URL = ('https://commons.wikimedia.org/wiki/'
              'Category:Old_Testament_by_James_Tissot')


def members(cat):
    files = []
    cont = {}
    while True:
        p = {'action': 'query', 'list': 'categorymembers', 'cmtitle': cat,
             'cmtype': 'file', 'cmlimit': '500', 'format': 'json'}
        p.update(cont)
        url = API + '?' + urllib.parse.urlencode(p)
        req = urllib.request.Request(
            url, headers={'User-Agent': 'scriptura-imagery/1.0'})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        files += [m['title'].replace('File:', '')
                  for m in d['query']['categorymembers']]
        if 'continue' in d:
            cont = d['continue']
        else:
            break
    return files


def norm(s):
    """Normalise a title for dict lookup: lower, fold accents and curly
    apostrophes, drop double-quotes, collapse ws, strip edge punctuation."""
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace('--', ' ').replace('’', "'").replace('"', '')
    s = re.sub(r'\s+', ' ', s).strip()
    s = s.strip(".' ")
    return s


def clean_nt_title(f):
    """Brooklyn filename → clean English title."""
    t = re.sub(r'\.jpg$', '', f, flags=re.I)
    t = re.sub(r'^Brooklyn Museum - ', '', t)
    t = re.sub(r'\s*-\s*James Tissot.*$', '', t)
    t = re.sub(r'\s*-\s*(overall|\d+)$', '', t)
    t = re.sub(r'\s*\([^)]*\)', '', t).strip()
    return t


# ── NT: scene title → (book, chapter, verse). Keys are matched via norm(). ──
NT_MAP = {
    # Infancy & childhood
    'the annunciation': ('Luke', 1, 28),
    'the visitation': ('Luke', 1, 40),
    'the magnificat': ('Luke', 1, 46),
    'the vision of zacharias': ('Luke', 1, 11),
    'the childhood of saint john the baptist': ('Luke', 1, 80),
    'the betrothal of the holy virgin and saint joseph': ('Matthew', 1, 18),
    'the anxiety of saint joseph': ('Matthew', 1, 19),
    'the vision of saint joseph': ('Matthew', 1, 20),
    'the magi journeying': ('Matthew', 2, 1),
    'the magi in the house of herod': ('Matthew', 2, 7),
    'the adoration of the magi': ('Matthew', 2, 11),
    'the angel and the shepherds': ('Luke', 2, 9),
    'the adoration of the shepherds': ('Luke', 2, 16),
    'saint joseph seeks a lodging in bethlehem': ('Luke', 2, 7),
    'the birth of our lord jesus christ': ('Luke', 2, 7),
    'the presentation of jesus in the temple': ('Luke', 2, 22),
    'the massacre of the innocents': ('Matthew', 2, 16),
    'the flight into egypt': ('Matthew', 2, 14),
    'the sojourn in egypt': ('Matthew', 2, 15),
    'the return from egypt': ('Matthew', 2, 21),
    'the youth of jesus': ('Luke', 2, 40),
    'jesus and his mother at the fountain': ('Luke', 2, 51),
    'on return from jerusalem, it is noticed that jesus is lost': ('Luke', 2, 43),
    'jesus found in the temple': ('Luke', 2, 46),
    'jesus among the doctors': ('Luke', 2, 46),
    'the brow of the hill near nazareth': ('Luke', 4, 29),
    # John the Baptist, baptism, temptation
    'the axe in the trunk of the tree': ('Matthew', 3, 10),
    'the voice in the desert': ('Matthew', 3, 3),
    'saint john the baptist sees jesus from afar': ('John', 1, 29),
    'saint john the baptist and the pharisees': ('John', 1, 24),
    'the baptism of jesus': ('Matthew', 3, 16),
    'the voice from on high': ('Matthew', 3, 17),
    'jesus tempted in the wilderness': ('Matthew', 4, 1),
    'jesus carried up to a pinnacle of the temple': ('Matthew', 4, 5),
    'jesus transported by a spirit onto a high mountain': ('Matthew', 4, 8),
    'get thee behind me satan': ('Matthew', 4, 10),
    'jesus ministered to by angels': ('Matthew', 4, 11),
    # Calling of disciples, early Judea
    'the calling of saint peter and saint andrew': ('Matthew', 4, 18),
    'the calling of saint john and saint andrew': ('John', 1, 35),
    'the calling of saint james and saint john': ('Matthew', 4, 21),
    'the calling of saint matthew': ('Matthew', 9, 9),
    'nathaniel under the fig tree': ('John', 1, 48),
    'the betrothed of cana': ('John', 2, 1),
    'the marriage at cana': ('John', 2, 7),
    'the merchants chased from the temple': ('John', 2, 15),
    'interview between jesus and nicodemus': ('John', 3, 2),
    'the disciples of jesus baptize': ('John', 3, 22),
    'the woman of samaria at the well': ('John', 4, 7),
    'the healing of the officer’s son': ('John', 4, 50),
    'jesus unrolls the book in the synagogue': ('Luke', 4, 17),
    # Galilee ministry — miracles & teaching
    'the miraculous draught of fishes': ('Luke', 5, 6),
    'the healing of peter’s mother-in-law': ('Mark', 1, 31),
    'all the city was gathered at his door': ('Mark', 1, 33),
    'the possessed man in the synagogue': ('Mark', 1, 23),
    'jesus chases a possessed man from the synagogue': ('Mark', 1, 26),
    'healing of the lepers at capernaum': ('Mark', 1, 40),
    'the blind of capernaum': ('Matthew', 9, 27),
    'the palsied man let down through the roof': ('Mark', 2, 4),
    'the meal in the house of matthew': ('Matthew', 9, 10),
    'the man with the withered hand': ('Mark', 3, 1),
    'the disciples eat wheat on the sabbath': ('Matthew', 12, 1),
    'ordaining of the twelve apostles': ('Mark', 3, 14),
    'the sermon of the beatitudes': ('Matthew', 5, 1),
    'the lord’s prayer': ('Matthew', 6, 9),
    'the man with an infirmity of thirty-eight years': ('John', 5, 5),
    'the piscina probatica or pool of bethesda': ('John', 5, 2),
    'the centurion': ('Matthew', 8, 5),
    'lord, i am not worthy': ('Matthew', 8, 8),
    'the resurrection of the widow’s son at nain': ('Luke', 7, 14),
    'the meal in the house of the pharisee': ('Luke', 7, 36),
    'mary magdalene at the feet of jesus': ('Luke', 7, 38),
    'the ointment of the magdalene': ('Luke', 7, 37),
    'the repentant mary magdalene': ('Luke', 7, 38),
    # Parables
    'the sower': ('Matthew', 13, 3),
    'the enemy who sows': ('Matthew', 13, 25),
    'the hidden treasure': ('Matthew', 13, 44),
    'he who winnows his wheat': ('Matthew', 3, 12),
    'the good samaritan': ('Luke', 10, 33),
    'the lost drachma': ('Luke', 15, 8),
    'the return of the prodigal son': ('Luke', 15, 20),
    'the prodigal son begging': ('Luke', 15, 16),
    'the bad rich man in hell': ('Luke', 16, 23),
    'the poor lazarus at the rich man’s door': ('Luke', 16, 20),
    'the man who hoards': ('Luke', 12, 18),
    'the man at the plough': ('Luke', 9, 62),
    'the foolish virgins': ('Matthew', 25, 3),
    'the wise virgins': ('Matthew', 25, 4),
    'the vine dresser and the fig tree': ('Luke', 13, 7),
    'the accursed fig tree': ('Matthew', 21, 19),
    'the son of the vineyard': ('Matthew', 21, 37),
    'the corner stone': ('Matthew', 21, 42),
    'the good shepherd': ('John', 10, 11),
    'the first shall be last': ('Matthew', 20, 16),
    'the rich young man went away sorrowful': ('Matthew', 19, 22),
    'the scribe stood to tempt jesus': ('Luke', 10, 25),
    'the two women at the mill': ('Matthew', 24, 41),
    'the blind in the ditch': ('Matthew', 15, 14),
    'the pharisee and the publican': ('Luke', 18, 10),
    # More miracles
    'the daughter of jairus': ('Mark', 5, 41),
    'the woman with an issue of blood': ('Mark', 5, 27),
    'jesus stilling the tempest': ('Mark', 4, 39),
    'jesus sleeping during the tempest': ('Mark', 4, 38),
    'my name is legion': ('Mark', 5, 9),
    'the two men possessed with devils': ('Matthew', 8, 28),
    'the swine driven into the sea': ('Mark', 5, 13),
    'the daughter of herodias dancing': ('Mark', 6, 22),
    'the head of saint john the baptist on a charger': ('Mark', 6, 28),
    'jesus commands the apostles to rest': ('Mark', 6, 31),
    'he sent them out two by two': ('Mark', 6, 7),
    'on entering the house, salute it': ('Matthew', 10, 12),
    'the exhortation to the apostles': ('Matthew', 10, 16),
    'jesus went out into a desert place': ('Matthew', 14, 13),
    'the miracle of the loaves and fishes by james tissot': ('Matthew', 14, 19),
    'the people seek jesus to make him king': ('John', 6, 15),
    'jesus walks on the sea': ('Matthew', 14, 25),
    'saint peter walks on the sea': ('Matthew', 14, 29),
    'the canaanite’s daughter': ('Matthew', 15, 28),
    'jesus heals the blind and lame on the mountain': ('Matthew', 15, 30),
    'the blind and mute man possessed by devils': ('Matthew', 12, 22),
    'jesus heals a mute possessed man': ('Matthew', 9, 32),
    'the pharisees and the saduccees come to tempt jesus': ('Matthew', 16, 1),
    'the transfiguration': ('Matthew', 17, 2),
    'le possede au pied du thabor': ('Mark', 9, 18),
    'suffer the little children to come unto me': ('Mark', 10, 14),
    'jesus and the little child': ('Matthew', 18, 2),
    'the healing of ten lepers': ('Luke', 17, 14),
    'the woman with an infirmity of eighteen years': ('Luke', 13, 11),
    'zacchaeus in the sycamore awaiting the passage of jesus': ('Luke', 19, 4),
    'the two blind men at jericho': ('Matthew', 20, 30),
    'the blind man washes in the pool of siloam': ('John', 9, 7),
    'the healed blind man tells his story to the jews': ('John', 9, 13),
    'the adulterous woman christ writing upon the ground': ('John', 8, 6),
    'the adulterous woman alone with jesus': ('John', 8, 10),
    'the jews took up rocks to stone jesus': ('John', 8, 59),
    'jesus walks in the portico of solomon': ('John', 10, 23),
    'the resurrection of lazarus': ('John', 11, 43),
    'jesus mary magdalene and martha at bethany': ('Luke', 10, 39),
    'he went on his way to ephraim': ('John', 11, 54),
    'you follow me for the miracles': ('John', 6, 26),
    'he who is of god hears the word of god': ('John', 8, 47),
    # Teaching toward Jerusalem
    'the last sermon of our lord': ('John', 12, 44),
    'curses against the pharisees': ('Matthew', 23, 13),
    'woe unto you, scribes and pharisees': ('Matthew', 23, 29),
    'the pharisees question jesus': ('Matthew', 22, 15),
    'the pharisees and the herodians conspire against jesus': ('Mark', 3, 6),
    'the tribute money': ('Matthew', 22, 21),
    'the widow’s mite': ('Mark', 12, 42),
    'jesus speaks near the treasury': ('John', 8, 20),
    'the chief priests ask jesus by what right does he act in this way':
        ('Matthew', 21, 23),
    'the disciples admire the buildings of the temple': ('Mark', 13, 1),
    'the prophecy of the destruction of the temple': ('Matthew', 24, 2),
    'the gentiles ask to see jesus': ('John', 12, 20),
    'two or three gathered in my name': ('Matthew', 18, 20),
    'jesus goes up alone onto a mountain to pray': ('Matthew', 14, 23),
    'christ retreats to the mountain at night': ('Luke', 6, 12),
    'jesus teaches in the synagogues': ('Matthew', 4, 23),
    'jesus teaches the people by the sea': ('Mark', 4, 1),
    'jesus sits by the seashore and preaches': ('Matthew', 13, 1),
    'jesus preaches in a ship': ('Luke', 5, 3),
    'jesus forbids the carrying of loads in the forecourt of the temple':
        ('Mark', 11, 16),
    'he went through the villages on the way to jerusalem': ('Luke', 13, 22),
    'with passover approaching, jesus goes up to jerusalem': ('John', 11, 55),
    'jesus goes in the evening to bethany': ('Mark', 11, 11),
    'the sick awaiting the passage of jesus': ('Mark', 6, 56),
    'in the villages the sick were presented to him': ('Mark', 6, 55),
    'he did no miracles but he healed them': ('Matthew', 13, 58),
    'he heals the lame': ('Matthew', 21, 14),
    # Passion week — entry, temple, supper
    'the foal of bethpage': ('Matthew', 21, 2),
    'the procession on the mount of olives': ('Luke', 19, 37),
    'the procession in the streets of jerusalem': ('Matthew', 21, 8),
    'the procession in the temple': ('Matthew', 21, 15),
    'jesus wept': ('John', 11, 35),
    'the lord wept': ('Luke', 19, 41),
    'the daughters of jerusalem': ('Luke', 23, 28),
    'meal of our lord and the apostles': ('Luke', 22, 14),
    'the last supper': ('Matthew', 26, 20),
    'the last supper judas dipping his hand in the dish': ('Matthew', 26, 23),
    'the communion of the apostles': ('Matthew', 26, 26),
    'the washing of the feet': ('John', 13, 5),
    'judas leaves the cenacle': ('John', 13, 30),
    'the man bearing a pitcher': ('Mark', 14, 13),
    # Passion — arrest, trials
    'the procession of judas': ('Matthew', 26, 47),
    'the grotto of the agony': ('Matthew', 26, 36),
    'my soul is sorrowful unto death': ('Matthew', 26, 38),
    'you could not watch one hour with me': ('Matthew', 26, 40),
    'the kiss of judas': ('Matthew', 26, 49),
    'the ear of malchus': ('John', 18, 10),
    'the healing of malchus': ('Luke', 22, 51),
    'the guards falling backwards': ('John', 18, 6),
    'but no man laid hands upon him': ('John', 7, 44),
    'the flight of the apostles': ('Mark', 14, 50),
    'the disciples having left their hiding place watch from afar in agony':
        ('Luke', 23, 49),
    'the tribunal of annas': ('John', 18, 19),
    'annas and caiaphas': ('John', 18, 24),
    'the morning judgment': ('Matthew', 27, 1),
    'maltreatments in the house of caiaphas': ('Matthew', 26, 67),
    'the false witnesses': ('Matthew', 26, 60),
    'the torn cloak jesus condemned to death by the jews': ('Matthew', 26, 65),
    'the first denial of saint peter': ('John', 18, 17),
    'the second denial of saint peter': ('Matthew', 26, 71),
    'the third denial of peter. jesus’ look of reproach': ('Luke', 22, 61),
    'the cock crowed': ('Matthew', 26, 74),
    'the protestations of saint peter': ('Matthew', 26, 35),
    'the sorrow of saint peter': ('Luke', 22, 62),
    'judas returns the money': ('Matthew', 27, 3),
    'judas hangs himself': ('Matthew', 27, 5),
    'judas goes to find the jews': ('Matthew', 26, 14),
    'the chief priests take counsel together': ('Matthew', 26, 3),
    'conspiracy of the jews': ('Matthew', 26, 4),
    'the evil counsel': ('John', 11, 47),
    'jesus led from caiaphas to pilate': ('John', 18, 28),
    'jesus before pilate first interview': ('John', 18, 33),
    'jesus before pilate second interview': ('John', 19, 9),
    'the message of pilate’s wife. pilate': ('Matthew', 27, 19),
    'jesus before herod': ('Luke', 23, 8),
    'jesus led from herod to pilate': ('Luke', 23, 11),
    'the scourging on the back': ('Matthew', 27, 26),
    'the scourging on the front': ('John', 19, 1),
    'the crowning of thorns': ('Matthew', 27, 29),
    'behold the man': ('John', 19, 5),
    'let him be crucified': ('Matthew', 27, 22),
    'jesus leaves the praetorium': ('John', 19, 16),
    'pilate washes his hands': ('Matthew', 27, 24),
    'the judgment on the gabbatha': ('John', 19, 13),
    'they dressed him in his own garments': ('Matthew', 27, 31),
    # Passion — Via Dolorosa & crucifixion
    'jesus bearing the cross': ('John', 19, 17),
    'jesus falls beneath the cross': ('John', 19, 17),
    'simon the cyrenian compelled to carry the cross with jesus':
        ('Matthew', 27, 32),
    'simon the cyrenian and his two sons alexander and rufus': ('Mark', 15, 21),
    'jesus meets his mother': ('Luke', 23, 27),
    'the procession nearing calvary': ('Luke', 23, 32),
    'the crowd left calvary while beating their breasts': ('Luke', 23, 48),
    'what our lord saw from the cross': ('Luke', 23, 35),
    'the raising of the cross': ('John', 19, 18),
    'jesus alone on the cross': ('John', 19, 18),
    'jesus stripped of his clothing': ('Mark', 15, 24),
    'the first nail': ('Matthew', 27, 35),
    'the nail for the feet': ('Matthew', 27, 35),
    'the vase of myrrh and gall': ('Matthew', 27, 34),
    'the garments divided by cast lots': ('John', 19, 24),
    'the title on the cross': ('John', 19, 19),
    'the four guards sat down and watched him': ('Matthew', 27, 36),
    'the confession of the centurion': ('Mark', 15, 39),
    'the confession of saint longinus': ('John', 19, 34),
    'the pardon of the good thief': ('Luke', 23, 43),
    'the soul of the good thief': ('Luke', 23, 46),
    'the holy women': ('Luke', 23, 49),
    'the holy women watch from afar': ('Mark', 15, 40),
    'woman behold thy son': ('John', 19, 26),
    'the sorrowful mother': ('John', 19, 25),
    'i thirst the vinegar given to jesus': ('John', 19, 28),
    'my god my god why hast thou forsaken me': ('Matthew', 27, 46),
    'it is finished': ('John', 19, 30),
    'the death of jesus': ('Luke', 23, 46),
    'the strike of the lance': ('John', 19, 34),
    'the earthquake': ('Matthew', 27, 51),
    'the dead appear in jerusalem': ('Matthew', 27, 53),
    'the dead appear in the temple': ('Matthew', 27, 52),
    'the thieves legs are broken': ('John', 19, 32),
    # Burial & resurrection
    'the descent from the cross': ('John', 19, 38),
    'the body of jesus carried to the anointing stone': ('John', 19, 40),
    'the holy virgin receives the body of jesus': ('John', 19, 38),
    'the holy virgin kisses the face of jesus before he is enshrouded on the '
    'anointing stone': ('John', 19, 40),
    'jesus carried to the tomb': ('John', 19, 41),
    'jesus in the sepulchre': ('Matthew', 27, 60),
    'joseph of arimathaea seeks pilate to beg permission to remove the body '
    'of jesus': ('Mark', 15, 43),
    'the watch over the tomb': ('Matthew', 27, 66),
    'the angel seated on the stone of the tomb': ('Matthew', 28, 2),
    'the resurrection': ('Matthew', 28, 6),
    'mary magdalene and the holy women at the tomb': ('Mark', 16, 1),
    'mary magdalene questions the angels in the tomb': ('John', 20, 13),
    'the madgalene runs to the cenacle to tell the apostles that the body of '
    'jesus is no longer in the tomb': ('John', 20, 2),
    'the two marys watch the tomb': ('Matthew', 27, 61),
    'saint peter and saint john run to the sepulchre': ('John', 20, 4),
    'saint peter and saint john follow from afar': ('Luke', 22, 54),
    'jesus appears to mary magdalene': ('John', 20, 16),
    'touch me not': ('John', 20, 17),
    'jesus appears to the holy women': ('Matthew', 28, 9),
    'the pilgrims of emmaus on the road': ('Luke', 24, 15),
    'he vanished from their sight': ('Luke', 24, 31),
    'the appearance of christ at the cenacle': ('Luke', 24, 36),
    'the disbelief of saint thomas': ('John', 20, 27),
    'the second miraculous draught of fishes': ('John', 21, 6),
    'christ appears on the shore of lake tiberias': ('John', 21, 4),
    'saint peter alerted by saint john to the presence of the lord casts '
    'himself into the water': ('John', 21, 7),
    'feed my lambs': ('John', 21, 15),
    'the primacy of saint peter': ('John', 21, 15),
    'apparition of our lord to saint peter': ('Luke', 24, 34),
    'the ascension': ('Acts', 1, 9),
    # A few scattered teaching/portrait-scene anchors
    'address to saint philip': ('John', 14, 8),
    'a woman cries out in a crowd': ('Luke', 11, 27),
    'agnus-dei the scapegoat': ('John', 1, 29),
    'good friday morning jesus in prison': ('Matthew', 27, 1),
    'jesus taken from the cistern': ('Luke', 22, 66),
    'the tower of siloam': ('Luke', 13, 4),
    'zacharias killed between the temple and the altar': ('Matthew', 23, 35),
}

# Non-scene Brooklyn titles to skip silently (topographic & ethnographic
# studies, apostle/evangelist portraits, architectural reconstructions,
# devotional portraits, non-canonical relics, and bare duplicates).
NT_DROP = {
    'a street in jaffa', 'a street in jerusalem', 'a typical woman of jerusalem',
    'a well near the bridge of kedron', 'a holy woman wipes the face of jesus',
    'album of sketches for the life of our lord jesus christ', 'an armenian',
    'ancient tombs valley of hinnom',
    'angels holding a dial indicating the different hours of the acts of the '
    'passion', 'asseenfromthecross-vi', 'barabbas',
    'bird’s-eye view of the forum jesus hears his death sentence',
    'column jerusalem', 'esplanade of the haram', 'fig-tree valley of hinnom',
    'garden of the citadel caire', 'garden of the dancing dervishes cairo',
    'haram mosque of es-sakrah called mosque of omar jerusalem', 'herod',
    'in old cairo', 'indiciphered drawing',
    'jerusalem from the south with sion and the mosques of el-aksa and omar '
    'at left', 'jerusalem jerusalem', 'jerusalem seen from the mount of olives',
    'jerusalem south-east corner taken from the road to bethany',
    'jerusalem taken from the mount of evil counsel', 'jewish ossuary',
    'judaic ornament', 'lamp mosque of el-aksa', 'lazarus', 'martha',
    'olive trees valley of hinnom', 'our lord jesus christ',
    'place of the gentiles’ court haram',
    'portico of the mosque of mohamet-ali', 'portrait of the pilgrim',
    'portrait of zacharias and elizabeth',
    'reconstruction of golgotha and the holy sepulchre, seen from the walls '
    'of herod’s palace',
    'reconstruction of golgotha and the holy sepulchre, seen from the walls '
    'of the judicial gate',
    'reconstruction of jerusalem and the temple of herod',
    'reconstruction of the temple of herod southeast corner', 'saint andrew',
    'saint anne', 'saint bartholomew', 'saint james major',
    'saint james the less', 'saint john the evangelist', 'saint joseph',
    'saint luke', 'saint mark', 'saint matthew', 'saint paul', 'saint peter',
    'saint philip', 'saint simon', 'saint thaddeus or saint jude',
    'saint thomas', 'sea of tiberias', 'synagogue of the maugrabians at '
    'jerusalem', 'the aged simeon', 'the apostles’ hiding place',
    'the bridge of kedron', 'the bridge of kedron and the tomb of absalom',
    'the bridge of kedron coming from gethsemane',
    'the chasm in the rock in the cave beneath calvary',
    'the entrance to the tomb of the prophets', 'the five wedges',
    'the holy face', 'the holy stair', 'the holy virgin in her youth',
    'the holy virgin in old age', 'the lake of gennesaret near the site of '
    'bethsaida', 'the magdalene before her conversion',
    'the pagan temple built by hadrian on the site of calvary',
    'the testing of the suitors of the holy virgin',
    'joseph of arimathaea', 'jesus discourses with his disciples',
    'jesus looking through a lattice', 'jesus traveling',
    'tomb of absalom valley of jehoshaphat', 'tombs in the valley of hinnom',
    'type of jew', 'type of jew jerusalem', 'types of jews',
    'types of jews jerusalem', 'types of judea', 'valley of hinnom',
    'valley of jehosaphat coming from bethany', 'valley of the kedron',
    'valley of the kedron near mar-saba', 'view of nazareth',
    'vineyards with their watch towers', 'walls of jerusalem north side',
    'women of cairo', 'women of galilee', 'woman of geba samaria',
    'judas iscariot', 'nicodemus',
}

# Important scenes that exist only as non-"Brooklyn Museum -" uploads.
NT_EXTRA = {
    'Tissot The Pharisee and the publican Brooklyn.jpg':
        ('The Pharisee and the Publican', 'Luke', 18, 10),
}

# ── OT: hand-mapped English-titled scenes (the Medhurst Genesis files are
# auto-mapped from their embedded reference). Keyed by norm(clean_ot_title). ──
OT_MAP = {
    # Genesis — primeval & patriarchs
    'the creation': ('Genesis', 1, 1),
    'adam is tempted by eve': ('Genesis', 3, 6),
    'adam and eve driven from paradise': ('Genesis', 3, 24),
    'god’s curse': ('Genesis', 3, 14),
    'cain leadeth abel to death': ('Genesis', 4, 8),
    'birth of noah': ('Genesis', 5, 29),
    'god appears to noah': ('Genesis', 6, 13),
    'building the ark': ('Genesis', 6, 14),
    'the animals enter the ark': ('Genesis', 7, 9),
    'the deluge': ('Genesis', 7, 17),
    'the dove returns to noah': ('Genesis', 8, 11),
    'noah’s sacrifice': ('Genesis', 8, 20),
    'noah’s drunkenness': ('Genesis', 9, 21),
    'shem, ham and japheth': ('Genesis', 9, 23),
    'building the tower of babel': ('Genesis', 11, 4),
    'the caravan of abraham': ('Genesis', 12, 5),
    'god’s promises to abram': ('Genesis', 15, 1),
    'abram guarding his sacrifice': ('Genesis', 15, 11),
    'the egyptians admire sarai’s beauty': ('Genesis', 12, 14),
    'sarai is taken to pharaoh’s palace': ('Genesis', 12, 15),
    'god renews his promises to abraham': ('Genesis', 17, 1),
    'abraham and the three angels': ('Genesis', 18, 2),
    'sarah hears and laughs': ('Genesis', 18, 12),
    'abraham sees sodom in flames': ('Genesis', 19, 28),
    'sarai sends hagar away': ('Genesis', 21, 14),
    'hagar and the angel in the desert': ('Genesis', 21, 17),
    'ishmael': ('Genesis', 21, 20),
    'isaac bears the wood for his sacrifice': ('Genesis', 22, 6),
    'abraham’s servant meets rebecca': ('Genesis', 24, 17),
    'rebecca meets isaac by the way': ('Genesis', 24, 64),
    'the mess of pottage': ('Genesis', 25, 34),
    'jacob deceives isaac': ('Genesis', 27, 22),
    'jacobs dream': ('Genesis', 28, 12),
    'jacob and rachel at the well': ('Genesis', 29, 10),
    'rachel and leah': ('Genesis', 29, 16),
    'jacob sees esau coming to meet him': ('Genesis', 33, 1),
    'the meeting of esau and jacob': ('Genesis', 33, 4),
    'dinah': ('Genesis', 34, 1),
    'judah and tamar': ('Genesis', 38, 18),
    # Genesis — Joseph
    'joseph reveals his dream to his brethren': ('Genesis', 37, 9),
    'joseph sold into egypt': ('Genesis', 37, 28),
    'jacob mourns his son joseph': ('Genesis', 37, 34),
    'joseph interprets the dreams while in prison': ('Genesis', 40, 8),
    'pharaoh’s dreams': ('Genesis', 41, 1),
    'joseph interprets pharaoh’s dream': ('Genesis', 41, 25),
    'the glory of joseph': ('Genesis', 41, 41),
    'the cup found': ('Genesis', 44, 12),
    'joseph converses with judah, his brother': ('Genesis', 44, 18),
    'joseph makes himself known to his brethren': ('Genesis', 45, 1),
    'joseph and his brethren welcomed by pharaoh': ('Genesis', 47, 7),
    'joseph dwells in egypt': ('Genesis', 47, 27),
    # Exodus
    'moses laid amid the flags': ('Exodus', 2, 3),
    'pharaoh’s daughter has moses brought to her': ('Exodus', 2, 5),
    'pharaoh’s daughter receives the mother of moses': ('Exodus', 2, 8),
    'pharaoh and the midwives': ('Exodus', 1, 15),
    'pharaoh notes the importance of the jewish people': ('Exodus', 1, 9),
    'the plague of flies': ('Exodus', 8, 24),
    'the plague of locusts': ('Exodus', 10, 13),
    'the signs on the door': ('Exodus', 12, 7),
    'the passover': ('Exodus', 12, 11),
    'the exodus': ('Exodus', 12, 37),
    'pharaoh pursues the israelites': ('Exodus', 14, 9),
    'the waters are divided': ('Exodus', 14, 21),
    'the egyptians are destroyed': ('Exodus', 14, 28),
    'the songs of joy': ('Exodus', 15, 20),
    'the gathering of the manna': ('Exodus', 16, 15),
    'gleaners': ('Ruth', 2, 3),
    'passover': ('Exodus', 12, 11),
    'moses strikes the rock': ('Exodus', 17, 6),
    'the ark of the covenant': ('Exodus', 25, 10),
    'moses and the ten commandments': ('Exodus', 31, 18),
    'the golden calf': ('Exodus', 32, 19),
    'bezalel': ('Exodus', 35, 30),
    # Leviticus / Numbers
    'the fire of atonement': ('Leviticus', 9, 24),
    'miriam shut out from the camp': ('Numbers', 12, 14),
    'the grapes of canaan': ('Numbers', 13, 23),
    'the flight of the spies': ('Numbers', 13, 26),
    'the sabbath-breaker stoned': ('Numbers', 15, 36),
    'balaam and the ass': ('Numbers', 22, 28),
    'the women of midian led captive by the hebrews': ('Numbers', 31, 9),
    # Joshua / Judges / Ruth
    'the ark passes over the jordan': ('Joshua', 3, 17),
    'the harlot of jericho and the two spies': ('Joshua', 2, 4),
    'the seven trumpets of jericho': ('Joshua', 6, 4),
    'the taking of jericho': ('Joshua', 6, 20),
    'the conquest of the amorites': ('Joshua', 10, 10),
    'deborah beneath the palm tree': ('Judges', 4, 5),
    'jael smote sisera, and slew him': ('Judges', 4, 21),
    'jael shows to barak, sisera lying dead': ('Judges', 4, 22),
    'jephthah’s daughter': ('Judges', 11, 34),
    'samson slays a thousand men': ('Judges', 15, 15),
    'the levite finds his concubine lying on the doorstep': ('Judges', 19, 26),
    'the levite’s wife dies at the door': ('Judges', 19, 26),
    'the levite before the corpse of his wife': ('Judges', 19, 27),
    'the gleaners': ('Ruth', 2, 3),
    # Samuel / Kings
    'saul meets samuel': ('1 Samuel', 9, 18),
    'michal watching david from a window': ('1 Samuel', 19, 12),
    'david returns to achish': ('1 Samuel', 29, 2),
    'david danced before the lord with all his might': ('2 Samuel', 6, 14),
    'nathan rebukes david': ('2 Samuel', 12, 7),
    'death of amnon': ('2 Samuel', 13, 29),
    'desolation of tamar': ('2 Samuel', 13, 19),
    'david mourns his son amnon': ('2 Samuel', 13, 37),
    'the wisdom of solomon': ('1 Kings', 3, 25),
    'solomon dedicates the temple at jerusalem': ('1 Kings', 8, 22),
    'the chaldees destroy the brazen sea': ('2 Kings', 25, 13),
    # Prophets (Tissot's imagined portraits → book opening)
    'elijah': ('1 Kings', 17, 1),
    'isaiah': ('Isaiah', 1, 1),
    'ezekiel': ('Ezekiel', 1, 1),
    'daniel in the lion’s den': ('Daniel', 6, 16),
    'hosea': ('Hosea', 1, 1),
    'joel': ('Joel', 1, 1),
    'amos': ('Amos', 1, 1),
    'obadiah': ('Obadiah', 1, 1),
    'jonah': ('Jonah', 1, 1),
    'micah': ('Micah', 1, 1),
    'nahum': ('Nahum', 1, 1),
    'habakkuk': ('Habakkuk', 1, 1),
    'haggai': ('Haggai', 1, 1),
    'zechariah': ('Zechariah', 1, 1),
    'malachi': ('Malachi', 1, 1),
}

# OT files to skip: duplicates, crops, b&w variants, Google Art copies, junk.
OT_DROP_RE = re.compile(
    r'(Google Art Project|\(cropped\)|Black&White|FXD|\.svg$|\(\d+\)\d*\.jpg$'
    r'|cropped\)\d)', re.I)

_OT_BOOKS = (r'Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth'
             r'|1 Samuel|2 Samuel|1 Kings|2 Kings|1 Chronicles|2 Chronicles'
             r'|Ezra|Nehemiah|Esther|Job|Psalms?|Proverbs|Ecclesiastes'
             r'|Song of Solomon|Isaiah|Jeremiah|Lamentations|Ezekiel|Daniel'
             r'|Hosea|Joel|Amos|Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah'
             r'|Haggai|Zechariah|Malachi|Tobit|Judith|Wisdom|Sirach|Baruch'
             r'|1 Maccabees|2 Maccabees')
_OT_REF = re.compile(r'\((' + _OT_BOOKS + r')\s+(\d+)[ ,:](\d+)')


def clean_ot_title(f):
    """Medhurst/Brooklyn OT filename → display title (French scene name)."""
    t = re.sub(r'\.jpg$', '', f, flags=re.I)
    t = re.sub(r'\s*•.*$', '', t)               # drop ' • invenit …' tail
    t = re.sub(r'^\d[\d. ]*\d*\s+', '', t)       # drop leading plate numbers
    t = re.sub(r'\s*\((?:' + _OT_BOOKS + r')[^)]*\)', '', t)  # drop the ref
    t = re.sub(r'^James Tissot\s*-\s*', '', t)
    t = re.sub(r'\s*-\s*James Tissot.*$', '', t)
    t = re.sub(r'\bby J(?:ames)?\.?\s*Tissot\b', '', t, flags=re.I)
    t = re.sub(r'\btissot\b', '', t, flags=re.I)
    t = re.sub(r'\s*\(cropped\).*$', '', t, flags=re.I)
    t = re.sub(r'\s+', ' ', t).strip(' -.')
    return t


def esc(s):
    return s.replace('\\', '\\\\').replace('"', '\\"')


_PD_NT = 'James Tissot, The Life of Our Lord Jesus Christ (Brooklyn Museum)'
_PD_OT = 'James Tissot, The Old Testament'
_MEDHURST = 'James Tissot · Phillip Medhurst Collection · CC BY-SA 4.0'


def emit(rows, out):
    out.write(
        '# James Tissot — colour gouache narrative (tradition = watercolor).\n'
        '# NT: *The Life of Our Lord Jesus Christ* (~1886–1894, Brooklyn\n'
        '# Museum, Public Domain). OT: *The Old Testament* (PD gouaches, plus\n'
        '# Phillip Medhurst colour reproductions for some Genesis scenes which\n'
        '# are CC BY-SA 4.0 — license/attribution carried per plate). Generated\n'
        '# by tools/gen_tissot.py; do not hand-edit. `n` keys are "TN###"/\n'
        '# "TO###" so dest filenames never collide with other sources.\n')
    for r in rows:
        out.write('\n[[plate]]\n')
        out.write(f'n = "{r["n"]}"\n')
        out.write(f'file = "{esc(r["file"])}"\n')
        out.write(f'title = "{esc(r["title"])}"\n')
        out.write(f'book = "{r["book"]}"\n')
        out.write(f'chapter = {r["chapter"]}\n')
        out.write(f'verse = {r["verse"]}\n')
        out.write(f'testament = "{r["testament"]}"\n')
        out.write(f'license = "{r["license"]}"\n')
        out.write(f'attribution = "{esc(r["attribution"])}"\n')


def main():
    # Normalise dict keys so accent/apostrophe folding is symmetric with norm().
    nt_map = {norm(k): v for k, v in NT_MAP.items()}
    nt_drop = {norm(k) for k in NT_DROP}
    ot_map = {norm(k): v for k, v in OT_MAP.items()}

    rows = []
    unmapped = []

    # ── NT ──
    nt = members(NT_CAT)
    # collapse title variants → prefer "overall", else plain Brooklyn file
    by_title = {}
    for f in nt:
        if not f.startswith('Brooklyn Museum - '):
            continue
        title = clean_nt_title(f)
        key = norm(title)
        prev = by_title.get(key)
        score = (2 if 'overall' in f else 1 if '(cropped)' not in f else 0)
        if prev is None or score > prev[2]:
            by_title[key] = (title, f, score)
    i = 0
    for key, (title, f, _score) in sorted(by_title.items()):
        if key in nt_drop:
            continue
        m = nt_map.get(key)
        if not m:
            unmapped.append(title)
            continue
        i += 1
        bk, ch, v = m
        rows.append({'n': f'TN{i:03d}', 'file': f, 'title': title,
                     'book': bk, 'chapter': ch, 'verse': v, 'testament': 'NT',
                     'license': 'PD', 'attribution': _PD_NT})
    for f, (title, bk, ch, v) in NT_EXTRA.items():
        i += 1
        rows.append({'n': f'TN{i:03d}', 'file': f, 'title': title,
                     'book': bk, 'chapter': ch, 'verse': v, 'testament': 'NT',
                     'license': 'PD', 'attribution': _PD_NT})

    # ── OT ── collect candidates, then dedupe by verse preferring the
    # Public-Domain English gouache over the CC-BY-SA Medhurst reproduction.
    ot = members(OT_CAT)
    ot_unmapped = []
    cand = {}   # (book, ch, v) -> (pref, row)  (higher pref wins)
    for f in sorted(ot):
        if OT_DROP_RE.search(f):
            continue
        ref = _OT_REF.search(f)
        title = clean_ot_title(f)
        if norm(title) in ot_map:
            bk, ch, v = ot_map[norm(title)]
            lic, attr, pref = 'PD', _PD_OT, 2          # PD English gouache
        elif ref:
            bk, ch, v = ref.group(1), int(ref.group(2)), int(ref.group(3))
            lic, attr, pref = 'CC-BY-SA-4.0', _MEDHURST, 1   # Medhurst repro
        else:
            ot_unmapped.append(f)
            continue
        row = {'file': f, 'title': title or f'{bk} {ch}', 'book': bk,
               'chapter': ch, 'verse': v, 'testament': 'OT',
               'license': lic, 'attribution': attr}
        kvv = (bk, ch, v)
        if kvv not in cand or pref > cand[kvv][0]:
            cand[kvv] = (pref, row)
    j = 0
    for _kvv, (_pref, row) in sorted(
            cand.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        j += 1
        row['n'] = f'TO{j:03d}'
        rows.append(row)

    with open('tools/tissot_plates.toml', 'w', encoding='utf-8') as out:
        emit(rows, out)

    nt_rows = [r for r in rows if r['testament'] == 'NT']
    ot_rows = [r for r in rows if r['testament'] == 'OT']
    print(f'wrote tools/tissot_plates.toml: {len(rows)} plates '
          f'({len(nt_rows)} NT, {len(ot_rows)} OT)')
    if unmapped:
        print(f'\n!! {len(unmapped)} NT scenes neither mapped nor dropped '
              f'(add to NT_MAP or NT_DROP):')
        for t in sorted(unmapped):
            print('   ', t)
    if ot_unmapped:
        print(f'\n.. {len(ot_unmapped)} OT files without ref or OT_MAP entry '
              f'(skipped):')
        for t in sorted(ot_unmapped):
            print('   ', t)


if __name__ == '__main__':
    sys.exit(main())
