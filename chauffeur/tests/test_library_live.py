"""Program library, live (spec 2026-10-19-program-library-design.md rev 3, section 5 "Live"; plan Task 6).

A checklist only: Task 6 writes the Playwright scenarios below this docstring, against a live
add-on run, with screenshots inspected in light and dark at phone width. A live test that needs
auth enforcement must not import tests/harness.py. No browser dialogs anywhere (showGlobalAlert,
promptConfirm, promptInput); buttons, not anchors, on the phone.

  1. Library page (/library, admin nav, Work group): one card per program with title, made-for,
     source chip, lesson count and the visible runners with their project as buttons.
  2. New program (adults): the create form shows "Everyone in the household will see this program
     as: {title}" above the title, the personal starting point is labelled "stays private to
     {name}'s run", and the age band defaults from the member's birthdate, else "any".
  3. Edit a program: inline lesson edit (title, steps, body or url, sessions, rotation label), drag
     to reorder, Add lesson; a refused editor sees "Only the person who made this program, or a
     parent, can change it."
  4. Archive (creator or parent): the card leaves the picker and stays on the library page.
  5. Delete: disabled while in use, with "In use by {names}'s project" for a runner the viewer
     sees, "In use by another project" otherwise; enabled and working once unused.
  6. Remove the current lesson: "{name} is on this lesson; her run moves to the next one." for a
     visible runner; a hidden runner is counted, never named.
  7. The picker (project page, Add a piece -> Program): library programs (title, made-for, visible
     runners; archived hidden) with "Make a new one" at the bottom; picking starts a proposed run.
  8. The run card (project page, record sheet, phone): "from the library: {title}" as a button and
     the current lesson by name under its phase ("Scales · Foundations"), never a count.
  9. The unresolved run card: "Its library program is missing" with Delete and "Pick a program".
 10. Next / Back ("Another session on this") on the run; "Reached it" on a non-final phase keeps
     the run going.
 11. Phone: More -> Library opens the library home (buttons only).
 12. Light and dark themes, phone width (16px gutter, no horizontal scroll), screenshots inspected.

Run from chauffeur/:  python tests/test_library_live.py   (Task 6)
"""
