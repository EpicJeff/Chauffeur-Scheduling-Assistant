import { request, checkpoint, plain, report } from './api.js';
import { pauseWords, sentence } from './words.js';

const FIRST_LOOK = 'First look at the outline while the drawings are read.';

export function createPanel({ afterSay, acceptPause }) {
  const log = document.getElementById('editor-log');
  const messages = document.getElementById('editor-messages');
  const scroll = document.getElementById('editor-panel-scroll');
  const quick = document.getElementById('editor-quick-replies');
  const form = document.getElementById('editor-say');
  const input = document.getElementById('editor-message');
  const send = form.querySelector('button');
  const history = [];
  const seen = new Set();
  const reasons = new Map(), pauses = new Set();
  const firstLooks = new Map();
  let buildId = null, busy = false, selection = null, readOnly = false;

  function message(text, speaker = 'argyle') {
    if (!text) return;
    const node = document.createElement('p'); node.className = 'editor-message';
    node.dataset.speaker = speaker; node.textContent = plain(text); messages.append(node);
    scroll.scrollTop = scroll.scrollHeight;
  }
  async function say(text) {
    text = text.trim();
    if (!text || busy || readOnly) return;
    busy = true; send.disabled = true;
    quick.querySelectorAll('button').forEach(button => { button.disabled = true; });
    message(text, 'you'); input.value = '';
    try {
      if (text.toLowerCase() === 'keep going' && await acceptPause?.()) return;
      const result = await request('say', 'POST', { message: text, history: history.slice(-20), selection: selection?.pieceId || null });
      history.push({ role: 'user', content: text }, { role: 'assistant', content: result.reply || '' });
      message(result.reply || 'Done.');
      await afterSay(result).catch(report);
    } catch (error) {
      if (error.status === 409 && error.detail?.checkpoint) {
        const summary = error.detail.summary;
        const reply = Array.isArray(summary) && summary.length ? summary.join('\n')
          : 'The spending checkpoint stopped this turn.';
        history.push({ role: 'user', content: text }, { role: 'assistant', content: reply });
        message(reply);
        try {
          await checkpoint(error.detail);
          await afterSay(error.detail);
        } catch (failure) { report(failure); }
        return;
      }
      if (!error.cancelled) {
        input.value = text;
        report(error);
      }
    } finally {
      busy = false; send.disabled = readOnly;
      quick.querySelectorAll('button').forEach(button => { button.disabled = readOnly; });
    }
  }
  const submit = event => { event.preventDefault(); say(input.value).catch(report); };
  form.addEventListener('submit', submit);
  function replies(labels = ['Keep going', 'What needs checking?']) {
    quick.replaceChildren();
    labels.forEach(label => {
      const button = document.createElement('button'); button.type = 'button';
      button.textContent = plain(label); button.disabled = busy || readOnly;
      button.addEventListener('click', () => say(label).catch(report)); quick.append(button);
    });
  }
  replies();
  return {
    message, say, replies,
    clearSelection() { selection = null; },
    focusSelection(item, label) {
      selection = item;
      input.value = `About ${label}: `;
      input.focus(); input.setSelectionRange(input.value.length, input.value.length);
    },
    readOnly(value) {
      readOnly = value; input.disabled = value; send.disabled = busy || value;
      quick.querySelectorAll('button').forEach(button => { button.disabled = busy || value; });
    },
    dispose() { form.removeEventListener('submit', submit); },
    events(build) {
      if (buildId !== build.id) { seen.clear(); reasons.clear(); firstLooks.clear(); pauses.clear(); log.replaceChildren(); buildId = build.id; }
      for (const event of build.events || []) {
        if (seen.has(event.seq)) continue;
        seen.add(event.seq);
        if (event.type === 'ghost' && event.why === FIRST_LOOK) {
          if (!firstLooks.has(event.step)) {
            const line = document.createElement('li'); line.textContent = FIRST_LOOK; log.append(line);
            firstLooks.set(event.step, line);
          }
          continue;
        }
        if (event.type === 'settled') {
          firstLooks.get(event.step)?.remove(); firstLooks.delete(event.step);
        }
        if (event.type === 'log' && event.text === FIRST_LOOK) continue;
        if (event.type === 'ghost' && event.why) {
          const name = event.piece?.id?.split(':')[0];
          const kind = name === 'roof' ? 'roof section' : ['wall', 'opening', 'room'].includes(name) ? name : 'piece';
          const reason = event.why.replace(/^This opening is /i, '').replace(/^Wall ends are /i, '').replace(/\.$/, '');
          const key = `${event.step}:${reason}`;
          let row = reasons.get(key);
          if (!row) {
            const node = document.createElement('li'); log.append(node);
            row = { node, ids: new Set(), kinds: new Set() }; reasons.set(key, row);
          }
          row.ids.add(event.piece.id);
          row.kinds.add(kind);
          const n = row.ids.size;
          const noun = row.kinds.size === 1 ? kind : 'piece';
          const why = n === 1 ? reason : reason
            .replace(/\bThis (opening|roof section|porch roof|interior wall|wall|room) (extends|does|has|is|needs)\b/g,
              (_, subject, verb) => `These ${subject}s ${{ extends: 'extend', does: 'do', has: 'have', is: 'are', needs: 'need' }[verb]}`)
            .replace(/\bits floor's outline\b/g, "their floors' outlines")
            .replace(/\bits bearing walls\b/g, 'their bearing walls')
            .replace(/\bits wall span\b/g, 'their wall span')
            .replace(/\bbeneath it\b/g, 'beneath them')
            .replace(/\bthis opening\b/g, 'these openings')
            .replace(/\bThe opening was\b/g, 'The openings were')
            .replace(/\bthis floor\b/g, 'these floors')
            .replace(/^This floor's/, "These floors'")
            .replace(/^The upper floor extends/, 'The upper floors extend')
            .replace(/^The upper floor is/, 'The upper floors are')
            .replace(/\bthe floor below\b/g, 'the floors below');
          row.node.textContent = `${n} ${noun}${n === 1 ? '' : 's'} ${n === 1 ? 'needs' : 'need'} checking: ${why}`;
        } else if (event.type === 'log') {
          // Older build records also carry raw ghost reasons as log events.
          // The summary above owns that copy across poll batches too.
          const reason = (event.text || '').replace(/^This opening is /i, '').replace(/^Wall ends are /i, '').replace(/\.$/, '');
          if ([...reasons.keys()].some(key => key.startsWith(`${event.step}:`) && key.endsWith(`:${reason}`))) continue;
          const line = document.createElement('li'); line.textContent = plain(event.text); log.append(line);
        } else if (event.type === 'question') {
          if (!(build.pause?.kind === 'draft' && event.step === build.pause.step
            && event.text === build.pause.why)) message(event.text);
        }
        else if (event.type === 'error') report(new Error(event.text));
      }
      if (['paused', 'stopped', 'failed'].includes(build.state)) {
        for (const line of firstLooks.values()) line.remove();
        firstLooks.clear();
      }
      if (build.state === 'paused' && build.pause) {
        const pause = build.pause, key = `${build.id}:${pause.step}:${pause.why}:${pause.confidence}`;
        if (!pauses.has(key)) {
          pauses.add(key);
          if (pause.kind === 'draft') {
            message(`${sentence(pause.why)} Choose Try again to read the drawings again, or Stop.`);
            replies(['What needs checking?']);
            return;
          }
          message(`${pauseWords(pause)} ${pause.kind === 'level_registration' ? 'Does the blue outline line up with the floor below? Use Drag or Pin 2 points to adjust it, then Looks right.'
            : pause.kind === 'lot_placement' ? 'Is the house in the right place? Drag or turn it, then choose Looks right.'
              : 'Does the blue outline match your drawing? Use Drag to slide it, then Looks right.'}`);
          replies(['Keep going', 'What needs checking?']);
        }
      }
    },
    reset() { seen.clear(); reasons.clear(); firstLooks.clear(); pauses.clear(); log.replaceChildren(); messages.replaceChildren(); history.length = 0; buildId = null; },
  };
}
