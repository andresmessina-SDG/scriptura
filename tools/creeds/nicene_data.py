# Curated links for the Nicene Creed (2026-09-30).
TITLE = "The Nicene Creed"
ORIG = "grc"
# Kinds: w = same words, t = same teaching, f = foretold (Old Testament).
# Each phrase: (id, 1662 English, Greek, lemmas for the word match, links, extra)
# extra keys: note, coined [(greek word, gloss)], disputed (bool)

ARTICLES = [
 {"n": 1, "phrases": [
  ("1a", "I believe in one God the Father Almighty,",
   "Πιστεύομεν εἰς ἕνα Θεὸν Πατέρα παντοκράτορα,", "εἷς θεός πατήρ παντοκράτωρ",
   [("w", "1 Corinthians 8:6"), ("w", "Ephesians 4:6"), ("w", "Revelation 1:8"),
    ("t", "Deuteronomy 6:4"), ("t", "Mark 12:29"), ("f", "Genesis 17:1")], {}),
  ("1b", " Maker of heaven and earth,",
   "ποιητὴν οὐρανοῦ καὶ γῆς,", "ποιέω οὐρανός γῆ",
   [("w", "Acts 4:24"), ("w", "Acts 14:15"), ("t", "Genesis 1:1"), ("t", "Psalms 33:6")], {}),
  ("1c", " And of all things visible and invisible:",
   "ὁρατῶν τε πάντων καὶ ἀοράτων·", "ὁρατός πᾶς ἀόρατος",
   [("w", "Colossians 1:16")],
   {"note": "The Nicene Creed adds this line to the older creeds. It is Paul's pair of words in Colossians 1:16, and the word match found it first."}),
 ], "left_out": [("1 John 5:7", "Philaret cites it for the Trinity. The words about “three that bear record in heaven” are missing from the Greek manuscripts before the late Middle Ages, so it is not shown as a proof.")]},

 {"n": 2, "phrases": [
  ("2a", "And in one Lord Jesus Christ,",
   "καὶ εἰς ἕνα Κύριον Ἰησοῦν Χριστόν,", "εἷς κύριος Ἰησοῦς Χριστός",
   [("w", "1 Corinthians 8:6"), ("w", "Ephesians 4:5"), ("t", "Philippians 2:11")], {}),
  ("2b", " the only-begotten Son of God,",
   "τὸν Υἱὸν τοῦ Θεοῦ τὸν μονογενῆ,", "υἱός θεός μονογενής",
   [("w", "John 3:18"), ("w", "John 1:14"), ("w", "John 1:18"), ("t", "John 3:16")], {}),
  ("2c", " Begotten of his Father before all worlds,",
   "τὸν ἐκ τοῦ Πατρὸς γεννηθέντα πρὸ πάντων τῶν αἰώνων,", "πατήρ γεννάω πρό πᾶς αἰών",
   [("t", "John 17:5"), ("t", "John 1:1"), ("f", "Psalms 2:7"), ("f", "Micah 5:2"),
    ("f", "Proverbs 8:23", "Both sides cited Proverbs 8:22–25 in the fourth century, Arius for “created”, the Nicenes for “before the hills”. Shown as history, not as proof.")],
   {"disputed": False}),
  ("2d", " God of God, Light of Light, Very God of very God,",
   "Φῶς ἐκ Φωτός, Θεὸν ἀληθινὸν ἐκ Θεοῦ ἀληθινοῦ,", "φῶς θεός ἀληθινός",
   [("w", "1 John 5:20"), ("t", "Hebrews 1:3"), ("t", "John 1:9"), ("t", "1 John 1:5"), ("t", "John 8:12")], {}),
  ("2e", " Begotten, not made,",
   "γεννηθέντα οὐ ποιηθέντα,", "γεννάω ποιέω",
   [("t", "John 1:3"), ("t", "Colossians 1:15")],
   {"note": "Arius read “the firstborn of every creature” (Colossians 1:15) as the Son being made. The creed answers from John 1:3: all things were made through him, so he is not one of them."}),
  ("2f", " Being of one substance with the Father,",
   "ὁμοούσιον τῷ Πατρί,", "πατήρ",
   [("t", "John 10:30"), ("t", "John 5:18"), ("t", "Philippians 2:6"), ("t", "John 1:1")],
   {"coined": [("ὁμοούσιον", "of one substance")],
    "note": "Not a Bible word. The council chose it because Arius's party could accept every biblical title for the Son while denying he was fully God. It says in one word what John 1:1 and 10:30 say."}),
  ("2g", " By whom all things were made;",
   "δι᾽ οὗ τὰ πάντα ἐγένετο·", "διά ὅς πᾶς γίνομαι",
   [("w", "John 1:3"), ("w", "1 Corinthians 8:6"), ("t", "Hebrews 1:2")], {}),
 ]},

 {"n": 3, "phrases": [
  ("3a", "Who for us men, and for our salvation",
   "τὸν δι᾽ ἡμᾶς τοὺς ἀνθρώπους καὶ διὰ τὴν ἡμετέραν σωτηρίαν", "ἄνθρωπος σωτηρία",
   [("t", "1 Timothy 1:15"), ("t", "Matthew 1:21"), ("t", "1 Timothy 2:5")], {}),
  ("3b", " came down from heaven,",
   "κατελθόντα ἐκ τῶν οὐρανῶν,", "κατέρχομαι οὐρανός",
   [("t", "John 3:13"), ("t", "John 6:38")], {}),
  ("3c", " And was incarnate by the Holy Ghost of the Virgin Mary,",
   "καὶ σαρκωθέντα ἐκ Πνεύματος Ἁγίου καὶ Μαρίας τῆς Παρθένου,", "πνεῦμα ἅγιος Μαρία παρθένος",
   [("w", "Matthew 1:20"), ("w", "Matthew 1:18"), ("t", "Luke 1:35"), ("t", "John 1:14"), ("f", "Isaiah 7:14")],
   {"coined": [("σαρκωθέντα", "made flesh")],
    "note": "“Incarnate” puts John 1:14, “the Word was made flesh”, into one verb that the New Testament itself does not use."}),
  ("3d", " And was made man,",
   "καὶ ἐνανθρωπήσαντα,", "ἄνθρωπος",
   [("t", "Philippians 2:7"), ("t", "1 Timothy 2:5"), ("t", "Hebrews 2:14")],
   {"coined": [("ἐνανθρωπήσαντα", "became man")]}),
 ]},

 {"n": 4, "phrases": [
  ("4a", "And was crucified also for us",
   "σταυρωθέντα τε ὑπὲρ ἡμῶν", "σταυρόω ὑπέρ",
   [("t", "1 Corinthians 15:3"), ("t", "Galatians 3:13"), ("f", "Isaiah 53:5")], {}),
  ("4b", " under Pontius Pilate.",
   "ἐπὶ Ποντίου Πιλάτου,", "Πόντιος Πιλᾶτος",
   [("w", "1 Timothy 6:13"), ("w", "Acts 4:27"), ("t", "Matthew 27:26")],
   {"note": "The creed fixes the cross in history. Paul uses the same three Greek words in 1 Timothy 6:13."}),
  ("4c", " He suffered",
   "καὶ παθόντα,", "πάσχω",
   [("t", "Luke 24:26"), ("t", "1 Peter 2:21"), ("f", "Isaiah 53:4")], {}),
  ("4d", " and was buried,",
   "καὶ ταφέντα,", "θάπτω",
   [("w", "1 Corinthians 15:4"), ("t", "Matthew 27:60"), ("f", "Isaiah 53:9")], {}),
 ]},

 {"n": 5, "phrases": [
  ("5a", "And the third day he rose again according to the Scriptures,",
   "καὶ ἀναστάντα τῇ τρίτῃ ἡμέρᾳ κατὰ τὰς Γραφάς,", "ἀνίστημι τρίτος ἡμέρα γραφή",
   [("w", "1 Corinthians 15:4"), ("w", "Luke 24:46"), ("f", "Psalms 16:10"), ("f", "Jonah 1:17"),
    ("f", "Hosea 6:2", "The early church read the third day here. In context the verse speaks of Israel restored.")],
   {"note": "“According to the Scriptures” is Paul's phrase in 1 Corinthians 15:3–4. The Scriptures he means are the Old Testament, so this line sends the reader to the prophets itself."}),
 ]},

 {"n": 6, "phrases": [
  ("6a", "And ascended into heaven,",
   "καὶ ἀνελθόντα εἰς τοὺς οὐρανούς,", "ἀνέρχομαι οὐρανός",
   [("t", "Acts 1:9"), ("t", "Luke 24:51"), ("t", "Ephesians 4:10"), ("f", "Psalms 68:18")], {}),
  ("6b", " And sitteth on the right hand of the Father.",
   "καὶ καθεζόμενον ἐν δεξιᾷ τοῦ Πατρός,", "καθέζομαι δεξιός πατήρ",
   [("t", "Hebrews 1:3"), ("t", "Hebrews 8:1"), ("t", "Acts 2:33"), ("f", "Psalms 110:1")],
   {"note": "The word match found nothing here: the New Testament says “sat down” with other verbs. Psalm 110:1 is the Old Testament verse the New Testament quotes most."}),
 ], "left_out": [("Mark 16:19", "It says this in so many words, but it stands in the longer ending of Mark, which the oldest manuscripts lack.")]},

 {"n": 7, "phrases": [
  ("7a", "And he shall come again with glory",
   "καὶ πάλιν ἐρχόμενον μετὰ δόξης", "πάλιν ἔρχομαι δόξα",
   [("w", "Matthew 25:31"), ("w", "Mark 13:26"), ("t", "Acts 1:11"), ("f", "Daniel 7:13")], {}),
  ("7b", " to judge both the quick and the dead:",
   "κρῖναι ζῶντας καὶ νεκρούς,", "κρίνω ζάω νεκρός",
   [("w", "2 Timothy 4:1"), ("w", "1 Peter 4:5"), ("w", "Acts 10:42")], {}),
  ("7c", " Whose kingdom shall have no end.",
   "οὗ τῆς βασιλείας οὐκ ἔσται τέλος·", "βασιλεία εἰμί τέλος",
   [("w", "Luke 1:33"), ("f", "Daniel 7:14"), ("f", "Isaiah 9:7"),
    ("f", "2 Samuel 7:13", "Philaret cites this as “2 Kings 7:12, 13”, the Greek and Slavonic name for 2 Samuel.")],
   {"note": "Word for word from the angel Gabriel in Luke 1:33."}),
 ]},

 {"n": 8, "phrases": [
  ("8a", "And I believe in the Holy Ghost, The Lord",
   "Καὶ εἰς τὸ Πνεῦμα τὸ Ἅγιον, τὸ Κύριον", "πνεῦμα ἅγιος κύριος",
   [("w", "2 Corinthians 3:17"), ("t", "Acts 5:3"), ("t", "Acts 5:4")], {}),
  ("8b", " and giver of life,",
   "τὸ ζωοποιόν,", "πνεῦμα ζῳοποιέω",
   [("w", "John 6:63"), ("w", "2 Corinthians 3:6"), ("t", "Romans 8:11"), ("f", "Ezekiel 37:14")],
   {"note": "Christ's own word, as a verb: “It is the spirit that quickeneth” (John 6:63), τὸ ζωοποιοῦν, “that which gives life”. The creed makes it a title."}),
  ("8c", " Who proceedeth from the Father",
   "τὸ ἐκ τοῦ Πατρὸς ἐκπορευόμενον,", "πατήρ ἐκπορεύω",
   [("w", "John 15:26")],
   {"note": "Christ's own words in John 15:26."}),
  ("8d", " and the Son,", "", "",
   [("t", "John 16:7", "Cited by the West."), ("t", "Galatians 4:6", "Cited by the West."), ("t", "John 15:26", "Cited by the East: it says “from the Father”.")],
   {"disputed": True,
    "note": "Not in the Greek of 381. Western churches added it (first at Toledo in 589) and the 1662 text has it. The Orthodox reject it. Both sides appeal to Scripture."}),
  ("8e", " Who with the Father and the Son together is worshipped and glorified,",
   "τὸ σὺν Πατρὶ καὶ Υἱῷ συμπροσκυνούμενον καὶ συνδοξαζόμενον,", "πατήρ υἱός",
   [("t", "Matthew 28:19"), ("t", "2 Corinthians 13:14")],
   {"coined": [("συμπροσκυνούμενον", "worshipped together with")]}),
  ("8f", " Who spake by the Prophets.",
   "τὸ λαλῆσαν διὰ τῶν Προφητῶν.", "λαλέω προφήτης",
   [("w", "Acts 28:25"), ("t", "2 Peter 1:21"), ("t", "Hebrews 1:1")], {}),
 ]},

 {"n": 9, "phrases": [
  ("9a", "And I believe one Catholick and Apostolick Church.",
   "Εἰς μίαν, Ἁγίαν, Καθολικὴν καὶ Ἀποστολικὴν Ἐκκλησίαν.", "εἷς ἅγιος ἐκκλησία",
   [("t", "Ephesians 4:4"), ("t", "Ephesians 5:27"), ("t", "Matthew 28:19"), ("t", "Ephesians 2:20"), ("t", "Matthew 16:18")],
   {"coined": [("Καθολικὴν", "catholic, “universal”"), ("Ἀποστολικὴν", "apostolic")],
    "note": "The 1662 text leaves out “holy”, which the Greek has. “Catholic” means whole or universal; some Lutherans say “Christian” instead."}),
 ]},

 {"n": 10, "phrases": [
  ("10a", "I acknowledge one Baptism for the remission of sins.",
   "Ὁμολογοῦμεν ἓν Βάπτισμα εἰς ἄφεσιν ἁμαρτιῶν.", "εἷς βάπτισμα ἄφεσις ἁμαρτία",
   [("w", "Ephesians 4:5"), ("w", "Acts 2:38"), ("w", "Mark 1:4", "John the Baptist's baptism, in the same words."), ("t", "Acts 22:16"), ("t", "Acts 10:43")],
   {"note": "Churches read this line differently. Orthodox, Catholic and Lutheran readers hold that baptism conveys forgiveness. Baptists read it as the sign of forgiveness already received by faith (Acts 10:43, which Philaret also cites)."}),
 ], "left_out": [("Mark 16:16", "Philaret cites it here. It stands in the longer ending of Mark, which the oldest manuscripts lack.")]},

 {"n": 11, "phrases": [
  ("11a", "And I look for the Resurrection of the dead,",
   "Προσδοκῶμεν ἀνάστασιν νεκρῶν,", "προσδοκάω ἀνάστασις νεκρός",
   [("w", "Acts 24:15"), ("w", "2 Peter 3:13"), ("t", "John 5:28"), ("t", "1 Corinthians 15:52"), ("f", "Daniel 12:2"), ("f", "Ezekiel 37:12"), ("f", "Isaiah 26:19")],
   {"note": "“We look for” (προσδοκῶμεν) is the very form Peter uses in 2 Peter 3:13."}),
 ]},

 {"n": 12, "phrases": [
  ("12a", "And the life of the world to come. Amen.",
   "καὶ ζωὴν τοῦ μέλλοντος αἰῶνος. Ἀμήν.", "ζωή μέλλω αἰών",
   [("w", "Hebrews 6:5"), ("w", "Mark 10:30"), ("t", "1 John 3:2"), ("t", "1 Corinthians 13:12"), ("t", "Revelation 21:4"), ("f", "Isaiah 65:17")], {}),
 ]},
]

# Cyril, Catechetical Lectures: which lectures treat which article.
CYRIL = {1: ["06", "07", "08", "09"], 2: ["10", "11"], 3: ["12"], 4: ["13"], 5: ["14"], 6: ["14"],
         7: ["15"], 8: ["16", "17"], 9: ["18"], 10: ["03"], 11: ["18"], 12: ["18"]}

AUTHOR = {
 "Genesis": "Moses", "Deuteronomy": "Moses", "Psalms": "David", "Proverbs": "Solomon",
 "Isaiah": "Isaiah", "Daniel": "Daniel", "Micah": "Micah", "Jonah": "Jonah", "Hosea": "Hosea",
 "Ezekiel": "Ezekiel", "2 Samuel": "Nathan", "Matthew": "Matthew", "Mark": "Mark", "Luke": "Luke",
 "John": "John", "Acts": "Luke", "Romans": "Paul", "1 Corinthians": "Paul", "2 Corinthians": "Paul",
 "Galatians": "Paul", "Ephesians": "Paul", "Philippians": "Paul", "Colossians": "Paul",
 "1 Timothy": "Paul", "2 Timothy": "Paul", "Hebrews": "Hebrews", "1 Peter": "Peter", "2 Peter": "Peter",
 "1 John": "John", "Revelation": "John",
}

# The creed's three parts, as Heidelberg Q 24 divides the Apostles': (first article, name).
SECTIONS = [(1, "God the Father"), (2, "God the Son"), (8, "God the Holy Ghost")]

COINED_EN = {"2f":["one substance"],"3c":["incarnate"],"3d":["made man"],"8e":["worshipped and glorified"],"9a":["Catholick","Apostolick"]}

# Witnesses: Cyril (lectures), Philaret (article), An Orthodox Creed (1679) articles.
_OC = {1:["2","3","11"],2:["4"],3:["5","6"],4:["17","18"],5:["17"],6:["17"],7:["17","50"],8:["8"],9:["29","30"],10:["27","28"],11:["49"],12:["49","50"]}
WITNESS = {n: {"Cyril": CYRIL[n], "Philaret": [str(n)], "OC": _OC[n]} for n in range(1, 13)}
