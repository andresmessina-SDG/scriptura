# Curated links for the Apostles' Creed (2026-09-30).
# Kinds: w = same words, t = same teaching, f = foretold.
# Each phrase: (id, 1662 English, Latin, Latin stems for the word match, links, extra)
# The stems are matched against the Vulgate: a verse word counts when it begins
# with a stem, or contains a stem of five letters or more.

TITLE = "The Apostles' Creed"
ORIG = "la"

ARTICLES = [
 {"n": 1, "phrases": [
  ("1a", "I believe in God the Father Almighty,", "Credo in Deum Patrem omnipotentem,", "cred deum deus dei patr omnipot",
   [("w", "2 Corinthians 6:18"), ("w", "Revelation 1:8"), ("w", "Genesis 17:1"),
    ("t", "1 Corinthians 8:6"), ("t", "Matthew 6:9"), ("t", "Hebrews 11:6")], {}),
  ("1b", " Maker of heaven and earth:", "Creatorem caeli et terrae.", "creat creav fecit fecist caelu caeli terra",
   [("w", "Genesis 14:19"), ("w", "Psalms 121:2"), ("w", "Acts 4:24"), ("t", "Genesis 1:1"), ("t", "Acts 17:24"), ("t", "Hebrews 11:3")],
   {"note": "Not in the Old Roman Creed of the fourth century. The received text added it in Gaul by the fifth."}),
 ]},
 {"n": 2, "phrases": [
  ("2a", "And in Jesus Christ", "Et in Iesum Christum,", "iesu christ cred",
   [("w", "Acts 16:31"), ("t", "John 14:1"), ("t", "Matthew 1:21"), ("t", "John 20:31")], {}),
  ("2b", " his only Son", "Filium eius unicum,", "fili unigen unic",
   [("w", "John 3:16"), ("w", "1 John 4:9"), ("w", "John 1:18"), ("t", "Mark 1:11"), ("f", "Psalms 2:7")], {}),
  ("2c", " our Lord,", "Dominum nostrum,", "domin nostr",
   [("w", "Romans 1:4"), ("w", "1 Corinthians 1:2"), ("t", "Philippians 2:11"), ("t", "Romans 10:9"), ("t", "John 20:28")], {}),
 ]},
 {"n": 3, "phrases": [
  ("3a", " Who was conceived by the Holy Ghost,", "qui conceptus est de Spiritu Sancto,", "concep concip spirit sanct",
   [("w", "Matthew 1:20"), ("w", "Matthew 1:18"), ("t", "Luke 1:35")], {}),
  ("3b", " Born of the Virgin Mary,", "natus ex Maria virgine,", "natus natum nata mari virgin",
   [("w", "Matthew 1:16"), ("w", "Luke 1:27"), ("t", "Galatians 4:4"), ("t", "Luke 2:7"), ("f", "Isaiah 7:14")], {}),
 ]},
 {"n": 4, "phrases": [
  ("4a", " Suffered under Pontius Pilate,", "passus sub Pontio Pilato,", "passus pass pati ponti pilat",
   [("w", "1 Timothy 6:13"), ("w", "1 Peter 2:21"), ("w", "Acts 4:27"), ("t", "Luke 24:26"), ("t", "Matthew 27:2"), ("f", "Isaiah 53:4")],
   {"note": "The creed fixes the cross in history, in the same words Paul uses in 1 Timothy 6:13."}),
  ("4b", " Was crucified,", "crucifixus,", "crucifi",
   [("w", "1 Corinthians 2:2"), ("w", "Mark 15:25"), ("t", "Galatians 3:13"), ("f", "Psalms 22:16"), ("f", "Isaiah 53:5")], {}),
  ("4c", " dead, and buried:", "mortuus, et sepultus,", "mortu sepult",
   [("w", "1 Corinthians 15:3-4"), ("t", "Romans 5:8"), ("t", "Matthew 27:60"), ("f", "Isaiah 53:9")], {}),
 ]},
 {"n": 5, "phrases": [
  ("5a", " He descended into hell;", "descendit ad inferos,", "descend infer",
   [("w", "Ephesians 4:9"), ("w", "Acts 2:27"), ("t", "1 Peter 3:19"), ("t", "Acts 2:31"), ("t", "Matthew 12:40"), ("f", "Psalms 16:10")],
   {"disputed": True,
    "note": "Missing from the oldest forms of the creed; it first appears in Rufinus's creed of Aquileia, about 400. The Latin says Christ went down “to those below”. Churches read it three ways: he entered the state of the dead (the General Baptist Orthodox Creed of 1679: “not … the place of the Damned, but … the state of the Dead”); he bore the anguish of hell on the cross (Calvin; Heidelberg Catechism, Q. 44); he went down to the dead in triumph (Catholic and Lutheran teaching)."}),
  ("5b", " The third day he rose again from the dead;", "tertia die resurrexit a mortuis,", "terti resurr resurg mortu",
   [("w", "Luke 24:46"), ("w", "1 Corinthians 15:4"), ("w", "Matthew 16:21"), ("t", "Acts 10:40"), ("f", "Jonah 1:17"),
    ("f", "Hosea 6:2", "The early church read the third day here. In context the verse speaks of Israel restored.")], {}),
 ]},
 {"n": 6, "phrases": [
  ("6a", " He ascended into heaven,", "ascendit ad caelos,", "ascend caelo caelu",
   [("w", "Ephesians 4:10"), ("t", "Acts 1:9"), ("t", "Luke 24:51"), ("f", "Psalms 68:18")], {}),
  ("6b", " And sitteth on the right hand of God the Father Almighty;", "sedet ad dexteram Dei Patris omnipotentis,", "sede sedit dexter dextr dei patr omnipot",
   [("w", "Colossians 3:1"), ("w", "Hebrews 10:12"), ("w", "Romans 8:34"), ("t", "Acts 7:55"), ("f", "Psalms 110:1")], {}),
 ], "left_out": [("Mark 16:19", "It says this in so many words, but it stands in the longer ending of Mark, which the oldest manuscripts lack.")]},
 {"n": 7, "phrases": [
  ("7a", " From thence he shall come to judge the quick and the dead.", "inde venturus est iudicare vivos et mortuos.", "ventur venie iudic vivos vivor mortu",
   [("w", "2 Timothy 4:1"), ("w", "Acts 10:42"), ("w", "1 Peter 4:5"), ("t", "Acts 1:11"), ("t", "Matthew 25:31"), ("t", "Philippians 3:20"), ("f", "Daniel 7:13")], {}),
 ]},
 {"n": 8, "phrases": [
  ("8a", "I believe in the Holy Ghost;", "Credo in Spiritum Sanctum,", "cred spirit sanct",
   [("w", "Acts 19:2"), ("t", "Matthew 28:19"), ("t", "John 14:26"), ("t", "Acts 5:3"), ("f", "Joel 2:28")], {}),
 ]},
 {"n": 9, "phrases": [
  ("9a", " The holy Catholick Church;", "sanctam Ecclesiam catholicam,", "sanct eccles",
   [("w", "Ephesians 5:27"), ("t", "Matthew 16:18"), ("t", "Ephesians 1:22"), ("t", "Revelation 7:9"), ("t", "Colossians 1:18")],
   {"coined": [("catholicam", "catholic, “universal”")],
    "note": "“Catholic” means whole or universal and is not a Bible word. Some Lutherans say “Christian” instead."}),
  ("9b", " The Communion of Saints;", "sanctorum communionem,", "sanct commun",
   [("w", "2 Corinthians 13:14"), ("w", "Acts 2:42"), ("t", "Ephesians 2:19"), ("t", "1 John 1:3"), ("t", "Hebrews 12:23")],
   {"note": "Not in the Old Roman Creed; added in Gaul. The Latin can mean fellowship with holy people or sharing in holy things."}),
 ]},
 {"n": 10, "phrases": [
  ("10a", " The Forgiveness of sins;", "remissionem peccatorum,", "remiss peccat",
   [("w", "Acts 2:38"), ("w", "Matthew 26:28"), ("w", "Luke 24:47"), ("t", "Ephesians 1:7"), ("t", "1 John 1:9"), ("f", "Jeremiah 31:34")], {}),
 ]},
 {"n": 11, "phrases": [
  ("11a", " The Resurrection of the body,", "carnis resurrectionem,", "carn caro resurr",
   [("w", "Job 19:26"), ("t", "1 Corinthians 15:42"), ("t", "John 5:28"), ("t", "Philippians 3:21"), ("t", "Luke 24:39"), ("f", "Daniel 12:2"), ("f", "Isaiah 26:19")],
   {"note": "The Latin says “of the flesh”; the 1662 text says “body”."}),
 ]},
 {"n": 12, "phrases": [
  ("12a", " And the Life everlasting. Amen.", "vitam aeternam. Amen.", "vita aetern",
   [("w", "John 3:16"), ("w", "Matthew 25:46"), ("w", "Romans 6:23"), ("t", "John 17:3"), ("f", "Daniel 12:2")], {}),
 ]},
]

COINED_EN = {"9a": ["Catholick"]}

# Witnesses: Westminster Larger Catechism (1648) questions, An Orthodox Creed (1679) articles.
WITNESS = {
 1: {"WLC": ["7", "8", "9", "10", "11", "15"], "OC": ["2", "3", "11"]},
 2: {"WLC": ["36", "38", "41", "42", "43", "44", "45"], "OC": ["4"]},
 3: {"WLC": ["37", "47"], "OC": ["5", "6"]},
 4: {"WLC": ["48", "49", "50"], "OC": ["17", "18"]},
 5: {"WLC": ["50", "52"], "OC": ["17"]},
 6: {"WLC": ["53", "54", "55"], "OC": ["17"]},
 7: {"WLC": ["56", "88", "89"], "OC": ["50"]},
 8: {"WLC": ["9", "10", "11", "58", "59"], "OC": ["8"]},
 9: {"WLC": ["61", "62", "63", "64", "65", "66", "69"], "OC": ["29", "30", "35"]},
 10: {"WLC": ["70", "71"], "OC": ["24"]},
 11: {"WLC": ["87"], "OC": ["49"]},
 12: {"WLC": ["90"], "OC": ["50"]},
}
