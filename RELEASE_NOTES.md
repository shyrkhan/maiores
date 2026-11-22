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
