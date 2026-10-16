"""Parity: every capability of the Threads, Missions and Programs pages lives in a
piece sheet, the Projects page or the Projects drawer before those pages retire
(front door spec §2 "Parity rule", slice 2, Task 6). One row per inventory line
(docs/superpowers/specs/2026-10-15-projects-front-door-inventory.md).

Run from chauffeur/:  python tests/test_projects_parity.py
"""
import os
import re

from harness import check  # noqa: F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = 'templates/components/'
TP, MP, PP, MT = T + 'threads_page.html', T + 'missions_page.html', T + 'programs_page.html', T + 'mission_transcript.html'
PJ, PF, APP = T + 'projects_page.html', T + 'project_piece_forms.html', 'templates/app.html'
SJ, MTJ = 'static/situations.js', 'static/mission_transcript.js'

# (inventory line, file, marker)
PARITY = [
    # Threads
    ('Threads: create (title, goal, kind, owner, contact or name+email, first next action and date)', PF, 'data-piece-form="thread"'),
    ('Threads: create posts the counterparty and next action', PJ, 'counterparty_name: f.counterparty_name'),
    ('Threads: lanes', PJ, 'data-lane'),
    ('Threads: show closed, remembered', PJ, 'chf_projects_show_closed'),
    ('Threads: card options through ACT', TP, 'window.Situations.cardHtml(s, cardCtx())'),
    ('Threads: set or change the next step', TP, 'submitAdvance('),
    ('Threads: draft a message', TP, 'requestDraft('),
    ('Threads: look something up', TP, 'submitResearch('),
    ('Threads: the asks ledger and reply options', SJ, 'asks'),
    ('Threads: history with photos and readings', TP, 't.history'),
    ('Threads: missions opened from the thread', TP, 'threadMissions[t.id]'),
    ('Threads: send a draft', TP, 'sendDraft('),
    ('Threads: add a note', TP, 'submitNote('),
    ('Threads: photo', TP, 'uploadPhoto('),
    ('Threads: work this', TP, 'workThis('),
    ('Threads: edit', TP, 'submitEdit('),
    ('Threads: done or drop', TP, 'closeThread('),
    ('Threads: delete', TP, 'deleteThread('),
    # Missions
    ('Missions: launch a goal with a tier', PF, 'name="tier"'),
    ('Missions: launch posts the tier', PJ, 'tier: f.tier'),
    ('Missions: the plan stepper', MP, 'planStepperHtml'),
    ('Missions: card options through ACT', MP, 'window.Situations.cardHtml(s, cardCtx())'),
    ('Missions: the transcript', MP, "include 'components/mission_transcript.html'"),
    ('Missions: answer or steer', MP, 'sendAnswer('),
    ('Missions: drop', MP, 'drop('),
    ('Missions: OK', MP, 'ack('),
    ('Missions: delete', MP, 'deleteMission('),
    ('Missions: proposal approve or dismiss', MT, 'proposalAct('),
    ('Missions: release, submit, verify', MT, 'releaseMission('),
    ('Missions: submit', MT, 'submitMission('),
    ('Missions: verify', MT, 'verifyMission('),
    ('Missions: transcript helpers', MTJ, 'actProposal'),
    ('Missions: the keeper and anyone with a record but not its project', PJ, "api/projects/for/"),
    ('Missions: your work elsewhere', PJ, 'data-lane="elsewhere"'),
    # Programs
    ('Programs: propose (aim, whom, start, sessions, minutes, days, target)', PF, 'data-piece-form="program"'),
    ('Programs: propose posts the shape', PJ, 'preferred_days: f.preferred_days'),
    ('Programs: the shelf', PJ, 'data-lane-filter="programs"'),
    ('Programs: Part of', PP, 'chfPartOf('),
    ('Programs: why this one, also considered', PP, 'whyText('),
    ('Programs: the lesson ladder and open the lesson', PP, 'toggleLesson('),
    ('Programs: play a lesson', PP, 'playLesson('),
    ('Programs: tonight windows and start session', PP, 'todayWindowsFor('),
    ('Programs: lesson editor add', PP, 'addLessonRow('),
    ('Programs: lesson editor remove', PP, 'removeLessonRow('),
    ('Programs: lesson editor reorder', PP, 'moveLessonRow('),
    ('Programs: lesson editor save', PP, 'saveLesson('),
    ('Programs: lesson regenerate', PP, 'regenerateLesson('),
    ('Programs: another session or move on', PP, 'moveUnit('),
    ('Programs: reached it', PP, 'markMilestone('),
    ('Programs: not these times', PP, 'startSlotEdit('),
    ('Programs: save the times', PP, 'saveSlots('),
    ('Programs: plan without the book', PP, 'replanWithoutBooks('),
    ('Programs: approve, claim this time', PP, 'approveProgram('),
    ('Programs: edit a proposal', PP, 'saveEdit('),
    ('Programs: look again', PP, 'lookAgain('),
    ('Programs: dismiss', PP, 'dismissProgram('),
    ('Programs: log a session', PP, 'logSession('),
    ('Programs: pause', PP, 'pauseProgram('),
    ('Programs: resume', PP, 'resumeProgram('),
    ('Programs: finished', PP, 'finishProgram('),
    ('Programs: re-shape the week', PP, 'reshapeProgram('),
    ('Programs: drop', PP, 'dropProgram('),
    # Phone surfaces stay (Decision 8)
    ('Phone: House threads', APP, 'renderHouseThreads'),
    ('Phone: House thread note and photo', APP, 'houseThreadExtras('),
    ('Phone: the program card', APP, 'renderProgramCard('),
    ('Phone: the session sheet', APP, 'openSessionSheet('),
    ('Phone: a project piece in the action sheet', APP, 'openPieceSheet('),
    ('Phone: mission chat cards', APP, 'renderMissionAskCard('),
]


def _rendered(path):
    """The file as a sheet renders it: sheet-hidden regions removed."""
    text = open(os.path.join(ROOT, path), encoding='utf-8').read()
    return re.sub(r'\{# sheet:hide #\}.*?\{# /sheet:hide #\}', '', text, flags=re.S)


def scenario_every_inventory_line_has_a_home():
    missing = [(line, path, marker) for line, path, marker in PARITY if marker not in _rendered(path)]
    check(not missing, "no home for: " + '; '.join(f"{l} ({p}: {m})" for l, p, m in missing))


def scenario_the_hidden_regions_are_only_chrome():
    for path in (TP, MP, PP):
        text = open(os.path.join(ROOT, path), encoding='utf-8').read()
        opened, closed = text.count('{# sheet:hide #}'), text.count('{# /sheet:hide #}')
        check(opened == closed and opened >= 1, f"{path}: balanced sheet-hidden regions ({opened}/{closed})")
        hidden = ''.join(re.findall(r'\{# sheet:hide #\}(.*?)\{# /sheet:hide #\}', text, flags=re.S))
        for marker in ('cardHtml(', 'sendAnswer(', 'approveProgram(', 'submitNote('):
            check(marker not in hidden, f"{path}: a record control hides in a sheet-hidden region: {marker}")


def scenario_the_sheets_mount_the_components():
    sheet = open(os.path.join(ROOT, T + 'record_sheet.html'), encoding='utf-8').read()
    for comp in ('threads_page.html', 'missions_page.html', 'programs_page.html'):
        check(f"include 'components/{comp}'" in sheet, f"the record sheet mounts {comp}")
    check('{% set sheet_mode = true %}' in sheet, "in sheet mode")
    for host in ('templates/work.html', 'templates/projects.html'):
        check("components/projects_admin.html" in open(os.path.join(ROOT, host), encoding='utf-8').read(), f"{host} hosts the sheet")


SCENARIOS = [scenario_every_inventory_line_has_a_home, scenario_the_hidden_regions_are_only_chrome, scenario_the_sheets_mount_the_components]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
