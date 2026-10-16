"""Parity: every capability of the Threads, Missions and Programs pages lives in a
piece sheet, the Projects page or the Projects drawer before those pages retire
(front door spec §2 "Parity rule", slice 2, Task 6). One row per inventory line
(docs/superpowers/specs/2026-10-15-projects-front-door-inventory.md).

Run from chauffeur/:  python tests/test_projects_parity.py
"""
import os
import re


def check(cond, msg):
    if not cond: raise AssertionError(msg)


def bound(name, args=''):
    """A real event attribute, never a method definition or a suffix match."""
    return re.compile(r'(?<![\w:-])(?:@[\w:.-]+|x-on:[\w:.-]+|on[a-z]+)=["\']\s*'
                      + re.escape(name + '(' + args))


def within(start, end, *markers):
    """All markers must occur inside this form/control/builder, not elsewhere."""
    return ('within', start, end, markers)


def matches(marker, text):
    if isinstance(marker, re.Pattern):
        return bool(marker.search(text))
    if isinstance(marker, tuple):
        if marker[0] == 'within':
            _, start, end, children = marker
            if start not in text or end not in text.split(start, 1)[1]:
                return False
            return all(matches(m, text.split(start, 1)[1].split(end, 1)[0]) for m in children)
        return all(matches(m, text) for m in marker)
    return marker in text


def form(kind, *markers):
    return within('<form data-piece-form="' + kind + '"', '</form>', *markers)


# Dynamic options share these actual primary/quiet controls and the same
# delegated dispatch. Names/labels come from the server; the live tests prove
# option production. The table pins their rendered home AND the binding.
OPTION_CONTROLS = ('data-sit-act="${esc(next.id)}"', 'data-sit-act="${esc(o.id)}"',
                   'if (b.dataset.sitAct)', 'return act(s, option, ctx2);')


def options(*verbs):
    """Shared rendered controls plus each verb's frontend declaration."""
    return (OPTION_CONTROLS,) + tuple(re.compile(r"['\"]" + re.escape(v) + r"['\"]\s*:") for v in verbs)


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
    ('Threads: lanes', PJ, ':data-lane="ln.key"'),
    ('Threads: show closed, remembered', PJ, (bound('rememberClosed'), "localStorage.setItem('chf_projects_show_closed'")),
    ('Threads: card options through ACT', TP, 'x-html="window.Situations.cardHtml(s, cardCtx())"'),
    ('Threads: set or change the next step', TP, bound('submitAdvance')),
    ('Threads: draft a message', TP, bound('requestDraft')),
    ('Threads: look something up', TP, bound('submitResearch')),
    ('Threads: the asks ledger and reply options', SJ, 'class="sit-asks">${(s.asks || []).filter(a => a.state !== \'withdrawn\').map(a => askLine(a, ctx)).join(\'\')}</div>'),
    ('Threads: history with photos and readings', TP, 'x-for="(h, i) in (t.history || [])"'),
    ('Threads: missions opened from the thread', TP, 'x-for="mission in (threadMissions[t.id] || [])"'),
    ('Threads: send a draft', TP, bound('sendDraft')),
    ('Threads: add a note', TP, bound('submitNote')),
    ('Threads: photo', TP, bound('uploadPhoto')),
    ('Threads: work this', TP, bound('workThis')),
    ('Threads: edit', TP, bound('submitEdit')),
    ('Threads: done or drop', TP, bound('closeThread')),
    ('Threads: delete', TP, bound('deleteThread')),
    # Missions
    ('Missions: launch a goal with a tier', PF, 'name="tier"'),
    ('Missions: launch posts the tier', PJ, 'tier: f.tier'),
    ('Missions: the plan stepper', MP, 'x-html="window.Situations.planStepperHtml((missionById(s.id) || {}).plan)"'),
    ('Missions: card options through ACT', MP, 'x-html="window.Situations.cardHtml(s, cardCtx())"'),
    ('Missions: the transcript', MP, "include 'components/mission_transcript.html'"),
    ('Missions: answer or steer', MP, bound('sendAnswer')),
    ('Missions: drop', MP, bound('drop')),
    ('Missions: OK', MP, bound('ack')),
    ('Missions: delete', MP, bound('deleteMission')),
    ('Missions: proposal approve or dismiss', MT, bound('proposalAct')),
    ('Missions: release, submit, verify', MT, bound('releaseMission')),
    ('Missions: submit', MT, bound('submitMission')),
    ('Missions: verify', MT, bound('verifyMission')),
    ('Missions: transcript helpers', TP, 'await window.MissionTranscript.actProposal('),
    ('Missions: the keeper and anyone with a record but not its project', PJ, "api/projects/for/"),
    ('Missions: your work elsewhere', PJ, 'data-lane="elsewhere"'),
    # Programs
    ('Programs: propose (aim, whom, start, sessions, minutes, days, target)', PF, 'data-piece-form="program"'),
    ('Programs: propose posts the shape', PJ, 'preferred_days: f.preferred_days'),
    ('Programs: the Programs filter', PJ, 'data-lane-filter="programs"'),
    ('Programs: Part of', PP, "x-init=\"window.chfPartOf('program', p.id, $el, false)\""),
    ('Programs: why this one, also considered', PP, ('@click="whyOpen[p.id] = !whyOpen[p.id]"', 'x-text="whyText(p)"', 'x-for="r in (p.source.runners_up || [])"')),
    ('Programs: the lesson ladder and open the lesson', PP, bound('toggleLesson')),
    ('Programs: play a lesson', PP, bound('playLesson')),
    ('Programs: tonight windows and start session', PP, ('x-for="w in todayWindowsFor(p)"', bound('window.dispatchEvent', "new CustomEvent('lesson-player:open'"))),
    ('Programs: lesson editor add', PP, bound('addLessonRow')),
    ('Programs: lesson editor remove', PP, bound('removeLessonRow')),
    ('Programs: lesson editor reorder', PP, bound('moveLessonRow')),
    ('Programs: lesson editor save', PP, bound('saveLesson')),
    ('Programs: lesson regenerate', PP, bound('regenerateLesson')),
    ('Programs: another session or move on', PP, bound('moveUnit')),
    ('Programs: reached it', PP, bound('markMilestone')),
    ('Programs: not these times', PP, bound('startSlotEdit')),
    ('Programs: save the times', PP, bound('saveSlots')),
    ('Programs: plan without the book', PP, bound('replanWithoutBooks')),
    ('Programs: approve, claim this time', PP, bound('approveProgram')),
    ('Programs: edit a proposal', PP, bound('saveEdit')),
    ('Programs: look again', PP, bound('lookAgain')),
    ('Programs: dismiss', PP, bound('dismissProgram')),
    ('Programs: log a session', PP, bound('logSession')),
    ('Programs: pause', PP, bound('pauseProgram')),
    ('Programs: resume', PP, bound('resumeProgram')),
    ('Programs: finished', PP, bound('finishProgram')),
    ('Programs: re-shape the week', PP, bound('reshapeProgram')),
    ('Programs: drop', PP, bound('dropProgram')),
    # Phone surfaces stay (Decision 8)
    ('Phone: House threads', APP, "window.Situations.render(document.getElementById('house-threads-lane'), houseThreads,"),
    ('Phone: House thread note and photo', APP, (bound('houseAddThreadNote'), bound('houseAddThreadPhoto'), 'extraHtml: (s) => houseThreadExtras(s, canNote)')),
    ('Phone: the program card', APP, '${programs.map(p => renderProgramCard(p, commitmentsById)).join(\'\')}'),
    ('Phone: the session sheet', APP, bound('openSessionSheet')),
    ('Phone: a project piece in the action sheet', APP, "window.addEventListener('chf-record-sheet-open', (e) => openPieceSheet(e.detail))"),
    ('Phone: mission chat cards', APP, ("if (card.kind === 'mission_ask') return renderMissionAskCard(card);", bound('missionAskAct'))),
]


# Each input is checked inside its own form; a mission goal cannot accidentally
# satisfy the thread goal row, nor a proposal editor the new-program fields.
for kind, fields in (
    ('thread', ('title', 'goal', 'kind', 'owner_member_id', 'contact_id',
                'counterparty_name', 'counterparty_email', 'next_action', 'next_action_at')),
    ('mission', ('goal', 'tier')),
    ('program', ('title', 'for_member_id', 'starting_point', 'sessions_per_week',
                 'minutes', 'target_date')),
):
    for field in fields:
        PARITY.append((f'{kind.title()}: create field {field}', PF,
                       form(kind, re.compile(r'<(?:input|select|textarea)\b[^>]*\bname="' + field + '"'))))
    PARITY.append((f'{kind.title()}: submit the piece form', PF, form(kind, bound('createPiece'))))

PARITY += [
    ('Threads: owner choices include every member, including children', PF,
     form('thread', within('<select name="owner_member_id"', '</select>',
                          'x-for="m in members"', '<option :value="m.id" x-text="m.name">'))),
    ('Programs: preferred days toggle', PF, form('program', bound('togglePieceDay'))),
    ('Threads: quiet Argyle got it wrong', SJ,
     ('data-sit-act="unread:${esc(a.id)}"', '${esc(VERB_LABELS.unread)}', 'if (b.dataset.sitAct)')),
    ('Threads: About link', SJ, 'href="${esc((ctx.apiBase || \'\') + s.subject.link)}">${esc(s.subject.title)}</a>'),
    ('Threads: About link or change', SJ,
     (options('subject'), "if (option.verb === 'subject')", "await promptInput('What is this about?'")),
    ('Threads: About unlink', SJ,
     (options('subject'), 'option.payload.clear', "await promptConfirm('Unlink it?'")),
    ('Threads: cached Argyle next steps', SJ,
     (OPTION_CONTROLS, 'const next = s.next_step;', 'const opts = s.options || [];', 'data-source="argyle">${esc(s.status_note)}')),
    ('Threads: reply to their reply', SJ,
     (OPTION_CONTROLS, "draft: 'What should the message say?'", 'option.payload.text')),
    ('Threads: confirm or read their reply', SJ,
     (OPTION_CONTROLS, "advance: 'What is the next step?'", 'option.payload.next_action')),
    ('Threads: forwarded mission asks and steer', SJ,
     (options('answer'), "answer: 'Your answer'", '/^answer:mission:/.test(next.id', '${esc(next.label)}')),
    ('Threads: read-only forwarded question', SJ, 'class="sit-ask-line text-xs text-amber-200 mt-1">Argyle asks: ${esc(next.label)}'),
    ('Threads: I will handle it and Handled', SJ, options('own', 'done')),
    ('Threads: draft edit recipient', TP, 'x-model="draftText[t.id].to"'),
    ('Threads: draft edit subject', TP, 'x-model="draftText[t.id].subject"'),
    ('Threads: draft edit body', TP, 'x-model="draftText[t.id].body"'),
    ('Threads: Redraft', TP, re.compile(r'<button\s+@click="requestDraft\(t\)"[^>]*>Redraft</button>')),
    ('Threads: research answer', TP, 'x-text="researchResult[t.id].answer"'),
    ('Threads: research sources', TP, ('x-for="src in researchResult[t.id].sources"', ':href="src.url"')),
    ('Threads: ask ledger said yes', SJ, ('data-ask-answer="yes"', 'api/asks/${b.dataset.askId}/answer')),
    ('Threads: ask ledger said no', SJ, ('data-ask-answer="no"', 'api/asks/${b.dataset.askId}/answer')),
    ('Threads: ask ledger Sent it', SJ, ('data-ask-sent="${a.id}"', 'api/asks/${b.dataset.askSent}/sent')),
    ('Threads: withdraw an ask', SJ, ('data-ask-withdraw="${a.id}"', 'api/asks/${b.dataset.askWithdraw}/withdraw')),
    ('Threads: details goal', TP, 'x-text="t.goal"'),
    ('Threads: details next step and date', TP, ('x-text="t.next_action"', 'x-show="t.next_action_at"')),
    ('Threads: details counterparty, owner, kind', TP,
     ('x-text="counterpartyLabel(t)"', 'x-text="memberName(t.owner_member_id)"', 'x-text="t.kind"')),
    ('Threads: history photos', TP, ':src="window.chfAuthUrl ? window.chfAuthUrl(apiBase + \'api/media/\' + h.media_id)'),
    ('Threads: history reading', TP, 'x-text="h.reading ?'),
    ('Threads: open edit', TP, bound('openEdit')),
    ('Threads: open next step', TP, bound('openAdvance')),
    ('Threads: done', TP, bound('closeThread', "t, 'done'")),
    ('Threads: drop', TP, bound('closeThread', "t, 'dropped'")),
    ('Missions: Needs you lane', MP, ('x-for="g in groups"', 'x-text="g.label"', "label: '✋ Needs you'")),
    ('Missions: Running lane', MP, ('x-for="g in groups"', 'x-text="g.label"', "label: 'Running'")),
    ('Missions: History lane', MP, ('x-for="g in groups"', 'x-text="g.label"', "label: 'History'")),
    ('Missions: details tier and started', MP, 'x-text="(mission.tier === \'flash\' ? \'Flash\' : \'Pro\') + \' · started \' + fmtTs(mission.created_at)'),
    ('Missions: details finished', MP, "(mission.finished_at ? ' · finished ' + fmtTs(mission.finished_at) : '')\""),
    ('Missions: details error', MP, 'x-text="mission.error"'),
    ('Missions: browse report', MT, within('<template x-if="step.kind === \'browse\'">', "<template x-if=\"step.kind === 'ask' && step.name === 'release'\">",
                                        'x-text="(step.result_json || {}).text || \'\'"')),
    ('Missions: last screenshot', MT, ':src="window.chfAuthUrl(apiBase + \'api/missions/\' + mission.id + \'/shots/\''),
    ('Missions: per-turn shots', MT, ':href="window.chfAuthUrl(apiBase + \'api/missions/\' + mission.id + \'/shots/turn_\''),
    ('Missions: handoff Open it', MT, within('<template x-if="step.kind === \'ask\' && step.name === \'handoff\'">', '</template>',
                                          ':href="(step.result_json || {}).url"', '>Open it</a>')),
    ('Missions: read-only draft', MT, within('<template x-if="step.kind === \'draft\'">', "<template x-if=\"step.kind === 'ask' && !",
                                           '<blockquote', 'x-text="(step.result_json || {}).subject"', 'x-text="(step.result_json || {}).body"')),
    ('Missions: raw JSON', MT, 'x-text="stepResultText(step)"'),
    ('Missions: proposal dismiss', MT, bound('proposalAct', "mission.id, (step.result_json || {}).proposal_id, 'dismiss'")),
    ('Missions: plan Looks good, Leave out, Stop', SJ, options('approve_plan')),
    ('Missions: stage Do this, Carry on, Not this one, Skip, Stop', SJ, options('run_stage')),
    ('Missions: card Book it and verification options', SJ, options('submit', 'verify')),
    ('Missions: Book it and finish myself', MT, (bound('submitMission', "mission, 'approve'"), bound('submitMission', "mission, 'decline'"))),
    ('Missions: It went through, did not, still cannot tell', MT,
     (bound('verifyMission', "mission, 'confirmed'"), bound('verifyMission', "mission, 'failed'"), bound('verifyMission', "mission, 'unsure'"))),
    ('Missions: Share, Not these, Stop', MT,
     (bound('releaseMission', "mission, 'approve'"), bound('releaseMission', "mission, 'decline'"), bound('releaseMission', "mission, 'stop'"))),
    ('Missions: About and I will handle it / Handled', SJ, options('subject', 'own', 'done')),
    ('Programs: Proposed shelf', PP, ('x-for="sec in sections"', 'x-text="sec.label"', "label: 'Proposed'")),
    ('Programs: Under way shelf', PP, ('x-for="sec in sections"', 'x-text="sec.label"', "label: 'Under way'")),
    ('Programs: Done and dropped shelf', PP, ('x-for="sec in sections"', 'x-text="sec.label"', "label: 'Done & dropped ('", '@click="archiveOpen = !archiveOpen"')),
    ('Programs: cited source tier', PP, ('x-if="tier(p) === \'cited\' && p.source.plan_name"', ':href="p.source.url"')),
    ('Programs: generated source tier', PP, ('x-if="tier(p) === \'generated\'"', '>Made by the app</span>')),
    ('Programs: no-plan source tier', PP, ('x-if="tier(p) === \'none\'"', 'Practice time only — <span')),
    ('Programs: progress sessions and minutes', PP, ('x-text="(p.progress.sessions || 0)', 'x-text="(p.progress.minutes || 0)')),
    ('Programs: current phase', PP, 'x-text="p.progress.phase.milestone || p.progress.phase.name"'),
    ('Programs: phase steps', PP, ('x-for="ph in (p.phases || [])"', 'x-for="st in (ph.steps || [])"', 'x-text="st"')),
    ('Programs: session rotation', PP, ('x-for="sess in (ph.rotation || [])"', 'x-for="st in (sess.steps || [])"')),
    ('Programs: Next time', PP, 'x-text="ph.progression"'),
    ('Programs: Done when', PP, 'x-text="ph.milestone"'),
    ('Programs: ladder Open the lesson', PP, ('x-for="u in (ph.units || [])"', ':href="u.url"')),
    ('Programs: kit thread', PP, 'x-text="\'Kit thread: \' + footprints[p.id].thread"'),
    ('Programs: calendar target', PP, 'x-text="footprints[p.id].event ? (\'Calendar target: \''),
    ('Programs: finishing a lesson logs the session', PP,
     (bound('onLessonDone'), "this.logSession(p, { source: 'asked', slot_date: w.date })")),
    ('Programs: open proposal editor', PP, bound('startEdit')),
    ('Programs: edit preferred days', PP, bound('toggleEditDay')),
    ('Programs: add a practice window', PP, bound('addSlot')),
    ('Programs: remove a practice window', PP, '@click="slotDraft[p.id].splice(i, 1)"'),
    ('Programs: another session', PP, bound('moveUnit', "p, 'stay'")),
    ('Programs: move on', PP, bound('moveUnit', "p, 'next'")),
    ('Programs: lesson editor move up', PP, bound('moveLessonRow', 'p, ph, label, i, -1')),
    ('Programs: lesson editor move down', PP, bound('moveLessonRow', 'p, ph, label, i, 1')),
    ('Programs: lesson editor say/do text', PP, 'x-model="row.text"'),
    ('Programs: lesson editor check question', PP, 'x-model="row.ask"'),
    ('Programs: lesson editor show caption', PP, 'x-model="row.caption"'),
    ('Programs: lesson editor beat type', PP, 'x-model="lessonAddType[lessonKey(p, ph, label)]"'),
    ('Phone: program Coming up sessions', APP, within('function renderProgramCard(', 'function renderProgramsSection(', bound('openSessionSheet'))),
    ('Phone: program Open the lesson', APP, within('function renderProgramCard(', 'function renderProgramsSection(', '>Open the lesson</a>')),
    ('Phone: program Yes it happened / Did it happen', APP, bound('askProgramSession')),
    ('Phone: program Add a session', APP, bound('addProgramSession')),
    ('Phone: program Reached it', APP, bound('markProgramMilestone')),
    ('Phone: session Done', APP, ('<button data-done ', "overlay.querySelector('[data-done]')", 'done.onclick = async () =>')),
    ('Phone: session Start lesson', APP, ('<button data-start ', "overlay.querySelector('[data-start]')", 'start.onclick = async () =>')),
    ('Phone: My Day program rows', APP,
     ('data-myday-program="${mfEscape(p.id)}"', 'const programItems = myDayProgramItems(parts, dateStr);', '.concat(programItems.timed)', '${programItems.rest}')),
    ('Phone: Drives Today program rows', APP,
     ('? myDayProgramItems(dateStr === todayStr() ? practiceParts : dated, dateStr)', 'data-myday-program="${mfEscape(p.id)}"')),
    ('Phone: Family practice card', APP, within('if (card.isPractice) {', 'if (card.isTrip)', bound('openSessionSheet'), 'action:`openSessionSheet(')),
    ('Phone: More My programs', 'static/pwa_shell.js',
     ("items.push({id: 'programs', title: 'My programs'", 'items.map(pwaFeatureButton)', 'button.onclick = item.run', "setView(pwaChildStage() ? 'myday' : pwaAllowed('drives') ? 'drives' : 'myday')")),
    ('Phone: child My programs', 'static/pwa_child_shell.js', '<section class="child-programs"><h2>My programs</h2>${programItems.rest}</section>'),
    ('Phone: Projects tab', APP, "include 'components/projects_page.html'"),
    ('Phone: interview question controls', APP, ('data-plan-question><label', 'data-q="${mfEscape(q.key)}"', 'details += (card.questions || []).map(q => renderPlanQuestion(q, canAct))', '<select ${attrs}', '<input type="${type}" ${attrs}>')),
    ('Phone: interview You decide', APP, ('<input type="checkbox" data-you-decide=', "ev.target.matches('[data-you-decide]')")),
    ('Phone: interview Send answers', APP, ('<button data-plan-answers=', 'api/missions/${encodeURIComponent(button.dataset.planAnswers)}/plan/answers')),
    ('Phone: mission done Copy drafts', APP,
     ('<button data-copy ', "if (card.kind === 'mission_done') return renderMissionDoneCard(card);", 'await navigator.clipboard.writeText(text)')),
    ('Phone: mission done Share drafts', APP, ('<button data-share ', 'await navigator.share({ text })')),
    ('Phone: action-proposal cards', APP,
     ("if (card.kind !== 'action_proposal') return '';", bound('actOnProposal'))),
    ('Phone: mission handoff', APP, within("if (card.ask === 'handoff'", 'const badge', 'href="${mfEscape(card.url)}"', '>Open it</a>')),
]


S = T + '{}_settings.html'
PARITY += [
    ('Settings: thread stall days', S.format('threads'),
     within("{% call settings_section('threads-settings',", '{% endcall %}',
            'x-model.number="s.thread_stall_days"', bound('saveStallDays'))),
    ('Settings: missions on, paid key, pool, caps', S.format('missions'),
     within("{% call settings_section('missions-settings',", '{% endcall %}',
            'x-model="s.missions_enabled"', 'x-model="s.model_pool_pro"',
            'x-model.number="s.mission_cap_launch"', 'x-model.number="s.mission_step_cap"',
            'x-model.number="s.mission_cap_pro_calls"', bound('save'), bound('savePaidKey'))),
    ('Settings: remove the paid key', S.format('missions'), bound('removePaidKey')),
    ('Settings: browser and check the network', S.format('missions'),
     within("{% call settings_section('browse',", '{% endcall %}', bound('save'), bound('netcheck'))),
    ('Settings: the household contact card', S.format('missions'),
     within("{% call settings_section('contact-card',", '{% endcall %}',
            'x-model="s.contact_first_name"', bound('save'))),
    ('Settings: programs on and generation', S.format('programs'),
     within("{% call settings_section('programs-settings',", '{% endcall %}',
            'x-model="s.programs_enabled"', 'x-model="s.programs_generate_enabled"', bound('saveProgramSettings'))),
    ('Settings: lessons and write lessons now', S.format('programs'),
     within('<section id="lessons"', '</section>',
            'x-model="s.program_lessons_enabled"', bound('saveProgramSettings'), bound('runLessonSweep'))),
    ('Settings: play a swept slot', S.format('programs'),
     within('<section id="lessons"', '</section>', bound('playSweepSlot', 'slot'))),
    ('Settings: pacing', S.format('programs'),
     within("{% call settings_section('programs-pacing',", '{% endcall %}',
            'x-model.number="s.programs_research_pages"', bound('saveProgramSettings'))),
    ('Settings: one Projects drawer', T + 'projects_admin.html',
     within("{% call settings_drawer('projects',", '{% endcall %}',
            "include 'components/missions_settings.html'", "include 'components/threads_settings.html'",
            "include 'components/programs_settings.html'")),
    ('Settings: missions off, turn on', T + 'projects_admin.html',
     re.compile(r"\{\{ settings_off\('[^']*', 'projects', 'missions-settings', 'loaded && !s.missions_enabled'\) \}\}")),
    ('Settings: programs off, turn on', T + 'projects_admin.html',
     re.compile(r"\{\{ settings_off\('[^']*', 'projects', 'programs-settings', 'settingsLoaded && !s.programs_enabled'\) \}\}")),
]


HIDE, END_HIDE = '{# sheet:hide #}', '{# /sheet:hide #}'
HIDDEN = re.compile(re.escape(HIDE) + r'(.*?)' + re.escape(END_HIDE), re.S)
EVENT = re.compile(r"(?:@[\w:.-]+|x-on:[\w:.-]+|on[a-z]+)=([\"'])(.*?)\1", re.S)
CHROME = {
    TP: {'createThread', 'creating', 'rememberClosed'},
    MP: {'launch'},
    PP: {'proposeProgram', 'toggleDay', 'creating'},
}


def _read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as source:
        return source.read()


def _no_comments(text):
    # Comments cannot provide a rendered control (onLessonDone's doc, etc.).
    text = re.sub(r'<!--.*?-->|\{#.*?#\}', '', text, flags=re.S)
    text = re.sub(r'^\s*/\*.*?\*/', '', text, flags=re.M | re.S)
    return re.sub(r'^\s*//[^\n]*', '', text, flags=re.M)


def _sheet_guards(text, path):
    """Complete, ordered regions and the Jinja conditions they annotate."""
    markers = re.findall(r'\{# /?sheet:hide #\}', text)
    check(markers and markers == [HIDE, END_HIDE] * (len(markers) // 2),
          f'{path}: balanced, non-nested sheet-hidden regions required')
    stack = []
    for token in re.finditer(r'\{%\s*(if\s+.*?|elif\s+.*?|else|endif)\s*%\}', text):
        statement = token[1].strip()
        if statement.startswith('if '):
            stack.append((token, []))
        elif statement == 'endif':
            check(bool(stack), f'{path}: unmatched endif')
            opening, branches = stack.pop()
            condition = opening[1].strip()[3:]
            if '_sheet' not in condition:
                continue
            if condition == 'not _sheet':
                check(not branches and text[opening.end():].lstrip().startswith(HIDE)
                      and text[token.end():].lstrip().startswith(END_HIDE),
                      f'{path}: unmarked sheet hide: {opening[0]}')
            else:
                # Existing positive guards ADD a sheet event hook/empty state.
                # Pin exact bodies, including the non-sheet tab-count branch;
                # no new unmarked conditional can conceal a record control.
                check(condition == '_sheet', f'{path}: unreviewed sheet condition: {condition}')
                body = text[opening.end():token.start()].strip()
                hook = '@chf-record-sheet.window="onSheet($event.detail)"'
                allowed = {hook}
                if path == TP:
                    allowed.add(hook + "{% else %}x-effect=\"window.chfSetPageTabCount && window.chfSetPageTabCount('threads', groups[0].items.length)\"")
                    allowed.add('<p class="text-xs text-gray-500 italic px-1" x-show="only && loadedOnce && !groups.length">That conversation isn’t here, or isn’t yours to see.</p>')
                if path == PP:
                    allowed.add(hook + "{% else %}x-effect=\"window.chfSetPageTabCount && window.chfSetPageTabCount('programs', programs.filter(p => p.state === 'proposed' && canAct(p)).length)\"")
                check(body in allowed, f'{path}: unmarked/unreviewed positive sheet conditional: {body}')
        else:
            check(bool(stack), f'{path}: unmatched {statement}')
            stack[-1][1].append(token)
    check(not stack, f'{path}: unclosed Jinja condition')


def _rendered(path):
    """Sheet-visible source; malformed/unmarked hides fail closed."""
    text = _read(path)
    if path in CHROME:
        _sheet_guards(text, path)
    return _no_comments(HIDDEN.sub('', text))


def scenario_every_inventory_line_has_a_home():
    rendered = {path: _rendered(path) for path in {p for _, p, _ in PARITY}}
    missing = [(line, path, marker) for line, path, marker in PARITY if not matches(marker, rendered[path])]
    check(not missing, "no home for: " + '; '.join(f"{l} ({p}: {m})" for l, p, m in missing))


def scenario_the_hidden_regions_are_only_chrome():
    for path, allowed in CHROME.items():
        text = _read(path)
        _sheet_guards(text, path)
        hidden = _no_comments(''.join(HIDDEN.findall(text)))
        handlers = set()
        for _, expression in EVENT.findall(hidden):
            # Include every call/assignment, not only the first statement.
            code = re.sub(r"(['\"]).*?\1", '', expression)
            names = re.findall(r'(?<![\w$])([\w$]+(?:\.[\w$]+)*)\s*(?:\(|=(?!=)|\+\+|--)', code)
            check(bool(names), f'{path}: unrecognized hidden event: {expression}')
            handlers.update(names)
        check(handlers == allowed,
              f'{path}: hidden handlers differ: unexpected={sorted(handlers - allowed)}, missing={sorted(allowed - handlers)}')


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
