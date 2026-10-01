# Curated links for the Chalcedonian Creed (Definition of Chalcedon, 451), 2026-09-30.
# Text: Schaff, The Creeds of Christendom II (1877), Greek and his English, set in
# 18 sense-lines. Kinds and lemmas as in nicene_data.
import quotes as Q

TITLE = "The Chalcedonian Creed"
ORIG = "grc"

# Schaff's English and Greek, whole: the lines must rebuild them exactly.
REF_EN = ("We, then, following the holy Fathers, all with one consent, teach men to confess one "
          "and the same Son, our Lord Jesus Christ, the same perfect in Godhead and also perfect "
          "in manhood; truly God and truly man, of a reasonable [rational] soul and body; "
          "consubstantial [coessential] with the Father according to the Godhead, and "
          "consubstantial with us according to the Manhood; in all things like unto us, without "
          "sin; begotten before all ages of the Father according to the Godhead, and in these "
          "latter days, for us and for our salvation, born of the Virgin Mary, the Mother of God, "
          "according to the Manhood; one and the same Christ, Son, Lord, Only-begotten, to be "
          "acknowledged in two natures, inconfusedly, unchangeably, indivisibly, inseparably; the "
          "distinction of natures being by no means taken away by the union, but rather the "
          "property of each nature being preserved, and concurring in one Person and one "
          "Subsistence, not parted or divided into two persons, but one and the same Son, and "
          "only begotten, God the Word, the Lord Jesus Christ, as the prophets from the "
          "beginning [have declared] concerning him, and the Lord Jesus Christ himself has "
          "taught us, and the Creed of the holy Fathers has handed down to us.")
# Four slips in the online transcription of Schaff's Greek, set right here and
# checked by the builder: (as printed there, as the Greek reads).
GREEK_FIXES = [("δἰ ἡμᾶς", "δι᾽ ἡμᾶς"), ("ὑπὸστασιν", "ὑπόστασιν"),
               ("ὁ κύριος Ιησοῦς", "ὁ κύριος Ἰησοῦς"), ("καραδέδωκε", "παραδέδωκε")]

L = [
 # (n, English, Greek, lemmas for the word match, links, extra)
 (1, "We, then, following the holy Fathers, all with one consent, teach men to confess one and the same Son, our Lord Jesus Christ,",
  "Ἑπόμενοι τοίνυν τοῖς ἁγίοις πατράσιν ἕνα καὶ τὸν αὐτὸν ὁμολογεῖν υἱὸν τὸν κύριον ἡμῶν Ἰησοῦν Χριστὸν συμφώνως ἅπαντες ἐκδιδάσκομεν,",
  "ὁμολογέω υἱός Ἰησοῦς Χριστός εἷς",
  [("w", "1 John 4:15"), ("w", "1 Corinthians 8:6"), ("t", "Hebrews 13:8"), ("t", "Romans 10:9")], {}),
 (2, "the same perfect in Godhead and also perfect in manhood;",
  "τέλειον τὸν αὐτὸν ἐν θεότητι καὶ τέλειον τὸν αὐτὸν ἐν ἀνθρωπότητι,",
  "τέλειος θεότης ἀνθρωπότης",
  [("w", "Colossians 2:9"), ("t", "John 1:14"), ("t", "Hebrews 2:17")], {}),
 (3, "truly God and truly man, of a reasonable [rational] soul and body;",
  "θεὸν ἀληθῶς καὶ ἄνθρωπον ἀληθῶς τὸν αὐτὸν, ἐκ ψυχῆς λογικῆς καὶ σώματος,",
  "θεός ἄνθρωπος ἀληθῶς ψυχή σῶμα",
  [("w", "1 Timothy 2:5"), ("t", "John 1:1"), ("t", "Matthew 26:38"), ("t", "Luke 24:39"), ("t", "Hebrews 10:5")],
  {"quotes": Q.RATIONAL_SOUL}),
 (4, "consubstantial [coessential] with the Father according to the Godhead,",
  "ὁμοούσιον τῷ πατρὶ κατὰ τὴν θεότητα,",
  "πατήρ θεότης",
  [("w", "Colossians 2:9"), ("t", "John 10:30"), ("t", "John 1:1"), ("t", "John 14:9"), ("t", "Philippians 2:6")],
  {"coined": [("ὁμοούσιον", "of one substance", "ὁμοούσιος")]}),
 (5, "and consubstantial with us according to the Manhood;",
  "καὶ ὁμοούσιον τὸν αὐτὸν ἡμῖν κατὰ τὴν ἀνθρωπότητα,",
  "ἀνθρωπότης",
  [("t", "Hebrews 2:14"), ("t", "Hebrews 2:17"), ("t", "Philippians 2:7"), ("t", "Romans 8:3")],
  {"coined": [("ὁμοούσιον", "of one substance", "ὁμοούσιος")], "quotes": Q.CONSUBSTANTIAL_WITH_US}),
 (6, "in all things like unto us, without sin;",
  "κατὰ πάντα ὅμοιον ἡμῖν χωρὶς ἁμαρτίας·",
  "πᾶς ὅμοιος ὁμοιότης ὁμοιόω χωρίς ἁμαρτία",
  [("w", "Hebrews 4:15"), ("w", "Hebrews 2:17"), ("t", "2 Corinthians 5:21"), ("t", "1 Peter 2:22"), ("t", "1 John 3:5")], {}),
 (7, "begotten before all ages of the Father according to the Godhead,",
  "πρὸ αἰώνων μὲν ἐκ τοῦ πατρὸς γεννηθέντα κατὰ τὴν θεότητα,",
  "πρό αἰών πατήρ γεννάω θεότης",
  [("t", "John 1:1"), ("t", "John 17:5"), ("t", "John 1:18"), ("f", "Psalms 2:7"), ("f", "Micah 5:2")], {}),
 (8, "and in these latter days, for us and for our salvation, born of the Virgin Mary, the Mother of God, according to the Manhood;",
  "ἐπ᾽ ἐσχάτων δὲ τῶν ἡμερῶν τὸν αὐτὸν δι᾽ ἡμᾶς καὶ διὰ τὴν ἡμετέραν σωτηρίαν ἐκ Μαρίας τῆς παρθένου τῆς θεοτόκου κατὰ τὴν ἀνθρωπότητα,",
  "ἔσχατος ἡμέρα σωτηρία Μαρία Μαριάμ παρθένος",
  [("w", "Hebrews 1:2"), ("w", "Luke 1:27"), ("t", "Galatians 4:4"), ("t", "Luke 1:43"), ("t", "Luke 2:11"), ("f", "Isaiah 7:14")],
  {"coined": [("θεοτόκου", "Mother of God, “God-bearer”", "θεοτόκος")], "quotes": Q.THEOTOKOS}),
 (9, "one and the same Christ, Son, Lord, Only-begotten,",
  "ἕνα καὶ τὸν αὐτὸν Χριστόν, υἱόν, κύριον, μονογενῆ,",
  "Χριστός υἱός μονογενής",
  [("w", "John 3:16"), ("w", "John 1:18"), ("w", "1 John 4:9"), ("t", "Hebrews 13:8")],
  {"quotes": Q.ONE_CHRIST}),
 (10, "to be acknowledged in two natures,",
  "ἐκ δύο φύσεων [ἐν δύο φύσεσιν],",
  "δύο φύσις",
  [("t", "Romans 1:3-4"), ("t", "Romans 9:5"), ("t", "John 1:14"),
   ("t", "1 Timothy 3:16", "“God was manifest in the flesh” follows the later manuscripts; the oldest read “He who was manifested”.")],
  {"quotes": Q.TWO_NATURES}),
 (11, "inconfusedly, unchangeably, indivisibly, inseparably;",
  "ἀσυγχύτως, ἀτρέπτως, ἀδιαιρέτως, ἀχωρίστως γνωριζόμενον·",
  "",
  [("t", "Philippians 2:6-7"), ("t", "Hebrews 13:8"), ("t", "Colossians 2:9"), ("t", "John 1:14")],
  {"coined": [("ἀσυγχύτως", "without confusion", "ἀσυγχύτως"), ("ἀτρέπτως", "without change", "ἀτρέπτως"),
              ("ἀδιαιρέτως", "without division", "ἀδιαιρέτως"), ("ἀχωρίστως", "without separation", "ἀχωρίστως")],
   "quotes": Q.FOUR_ADVERBS}),
 (12, "the distinction of natures being by no means taken away by the union,",
  "οὐδαμοῦ τῆς τῶν φύσεων διαφορᾶς ἀνῃρημένης διὰ τὴν ἕνωσιν,",
  "φύσις",
  [("t", "Philippians 2:6-7"), ("t", "John 10:30"), ("t", "John 14:28")],
  {"quotes": Q.NATURES_KEPT}),
 (13, "but rather the property of each nature being preserved, and concurring in one Person and one Subsistence,",
  "σωζομένης δὲ μᾶλλον τῆς ἰδιότητος ἑκατέρας φύσεως καὶ εἰς ἓν πρόσωπον καὶ μίαν ὑπόστασιν συντρεχούσης,",
  "ὑπόστασις",
  [("w", "Hebrews 1:3"), ("t", "John 4:6"), ("t", "Matthew 14:25"), ("t", "Matthew 8:24"), ("t", "Matthew 8:26")],
  {"quotes": Q.EACH_FORM}),
 (14, "not parted or divided into two persons,",
  "οὐκ εἰς δύο πρόσωπα μεριζόμενον ἢ διαιρούμενον,",
  "",
  [("t", "1 Timothy 2:5"), ("t", "John 1:14"), ("t", "Ephesians 4:5")],
  {"quotes": Q.ONE_PERSON}),
 (15, "but one and the same Son, and only begotten, God the Word, the Lord Jesus Christ,",
  "ἀλλ᾽ ἕνα καὶ τὸν αὐτὸν υἱὸν καὶ μονογενῆ, θεὸν λόγον, κύριον Ἰησοῦν Χριστόν·",
  "μονογενής θεός λόγος",
  [("w", "John 1:1"), ("w", "John 1:14"), ("w", "Revelation 19:13")], {}),
 (16, "as the prophets from the beginning [have declared] concerning him,",
  "καθάπερ ἄνωθεν οἱ προφῆται περὶ αὐτοῦ",
  "προφήτης",
  [("w", "Luke 24:27"), ("t", "Hebrews 1:1"), ("t", "Acts 3:21"), ("t", "Acts 10:43"), ("t", "1 Peter 1:10-11")], {}),
 (17, "and the Lord Jesus Christ himself has taught us,",
  "καὶ αὐτὸς ἡμᾶς ὁ κύριος Ἰησοῦς Χριστὸς ἐξεπαίδευσε",
  "",
  [("t", "Matthew 16:15-16"), ("t", "John 10:30"), ("t", "John 8:58")], {}),
 (18, "and the Creed of the holy Fathers has handed down to us.",
  "καὶ τὸ τῶν πατέρων ἡμῖν παραδέδωκε σύμβολον.",
  "παραδίδωμι",
  [("w", "Jude 1:3"), ("w", "1 Corinthians 15:3"), ("t", "2 Thessalonians 2:15"), ("t", "2 Timothy 1:13")],
  {"quotes": Q.CHALCEDON_FATHERS}),
]

ARTICLES = [{"n": n, "phrases": [(str(n), en, gr, keys, links, extra)]}
            for n, en, gr, keys, links, extra in L]

COINED_EN = {"4": ["consubstantial"], "5": ["consubstantial"], "8": ["Mother of God"],
             "11": ["inconfusedly", "unchangeably", "indivisibly", "inseparably"]}

# The creed's parts, named from its own words: (first line, name).
SECTIONS = [(1, "One and the same Son"), (2, "Truly God and truly man"),
            (9, "In two natures"), (16, "As the prophets declared")]

# Witnesses for every line: Leo's Tome (449), which the council read and approved;
# Westminster Confession 8.2 (1647), on the two natures; An Orthodox Creed (1679),
# Articles 5-7, on the Son, the union of the two natures and their properties;
# the Westminster Larger Catechism, Questions 36-39, on the person of the Mediator.
WITNESS = {n: {"Leo": ["tome"], "WCF": ["8.2"], "OC": ["5", "6", "7"],
               "WLC": ["36", "37", "38", "39"]} for n in range(1, 19)}
