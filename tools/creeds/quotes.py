"""What the page says in words not its own: each a quotation from the Fathers,
a confession, a catechism or Schaff, with where it stands.

(source file, citation, text[, pieces]). The source file is a name in src/texts/ (see
fetch_texts.py) or 'oc' for An Orthodox Creed (src/oc.txt). An ellipsis marks
words left out; build_creeds.py finds each piece, in order, in the source.
`pieces`, when given, are what it looks for instead: the Heidelberg page sets
its German beside the English, so one English answer is cut by German there.
"""

SCHAFF = 'Philip Schaff, The Creeds of Christendom (1877)'

# Under each creed's title: what it is.
ORIGINS = {
    'apostles': ('schaff_apostles', SCHAFF,
                 "As the Lord's Prayer is the Prayer of prayers, the Decalogue the Law "
                 "of laws, so the Apostles' Creed is the Creed of creeds."),
    'nicene': ('schaff_nicene', SCHAFF,
               "The original Nicene Creed dates from the first œcumenical Council, "
               "which was held at Nicæa, A.D. 325, for the settlement of the Arian "
               "controversy… The Nicæno-Constantinopolitan Creed … adds all the "
               "clauses after 'Holy Ghost,' but omits the anathema."),
    'athanasian': ('schaff_athanasian', SCHAFF,
                   "The Symbolum Quicunque is a remarkably clear and precise summary "
                   "of the doctrinal decisions of the first four œcumenical Councils "
                   "(from A.D. 325 to A.D. 451)…"),
    'chalcedon': ('schaff_chalcedon', SCHAFF,
                  "The Creed of Chalcedon was adopted at the fourth and fifth sessions of the "
                  "fourth œcumenical Council, held at Chalcedon, opposite Constantinople, A.D. "
                  "451 (Oct. 22d and 25th)."),
}

# The opening: why each line is set beside the Scripture.
WHY = [
    ('cyril05', 'Cyril of Jerusalem, Catechetical Lectures 5.12 (c. 350)',
     "For the articles of the Faith were not composed as seemed good to men; but "
     "the most important points collected out of all the Scripture make up one "
     "complete teaching of the Faith."),
    ('oc', 'An Orthodox Creed (General Baptists, 1679), Article 38',
     "The Three Creeds … ought throughly to be received, and believed. For we "
     "believe they may be proved by most undoubted Authority of holy Scripture…"),
    ('cyril04', 'Cyril of Jerusalem, Catechetical Lectures 4.17',
     "Even to me, who tell you these things, give not absolute credence, unless "
     "thou receive the proof of the things which I announce from the Divine "
     "Scriptures."),
]

# The opening: the words the Church chose.
WORDS = ('augustine_trinity5', 'Augustine, On the Trinity V.9 (c. 415)',
         "Yet, when the question is asked, What three? human language labors "
         "altogether under great poverty of speech. The answer, however, is given, "
         "three persons, not that it might be [completely] spoken, but that it might "
         "not be left [wholly] unspoken.")

PILATE = [('rufinus', "Rufinus, Commentary on the Apostles' Creed 18 (c. 404)",
           "They who have handed down the Creed to us have with much forethought "
           "specified the time when these things were done — under Pontius Pilate,— "
           "lest in any respect the tradition should falter, as though vague and "
           "uncertain.")]

DESCENT = [
    ('rufinus', "Rufinus, Commentary on the Apostles' Creed 18 (c. 404)",
     "But it should be known that the clause, He descended into Hell, is not added "
     "in the Creed of the Roman Church, neither is it in that of the Oriental "
     "Churches. It seems to be implied, however, when it is said that He was "
     "buried."),
    ('oc', 'An Orthodox Creed (General Baptists, 1679), its note on this line',
     "Not that he (to wit) Christ went into the place of the Damned, but that he "
     "went absolutely unto the state of the Dead."),
    ('heidelberg', 'Heidelberg Catechism, Question 44 (1563)',
     "Why is it added: He descended into Hades? "
     "That in my greatest temptations I may be assured that Christ, my Lord, by his "
     "inexpressible anguish, pains, and terrors which he suffered in his soul on "
     "the cross and before, has redeemed me from the anguish and torment of hell.",
     ["Why is it added: He descended into Hades?",
      "That in my greatest temptations I may be assured that Christ, my Lord, by his "
      "inexpressible anguish, pains, and terrors which he suffered in his soul on "
      "the cross and before, has redeemed me from the anguish and torment of hell."]),
    ('philaret', 'Philaret of Moscow, Longer Catechism, Question 215 (1839)',
     "Wherefore did Jesus Christ descend into hell? "
     "To the end that he might there also preach his victory over death, and "
     "deliver the souls which with faith awaited his coming."),
]

CATHOLIC = [('cyril18', 'Cyril of Jerusalem, Catechetical Lectures 18.23',
             "It is called Catholic then because it extends over all the world, from "
             "one end of the earth to the other…")]

COMMUNION = [('heidelberg', 'Heidelberg Catechism, Question 55',
              "What dost thou understand by the communion of saints? "
              "First, that believers, all and every one, as members of Christ, have "
              "part in him and in all his treasures and gifts. Secondly, that each one "
              "must feel himself bound to use his gifts, readily and cheerfully, for "
              "the advantage and welfare of other members.",
              ["What dost thou understand by the communion of saints?",
               "First, that believers, all and every one, as members of Christ, have "
               "part in him and in all his treasures and gifts. Secondly, that each "
               "one must feel himself bound to use his gifts, readily and cheerfully, "
               "for the advantage and welfare of other members."])]

FLESH = [
    ('schaff_apostles', SCHAFF,
     "The Latin reads carnis, the Greek σαρκός, flesh…"),
    ('heidelberg', 'Heidelberg Catechism, Question 57',
     "What comfort does the resurrection of the body afford thee? "
     "That not only my soul, after this life, shall be immediately taken up to "
     "Christ its Head, but also that this my body, raised by the power of Christ, "
     "shall again be united with my soul, and made like unto the glorious body of "
     "Christ.",
     ["What comfort does the resurrection of the body afford thee?",
      "That not only my soul, after this life, shall be immediately taken up to "
      "Christ its Head, but also that this my body, raised by the power",
      "of Christ, shall again be united with my soul, and made like unto the "
      "glorious body of Christ."]),
]

FIRSTBORN = [('cyril11', 'Cyril of Jerusalem, Catechetical Lectures 11.4',
              "…a Son eternally begotten by an inscrutable and incomprehensible "
              "generation. And in like manner on hearing of the First-born, think not "
              "that this is after the manner of men; for the first-born among men have "
              "other brothers also.")]

ESSENCE = [('athanasius_decretis', 'Athanasius, De Decretis 20 (c. 351)',
            "But the Bishops … were again compelled on their part to collect the "
            "sense of the Scriptures, and to re-say and re-write what they had said "
            "before, more distinctly still, namely, that the Son is 'one in essence' "
            "with the Father…")]

SCRIPTURES = [('cyril14', 'Cyril of Jerusalem, Catechetical Lectures 14.2',
               "As an Apostle, therefore, has sent us back to the testimonies of the "
               "Scriptures, it is good that we should get full knowledge of the hope "
               "of our salvation…")]

NO_END = [('cyril15', 'Cyril of Jerusalem, Catechetical Lectures 15.27',
           "And should you ever hear any say that the kingdom of Christ shall have an "
           "end, abhor the heresy… He has not listened to Gabriel, saying, And He "
           "shall reign over the house of Jacob for ever, and of His kingdom there "
           "shall be no end.")]

FILIOQUE = [
    ('schaff_nicene', SCHAFF,
     "The Latin or Western form differs from the Greek by the little word Filioque, "
     "which, next to the authority of the Pope, is the chief source of the greatest "
     "schism in Christendom."),
    ('schaff_nicene', SCHAFF,
     "The first clear trace of the Filioque in the Nicene Creed we find at the "
     "third Council of Toledo in Spain, A.D. 589…"),
]

DOUBLE_PROCESSION = [('schaff_nicene', SCHAFF,
                      "The Latin Church … taught since Augustine the double "
                      "procession of the Spirit from the Father and the Son, and, "
                      "without consulting the East, put it into the Creed.")]

BAPTISM = [
    ('oc', 'An Orthodox Creed (General Baptists, 1679), Article 28',
     "Baptism is an Ordinance of the New Testament, ordained by Jesus Christ to be "
     "unto the Party Baptized, or Dipped, a Sign of our entrance into the Covenant "
     "of Grace, and ingrafting into Christ, and into the Body of Christ, which is "
     "his Church: And of Remission of Sin in the Blood of Christ…"),
    ('philaret', 'Philaret of Moscow, Longer Catechism, Question 288 (1839)',
     "Baptism is a Sacrament, in which a man who believes, having his body thrice "
     "plunged in water in the name of God the Father, the Son, and the Holy Ghost, "
     "dies to the carnal life of sin, and is born again of the Holy Ghost to a life "
     "spiritual and holy."),
]

TRINITY = [('tertullian_praxeas', 'Tertullian, Against Praxeas 2 (c. 213)',
            "…the mystery of the dispensation is still guarded, which distributes the "
            "Unity into a Trinity, placing in their order the three Persons — the "
            "Father, the Son, and the Holy Ghost: three, however, not in condition, but "
            "in degree; not in substance, but in form; not in power, but in aspect; yet "
            "of one substance, and of one condition, and of one power, inasmuch as He is "
            "one God…")]

WARNINGS = [
    ('schaff_athanasian', SCHAFF,
     "The Athanasian Creed, in strong contrast with the uncontroversial and peaceful "
     "tone of the Apostles' Creed, begins and ends with the solemn declaration that "
     "the catholic faith in the Trinity and the Incarnation herein set forth is the "
     "indispensable condition of salvation, and that those who reject it will be lost "
     "forever."),
    ('schaff_athanasian', SCHAFF + ", quoting Richard Baxter",
     "…'the best explication [better, statement] of the Trinity,' provided, however, "
     "'that the damnatory sentences be excepted, or modestly expounded.'"),
]


# ── The Chalcedonian Creed ──────────────────────────────────────────────────
# Schaff's footnotes to the text itself (Creeds of Christendom II), Leo's Tome,
# which the council read and approved, and An Orthodox Creed's article on the
# two natures.
SCHAFF_TEXT = 'Philip Schaff, notes to the text, The Creeds of Christendom (1877)'
LEO = 'Leo the Great, Tome to Flavian (Letter 28) {} (449)'
OC6 = 'An Orthodox Creed (General Baptists, 1679), Article 6'

RATIONAL_SOUL = [('schaff_chalcedon_text', SCHAFF_TEXT,
                  "Against Apollinaris, who denied that Christ had a ψυχὴ λογική, anima "
                  "rationalis… But the rational spirit of man requires salvation as much as "
                  "the body.")]

CONSUBSTANTIAL_WITH_US = [('schaff_chalcedon_text', SCHAFF_TEXT,
                           "Ὁμοούσιος … is used in both clauses, though with a shade of "
                           "difference. Christ's homoousia with the Father implies numerical "
                           "unity, or identity of essence…; Christ's homoousia with men means "
                           "only generic unity, or equality of nature.")]

THEOTOKOS = [('schaff_chalcedon_text', SCHAFF_TEXT,
              "The predicate θεοτόκος, the Bringer-forth of God … is directed against "
              "Nestorius, and was meant originally not so much to exalt the Virgin Mary, as to "
              "assert the true divinity of Christ and the realness of the Incarnation… It is "
              "immediately after qualified by the phrase κατὰ τὴν ἀνθρωπότητα (secundum "
              "humanitatem)… It is safer to adhere to the New Testament designation of Mary as "
              "μήτηρ Ἰησοῦ, or μήτηρ τοῦ Κυρίου (Luke i. 43).")]

ONE_CHRIST = [('oc', OC6,
               "…and of two Natures is one Christ, God-Man, or Immanuel, God with us.")]

TWO_NATURES = [('schaff_chalcedon_text', SCHAFF_TEXT,
                "Ἐν δύο φύσεσιν, and all the Latin translations, in duabus naturis …, are "
                "directed against Eutyches. The present Greek text reads, it is true, ἐκ δύο "
                "φύσεων, from two natures; but this signifies, and, according to the connection, "
                "can only signify, essentially the same thing…")]

FOUR_ADVERBS = [
    ('schaff_chalcedon_text', SCHAFF_TEXT,
     "ἀσυγχύτως, inconfuse, and ἀτρέπτως, immutabiliter (without confusion, without "
     "conversion or change), are directed against Eutychianism, which mixes and confounds "
     "the human and the divine natures in Christ…"),
    ('schaff_chalcedon_text', SCHAFF_TEXT,
     "ἀδιαιρέτως, indivise, ἀχωρίστως, inseparabiliter (without division, without "
     "separation), both in opposition to Nestorianism, which so emphasized the duality of "
     "natures … as to lose sight of the unity of person…"),
    ('oc', OC6, "…without change of either Nature, or mixture of both…"),
]

NATURES_KEPT = [('leo_tome', LEO.format(3),
                 "For both natures retain their own proper character without loss: and as "
                 "the form of God did not do away with the form of a slave, so the form of a "
                 "slave did not impair the form of God.")]

EACH_FORM = [
    ('leo_tome', LEO.format(4),
     "For each form does what is proper to it with the co-operation of the other; that is "
     "the Word performing what appertains to the Word, and the flesh carrying out what "
     "appertains to the flesh."),
    ('leo_tome', LEO.format(4),
     "To be hungry and thirsty, to be weary, and to sleep, is clearly human: but to satisfy "
     "5,000 men with five loaves … to walk upon the surface of the sea with feet that do not "
     "sink, and to quell the risings of the waves by rebuking the winds, is, without any "
     "doubt, Divine."),
]

ONE_PERSON = [('leo_tome', LEO.format(4),
               "…it is not part of the same nature to say, I and the Father are one, and to "
               "say, the Father is greater than I. For although in the Lord Jesus Christ God "
               "and man is one person, yet the source of the degradation, which is shared by "
               "both, is one, and the source of the glory, which is shared by both, is "
               "another.")]

CHALCEDON_FATHERS = [('schaff_chalcedon', SCHAFF,
                      "It embraces the Nicæno-Constantinopolitan Creed, and the "
                      "christological doctrine set forth in the classical Epistola Dogmatica "
                      "of Pope Leo the Great to Flavian…",
                      ["It embraces the Nicæno-Constantinopolitan Creed, and the "
                       "christological doctrine set forth in",
                       "the classical Epistola Dogmatica of Pope Leo the Great to Flavian"])]
