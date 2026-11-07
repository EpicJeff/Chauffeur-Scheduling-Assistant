import { request, plain, report } from './api.js';

export function createPanel({ afterSay }) {
  const log = document.getElementById('editor-log');
  const messages = document.getElementById('editor-messages');
  const scroll = document.getElementById('editor-panel-scroll');
  const quick = document.getElementById('editor-quick-replies');
  const form = document.getElementById('editor-say');
  const input = document.getElementById('editor-message');
  const send = form.querySelector('button');
  const history = [];
  const seen = new Set();
  let buildId = null, busy = false;

  function message(text, speaker = 'argyle') {
    if (!text) return;
    const node = document.createElement('p'); node.className = 'editor-message';
    node.dataset.speaker = speaker; node.textContent = plain(text); messages.append(node);
    scroll.scrollTop = scroll.scrollHeight;
  }
  async function say(text) {
    text = text.trim();
    if (!text || busy) return;
    busy = true; send.disabled = true;
    quick.querySelectorAll('button').forEach(button => { button.disabled = true; });
    message(text, 'you'); input.value = '';
    try {
      const result = await request('say', 'POST', { message: text, history: history.slice(-20) });
      history.push({ role: 'user', content: text }, { role: 'assistant', content: result.reply || '' });
      message(result.reply || 'Done.');
      await afterSay(result);
    } catch (error) {
      if (!error.cancelled) {
        input.value = text;
        if (!error.shown) message(error.message || 'Could not reach Argyle. Try again.');
      }
    } finally {
      busy = false; send.disabled = false;
      quick.querySelectorAll('button').forEach(button => { button.disabled = false; });
    }
  }
  form.addEventListener('submit', event => { event.preventDefault(); say(input.value).catch(report); });
  function replies(labels = ['Keep going', 'What needs checking?']) {
    quick.replaceChildren();
    labels.forEach(label => {
      const button = document.createElement('button'); button.type = 'button';
      button.textContent = plain(label); button.disabled = busy;
      button.addEventListener('click', () => say(label).catch(report)); quick.append(button);
    });
  }
  replies();
  return {
    message, say, replies,
    events(build) {
      if (buildId !== build.id) { seen.clear(); log.replaceChildren(); buildId = build.id; }
      for (const event of build.events || []) {
        if (seen.has(event.seq)) continue;
        seen.add(event.seq);
        if (event.type === 'log') {
          const line = document.createElement('li'); line.textContent = plain(event.text); log.append(line);
        } else if (event.type === 'question' || event.type === 'error') message(event.text);
      }
    },
    reset() { seen.clear(); log.replaceChildren(); messages.replaceChildren(); history.length = 0; buildId = null; },
  };
}
