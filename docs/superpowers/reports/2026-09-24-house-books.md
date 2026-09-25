# Working pages in the living room

Version 2.499.170 · `feature/living-room-atmosphere`

Home ledger and Program book now lean into close, overhead views of their
physical pages. Live household information is printed on the photographed paper.
The image and text share a coordinate plane through resizing and camera moves.
Phones move between left and right pages; reduced motion removes those moves.
Short landscape screens temporarily hide comparison controls and the chat bar
while reading a book, leaving room for the book controls and return button.

The ledger reuses `houseLife` and the existing home-board task projection:
owners, due dates, overdue markings, and its existing overdue/unclaimed ordering.
It displays up to six tasks and identifies when management contains more.
Management uses the existing parent-PIN flow; this presentation adds no task
completion or editing permission. Long entries scroll within the paper.

The program book reuses `programsCard`, its permitted celebrations and practice
window feeds, its lesson-scenes fetch, and its polling teardown. Today occupies
the left page and milestones/practice/celebrations the right. Longer lists have
page-turn controls. Failed refreshes retain existing data and offer retry rather
than displaying an empty schedule. No private program-record route is added.

Starting a session puts the existing lesson player on the right page. Its scene
types, voice, controls, and finish semantics remain shared. Escape closes the
session first and returns focus to its start button; leaving the book closes
the player and stops scene timers/audio. The House has no session-log listener,
so finishing here retains the existing behavior: it does not log practice.

Critters retains its preceding presentation. This remains an isolated hybrid
comparison, with the 3D room and its existing cards still available.

## Artwork

Four new assets were generated and inspected using built-in ImageGen:

- `chauffeur/static/house_hybrid/ledger-pages-day.png`
- `chauffeur/static/house_hybrid/ledger-pages-night.png`
- `chauffeur/static/house_hybrid/program-pages-day.png`
- `chauffeur/static/house_hybrid/program-pages-night.png`

The original ledger scene supplied continuity, followed by aligned lighting and
cover-color edits. Original assets remain intact. The [exact prompts](2026-09-24-house-books-prompts.md)
are recorded separately; no external generation API was used.

## Verification

Passed `test_house_books_live.py`, `test_house_hybrid_live.py`, and
`test_lesson_player_runtime.py`. Browser proof covers live data projection,
paper/image registration, desktop day/night, portrait and landscape touch,
pagination, PIN cancellation without a write, sessions in the book, Escape and
focus restoration, loading failures and empty states, timer/poll teardown,
the no-WebGL hybrid path, and switching back to 3D.

Desktop and phone screenshots were inspected in ignored `scratch/book-review/`
and `scratch/books-regression/`. The local preview uses isolated sample data;
its lessons use browser speech without connecting to real Music Assistant.
