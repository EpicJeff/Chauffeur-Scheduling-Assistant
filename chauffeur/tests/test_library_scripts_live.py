"""Program-owned lesson scripts, live (spec 2026-10-20-lesson-depth-design.md rev 3, sections 8 and 9 "Live").

A checklist only: Task 5 writes the Playwright scenarios below this docstring, against a live
add-on run, with screenshots inspected in light and dark at phone width. A live test that needs
auth enforcement must not import tests/harness.py. No browser dialogs anywhere (showGlobalAlert,
promptConfirm, promptInput); buttons, not anchors, on the phone.

  1. Library page: each lesson row shows a chip (`no script yet` / `ready · about 12 min` /
     `failed · {note}` / `writing…`), Play for everyone, Edit and Regenerate for `can_edit`.
  2. Card header: Write lessons for `can_edit`; `Writing lessons · 2 of 4` when the job map holds
     an entry.
  3. Edit: add a teach row, fill title, text, two examples (`Dó | pt-BR`), speak; Save; reload;
     the fields come back; the thirteenth row on a 30-minute profile is accepted; the thirty-first
     refused.
  4. Play opens the player in preview with `{name}` filled with the viewer's name.
  5. Rhythms (`/rhythms`): a library run shows `Scripts live in the library: Learn piano` and no
     editor; an unconverted run still shows the editor.
  6. Settings drawer Lessons tab: `lesson_pool` select present; no Write lessons now; no report.
  7. Phone More → Library: chips and Play only; buttons, not anchors.
  8. Light and dark at phone width; screenshots inspected.

Run from chauffeur/:  python tests/test_library_scripts_live.py   (LIBRARY_SHOTS=<dir> for screenshots)
"""
import atexit
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = tempfile.mkdtemp(prefix='chauffeur_library_scripts_live_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))

from services import storage  # noqa: E402,F401  (Task 5 seeds through it)

TOKENS = {}
SHOTS = os.environ.get('LIBRARY_SHOTS')


if __name__ == '__main__':
    print('test_library_scripts_live: checklist only (Task 5 writes the scenarios)')
    sys.exit(0)
