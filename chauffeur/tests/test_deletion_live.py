"""Projects delete, the UI, live in a browser (spec rev 3 section 7; plan Task 7). PLACEHOLDER.

Task 7 writes these scenarios with the UI. This file must NOT import tests/harness.py: the live tests
need auth enforcement on (memory: auth-flip-aftermath).

Scenarios to write (each screenshot in light and dark at phone width, inspected):
  * project Delete names its pieces and deletes: the red Delete beside Drop, for the owner or a parent
    who sees the project; one promptConfirm listing every thread, mission and program by title, ending
    "Linked trips, lists and events stay."; the project vanishes on return;
  * a piece's Delete (thread, mission, program: the same preview and confirm for that record) and
    Remove (every other linked kind: projects.remove_piece, unlink only);
  * folding when the thread card renders: a mission launched from a thread in the same project sits
    inside that thread's card, with its open and Delete;
  * standalone fallback for a keeper-only viewer, and for a mission whose thread piece is missing;
  * the phone thread sheet lists every mission (no five cap), each with open and Delete;
  * a child owner gets "Ask a parent to delete this." when the project holds something she cannot see;
  * after a `changed` answer the UI shows showGlobalAlert and previews again; no browser dialogs.

Run from chauffeur/:  python tests/test_deletion_live.py
"""

if __name__ == '__main__':
    print('test_deletion_live.py is a placeholder until Task 7 (the UI) writes its scenarios.')
