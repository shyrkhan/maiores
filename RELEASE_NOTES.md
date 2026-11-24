## Maiores 1.4.3

What other people see: shared pages, reports and the names on them.

- **Hide living** now also protects someone whose birth is recorded only as "after 1910":
  such a date has no latest year, so the person could be alive.
- **Reports** suggest a file name with the name as the report shows it: with living
  people hidden, a hidden person's first name is no longer in the suggested file name.
- **Report sources**: two sources with the same title (two parish registers, say) are now
  two numbered notes, each with its author and archive, instead of one.
- **Family sheets** show when a couple divorced, not only "Married".
- **Shared web page**: search finds a married woman by her birth surname too, and
  "Đaković" typed with its own letters finds her (before, only "Dakovic" did). Each
  person's sources now include those of a marriage and of other names, with author and
  archive. In Arabic the page reads right to left.
- **DNA** compares a match only through birth links: adoptive and foster parents are
  family, but share no DNA, so they no longer raise a "lower than expected" warning.
- **How are they related?** finds brothers and sisters added with Add sibling while
  their parents are still unknown (and their children: nieces, nephews, cousins).
- **Map**: clicking to place a pin across the 180th meridian works (before, the click
  gave a longitude past 180 and was lost). The list beside the map follows the
  Births / Deaths / Marriages filter.
- **Combine** keeps two sources of the same title apart when their author or archive
  differs (two parish registers from different archives were made one), and brings a
  source's publication details and abbreviation along.
- **Documents**: dropping several files on someone attaches all of them, not only the
  first. When the tree can't be saved (a full disk), attaching or merging no longer
  reports success over the message saying so.
- **Recovering a damaged tree** offers only a backup that really opens (one without its
  format version, say, is skipped for the next good one), and checks it before anything
  is replaced.
- **A tree whose file has gone missing but whose backups remain** stays on the start
  page, in Open recent and in reopening at start; File > Open reaches it through any
  file inside its folder (a backup's tree.json, say). New tree with its name opens it
  for recovery instead of starting an empty tree over it.
- **New tree and Import GEDCOM** ask about an unsaved change in the open tree before
  making anything: answering No leaves no new tree behind.
- **Dates between two exact days** ("between 12 May 1880 and 19 May 1880") keep their
  days on GEDCOM import and export; before, only the years were kept. They can be typed
  as 12.5.1880-19.5.1880. (Maiores 1.4.2 and older show such a date as written.)
- **Editing only a note** no longer changes a date's calendar: a residence "from 1700 to
  1710" with only its end in the old (Julian) calendar stays so. A date left as the
  window showed it is always kept exactly as stored.
- **Died before born** is judged by the whole dates and what uncertain ones allow: "born
  before 1900, died 1880" can be saved; born 31.12.1900 and died 1.1.1900 cannot, and
  Check dates now reports it.
- **Lifelines** no longer keeps every earlier chart in memory while History is switched
  on and off.
- **A damaged portrait** in a recent tree no longer stops Maiores from starting or
  closing a tree: its start card shows the initials instead.
- **Switching trees** clears the search box, its suggestions and a highlighted
  relationship, so nothing of the last tree is picked by mistake in the next.
- **A range whose end is less exact** ("between 12 May 1880 and May 1880") keeps both
  ends; a range that can't be held as written (the old calendar, the end before the
  start) goes to the notes and back out unchanged, never cut to its years.
- **Memory**: closing a tree lets go of its chart, and the Gallery reads a photo shared
  by many people once.
- **Deleting a partner** ends the couple as removing one does: a partner added later no
  longer inherits the old wedding date and place.
- **DNA segments**: a match known only by name takes the kit id of the first segment
  file row that names it, so another person of the same name with another kit becomes
  a match of their own instead of being joined to it.
- **Combine** names any document or portrait it couldn't bring across because the file
  is missing in the other tree, instead of dropping it without a word.
- **Godparent** is a role of its own: GEDCOM's gender-neutral "Godparent" is no longer
  read as Godmother, and goes back out as Godparent.
- **Unsourced facts** also lists a birth known only by its address, a death known only
  by its cause, and other facts whose only detail is an age or a label.
- **Faces**: a face removed, or changed to someone else, after "Use as portrait" no
  longer becomes the portrait of whoever it named first.
- **Photos** of 108 megapixels and more (newer phones) are read at a smaller size
  instead of being refused; a picture this computer cannot show (an iPhone .heic)
  dropped on a card is kept as a document.
- **Deleting someone with no name** no longer writes "Unknown", in whatever language the
  program runs in, into the people at events and the faces in photos.
- **Merging** two records of one person keeps the second portrait among the photos;
  differing dates go into the notes as "* 1936" and "† 1980", the same in every language.
  Brothers and sisters recorded with no parents follow when the parents are found for
  one of them, and a couple recorded twice keeps "divorced".
- **Connecting both parents** of a known couple puts the child in that couple's family,
  instead of making a second family for the same two people.
- **Places**: renaming a place onto another keeps the other's coordinates and kind, and
  both notes; a rename refused (a place inside itself) leaves nothing behind.
- **Reports**: someone with no name is listed in the index of names as in the entry.
- **GEDCOM export** keeps shared notes that a birth, residence, marriage or source points
  to, and writes them as shared notes again (loose notes still stay home). A shared note
  on an event or a source is no longer read as the words "@N2@".
- **GEDCOM** keeps nicknames on every name, family links of kinds Maiores has no word for
  ("step", "sealing"), archives no source points to yet, coordinates written in degrees
  and minutes (N47°04'), and up to six decimals of coordinates. Details kept with a name
  or a family link stay with that name or link when they are written in another order,
  and long event descriptions are split into short lines as GEDCOM requires.
- **Side panel**: a long web address in the notes wraps instead of pushing the buttons
  out of sight.
- **Charts**: when cousins married, the family view no longer hangs them from the wrong
  couple; the children of a third or fourth partner hang from a bar of their own instead
  of sharing the first partner's.
- **Relationships**: an adopted child is related to the adoptive family (mother, brother,
  grandmother), and the couple's own child is a brother, not a half-brother; DNA still
  counts the birth family only. A child recorded in two families (one knew only the
  mother) is the child of the family that knows both parents, whatever the file order.
  "Ana and Ivo are not related through the recorded links" now reads as a sentence.
- **Combine**: choosing "Theirs" keeps yours in the notes or as another name, as the
  window says; a choice made before changing the match is not applied to the new one.
  Combining the same tree again writes no note or difference twice and copies no
  untitled source again. A different birth surname is kept as a birth name, their
  different wedding date and place go into the notes, a source both trees have takes
  the details only theirs has, and someone hidden in an earlier shared copy is no longer
  hidden once matched with the real person.
- **Details kept from another program's file** stay with their own event or citation:
  deleting an event or a citation no longer hands its kept details (an agency, a
  quality) to the next one, no empty source line is written, and a quality set in
  Maiores replaces the one from the file instead of being written twice. A citation of
  a whole person ("1 SOUR @S3@") is counted in the Sources window, goes out in exports,
  and moves along when its source is merged into another.
- **Story**: changing only its private tick keeps the indent of the first paragraph.
- **Check dates** compares parents' and partners' deaths with births to the day (a
  child born 22 months after the father died in the year before is found), and also
  finds a mother over 60 or a father over 90 at a birth, a marriage before birth, and an
  age at death over 110. The list is in surname order, accents and all.
- **Statistics**: "after 1909" and "before 1900" are no longer counted as births in the
  1900s, and the overview and the Surnames tab count surnames the same way.
- **Timeline and Places** sort by the real date: "before 1900" ahead of 1900, "after 1900"
  behind 1.6.1900, "about 1700" in 1700; on one day a birth before a baptism and a death
  before a burial.
- **DNA**:
  - Half cousins are called half cousins (English and Croatian), and the short labels
    say Grandchild or Grandparent the right way round.
  - A child whose link is "unknown" is related by DNA to their recorded parent again.
  - A cM total typed in by hand is no longer added up again from a segment file read later.
  - Files read in more of the companies' own forms: 23andMe's per-segment download,
    GEDmatch segment kit numbers (so two people of one name stay two), segment and
    match files with German, French or Croatian column names, and "2.612" in a file
    that writes decimals with a comma.
- **Languages**:
  - A new event typed to look like an older one ("from 1700 to 1710 (Julian)") is
    saved as typed, not in the older event's stored form.
  - Japanese, Chinese and Korean dates read back as the program shows them ("1921 年頃",
    "1921年", "1950年から1960年まで"), and so do "environ 1921" and "约1921年".
  - Arabic reports (PDF and ODT) read right to left, the index tables too.
  - Counts no longer say "1 people" or "2 osoba": they read "people: 1" in every language.
  - The start page shows dates in the chosen language's form, not the computer's.
- **A full disk** no longer makes a PDF picture, PDF or ODT report or poster say "Saved"
  while the file it replaced is left cut short or empty: the old file stays, and you are
  told. A full disk no longer keeps you out of your tree either: it opens, with a word
  that changes can't be saved until there is room.
- **Saving** is no longer stopped by an old backup that can't be deleted, and the "Could
  not save" line goes away once a save works again.
- **Failed writes** are told plainly: a document that couldn't be copied is no longer
  called "too big or missing", a photo on a full disk no longer says "Unknown error", and
  every export names the file you chose and why it failed, taking away the earlier
  "Saved" line. A new tree that couldn't be made leaves no half-made folder, an export
  cut short by a removed USB stick leaves no hidden folder behind for good, and long
  file names the system allows are no longer refused.
- **Menus**: Highlight a family line (Ctrl+B) no longer breaks on the start page;
  Combine, Make a copy to share, Share as a web page and Show on phones are enabled only
  where they can work; the tour ends when its tree is closed; and a save that failed in
  a tree you closed is not asked about again in the next tree or the sample.
- **Someone hidden in a shared copy** who is given a name or a date in the edit window
  is shown by it again, not as "Šimić (living)".
- **Hand-edited files**: a tree.json saved with a byte-order mark (as many Windows
  editors do) opens as it is, instead of being taken for damaged and swapped for an older
  backup. A marriage date written as a number, sources that are not records, or a "NaN"
  coordinate no longer stop the tree opening, editing, exporting or saving. Details of a
  birth, death or marriage that the windows don't show (a time, keys from a newer
  version) stay through an edit.
- **Big trees**: Statistics (281 s on 20,000 people before), Combine's suggestions, the
  descendant and ancestor books and the DNA window share one family index instead of
  building one per person. The duplicate finder is about three times faster and no
  longer searches the whole tree again after each "not the same" answer.
- **GEDCOM pictures and documents**:
  - The picture another program marks as the main one (_PRIM Y, _PHOTO) becomes the
    portrait.
  - Files named by where they were on the other computer ("C:\Users\Ana\b.jpg") are
    found by their name beside the GEDCOM file, or in a folder there, as the message
    advises; "my%20photo.jpg" is read as "my photo.jpg".
  - A shared picture record whose files were only partly found keeps the missing ones,
    and every file not found is counted; web and e-mail addresses are no longer counted
    as missing photos.
  - A file that could not be used keeps its line, so the export still names it.
  - "Photos copied in" counts photos only; documents have their own line. A file's FORM
    line no longer doubles at every export and import.
  - Combining with a .ged names the pictures and documents it could not bring across.
- **Shared web page**: a note such as "Old page said: <!--" followed anywhere later by
  "<script" no longer leaves the page blank; an odd address ending ("#%", "#constructor")
  goes to the start instead of a blank page; and a password with accents opens the page
  however the device's keyboard writes those letters.
- **Show on phones**: "Stop showing" now ends connections already open too, and a device
  that connects and says nothing is let go after 15 seconds, so nobody on the network
  can tie up the program. A phone that hangs up no longer prints an error.
- **Half an emoji** in a hand-edited file (it can be read, never written) becomes "�"
  when the tree is opened, so saving, sharing and exporting work.
- **Combining the same tree again** (a relative's copy of yours, your own share copy)
  repeats nothing: no event twice when it names another person, one DNA test with its
  matches once, no second copy of a portrait kept as a photo, your place spellings
  ("trogir" and "Trogir" both) and your own sources as they were.
- **Merging** two brothers recorded with no parents leaves no empty family behind, and
  merging someone with their own DNA match unlinks the match instead of pointing it at
  themselves.
- **Reports as OpenDocument (.odt)** are offered again: Qt names the format "ODF" in
  capitals, and the check looked for lower case, so the report window only ever offered
  PDF. The list of bundled libraries and their licences is complete.
- **Starting up**: a tree opened as "maiores A.tree" from a terminal is remembered by
  its whole path, so the next start no longer opens another "A.tree" in whatever folder
  it was started from, or loses the tree from the recent list. Odd values in a
  hand-edited settings file (a list as the card style, a point as the recent list) no
  longer stop the program starting.
- **Two windows**: one no longer wipes the other's tree from the recent list, and
  Preferences in one no longer undoes what was changed in the other. The same tree
  reached by a link or a trailing slash is listed once.
- **Language**: a stored language this version doesn't know means "System", as
  Preferences says, and choosing System really stores it.
- **Keyboard**:
  - Enter goes to the person in the Timeline, Research to-do, Facts without a source,
    Places, Map, Gallery and Lifelines lists, not only a double-click.
  - Enter in the person window saves, instead of opening "Other names".
  - Shift with the arrow keys folds or unfolds the selected person's ancestors,
    descendants, or brothers and sisters, as the fold buttons do (listed under Keyboard
    shortcuts).
  - The tour takes the keys while it is shown: Escape skips it, Enter or the right arrow
    goes on, the left arrow back; nothing reaches the chart behind it.
  - Tab leaves the story, source note and DNA note boxes.
- **Large text**: Preferences and the DNA window scroll on a small screen instead of
  pushing OK and Cancel out of sight.
- **Screen readers** hear the chart's name and who is selected, the search box and the
  portrait.
- **Light and paper themes**: links and warnings are dark enough to read easily (WCAG AA).
- **More for keyboards and screen readers**:
  - Every menu item has an access letter of its own, in every language.
  - Tab follows the order things are seen in, in forms and in the side panel.
  - The side panel's links (parents, documents, photos with them) can be reached with
    Tab and followed with Enter.
  - The Menu key opens the selected person's menu.
  - Arrow keys move around the fan chart too.
  - Every field in every window has a name a screen reader can say.
- **Side panel**: a label too long for half the panel (German, Russian, large text) takes
  a whole row instead of being cut, and the "Add a relative" heading wraps.
- **Seeing things**: initials on a deceased person's card are always readable,
  checkboxes have an outline you can see in every theme, and Find duplicates marks a
  difference in bold with "≠", not only in colour.
- **"maiores fam.ged"** from a terminal imports the file into a new tree, as File >
  Import does.
- **OK with nothing changed** in the person, Documents, To do, Life story, DNA and
  Sources windows saves nothing and adds no undo step, so it can no longer rewrite what
  the window doesn't show: details from another program's file, or the odd shapes of a
  hand-edited one.
- **GEDCOM, the rest**:
  - A married name with other given names ("Mary /Jones/" beside "Mary Ann /Smith/") stays
    one of the other names: no "Mary Ann /Jones/" is made up on export.
  - Notes on events, citation pages, causes of death and source titles keep their line
    breaks, and long ones are written back on continuation lines.
  - Pictures and scans on an event (a baptism record on the baptism) or on a family (a
    wedding photo) come in as documents, a family's for both partners.
  - Zipped bundles (.zip with the file and its pictures, GEDCOM 7's .gdz) can be
    imported; nothing in them is written outside a private working folder.
  - The portrait's title is kept and written back, and lines kept from another program
    under a picture stay with that picture.
- **Combine** on a big tree: one combine of 60 people into 5,000 took 43 s, now 4 s.
- **Lists** sort in the order of the chosen language's alphabet: Croatian Č and Ć after
  C, Turkish Ç after C, Czech Ch after H.
- **Turkish dates** take the ending each number needs ("1960'tan", "1960'a",
  "1950'ye"), and typing them that way works.
- **A tree.json saved by an old Windows editor** in its own encoding opens, and is
  written back as UTF-8.
- **The .deb** carries the licences, in /usr/share/doc/maiores/copyright.

## Maiores 1.4.2

A safety release: what Maiores says now always matches what is on disk, and less can slip
out of a shared copy by accident.

- **Combine keeps everything**: sources, places and face marks from the other tree are
  saved along with the people (before, they could be lost while Combine reported
  success). A DNA raw file comes across with its test, and nothing is combined if the
  result would refer to something it doesn't have.
- **No more silent loss of unsaved changes**: if a change couldn't be saved (a full disk,
  say), closing the tree, opening another or opening the sample now asks first, just as
  quitting did.
- **Restore from backup** says so when the restored tree couldn't be saved, instead of
  reporting success.
- **A damaged tree can be recovered**: when a tree's file is damaged, Maiores offers its
  newest good backup. The damaged file is kept beside it; photos and documents stay. A
  disk error (say, while writing a backup) never leads to this offer. A tree whose file
  has gone missing but whose backups remain is offered them too.
- **GEDCOM export** makes its photo folder fresh each time, so a picture you have since
  hidden or marked private is never left beside the file. Only a folder Maiores marked as
  its own is replaced; if one of yours has the name, the photos go to `<name>_media-2`.
  If the export fails at any point, the previous file and folder are put back as they were.
  Exports and shared copies work in a private folder of their own and never delete anything else.
- **GEDCOM import** says how many documents couldn't be copied, treats a record marked
  confidential by another program as private, and keeps a document's date and kind.
- **Privacy**: someone of unknown status stays protected until their 100th birthday (by the
  full date, and by the latest year of a range); a name typed on a face is no longer shared
  when that person is hidden; merging duplicates keeps a document private if either copy
  was; photos and documents must stay inside the tree's own folder.
- Cancelling the Documents window removes the files it had just copied in.
- **A full disk is never mistaken for a missing file**: when copying a photo or document
  fails for lack of space, combining and importing stop with a clear message instead of
  reporting success without the file. Importing a GEDCOM file builds the new tree out of
  sight and leaves nothing half-made behind. A tree still opens when its routine backup
  can't be written.
- **Copy to share** is built in a hidden folder and appears only when complete, so an
  interrupted copy leaves nothing behind and trying again works. A file the tree refers
  to but can't find is left out of the copy, and the message says how many.
- **GEDCOM import** no longer records a death for someone born "between 1910 and 1940" or
  "after 1910": an uncertain birth date never makes someone deceased.
- **DNA**: a match's totals are added up again after each segment import; raw files of
  different reference builds are no longer compared; two matches with the same name stay
  two people (the company's kit id is used when given); amounts written 1.234,5 are read;
  a Windows-encoded match list is recognised whatever its length.
- **Editing keeps what the window doesn't show**: changing only the notes no longer drops a
  birth record that held just an address, or another name exactly as another program
  wrote it ("Elena /Case/ Jr."). Pressing OK in Sources keeps a source's publication
  details and abbreviation; correcting a citation's page keeps its transcription. Every
  editing window was checked on real trees: pressing OK without a change changes nothing.
- **Saving files**: pictures, PDFs, posters, books and web pages are written under a
  temporary name of their own and appear only when complete, so a failed save never
  leaves a half-written file or harms the previous one. Adding a DNA raw file says so
  when it can't be copied.
- **Couples**: after a partner is removed, a partner added later no longer inherits the
  old couple's marriage; merging duplicate spouses keeps the marriage date, place,
  witnesses and citations of either record.
- **Places**: renaming a place onto one already known merges the two: coordinates,
  region, old names and notes of both are kept.
- **Map**: places on both sides of the 180th meridian are fitted on screen together.
- **Books** list children in birth order ("about 1870" before 1900, undated last).
- **Memory and speed**: the Guide opens one window instead of a new one each time, the
  portrait cache has a size limit, and web pages of large trees are prepared about 100
  times faster.
- **Linux**: fixed a crash on closing under X11 on some systems (newer libxkbcommon);
  the program now uses the computer's own copy. The bundled `cryptography` library is
  updated to 50.0.2 for upstream security fixes.

## Maiores 1.4.1

- **Small laptop screens**: every window now fits a 1366 x 768 screen. Editing a person
  was taller than that, which put Save and Cancel below the edge of the screen; the form
  now scrolls and the buttons always stay in sight.
- **Help menu**: "Report a problem or idea" opens a short form on GitHub, and "Support
  Maiores" shows how to support the program (also linked from About).
- **Check dates** now warns about a birth or death after today (a mistyped 2090, say).
- Fixed: the first-run tour's "Don't show again" button was cut short, and its bubble
  could cover the card it was explaining; it now moves with the card.
- Fixed: choosing the tree that is already open from Open recent said it was open in
  another window.
- Date fields show only the whole examples that fit ("1921, 14.5.1921, about 1921");
  all of them appear when you point at the field.

## Maiores 1.4

**Family Tree is now Maiores** — Latin for "the ancestors". Same program, new name and a
new logo: an M drawn as a family, two ancestors whose lines meet at their child.
Settings carry over by themselves, your trees stay where they were, and the installer
updates the old program instead of adding a second one.

### New in 1.4

- **DNA**: record DNA tests and matches; import match lists and segment files from
  MyHeritage, FamilyTreeDNA, GEDmatch and 23andMe; see what a shared amount could mean
  and whether your tree agrees with it; a chromosome map; and compare two relatives' raw
  DNA files on your own computer. DNA never leaves your computer.
- **Nothing lost from other programs' files** (since 1.3.2): GEDCOM files from MyHeritage,
  Family Tree Maker, Ancestry, Findmypast and Gramps come in whole, and what the program
  does not use is written back unchanged.

## Earlier: 1.3.2

**Nothing lost from other programs' files.** A family tree file from MyHeritage, Family
Tree Maker, Ancestry, Findmypast or Gramps now comes in whole: what this program uses is
read, and everything else is kept with the person, family or source it belongs to and
written back unchanged when you export. Tested line by line on 38 real files.

- Newly understood: adoptive and step parents (Family Tree Maker, Ancestry), titles,
  nationality, immigration, census, confirmation, first communion, will, probate and
  other standard events; cause of death, age and address at an event; citation text;
  years before 1000; names exactly as written.
- The side panel shows the rest under "Other details from ...".
- Fixed: long titles and names split over two lines lost a space or a surname; a few
  kinds of repeated citations and names were dropped.

## Earlier: 1.3.1

Fixes one mistake in 1.3.0 and earlier: linking someone as a brother or sister when they
already stood with brothers and sisters whose parents weren't known left them with two
birth families. Now the whole group joins, each keeping their own link.

## Earlier: 1.3

Trees saved by 1.3 still open in 1.1 and 1.2. The one exception: a person given an
old-calendar date or a date range in 1.3 can be looked at in 1.2, but 1.2 won't save
changes to that person until it is updated.

### New in 1.3

- **Looks**: themes (dark, light, old paper, or as the computer is set), nicer cards
  with initials or silhouettes, square, rounded or curved lines, colours by family side
  or surname, soft shadows, a cross for those who have died. All in Preferences.
- **Family lines**: View > Highlight a family line (Ctrl+B), or right-click someone.
  Everyone born with that surname stays clear and is joined by gold lines; everyone else
  fades, as much as you like. "Only this line" shows just that line from its first known
  ancestor.
- **Birth surnames on cards**: "Vesna Radić, rođ. Lukač", with each language's own
  word (geb., née, z d., roz. ...). Preferences can show the birth surname instead.
- **Folding both ways**: on a line from someone's parents, ˄ folds everything above away
  and ˅ folds that level's aunts, uncles and cousins onto the direct line.
- **New views**: Lifelines (everyone's life on a timeline over the states and wars of the
  time), Gallery (every picture in one place), Statistics with charts.
- **Moving around**: toolbar pictures, gliding to a person, View > Overview map, and the
  start page shows your trees as cards.
- **Old calendars and date ranges**: Julian dates, double years (1700/01) and periods
  ("from 1920 to 1935").
- **Sharing**: File > Share as a web page (one file anyone can open in a browser, with an
  optional password), and Share on this network (relatives on the same Wi-Fi open it on a
  phone by scanning a code; it stops when you close it).
- **Importing from other programs**: married names from MyHeritage and Family Tree Maker
  come in as current and birth surnames. Very large files (tens of thousands of people)
  import, open and export quickly.

### Which file to download

| Computer | File |
|---|---|
| Windows 10 or 11 | `Maiores.1.4.1.setup.exe` |
| Mac with an Apple chip (M1 and newer) | `Maiores.1.4.1.Apple.chip.dmg` |
| Older Mac with an Intel chip | `Maiores.1.4.1.Intel.dmg` |
| Ubuntu, Debian, Mint | `maiores_1.4.1_amd64.deb` |

The `.zip` and `.tar.gz` files are the same program without an installer. The installers
are not signed yet: on Windows choose "More info" → "Run anyway"; on a Mac right-click the
app → "Open".
