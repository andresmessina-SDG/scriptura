# Changelog

All notable changes to Scriptura. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/). Versioning is
semver-ish — 0.x was the pre-Flathub testing track.

## [Unreleased]

### Added

- **Scriptura has a website**, <https://andresmessina-sdg.github.io/scriptura/>,
  in English, Spanish and Russian: a working reading pane, the install
  steps, and every release's notes. The store listing's homepage, the
  README and the old install page now point to it.

### Changed

- **Compare runs from word for word to free.** Comparing a verse now lists
  your English Bibles from the most literal to the freest, each with a
  small mark showing where it sits. A filled dot means published charts
  place it there; a ring means Scriptura measured it. Hover the mark to
  read which. Compare now shows only the Bibles in the language you are
  reading; the Other languages switch at the top adds the rest, and the
  app remembers your choice.
- **The chapter's first line keeps the rhythm.** The large first letter
  made the gap under the first line about a third wider than every other
  line. That line now steps like the rest, at every line spacing, and the
  letter keeps its size.
- **A break between stanzas is half a line, not a whole one.** In the
  Psalms and other poetry the blank line between stanzas was a full line
  tall, so a break read as a missing line. It is now half as tall.
- **Each search button has one job.** The magnifier in the window bar
  searches the whole Bible, as before, and now says so. The button above
  the page finds words in the chapter you are reading, with its own icon:
  type to highlight, Enter for the next match, Shift+Enter for the one
  before. It used to run a second whole-Bible search when you pressed
  Enter.
- The passage menu above the page now shows three dots across (⋯), so it
  no longer looks like the window's menu (⋮) when the two sit together.
- **A shorter menu, and a Preferences window.** The menu now holds only
  the places you go: Annotations, Modules, Presentation, Appearance and
  your reading plan. Appearance opens beside the page, so you still see
  every change to the text as you make it. The settings you set once are
  in Preferences (Ctrl+,): how the app starts and its language, the
  reading aids, and backing up your study data. Tips, keyboard shortcuts
  and About are under Help, each with its name.

### Added

- **The Bible Family Tree.** A new entry in each pane's module list.
  It opens on the Family: the Bibles people read today and every Bible
  they were revised from, back to Wycliffe and Tyndale, drawn down the
  page in time with a note at the moments that shaped them. Hover a Bible
  to light its whole line; arrow keys walk from parent to child. Switch
  it to By literalness and every Bible slides sideways to its place from
  word for word to free, so you can watch a family drift: the RSV's line
  toward word for word in the ESV, the Living Bible's back toward
  translation in the NLT. A List button shows the same family as an
  indented list, and Print makes it a poster for a classroom wall, in
  either arrangement, with a key to its lines and marks. The Line lays out
  every English Bible from word for word to free; filter it by what you
  have installed, by tradition and by era. The Bible you are reading is
  marked, and pressing any Bible opens its card. Under the desktop's high
  contrast setting its faint lines, ranges and dates are drawn darker.
- **About this translation.** For an English Bible, the module list's
  info page now opens a card beside the page: where the Bible sits from
  word for word to free, the line of Bibles it was revised from, the
  Hebrew and Greek texts it translates, notes, and the sources behind
  every fact. Each Bible it names opens its own card. From the card you
  can open the Bible in the pane, install it, compare the verse you are
  on, or show it in the Family.

### Fixed

- **The store listing tells the truth about going online.** It said
  Scriptura goes online only to download the texts you choose. Spoken
  readings go online too, so it now says so, and that Preferences can
  turn them off. The website is corrected too.
- The ESV's info page in the module list opened on nothing: a copyright
  sign in its About text stopped the page from being built.
- **Compare translations flashed open and closed at once**, from the verse
  menu, the ⋮ button and the Family Card alike. Its Other languages switch
  appeared only after the verses arrived, which resized a popup already on
  screen, and GNOME Shell closed it. The switch is now settled before
  Compare opens.
- **Shortcuts misfired while the Family Tree had the focus.** Ctrl+Shift+C
  did nothing, and Ctrl+P and Ctrl+E printed or exported an empty passage.
  Compare and export now act on the Bible beside the Family Tree, and say
  so when the window is too narrow to show one. Ctrl+P prints the Family
  as a poster, as its own Print button does.

## [1.7.3] — 2026-09-22

### Changed

- **The interface font now ships with the app.** Scriptura already carried
  its reading faces so the page looks the same on every machine; the face
  the menus and buttons are set in did not travel with them. On a desktop
  that is not GNOME it fell back to whatever the system had, which sets
  lines about a tenth taller. It is bundled now, so the chrome matches the
  page everywhere. Nothing changes for anyone installing the Flatpak.
- **“Evening paper” says when it cannot work.** The switch follows the
  desktop’s Night Light, and not every desktop has one. Where there is
  none the switch is now dimmed and says so, instead of turning on and
  doing nothing.
- The app’s one-line description no longer names a desktop. It says what
  Scriptura does.
- The window bar no longer shows the app’s colour icon on desktops that
  put one there, such as KDE. The window buttons stay where the desktop
  puts them.
- **Double-clicking a word in a Russian Bible finds its article far more
  often.** Russian changes a word’s ending, and the dictionary is filed
  under the base form, so спросил or иисуса found nothing. The
  dictionary now carries Door43’s links from each verse’s words to its
  articles, and a Bible tagged with Strong’s numbers, like the Synodal,
  follows them: a quarter to a third of the words in a book now open
  an article, up from one in ten. The Module Manager offers the updated
  dictionary.
- The starting-library cards on the welcome screen give each download’s
  size in megabytes. “Small download” was on a card that downloads
  about 60 MB.

### Added

- **Search by the Greek or Hebrew word.** A query may now ask about the
  word under the translation: `strong:G26` finds every verse whose Greek
  carries ἀγάπη, `lemma:חֶסֶד` every verse whose Hebrew carries that
  word, and `morph:V-AAM` every aorist imperative. Ordinary words still
  mean what they meant, so `strong:G26 charity` asks the question a
  concordance exists to answer — where one Greek word was rendered that
  way, and `strong:G26 -love` the 26 places it is not — charity, dear,
  beloved. The results are the reader’s own translation, with the count per
  section and per book the search panel already draws. The header names
  the word; where one spelling covers several words, as חֶסֶד covers
  kindness, shame and a man’s name, it says so and offers each. A bare
  `G26` is still a search for that text. Needs the interlinear data,
  which the Module Manager installs.
- **A whole-Bible concordance.** The occurrences list beside a Strong’s
  definition now has a scope: this book, as before, or the whole Bible.
  Long lists page instead of stopping at 200, so a common word can be
  read to its last verse, and Frequency opens the word in search with its
  count per book.

- **The historical commentaries pack has 2,000 more voices on the
  page.** Origen of Alexandria goes from 2,858 comments to 4,271 —
  his homilies on Genesis, Exodus, Leviticus, Joshua, Judges,
  1 Samuel, the Psalms, Isaiah, Luke and the Song of Songs, and the
  commentaries on Matthew, Romans, Ephesians and 1 Corinthians —
  and Ambrosiaster from 1,041 to 1,567. Dionysius bar Salibi joins
  the Syriac voices. A few quotes that showed stray markup read
  cleanly now. The Module Manager offers the new pack.

### Fixed

- A file chooser that cannot open now says so. On a desktop without one,
  Export, Share as image, Backup, Restore and the imports used to do
  nothing at all.
- Where the system cannot play audio, no play button is offered. It used
  to download the reading and then stop without a word.
- The Share and “Written on this chapter” pages of the verse menu fit
  their rows. They opened at the full menu’s height, mostly empty.

## [1.7.2] — 2026-09-17

### Added

- **Textual variants in the Greek interlinear.** A Variants chip beside
  Strong’s, Translit, Gloss and Parsing. With it on, the words the
  Textus Receptus or the Byzantine text add appear in place in ⟦ ⟧ with
  the editions that carry them, a word those editions lack says so
  (− TR Byz), and where they read another word it is named under the
  Nestle-Aland one (Tyn TR Byz: υἱός “son” under θεός at John 1:18).
  Hovering gives the source’s own note. Passage exports name the other
  reading too. The data is Tyndale House’s TAGNT, already on disk; an
  interlinear installed before this release shows an Update button in
  the Module Manager, since the other readings and notes come with the
  new build.
- **Ketiv under Qere in the Hebrew interlinear.** A Ketiv chip beside
  Accents. With it on, a word the scribes corrected shows the form they
  wrote under the form that is read, with its gloss (Joshua 2:13 reads
  “sisters” over a written “sister”). Hovering names both. An interlinear
  installed before this release shows the same Update button.
- **Find and replace in journal entries and sermons.** Ctrl+F, or the
  search button at the head of the page, finds a word without regard to
  case and steps through every use of it; Ctrl+H adds a replace field.
  *Replace All* is a single undo.
- **Ctrl+D bookmarks the chapter you are reading.** Until now the header
  button was the only way.
- **Back and forward from the keyboard and mouse.** Alt+[ and Alt+], or a
  mouse's back and forward buttons, move through the passages you visited.
- **A daily copy of your study data.** Each day the app is first opened, it
  saves your annotations, journal, sermons, bookmarks and plan progress to a
  folder on this device and keeps the last 14 copies. An app left open
  across midnight makes the next day's copy within the hour. *Daily Copies*
  in the menu opens that folder, and *Restore…* starts there.
- **Restore… keeps what it replaces.** Before a restore, a copy of your
  current study data is written beside the daily copies, named
  *before-restore*, so the wrong file chosen is one more Restore… from
  undone.
- **Look up a verse from the GNOME search.** Type a reference such as
  "John 3:16" in Activities to see the verse in the translation you last
  read; Enter opens Scriptura there. A book name alone is not enough, so
  other searches are left alone.

### Changed

- **Single-pane view no longer shows controls for two panes.** The pane
  lock and the swap button are hidden until there is a second pane. A lock
  that is on stays in sight, so a pane that isn't following navigation still
  says so.
- **The annotations list shows the verse, and keeps itself current.** A
  highlight or underline with no note shows a line of its verse, where it
  showed only its colour. A mark made in the reading view appears in an
  open list at once, so the Refresh button is gone.
- **Scripture in Stone and the genealogies say what the evidence carries.**
  A few captions claimed more than is certain: the Pilate Stone as the only
  inscription with his name, a Tiberius denarius as the tribute penny
  itself, the Siloam steps as the ones the blind man stood on. They now
  separate what is certain from what is traditional or debated. What
  Scripture states stays as stated. Spanish and Russian follow.

### Fixed

- **Closing the main window could drop the last sentence of a sermon.** An
  edit still waiting to be saved in the Annotations window was lost when the
  main window closed first. It is written now.
- **Logging out could drop the last sentence too.** The session ending the
  app skipped the close path where the editors write. The app now closes its
  windows first, so what was queued is written and the reading position kept.
- **Restoring study data could keep an old sermon.** If Restore… ran while
  the Annotations window still had an edit waiting to be saved, that edit
  was written over the restored file a moment later: the window showed the
  restored sermon, the file kept the old one, and the next launch showed
  the old one. The waiting edit is now saved first, then replaced with the
  rest.
- **A settings file edited by hand no longer stops the app opening.** A
  paper that was not a colour, a window size below a pixel, a language that
  was not a name, or any setting of the wrong type failed the window while
  it was being built. Such a value now means the default.
- **Russian and Spanish named a mark with a verb.** The annotations list
  and exports labelled an underline «Подчеркнуть» and «Subrayar», which
  read as an order to underline; they now read «Подчёркивание» and
  «Subrayado», and highlights likewise.
- **The back and forward buttons named the wrong keys.** Their tooltips
  said Alt+← and Alt+→, which change chapter.
- **Two copies of the app could erase each other's notes.** Opening
  Scriptura a second time, or clicking a `bible:` link while it was open,
  started a second copy, and whichever saved last wiped out what the other
  had written to your notes, journal and sermons. A second launch now
  brings forward the window already open, and a link opens there.
- **Copying from an eBible translation named its internal id.** A copied
  verse read "John 3:16 (eBible: engwebp)"; it now names the translation,
  as exports have since 1.6.2.
- **With footnotes hidden, underlines and highlights sat one word late.**
  In a chapter with footnotes, an underline on John 3:16 began at "God"
  and ran on under the number 17. Search matches and the flash on a verse
  you jump to were off the same way. They now sit on their words.

## [1.7.1] — 2026-09-15

### Fixed

- **Giving a sermon manuscript a series could close the app.** With a
  manuscript open on the Sermons page, typing a series name or a part and
  then clicking into the text lost the whole window — and, because the
  autosave had already run, it came back with the words but without the
  series. Leaving those two fields re-sorted the list while the click that
  moved the keyboard was still being handled, which pulled the manuscript
  out from under the text you were clicking into. The re-sort now waits
  until the click is finished.
- **Typing in a long manuscript no longer slows down as it grows.** Every
  keystroke re-read the whole text to decide what was bold, quoted or a
  heading — fine for a journal entry, but a sermon of several thousand
  words was spending over half of each frame on it before a single letter
  appeared. Only the lines you are actually editing are re-read now, and
  what is on the page is identical.

### Changed

- **Russian: the verse menu's *Write an entry* is now «Новая запись в
  дневнике».** It had read as an offer to add a bookmark — which is a
  different feature — and the alternatives suggested each named something
  else already in that same menu.

## [1.7.0] — 2026-09-14

### Added

- **The passage actions are no longer behind a right-click only.** Export,
  the verse card, printing and Compare translations lived in the verse menu
  and nowhere else in the app, so a reader who never right-clicked a verse
  could not print a passage at all. The pane toolbar now carries a **⋮** that
  opens that same menu, and **Ctrl+P**, **Ctrl+E** and **Ctrl+Shift+C** print,
  export and compare directly — each acting on your selection, else the verse
  you are on, else the whole chapter. **Shift+F10** opens the verse menu from
  the keyboard, which is the context-menu key on a laptop with no Menu key.

- **The Annotations window now has pages** — *Annotations*, *Journal* and
  *Sermons* — chosen by a switcher at the top of the list, each with its own
  name and glyph. Your marks and your writing are different things to be looking for,
  and the search field, the type filter and the empty state follow whichever
  page you are on.
- **A journal.** An entry is a page where a note is a margin: it has a title,
  a date it is *about* rather than the day it was typed, and none, one or
  several passages. It lives in the list you already have, in canonical
  order — the canon leads here as everywhere else in Scriptura. Entries about no passage at all (a sermon, a conversation, a
  season) are perfectly legal and group at the end, newest first. The type
  filter narrows to entries with a passage or without one, a date-range
  filter finds what you wrote when you can only remember roughly when, and
  tags are one vocabulary across marks and entries together.

  **An entry's passages can be changed after it is written.** Each one is a
  chip you can leave — the name goes to the passage, the ✕ takes it off — and
  *Add passage* takes a reference typed the way you would write it anywhere
  else in the app: *Romans 5*, *Juan 3:16*, *John 3:16-18*. An entry that
  began about nothing can be filed later, which is what a sermon usually
  needs.

  There are four ways in. **Today** offers *Write about today* under the
  day's reading: the entry arrives already anchored to that day's passages
  and quietly records which plan day and which Sunday of the church year it
  came from — provenance you cannot reconstruct later. Right-clicking a verse
  offers *Write an entry* beside *Edit Note & Tags*. **Ctrl+J** opens
  Annotations and **Ctrl+Shift+J** starts an entry on the chapter you are
  reading. Or the pencil in the Annotations header, for writing that is not
  about a passage at all. Nothing is saved until you have written something,
  so starting one and changing your mind leaves no trace.

  An entry is written on a sheet with its tools at the head: **bold**,
  *italic*, heading, quotation and list, with Ctrl+B and Ctrl+I. Every button
  types what you could have typed yourself — a little **Markdown**:
  `**bold**`, `*emphasis*`, `# a heading`, `> a quotation`, and `- a list` —
  so an entry written by hand and one written by button are the same entry.
  The marks you type stay where you typed them — dimmed, so they recede —
  and what they enclose takes the styling as you write. **Enter carries a
  list on**: the next bullet or the next number is already there, an item
  added in the middle renumbers the ones under it, and an empty item ends
  the list. **A reference typed in the body becomes a link**:
  write *John 3:16*, or *Juan 3:16* in Spanish, and clicking it goes there.
  Book names are recognised in the language the app is in, and by their
  standard English abbreviations.

- **Sermons.** A manuscript is a third kind of writing, with a page of its
  own. It has a title, a **big idea** — one line saying what the sermon is
  saying — however many passages it was written against, a **series** with a
  part number, and the days it was **preached**, which may be none: a sermon
  you have not preached yet is simply one the list marks as such, and nothing
  ever asks you for a date. There is no "date written": a sermon is written
  across a span and preached on days of its own.

  The list leads with the series. Each one is a heading, its sermons in the
  order they were preached — part 2 above part 3 even when the passages run
  the other way, which is what a preacher working backwards through a book
  needs. Sermons in no series fall to the end in canonical order. The type
  filter asks the one question a manuscript answers — preached, or not yet —
  the date filter reads the day it was last preached, and the sort offers
  *By series*, *Recently preached* and *Recently edited*.

  The body is the journal's: the same Markdown, the same live formatting, the
  same reference links. **Ctrl+Shift+M** starts a sermon on the chapter you
  are reading, the pencil in the header starts one from nothing, and either
  way it quietly records which Sunday of the church year it was begun for.
  The caption under the sheet says how long it runs — *421 words · ≈ 3 min*,
  at about 130 words a minute read aloud — because a manuscript is written
  against the time it is given.

  **A series can be renamed from its own heading**, which renames every
  sermon in it; type a name already in use and the two series are joined,
  the way the tag manager merges tags.

- **Verses, cross-references, lexicon entries and your own notes can be
  collected into the sermon you are writing.** Right-clicking a verse offers
  *Add to "The Sower Went Forth"* — the manuscript is named, so it can never
  be wrong about where the words went — and drops the verse in as a quotation
  with its reference. A cross-reference adds its reference; a Strong's entry
  adds its headword and gloss; a note you made adds the verse and what you
  wrote under it. Every one of them adds the passage to the sermon's own, so
  a manuscript is never quoting something it is not filed under. The sermon
  collected into is the one you last wrote in, and the row disappears when
  there is no sermon to add to.

- **And the manuscript can ask what you already have.** *From your study*,
  beside the sermon's passages, lists every mark and note you have left on
  them and every journal entry written about them. A note goes in where you
  are writing — the verse, then what you saw in it, then the reference — and
  an entry opens, because an entry is a page and not a quotation. Every other
  door in the app carries writing *into* the manuscript; this is the one that
  fetches.

- **Tags suggest themselves.** Both editors offer the tags you already use —
  marks and entries together, since they share one vocabulary — as you type.
  It is the same list the tag manager cleans up; this is what stops *prayer*,
  *prayers* and *Prayer* being three tags in the first place.

- **The reading page says what you have written about a chapter, and what
  you have preached from it.** Nothing on the verse — the verse number already
  carries the note marker — and rows in the study menu that appear only when
  there is something to say: *3 entries on this chapter* and *1 sermon on this
  chapter*, each of which opens them.

- **Entries can be imported.** *Import entries…* takes Markdown or text
  files, one file per entry: front matter if a file has it, the opening
  heading as the title if not, the file name if not that, and the date from
  the front matter, the file name or the file itself. Nothing is anchored on
  the way in — an entry should not claim a passage its writer did not give
  it — and passages can now be added in a click.

- **Export can take just the entry you are looking at**, and export and
  import share one menu in the header.

- **Numbered lists, and a word count.** The list button numbers from 1 and
  renumbers a range someone else numbered badly. The count sits by the tags
  caption and appears only once there are words.

- **References in an entry now link by their usual abbreviations.** *Jn 3:16*
  in English, *Jn*/*Gn* in Spanish, «Ин. 3:16» in Russian — read from
  SWORD's own per-language abbreviation tables rather than invented here.

- **Search finds your own words.** Searching now answers with **Your notes**,
  **Your journal** and **Your sermons** above the scripture results — your
  marks, entries and manuscripts whose words match, whatever translation you
  are searching. A note leads to its verse; an entry or a sermon opens in
  Annotations. F3 still steps through scripture
  alone.
- **A day you wrote about carries a dot** on the reading plan's calendar.
  It records that something happened, not how well: no count, no chain, no
  streak.
- **The list folds away, and the window can be given over to writing.** The
  button at the head of the editor — or **F9** — hides the list and gives the
  whole window to what you are writing. It works at every width, where the
  back button it replaces appeared only when the window was narrow. **F11**
  goes further and takes everything: the list, the header, the series and
  dates and passages, the formatting row, the tags. What is left is the title
  and the page. Escape, F11, or moving the pointer to the top edge brings the
  window back — the same key and the same way out as reading mode on the
  reading page.

- **Export and print carry the text with them.** The Annotations export is
  now Markdown and includes the verse each mark or entry is about, an SBL
  citation naming the translation, and the attribution line every export in
  Scriptura carries. It writes what the list is showing, so the filters
  choose the scope — one entry, a season, the lot. There is a Print button
  beside it, setting the same serif on the same margins as a printed
  passage. **The open sermon can be exported or printed on its own**, headed
  by its own title rather than by the page it is filed on — the one sheet a
  preacher carries into the pulpit is not the archive it lives in.

- **The Today page opens with Scripture.** It had none on it: the day's
  reading was named and offered, but not a word of it was shown. The first
  verse of the day's first appointed chapter now stands under the reference,
  in the reading voice — the passage, and then a taste of it.

- **The Today page is written on.** Its surface used to be laid paper, the
  wire marks of a paper mould — which is the stock of a *printed* Bible and
  nothing older. It is now prepared skin, with the alphabet written down both
  margins the way a scribe practised it and the way Psalm 119, Lamentations
  and Proverbs 31 are built: the twenty-two Hebrew letters in order, every
  fourth line in Greek, with the older Paleo-Hebrew and Aramaic hands
  surfacing inside it — roughly in the proportion the canon itself is written
  in. The letters run in order, so nothing spells anything. The reading
  column stands on clean skin, as a written block does inside a ruled margin,
  and the whole ground is struck in your own ink, so it follows your paper
  through sepia, the dark papers and the evening blend.

- **At a wide window the date and the day leave the column** and stand in the
  left margin as a Kalendar heading, so a wide screen carries something
  instead of stretching.

### Changed

- **The header steps aside on the Today page.** A header bar wears the
  desktop's colour and the page wears yours, and only one of the seven papers
  ever matched — under a dark desktop a light paper met a near-black bar
  across the top of the page. While the Today page is up the page now runs to
  the top edge and the bar stops painting, leaving only its controls, drawn
  in the page's own ink. The page gets that height back with it, and the
  header no longer repeats a title the page has already given you.

- **Leading is corrected across the app.** Scripture in Stone, the catena,
  the genealogy pages and the projected presentation text were all set looser
  than intended — the projected text at nearly two full lines of space per
  line. They now sit at the spacing they were designed for.

- **The verse menu says which verse it is about, over the middle of it.** The
  reference was a small dim caption pushed against the left edge of the rows
  and read as a row that had lost its icon.

- **A submenu in the verse menu opens at its own height.** *Share* and
  *Written on this chapter* used to open as their two or three rows above a
  few hundred pixels of empty menu, because the page stack kept asking for
  the tallest page's height whichever page was showing.

- **One thing written on a chapter is a row, not a submenu.** If you have
  entries on the chapter but no sermon, or a sermon and no entries, that
  single line now sits in the menu instead of behind *Written on this
  chapter ▸* — the same height, one click fewer. Two of them still earn the
  slide.

- **Writing an entry is a row in the verse menu again, not a slide.** The
  `Write` submenu held a single item until you had saved a sermon, and two
  ever after — a whole extra click for the commonest thing to do with a verse
  after marking it. *Write an entry* sits on the first page, and *Add to
  “…”* joins *Written on this chapter* in the last group, where the rest of
  what you have written already lives.

- **The right-click menu is grouped, and half the height.** It had grown to
  twelve flat rows — 540px for a reader with marks, entries and a sermon
  behind them, against 388px on a fresh install — and five of those rows
  appeared in the middle as your own writing accumulated, so the row you
  reached for moved with use. The three things done oftenest stay where they
  were: the highlight colours — with *Clear* now a fifth chip in the row, the
  same size and shape as the four, instead of a small button stranded at the
  end of it — *Underline*, *Note & Tags* and *Copy verse*. The occasional
  ones are one slide deep behind the verb they belong to — **Write** (an
  entry, or into the sermon you are writing), **Share** (export, as an image,
  print) — with *Compare translations* beside them, and what you have already
  written on the chapter is last, so nothing above it can move. 353px now,
  and the same menu on day one as a year in.

  The pages slide in place behind a back row rather than flying out
  sideways, so the menu never needs room it does not have, and the keyboard
  walks it: arrows move, Right opens a page, Left and Escape come back. A
  screen reader hears menu items in a menu, where before it heard a dozen
  plain buttons in a box. Every row keeps its glyph, and no two rows on a
  page share one — the pencil beside *Note & Tags* and the one beside
  *Write* used to be the same drawing, on the one distinction that most
  needed to be legible.

- **An entry's or a sermon's facts share one line.** The series and its part,
  the days it was preached, the passages it is filed under and the Sunday it
  was begun for each took a row of their own between the title and the first
  line you could write on — more of the window was about the writing than was
  the writing. They sit on one line now, wrapping onto a second only when
  they must, and the sheet gets the room back.

- **The Annotations window folds to one pane sooner** — under 810 pixels
  rather than 660. Between those two widths it kept both panes and squeezed
  them instead, which cut a sermon's quoted verse and its text off mid-word.

- **The Annotations export was plain text and carried no attribution.** It
  listed references and notes with neither the words they were about nor the
  name of the translation they came from — the one thing that must travel
  with a quotation. It is Markdown now, through the same path every other
  export in Scriptura uses.
- **Study-data backup files are now version 3.** They carry your journal and
  your sermons alongside annotations, bookmarks and plan progress. An older
  file still restores, with that section empty — it was written by a
  Scriptura that had none. An older Scriptura will decline a newer file
  rather than restore it and quietly drop what is in it.
- **Notes and tags save themselves.** The Save button is gone from the note
  editor, the chapter-note editor and the Annotations detail pane: what you
  write is written once you pause, when you leave the field, and when you
  close the editor. The highlight and the underline beside them already
  worked this way, so the pane had two save models and now has one. **Escape
  now closes the editor rather than cancelling it** — to take words back, use
  Undo (Ctrl+Z) while the editor is open. A store that cannot be written now
  says so once per run of failures instead of once per write.

### Fixed

- **Resizing the window with the Today page up dragged heavily.** The page's
  ground was redrawn from scratch on every frame the window moved — a
  twenty-step drag struck twenty of them — because it was cached by size and
  every frame of a resize is a new size. The ground now follows the page
  while it moves and is redrawn once it settles.

- **A reading plan could say it was finished while the panel underneath said
  otherwise.** A thirty-day plan begun ten weeks ago reported "Plan complete"
  on the Today page while the plan panel said two of thirty days read. Both
  surfaces had let the calendar decide. Inside the schedule the day is the
  day; once the schedule has run out, the day offered is the earliest one you
  have not read; and a plan is finished only when every day of it is.

- **Opening the menu over the Today page felt stuck.** The page slid away
  while the sidebar slid in, so it was re-laid out at a new width on every
  frame of the other animation — most of a second of dropped frames. Anything
  that opens over the same area now dismisses the page at once instead.

- **A space could open after a quotation mark.** Some translations set the
  opening mark outside the tagged word, which left "say to me: " Flee like a
  bird". French guillemets are untouched — they are set with a space by
  design.

- **A module's centred headings were read as ordinary prose.** Concord
  centres its title page, and both the pattern that draws inline headings and
  the one that detects them matched only a bare `<h1>`–`<h6>` — an `h` tag
  carrying any attribute at all was not recognised. The tag was stripped and
  the text left behind, so "CONCORDIA" and eight more on that one page sat in
  the body copy, and the headings toggle rebuilt nothing because it could see
  no title to rebuild.

- **Double-clicking a word said "No entry" with dictionaries installed.** The
  dictionary peek has been dead since 1.6.2 — every lookup raised inside the
  background task, and a failed lookup is reported as an empty one, so the
  peek looked like a dictionary with nothing to say rather than a broken one.
  The cause was a name: the method that builds the popover calls its box
  `content`, which is also the module the lookup asks for the reading
  language, so the call reached the box. The box is called `body` now, the
  lookup moved out to where nothing can shadow it, and a check across the
  whole repo makes sure no other local is standing in front of a module its
  own scope calls into.

- **A reference typed in an entry could stop linking.** The parser reads
  SWORD's own abbreviation tables, and its recovery path for a locale file it
  cannot decode logged through a name that module does not have — so a handled
  read error became a crash, out through the reference scan and into the timer
  that runs it. Whichever entry was open lost its links, and nothing said why.

- **The search box in Annotations was cut off in Spanish and Russian.**
  «Искать по заметкам, меткам, ссылкам…» and *Buscar en notas, etiquetas y
  referencias…* ran past the end of the field at every width the list can
  take, on all three pages, and the English one on the Sermons page did too.
  All of them fit now, and none of them lost anything they name.

- **The store description still advertised the Study Journal.** 1.6.2 renamed
  it to Annotations and said so in its own release notes, but the feature list
  above them was missed, in English, Spanish and Russian. It now names
  Annotations, and says the thing that actually changed: a mark belongs to the
  verse and appears in every translation.

## [1.6.2] — 2026-09-10

### Changed

- **The Study Journal is now called Annotations.** It lists the marks you
  have made — highlights, underlines, notes, tags — and it was never a
  journal. Nothing about it moved; it goes by its own name.
- **A mark now belongs to the verse, not to the translation you were
  reading.** Highlights, underlines, notes and tags were filed under the
  module they were made in, so a note written in the KJV did not exist in
  the RVR60 and a new translation opened an unmarked Bible. They are filed
  under the reference now and appear in every translation, each one
  numbering them its own way — a Synodal or Vulgate psalter numbers the
  superscription, and its marks stay on the line they were put on. Existing
  marks are migrated on first launch, and the old file is kept beside the
  new one. Two translations marked on the same verse are merged, keeping
  both notes.
- **The Annotations list can be sorted by what you edited last.** The
  module filter is gone — marks are no longer per module — and the sort
  takes its place.

### Added

- **The verse itself, above the note.** The note editor and the Annotations
  detail pane quote the words the note is about. The note editor reads them
  out of the translation you have open; the Annotations window, where a
  mark belongs to no translation in particular, reads them in the one that
  fits the language the app is in — the Berean Standard Bible in English,
  the Nueva Biblia de las Américas in Spanish, the Русский открытый перевод
  in Russian — and falls back to whatever you have open when that one is
  not installed. Long verses are shown four lines deep — the whole verse is
  one hover away, and the note field keeps its room.
- **Marks record when they were made and last changed**, shown on the row
  and in the detail header. Marks made before this have no date and sort
  last.
- **The Old Calendar, which is most of Orthodoxy.** The Orthodox option
  kept the New (Revised Julian) calendar and only that, so a reader whose
  parish keeps the Nativity on 7 January was shown it on 25 December, and
  Theophany on the 6th rather than the 19th. Both calendars are offered
  now. Only the fixed feasts move between them — Pascha is reckoned the
  same way under each, so Holy Week, the Pentecostarion and the Sundays
  after Pentecost were always shared.
- **The Orthodox collects are in Church Slavonic.** Under a Russian
  interface the day's troparion was printed from a 1906 American service
  book, in English, beneath a Russian church line. The tradition now
  carries its own text — Slavonic rather than modern Russian, because that
  is what is sung and what a Russian prayer book prints — with the stress
  marks kept, since it is barely readable aloud without them. Where a
  Slavonic text is missing for a day the English one is still shown, rather
  than nothing. The Nativity of the Theotokos, one of the Twelve Great
  Feasts, had been left out altogether and is now there in both languages.

### Fixed

- **Exporting, printing, sharing or copying from an eBible translation gave
  a blank page.** The World English Bible the English welcome bundle
  installs is one, as are the Nueva Biblia Viva, the Reina Valera 1909 and
  the Biblia en Español Sencillo in the Spanish ones. Export passage, Print,
  Share as image and Copy verse each asked the SWORD library for a chapter
  it does not hold, and it answered with nothing rather than an error, so
  the reference and the attribution line came out with no words between
  them. The Annotations window's quoted verse was blank for the same
  reason. Every one of them now asks whichever source owns the translation.
- **Highlights and notes made in an eBible translation landed on the wrong
  line.** In the Russian Synodal text 1,126 verses were affected, in the
  Clementine Vulgate 1,113 — mostly the Psalms, where a mark on the first
  line of Psalm 3 was filed above the psalm and one on the second line
  painted on the superscription instead.
- **A note could destroy another note in a Vulgate or Synodal psalter.**
  Where those texts print a psalm title as two lines, both are one verse in
  the King James numbering the marks are filed under, so the second note
  written overwrote the first and the second highlight painted on the first
  line. The two lines are told apart now, and a translation that prints
  them as one shows both marks together.
- **“Match case” turned OR searches into AND searches.** Searching
  `Jesus OR Christ` with Match case on returned 258 verses of the 1,217 the
  same search finds with it off — it quietly required *both* words, and
  threw away every verse that carried only one, cased exactly as typed.
  `bread OR wine OR oil` came back with four verses instead of 661.
- **A first run could report that no Bible was downloaded when one was.**
  Three welcome bundles install their Bible as an eBible download, and the
  smallest Spanish bundle carries one specifically so that a bad day at
  CrossWire still leaves the reader with a Spanish Bible. The check that
  asks whether a Bible arrived counted only the other kind, so on exactly
  that bad day it met the reader with “Couldn’t download a Bible” and a
  Back button, with the Nueva Biblia Viva installed and ready behind it.
- **The dictionary opened on the wrong language.** Double-clicking a word
  offers every dictionary you have and opens the one in the language you
  are reading. On a Bible that came from eBible — the World English Bible,
  the Nueva Biblia Viva, the Reina Valera 1909 — it had no language to go
  on and opened them in alphabetical order instead, which in Spanish means
  Easton’s before the Wikcionario.
- **Search could fall back to no Bible at all.** Opening search while a
  devotional is in the pane picks a Bible to search instead; it looked
  only at one kind, so a library whose Bibles all came from eBible left it
  searching the devotional.
- **Exports cited the translation by its internal id.** A worksheet or a
  share card made from an eBible translation was signed `eBible: russyn`
  rather than *Russian Synodal Bible*.
- **A link to a book your Bible has not got did nothing at all.** The
  Scripture in Stone gallery cites 2 Maccabees for the Heliodorus Stele and
  1 Maccabees for the coin of John Hyrcanus; on the 66-book Bible the
  English welcome bundle installs, pressing “Open in the Bible pane” moved
  nothing and said nothing. Cross-reference links, Strong's links, search
  results carried over from another translation and bookmarks all refused
  the same way. Any of them now says which book is missing, in the same
  words the book list uses when it dims one.
- **“Bible in a Year — Blended” promised more than it gives.** It said
  “Four daily readings”, but Psalms and Proverbs are 181 chapters spread
  over 365 days, so that stream is silent on 184 of them and all four speak
  on only 95. The plan is unchanged — no reader's schedule moves — and its
  description now says what it delivers.
- **Two highlight colours wore the same letter in Spanish.** The swatches
  carry a letter as well as a colour, so hue is never the only cue — and it
  was the first letter of the colour's name, which made *Amarillo* and
  *Azul* both **A**. The letters are their own translation now: Spanish
  keeps the English Y G B O, Russian uses Ж З С О.
- **Two eBible psalters were numbered against the wrong text.** The
  Clementine Vulgate and the Russian Synodal text downloaded from eBible
  both merge the Hebrew psalms 9 and 10, so every psalm from there to 147
  sits one number behind — asking for Psalm 23 rendered «Господня земля»,
  which is Psalm 24. Measured against the same two texts as SWORD editions,
  138 of the 150 psalms disagreed; they agree on all 150 now. Three things
  followed from it: the verse grid offered 31 buttons for a chapter holding
  six, the comparison column and the dictionary's verse peek showed a
  psalm's superscription where the other column showed verse 1, and a
  chapter's footnotes could belong to a different chapter than the text
  above them.
- **The devotional could show the wrong day.** Asking a devotional for a
  date was tried in five key shapes and the first answer longer than twenty
  characters was accepted — but a devotional does not refuse a date it has
  not got; it snaps to some other entry and answers with that, at full
  length. The reading shown as today's could be any day of the year. The
  answer's own key is now compared against the date asked for. On a Spanish
  or Russian desktop the app was also asking for «sep 2» and «сен 2», which
  no devotional is written with.
- **Dates read in English whatever language the app was in.** The Today
  page headed a Russian church line with “THURSDAY · 3 SEPTEMBER 2026”.
  Month and weekday names were taken from the system, and a Flatpak carries
  only the languages the desktop itself is set up for — on an English
  machine, only English ones. They come from the app's own catalogue now,
  and the order of the parts moves with them, so a language that writes the
  day first is not made to accept English order to get its own month names.
- **The Russian church line used the civil wording.** It read «Тринадцатое
  воскресенье после Пятидесятницы»; no Orthodox calendar prints that. The
  church counts «Неделя 13-я по Пятидесятнице» — its own word for Sunday,
  its own preposition, and a numeral rather than the spelt-out ordinal. The
  Western traditions keep the civil wording, which is right for them.
- **Slavonic stress marks stood beside their letters in Georgia.** A
  combining accent is drawn over its letter only when the font gives it no
  width of its own. Georgia gives it 13 pixels at reading size, so
  «Све́тлую» came out as “Све ́тлую” — and Georgia is a face the font picker
  offers, so any Orthodox troparion landed in it for the readers who choose
  it.
- **A floating space before a comma, in four places at once.** Verse markup
  is stripped by replacing each tag with a space, which is right between two
  tagged words and wrong in front of punctuation — and the KJV with
  Apocrypha puts its tags between the word and the comma. “For God so loved
  the world , that he gave his only begotten Son ,” is what the Today
  epigraph, the devotional pane, every cross-reference and every dictionary
  gloss were showing. One routine does the stripping now. Thirty-four of the
  eighty-two Anglican collects carried the same space, from the same cause
  in the tool that extracted them; the words are untouched.
- **A highlight stopped at the verse number.** A highlight over a verse
  that begins mid-line covered the number and one space and went no
  further, leaving the rest of the line bare — which at a comfortable
  measure is most verses. The verse number is set smaller and raised, and
  that was enough for the rest of the line to be read as belonging to
  another line.
- **Highlights could load beside the text they belong to.** A freshly drawn
  chapter is still settling for up to a second, and the bands were measured
  from it as it moved, then left where they landed until something else
  asked the page to redraw. Bands are now drawn only once the layout has
  stopped moving.
- **A third corrupt settings file destroyed the second.** A file that
  cannot be read is set aside rather than overwritten, with a timestamp
  added when one is already there — but the timestamp counts whole seconds,
  so the third copy in the same second took the second copy's name. Four
  bad files in a row left two.

## [1.6.1] — 2026-09-02

### Fixed

- **The right-click study menu did not open in the middle of the page.** It
  is placed below the pointer, flipped above when it will not fit there,
  and when neither fits it was not shown at all — so on a window shorter
  than about 1,100px a band across the middle of the column answered
  nothing, while the same verse answered a line higher or lower. The menu
  can now be smaller than it would like: it keeps its full height wherever
  there is room and scrolls where there is not.
- **The Book of Generations opened at its own type size rather than
  yours**, then jumped to yours the moment you changed it. It takes the
  reading size when it is built, as the other document readers do.

## [1.6.0] — 2026-09-02

### Added

- **The Book of Generations.** Scripture keeps lists of names and readers
  skip them, so Scriptura draws them, and binds them as a book: one genealogy
  to a page, turned by the arrows in the running foot, from Adam to Noah
  through to Matthew and Luke laid side by side, with the ten lifespans of
  Genesis 5 on one axis so you can see that Methuselah's years run out in the
  flood year. A table of contents lists the eight pages and marks the one you
  are on, and each page keeps its place, so turning away and back returns you
  to the line you left. The charts are live, not pictures — a folded run of
  ten generations opens in place, a name opens the person, a chip opens the
  verse — and the same
  geometry writes printable plates, so what prints and what is on screen
  cannot disagree. Where a genealogy leaves generations out the gap is drawn
  as a gap, says how many, and cites who does name them. Where Matthew and
  Luke disagree both are shown as their writers give them, with the three
  classical answers set out below and attributed, and none of them chosen.
  Every one of the 165 lines carries the verse it comes from; the build reads
  all 186 citations back against the text and fails if one of them does not
  name the people it is drawn from. In English, Spanish and Russian, with the
  names in each read off the Bibles themselves.

- **Scriptura reads in Russian.** The whole interface — 1,134 strings,
  every one of them, with the three plural forms Russian needs — plus the
  Synodal book names it expects: 1 Kings is 3-я Царств. Names are said the
  way Russian Bible software says them: the references beside a verse are
  «Параллельные места», the interlinear is «Подстрочник», and a module is
  named in its own language to the reader running the app in it. Two fonts
  were set in the wrong voice, because the reading serif carries no Cyrillic
  and nobody had asked it to; the verse card and the printed handout now fall
  through to one that does.
- **A modern Russian Bible, and the first Russian dictionary.** Every
  Russian Bible anyone distributes is the 1876 Synodal or a revision of it,
  and the four Russian lexicons in the SWORD repositories are glossaries of
  the Central Asian translations' own terms — so a Russian reader had
  archaic prose and nothing at all behind the double-click. Scriptura now
  builds two modules and serves them from its own release. The Russian Open
  Bible is a modern text from the Door43 community, complete in 66 books, and
  23 of them — the Gospels, Acts, most of Paul, Genesis and Exodus among them
  — carry a Strong's number, lemma and morphological parse on every word,
  167,212 in all, so word study works in Russian for the first time. The
  Bible dictionary holds 1,018 articles on the terms, names and ideas of
  Scripture. Russian's first run now offers two collections instead of one,
  and the reading window opens on the modern text with the Synodal beside
  it.
- **A Spanish dictionary, where there was none.** Every one of the 168
  dictionaries the SWORD repositories distribute is English, French,
  Russian or Portuguese, so for a reader of the Spanish Bibles the
  double-click this app teaches on first run did nothing. Scriptura now
  builds one and serves it from its own release: a million keys from the
  Spanish Wiktionary, with the 2,691 entries of W. W. Rand's
  *Diccionario de la Santa Biblia* of 1890 laid over them, so *Moisés*
  opens on the prophet rather than on a wicker carrycot and
  *circuncisión* on the covenant rather than the surgery. Looking a word
  up follows Spanish too: the accents the 1909 spellings do not carry
  are ignored, and *alegróse* reaches *alegrar*.
- **First run asks which language you read in, and the answer leads.**
  Spanish used to be a fourth card beside three English ones, which made
  a language a kind of collection rather than the question above them: a
  Spanish reader met four choices of which three were the wrong
  language, with the interface in whatever the desktop had decided. The
  first screen now asks the language and sets both the interface and the
  library offered on the second, where the same three collections are
  filled from what that language actually has — and each card counts its
  own contents, so it can no longer promise a commentary the language
  has none of.

### Changed

- **The language cards say what each language holds**, counted from that
  language's own catalogue and written in that language — "3 Biblias · notas
  · diccionario" under Español whatever language the interface is in. The one
  your desktop already asked for is marked, so the screen shows you its answer
  rather than making you find it.
- **The dictionary peek stopped describing dictionaries and started naming
  yours.** Where a word has no entry it used to say that Bible dictionaries
  index proper nouns and key terms and suggest trying "covenant" or
  "atonement" — advice written when the only dictionaries were English Bible
  dictionaries, and false for the Spanish reader whose dictionary answers
  ordinary vocabulary. It now says which dictionaries were searched.
- **Scripture in Stone opens as soon as you ask for it.** The gallery
  decoded all 56 of its photographs before it would appear — 485ms of
  waiting, and 126MB of texture held for as long as it stayed open, to
  show you the two plates that fit on screen. The pictures now load as
  they come into view and are dropped once they are well past it: 102ms
  to open, 31MB held, and nothing moves under you as they arrive.

### Fixed

- **Jumping to a reference took English book names only.** Typing
  «Бытие 3» — the name the book picker two inches away was showing —
  flashed the box red, and had done the same to *Génesis 3* since Spanish
  shipped. The jump bar now takes the name you are reading as well as the
  canonical one, including the part of it you would actually type: Russian
  calls the Gospel «От Иоанна» and a reader types «Иоанна».
- **Book names sat in English inside a translated interface.** The
  cross-reference chips under a verse, and the per-book bars inside a
  search result's chart, were built where the English name is the key and
  never translated on the way out — so «Большие пророки» opened onto
  "Isaiah / Jeremiah / Ezekiel" with «Исаия 1:2» in the results beneath.
- **Scripture in Stone was English in every language.** The gallery is
  curated in TOML, which the string extractor cannot read, so none of its
  342 strings had ever reached a catalogue: a Russian reader opened
  «Писание в камне» onto a page headed "Scripture in Stone" and read 62
  captions, 11 introductions and a 15-entry glossary in a language they
  had not chosen. They are translated now at the one place every display
  site reads from, which covers the page, the artifact dialog and the
  search index together. Three things stay as printed, because a
  photographer's credit, a library catalogue and a verse chip each need
  the words they were given. Two Spanish cards also quoted a Bible no
  Spanish collection installs — every Spanish Bible here has «¡Grande es
  Diana de los efesios!» where the cards said «Artemisa», so the chip
  beside the sentence opened a verse naming someone else.
- **Translated labels overflowed the places that hold them.** A paper
  chip draws its name inside a fixed 56px ring, so «Грифельный» ran
  through it and lost its Г — and the Spanish *Personalizado* had been
  spilling since Spanish shipped. The Module Manager's four tabs share
  one header, and both translations were cut mid-word in the one place
  you are choosing between four of them. The names are shorter now, and
  two tests measure every one of them in every catalogue, in pixels.
- **The menu's cards lost their right-hand corners.** The panel reserves a
  gutter for its scrollbar, and the content underneath it had a minimum
  width equal to the whole panel — one long font name in the appearance
  card was setting it — so the overflow came off the right edge in every
  language. Opening Advanced made the whole panel jump wider, too.
- **A first-run download that failed for a module that exists.** The
  list of available modules is cached and nothing aged it out, so a
  profile that had read the list before a module was published had no
  row for it; the install fell back to a repository that module had
  never been in, and the download 404'd. Every profile that had ever
  opened the Module Manager was in that state when the Spanish
  dictionary shipped — the collection installed, reported a warning, and
  opened a reading window with nothing behind the double-click the same
  screen had just taught. The list is refetched now whenever it has no
  row for something the collection asks for.
- **Closing the first-run window mid-download left part of a library.**
  The install runs in the background and the titlebar close button stayed
  live through all of it, so closing at the fourth module of eight ended
  the app with some of the collection on disk, no record of what to open
  on, and nothing said about either. It asks now: whatever has arrived is
  kept, and it says where the rest can be downloaded later.
- **Russian was set in whichever serif the machine happened to own.** The
  app's reading serif carries no Cyrillic, so every Russian word fell out
  of the chain to a face nobody chose: Georgia on one machine, DejaVu
  Serif on the next. The widest of them was struck through by the
  genealogy charts' own column rails, which broke around a name by the
  size of the type rather than the size of the ink. Russian now sets in a
  serif the app ships with, the same one everywhere, and a rail breaks
  around what is actually on the paper.

### Internal

- Flatpak packaging: the catalogues ship with the app rather than in a
  locale extension that arrives empty on a host set to another language,
  and the icon is one flatpak will export past a validator that can read
  SVG.

## [1.5.0] — 2026-08-19

Scriptura in Spanish, and the books it would not open.

### Added

- **Scriptura speaks Spanish.** The whole application — menus, dialogs,
  the Module Manager, first run, the reading plans, the liturgical
  calendar and all 66 book names. A picker sits in the header of the
  first screen you meet and in the menu thereafter, each language listed
  in its own name.
- **Spanish Bibles, and a Spanish reading.** La Biblia de las Américas
  and the Nueva Biblia de las Américas (Lockman), the Versión Biblia
  Libre, and Straubinger's, whose 13,099 footnotes are paragraph-length
  commentary. La Biblia en Español Sencillo brings text and narration
  from one publisher, all 1,189 chapters.
- **The deuterocanonical books.** A translation that carries them shows
  them in an appendix after Revelation. They were unreachable before:
  the navigation stopped at 66 books, and asking a versification for a
  book it has never heard of clamps to its last one, so Tobit read back
  Revelation without anything looking wrong.
- **Every dictionary you install now appears**, whatever language it is
  in. The list had been filtered to English, which hid a dictionary the
  reader had gone to the Module Manager and installed on purpose.
- **The app draws its own icons.** The toolbar is the same line art on
  every desktop instead of whatever the local icon theme supplies — a
  KDE reader was meeting colour cartoons. The window controls are still
  the desktop's own.
- **Nineteenth-century plates** join the imagery pack, and an installed
  pack that has fallen behind the published one now offers its update.
- **Letter spacing.** Appearance → Advanced now opens the space between
  letters, from the face's own metrics up to a fifth of the type size.
  Widening it is the best-supported thing typography can do for a reader
  who finds text hard going — better than any special typeface — and it
  is set as a proportion of the size, so it holds when you change how
  big the text is.
- **OpenDyslexic is bundled.** The typeface now sits at the top of
  Appearance → Font, so a reader who wants it does not have to go and
  install one. It is offered honestly: testing has found no gain in
  reading speed, and the app says so where you choose it — but readers
  who find it easier find it easier all the same. It reads noticeably
  wider than the serif, so expect a longer chapter.
- **Scriptura follows the desktop's high-contrast setting.** Turn on
  *Accessibility → Seeing → High Contrast* and the app's own outlines
  come with it: the chips, swatches, cards, buttons and panel edges it
  draws are all lifted over the 3:1 contrast the guidelines ask of a
  control's boundary, in both light and dark. Nothing moves and nothing
  changes size — only how clearly each edge is drawn.
- **Readings on the desktop's media controls.** Whatever the app is
  reading aloud — a chapter, a psalm, either devotional — now appears on
  the media keys, the lock screen and the Shell's media control, named by
  what it is: "John 3", from the Berean Standard Bible. Play, pause, stop,
  skip back, reading speed and volume all work from there. There is no
  next or previous, because a reading stops at the end of its chapter and
  does not read on.
- **Quiet the rest of the page.** An optional reading focus: the passage
  you are in stays on lit paper while the rest of the page is laid back
  under a veil of that same paper — its heading stays with it, and
  nothing moves. It follows your scrolling, not your cursor, and it
  needs a translation that marks its own section headings. Appearance →
  Advanced → *Quiet the rest of the page*, off until you ask for it.
- **First run opens on a Bible and a commentary** rather than the same
  text twice, installs the collection you choose for real, and hands you
  the gestures reference where the gestures are taught.

### Fixed

- **Strong's numbers were invisible in the Spanish texts that carry
  them.** SpaRV1909 writes `Strong:` and both copies of the renderer
  read `strong:`, so a fully tagged Bible showed none of its 31 tagged
  verses in Genesis 1 — while search, which ignored case all along,
  found what the page refused to mark.
- **Texts imported from eBible keep their Strong's numbers** instead of
  discarding them at import, and an eBible translation that has fallen
  behind its source now offers an Update — the button used to be there
  whether or not there was anything to update.
- **The page holds still.** Flipping the theme, showing footnote
  markers, switching to old-style figures and lighting the drop cap
  recolour the chapter instead of rebuilding it; where a rebuild remains,
  your reading place is held through it, including in poetry, where the
  probe used to land between lines and lose the position.
- **A settings file the app cannot read is set aside, not overwritten.**
  A backup that did not reach the disk now says so, and a module archive
  that tries to write through a symlink is refused.
- **The lexicon hint no longer fires where tapping a word does nothing** —
  it is now gated on the text actually carrying Strong's numbers.
- **A long footnote now opens.** Where a note runs to an essay rather
  than a line — Straubinger's Spanish Bible writes 2,400 characters of
  commentary on one verse of Psalm 51 — the note asked for a popover
  taller than the window, which GTK will not place, so the marker did
  nothing when clicked while a shorter note two lines below opened first
  time. The note now opens on whichever side of the marker has more room,
  and scrolls inside the peek when it is long. The lexicon's verse peek
  and the Strong's hovercard are held to the same rule, so a long verse
  or a wordy gloss can no longer be unopenable either.
- **Voices of the Church: numbers were losing their thousands.** Four
  quotes printed figures like "Hezekiah routed 185, of the enemy" — a
  parser upstream had been dropping the digits after the comma. Fixed at
  the source and carried in the rebuilt pack, along with Origen on
  Romans and Jeremiah (+914 quotes), two verses reattributed from Jerome
  to Pseudo-Jerome, and a commentary wrongly given to Pacian of
  Barcelona removed. Installed packs will offer the update.

## [1.4.0] — 2026-07-27

Chapters read aloud, and passages you can take with you.

### Added

- **Chapters read aloud.** With the Berean Standard Bible open, the
  headphones in the pane toolbar bring up a small player over the page —
  the whole canon, all 1189 chapters, narrated by Bob Souer and dedicated
  to the public domain by the translation's own publisher. It carries
  play, back fifteen seconds, how far through you are, how long the
  chapter runs, and a reading speed from 0.75× to 2× that holds the
  narrator's pitch — set it once and every chapter follows. The player is
  drawn from your own paper and ink, so it belongs to the page rather
  than sitting on it. Chapters are fetched one at a time as you press
  play and kept for later, so a chapter you have heard stays available
  offline; a fetch that fails now says so instead of quietly stopping.
  Turn it all off under Appearance → Advanced → *Spoken readings*.
- **Spoken devotionals** from their publishers' own feeds — Spurgeon's
  Morning and Evening, the Psalms read one at a time, and the day's
  Daily Strength reading on the Today page.
- **Take a passage with you.** Export it as a study worksheet in Markdown
  or plain text, carrying your own notes and highlights, with optional
  interlinear, textual-variant and church-fathers layers. Citations
  follow the SBTS/Turabian short form.
- **A verse as an image**, set in the app's own serif on its own paper —
  three shapes, saved to a file or copied straight to the clipboard.
- **Print a passage** as a study handout, paginated so no line is ever
  cut in half.
- **The section headings your translation ships.** Until now they were
  dropped altogether. Move a whole thought at a time with `[` and `]`,
  and see at a glance which sense-unit you are reading.
- **The reading pane from the keyboard, throughout.** Step between verses
  and words with the arrow keys, open the lexicon, a footnote or the
  dictionary with Enter, and hear every move announced by a screen
  reader.
- **More of the Roman calendar's collects**, and a steadier Today page.

### Fixed

- **Modules keep installing when CrossWire's server is down.** The app
  falls back to FTP, and then to a mirror of everything CrossWire's own
  licences allow anyone to redistribute.
- Every translation now gets its verse-one drop cap, and commentaries
  render the inline titles they carry.

## [1.3.0] — 2026-07-10

The original languages, word by word.

### Added

- **Two interlinear reading surfaces** — the Greek New Testament and the
  Hebrew Old Testament (Tyndale House data). Every word carries its
  English gloss and parsing, with transliteration and Strong's numbers a
  chip away and the lexicon a click away. A Hebrew Accents chip calms the
  cantillation marks.
- **A Scholar's Greek Lexicon pack.** Abbott-Smith becomes the brief
  Greek entry, with the full Liddell-Scott-Jones one click deeper.
  Scripture citations inside entries are live — click one to peek the
  verse in place, or send it to the other pane.
- **Presentation mode.** Press F5 to project the current passage
  full-screen for a projector or mirrored display, with paging through
  chapters, a verse-per-page toggle, live type-size control, and a
  side-by-side parallel view of two translations.
- **Passage chips on the maps.** A map in Scripture in Art carries its
  passage as a chip — click it to drive the partnered Bible pane there.
  The Historical Commentaries pane shows place chips for the verse under
  commentary: click one for the place's photo and identification, without
  displacing what you're reading.

### Fixed

- Greek in the reading panes now renders with correctly composed accents
  on systems where the default serif drew them detached.

## [1.2.0] — 2026-07-05

Getting started, made discoverable.

### Added

- **Tips & Gestures.** A guide in the menu gathering every reading
  gesture in one place.
- **Gentle one-time tips** point out a hidden gesture — tapping a verse
  for its cross-references — the first time it is useful, then never
  again. You can turn them off at any time.

## [1.1.0] — 2026-06-28

Customizable reading appearance.

### Added

- **A reading appearance you choose.** A new Appearance panel: pick the
  paper — Paper, White, Sepia, Green, or a colour of your own — with ink
  that adapts to the page, a warm one on sepia and so on.
- **Reading plans redesigned** around a Today view and a month calendar
  of your progress.
- **Historical Commentaries.** An optional church-history commentary
  pane: how the church read each verse across time — the ante-Nicene
  fathers, the medieval doctors, and the Reformers — as chronological
  cards grouped by era, synced to the verse you're studying. Download
  the pack from Module Manager → Open Databases (compiled from the
  public-domain HistoricalChristianFaith Commentaries Database).
- **Import your own SWORD modules.** A `.zip` you already have on disk
  (a commercial translation, a shared draft, anything CrossWire doesn't
  carry) installs via Module Manager — an import button plus drag-and-
  drop, with a preview sheet and support for cipher-locked modules.
- **Remove a module from the pane picker.** The picker's info page now
  has a "Remove module" action, behind a confirmation.
- **Manage search history.** Each recent search has a remove button, a
  "Clear" button wipes the list, and searching an empty field returns
  to the recent-searches view.
- **Guided first run.** The welcome screen now offers three curated
  starting points — *Just reading*, *Reading + study* (recommended), and
  *Full library* — framed by what you get rather than by SWORD module
  names, so a newcomer can pick one and start reading. Everything stays
  addable or removable later from the Module Manager.

### Fixed

- Faint text trails when scrolling the reading view under Flatpak.
- Wrong/missing cipher key on an encrypted module now shows a "the
  cipher key may be incorrect" message with an Edit Key action instead
  of rendering gibberish (or nothing).
- Global keyboard shortcuts now work reliably from launch and after the
  window loses and regains focus. They were dispatched through a
  focus-dependent key handler that went dead whenever no widget held
  focus on Wayland; they're now window actions with accelerators.
- The chapter-note editor now opens as a dialog instead of a popover, so
  its text field reliably accepts keyboard input on Wayland.
- Verse highlights (and the search-match and navigation-flash highlights)
  now render as uniform bands that hug the text — no more tall blocks on
  the drop-cap line, notches around verse numbers, or per-verse stepping
  — and stay aligned at any font size, line spacing, or margin.

### Changed

- Bold and justified move to compact controls beside the font, and the
  menu's sections gain a clearer, calmer layout.
- **Empty placeholders are now actionable.** The “can’t read this module
  here” and “passage isn’t in this module” pages offer a *Choose another
  module* button (it opens the module picker), and a locked module offers
  *Edit Key* — instead of only describing what to do.
- **UI polish pass.** Consistent transition timing across panels and menus,
  search-result bars that follow your GNOME accent colour, and the lexicon
  toggle regrouped with the reading-view controls rather than the
  navigation buttons.

### Internal

- **Shared empty-state widget** (`empty_state.py`) deduplicates the compact
  placeholder used by the search panel and study journal; `style.css` now
  documents the spacing / radius / motion scale as a convention.

- **`content.py` routing facade** over the SWORD / eBible / catena
  bridges, so source dispatch lives in one place rather than scattered
  `if/elif` chains.
- **`ModulePicker` extracted** from `pane.py` into `module_picker.py`
  (the module selector popover); plus a consolidated module-flag helper.
  From a whole-app code review.
- **Keyboard shortcuts as GActions.** Global shortcuts moved to window
  actions + `set_accels_for_action`; the Keyboard Shortcuts window is now
  an `Adw.Dialog` with `Gtk.ShortcutLabel` key-caps read back from the
  action map. Only Escape and Home/End remain on a key controller.
- **Modern dialog / widget pass.** Note editors and the module-import
  sheet converted from transient `Adw.Window` to `Adw.Dialog` (dropping
  their manual Escape handlers); journal export uses `Gtk.FileDialog`;
  the catena and "can't read this module" placeholders use
  `Adw.StatusPage`.
- **Highlights painted, not tag backgrounds.** `BibleTextView` draws the
  verse / search / flash highlights as uniform bands in `do_snapshot` (from
  zero-visual marker tags `hl_bg_<hex>` / `_search_hl` / `_flash`); GTK tag
  backgrounds hug line metrics and broke on the drop cap and small verse
  numbers. Anchored to the display-line start so adjacent bands can't drift.

## [1.0.1] — 2026-05-28

Packaging fixes.

### Changed

- The build moved to meson, for a cleaner Flatpak install.

### Fixed

- SWORD's CMake now links libcurl properly (upstream bug API-263). It
  had been substituting a deprecated singular variable that modern CMake
  no longer sets, so the link silently pulled in nothing.

### Internal (post-1.0 cleanup)

- **Logging migration.** Replaced ~25 `print('[tag] …')` sites across
  11 modules with the standard `logging` module, rooted at the
  `scriptura.*` logger tree. Exception handlers now use
  `_log.exception()` so caught errors include a traceback —
  invaluable for debugging user-reported SWORD setup issues.
  Verbosity is controlled with `SCRIPTURA_LOG_LEVEL` (default
  `WARNING`); README's "Reporting bugs" section asks users to attach
  the `DEBUG` output to issues.
- **`Adw.MessageDialog` → `Adw.AlertDialog`** in `study_journal.py`
  (rename / delete tag, export error). `MessageDialog` is deprecated
  in libadwaita 1.6 and emits runtime warnings.
- **Tests for the pure-Python bridges.** 91 new tests across
  `paths.py` (XDG resolution + legacy migration), `bookmarks.py`,
  `settings.py` (debounce + corrupt-file recovery), and
  `ebible_bridge.py` (USFM parsing + SQLite-backed verse storage).
  Total suite: 227 tests.
- **Type hints — persistence layer.** Annotated `paths`, `bookmarks`,
  `settings`, `annotations`, `module_positions`, `reading_plans` with
  modern syntax (PEP 585/604). Introduced TypedDicts for the
  on-disk shapes (`Bookmark`, `Plan`, `ChapterNoteData`). `mypy.ini`
  enforces `disallow_untyped_defs` on these six modules and runs
  clean (the rest of the tree remains `ignore_errors` for now,
  widening module-by-module). Tooling: `mypy>=1.10` added to
  `requirements-dev.txt`.
- **CSS centralised.** All static styling moved from five inline blocks
  (in `search_panel.py`, `annotation_dialogs.py`, `study_journal.py`,
  `window.py`) into `data/style.css`. A small `styles.py` loader calls
  `Gtk.CssProvider.load_from_path` once at startup. The per-pane dynamic
  CSS (font family, size, line spacing, user-chosen text color) stays
  in `pane.py` since it depends on runtime state. Saved ~160 lines of
  per-module CSS plumbing; one place to edit, with editor syntax
  highlighting and a clearer comment trail about Revealer-shadow and
  `@view_bg_color`-vs-`@card_bg_color` quirks. Flatpak manifest updated
  to install `data/style.css` and the previously-missing
  `genbook_reader.py` and `styles.py`.
- **Generic Books subsystem extracted from `pane.py`.** ~270 lines
  of TreeKey rendering, prev/next/TOC widgets, async fetch, and
  entry-path persistence moved into a new `GenbookReader` class in
  `genbook_reader.py`. `pane.py` drops from 2 681 → 2 381 lines;
  the new file is fully type-hinted and joins the strict mypy
  surface. Behavior is unchanged — same icons, same fallback
  heuristics, same TreeKey auto-scroll. The pane retains
  `_is_genbook` because it gates pane-level chrome and dispatches
  between verse-keyed / genbook / devotional render paths.

## [1.0.0] — 2026-05-23

First Flathub release. The app gets its proper name, a hardened
persistence layer, and the Flatpak packaging story closed.

### Name

- **Renamed from Bible Reader to Scriptura.** Latin for
  *Scripture* — distinctive, memorable, and aligned with the
  audience this app is built for. App-ID is now
  `page.codeberg.andresmessina.Scriptura`.

### New features

- **Pane-swap button** in the headerbar (alongside the single /
  split toggle) — flips the two panes' modules in one click,
  preserving scroll position via the new per-module memory.
- **`bible:` URI scheme** — `xdg-open 'bible:John+3:16'` opens
  Scriptura at the requested reference. Works for both `+`-
  encoded spaces and proper `%20`. Lets external apps
  (browsers, chat clients, notes) link directly into Scripture.
- **Current-verse indicator** — the active verse number wears a
  subtle accent (purple, bold). Persists across annotation saves;
  cleared on chapter change. Distinct from the click-flash and
  from annotation highlights.

### Persistence

- **Per-module position memory.** A single record per module
  tracks the last reading position (top verse for verse-keyed
  modules, entry path for Generic Books). Both panes consult the
  same store, so swapping modules between panes — or opening the
  same module in either pane on next launch — returns to the
  last place it was viewed.
- **Atomic writes** across every state file (annotations,
  bookmarks, settings, module positions). A crash mid-write
  leaves the original file intact instead of truncating it — your
  annotations are no longer at risk if the system loses power
  during a save.
- **Debounced + locked-down module-position writes.** A pane
  swap fires two module changes in quick succession; the
  debounce coalesces them into one disk write, and the lock is
  released before disk I/O so concurrent callers don't serialise.

### Performance

- **LRU caps on chapter and Strong's caches.** Reading the entire
  canon in one session previously grew memory by ~230 MB. The
  cap holds steady-state at ~175 MB. Re-rendering an evicted
  chapter costs one SWORD round-trip (~20–80 ms).
- **Lazy Whoosh import** — `sword_bridge` no longer pulls in the
  full-text search engine at startup. Cold-start of the bridge
  module dropped from ~102 ms to ~90 ms. Whoosh loads on first
  search.
- **Cheap module-presence probe.** The welcome-vs-main decision
  reads `~/.sword/mods.d/` directly instead of instantiating
  `Sword.SWMgr()` (105 ms → 0.09 ms). The full SWMgr init still
  happens — just after first paint instead of before it.
- **Stop caching Strong's misses.** A failed lookup is no longer
  permanently cached as `None`; subsequent clicks on the same
  Strong's number will retry, so installing the missing module
  takes effect immediately.

### Stability fixes

- **Pane-swap scroll preservation** for all common chapter
  positions, not just deep scrolls.
- **`bible:` URI** parses from `sys.argv` directly — Gio.File
  doesn't always round-trip custom URI schemes cleanly.
- **Welcome / panel UI:** shadows on overlay panels (menu,
  search, F11 exit button) no longer render with 90° artifacts
  on certain themes. Borders carry the visual weight; revealer
  clipping no longer fights the shadow.
- **Genbook position saved as a string,** not a list of
  characters. (A regression introduced during the per-module
  refactor that broke Concord / Westminster Confession startup
  briefly during testing.)

### Code health

- **Extract pane search into its own module** (`pane_search.py`,
  ~345 lines). `pane.py` shrank from 2 831 to 2 607 lines as a
  result; the external interface for window callers stayed
  identical via property delegators.
- **PROJECT.md → ARCHITECTURE.md.** The project brief is now a
  neutral architecture document; AI-assistance acknowledgement
  is consolidated into a single paragraph in the README.

### Packaging

- **Flatpak builds and runs end-to-end** in clean Zorin OS 18
  VM and on Fedora. The SWORD-Python binding integration is
  solved via `greg-hellings/python-libsword` 1.9.0.post1, which
  ships pre-generated SWIG output and links against the
  libsword built in the same manifest.
- **Bytecode precompiled at install** (`python3 -m compileall`)
  so first launch doesn't pay the compile cost.
- **Atomic-write tmp files** auto-clean — the rename pattern
  overwrites the same `.tmp` path on each save, so no orphan
  files accumulate.

### Tests

- 124 → 136 tests, all passing in under a second. The 12 new
  cases cover `module_positions` round-trip, kind discrimination,
  chapter/book scoping, legacy data recovery, debounce, and
  flush behaviour.

## [0.9.0] — 2026-05-21

First public testing release. Everything below is stable and
exercised in real reading sessions; the only thing standing between
this and a 1.0 tag is the Flathub submission round-trip.

### Reader

- Two-pane reading view with per-pane sync locks and an independent
  module selector on each pane.
- SWORD module support: Bibles, commentaries, devotionals, and
  Generic Books (tree-keyed reference works).
- eBible.org modern translations (LEB, BSB, etc.) via a SQLite
  backend, surfaced as just-another module in the picker.
- Greek and Hebrew Strong's lexicon with hover-only word underlines,
  a per-pane lexicon panel, word-study list across the current
  book, and Greek (Robinson via MorphGNT) + Hebrew (OSHB)
  morphology displayed in the header.
- Adjustable reading-column width via Text Appearance slider
  (540–1600 px); scrollbar sits at the pane's outer edge for a
  modern reader feel.
- F11 reading mode with a hover-to-reveal exit affordance at the
  top of the window for users who don't remember Esc/F11.

### Annotations

- Four highlight colors plus underlines plus per-verse and
  per-chapter notes with topical tags.
- All annotation actions are in-place tag mutations — the scroll
  position never moves on save.
- Soft pastel highlight palette at render time; underlying storage
  values unchanged for forward compatibility.
- Drag-select across verses works; Ctrl+C copies with the verse
  reference prepended.

### Cross-references and topics

- Slim single-row cross-reference bar at the bottom of the window.
- OpenBible.info's 340 000-reference database (CC-BY), with TSK as
  the fallback.
- OpenBible topical tags surfaced as Suggested chips inside the
  note editor.

### Search

- Whoosh full-text per-module search with a canon-distribution
  bar chart and click-to-navigate results.
- F3 / Shift+F3 step through results without re-opening the
  panel; tolerates a closed panel by re-revealing.
- Aa match-case toggle (Whoosh post-filter for SWORD modules;
  SQLite GLOB for eBible).
- Matched-word highlighting in the chapter on arrival from a
  search result (5-second amber highlight, distinct from the
  yellow verse flash).

### Study Journal

- Master-detail layout: sidebar with type / tag / module / book
  filters + free-text search; detail editor on the right with
  color swatches, underline toggle, tags entry, and a note
  TextView.
- Live-save for color and underline; explicit Save for note +
  tags so unsaved text isn't blown away by a swatch click.
- Clickable tag chips on rows filter by that tag.
- Tag Manager dialog (rename / merge / delete) launched from a
  header button.

### Reading plans

- Six built-in plans: Bible in a Year, Blended (4-stream
  OT+NT+Psalms+Proverbs), OT in a Year, NT in 90 Days, Psalms in
  30 Days, Proverbs in 31 Days.
- Day-by-day progress tracking with a today highlight; multi-passage
  days surface a small popover.

### Devotionals

- Spurgeon's Morning and Evening (SME) with morning/evening
  section split; other devotionals supported through the standard
  Daily Devotional SWORD convention.

### Generic Books

- Tree-keyed reference works (Didache, Westminster Confession,
  Book of Concord, Dark Night of the Soul, Apostolic Fathers)
  read via a TOC popover and prev/next entry buttons.
- Breadcrumb title above the entry body for deep hierarchies.
- Per-pane reading position persistence — switching modules and
  coming back returns to the last-read entry; same across app
  restarts.
- Section-heading entries (no body, only sub-entries) get a hint
  pointing the user to the TOC.

### Navigation

- Ctrl+L quick jump (`Goto: John 3:16`, abbreviations supported).
- Alt+←/→ for chapter; Alt+↑/↓ for book.
- Home / End for first / last verse of current chapter.
- Ctrl+1 / Ctrl+2 / Ctrl+Tab for pane focus.
- Ctrl++ / Ctrl+- for font size; Ctrl+scroll and touchpad pinch
  for the same.
- Mouse wheel over the title button cycles chapters.
- Right-click a chapter in the picker to slide over to a verse
  picker for that chapter.
- Recent-passages menu (header clock icon, 10 distinct passages,
  persistent across sessions).

### State

- Per-pane scroll position restored on next launch.
- Per-pane Generic Book reading position restored on next launch
  and across module switches.
- Window size, maximized state, split-pane mode, last book /
  chapter, and pane modules all persisted.
- All data lives under XDG locations
  (`$XDG_{CONFIG,DATA,CACHE}_HOME/bible-reader/`). One-shot
  migration moves legacy in-tree state out on first launch.

### Module Manager

- Three tabs: SWORD modules, Open Databases (OpenBible cross-refs
  + topics, Dodson Greek), eBible.org translations.
- Module picker has language chips, per-module info popover, and
  free-text filtering.

### Internals

- 124 pytest tests across `sword_bridge`, `open_data`,
  `annotations`, `reading_plans`. GTK-side code verified by
  running the app.
- Performance audit pass (release-blocker hot paths): eBible SQLite
  thread-local singleton, BiblePane module-language memoization,
  SearchPanel display cap at 500 rows, settings.put debounce,
  tag-table bounded per render.

### Packaging

- Flatpak manifest for `page.codeberg.andresmessina.Scriptura`
  is checked in but the SWORD-Python binding integration step is
  pending Flathub-maintainer help. See `flatpak/STATUS.md`.

### Known limitations

- Generic Books cannot be searched (Whoosh indexes verse-keyed
  modules).
- Annotations and bookmarks are not yet extendable to genbook
  entries.
- Some long-form dictionaries (Webster's 1913) ship HTML markup
  that renders fine but isn't perfectly typeset.
- Module Manager doesn't filter out Maps / Images or
  "Cults / Unorthodox / Questionable Material" categories — they
  can be installed but won't render in panes.
