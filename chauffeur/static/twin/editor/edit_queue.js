import { applyLocal, LocalMissing } from './local_ops.js';

// Confirmed house + ordered pending operations. I/O and notices belong to the caller.
// onChange({ round, plan, model, state, refused, dropped }) receives the shown plan,
// the confirmed round/model, and state(). Ordinary changes have empty notice arrays;
// accumulated {label, reason} refusals and dropped labels are delivered once at empty.
// state(): saving counts all pending steps while sending; unsaved counts them all
// during retry sleep or a sign-out stop. saved means there are no pending steps.
// Plans are immutable inputs. A supplied local preview is used only at push time:
// every accepted base, answer or refusal replays operations, discarding shortcuts.
export function createEditQueue({ send, onChange, onSignedOut,
  retryMs = [1000, 2000, 5000, 10000], now = () => performance.now(), sleep }) {
  const wait = sleep || (ms => new Promise(resolve => setTimeout(resolve, ms)));
  const steps = [];
  let confirmed = { round: -Infinity, plan: null, model: null }, shownPlan = null;
  let sequence = 0, running = false, stopped = false, waiting = false, inFlight = null;
  let refused = [], dropped = [];

  function state() {
    const unsaved = stopped || waiting ? steps.length : 0;
    return { saved: steps.length === 0, saving: steps.length - unsaved, unsaved };
  }

  function changed() {
    const notice = { refused: [], dropped: [] };
    if (!steps.length) {
      notice.refused = refused; notice.dropped = dropped;
      refused = []; dropped = [];
    }
    onChange?.({ round: confirmed.round, plan: shownPlan, model: confirmed.model, state: state(), ...notice });
  }

  function drop(step, error) {
    steps.splice(steps.indexOf(step), 1);
    error.dropped = true;
    dropped.push(step.label);
    step.reject(error);
  }

  function replay() {
    let plan = confirmed.plan;
    for (const step of [...steps]) {
      try { plan = applyLocal(plan, step.op)?.plan || plan; }
      catch (error) {
        // Any other failure only means no local preview; the server still judges the step.
        if (!(error instanceof LocalMissing)) { console.warn('Local replay failed', error); continue; }
        // A request already sent still needs its own server answer. Only unsent
        // dependencies can be discarded when the confirmed house changes.
        if (step !== inFlight) drop(step, error);
      }
    }
    shownPlan = plan;
  }

  function accept(value) {
    if (value.round < confirmed.round) return false;
    confirmed = { round: value.round, plan: value.plan, model: value.model };
    return true;
  }

  function base(value) {
    if (!accept(value)) return false;
    replay(); changed();
    return true;
  }

  async function drain() {
    try {
      while (steps.length && !stopped) {
        const step = steps[0];
        inFlight = step;
        let result;
        try { result = await send(step.op); }
        catch (error) {
          inFlight = null;
          if (error.status === 401 || error.status === 403) {
            stopped = true;
            changed(); onSignedOut?.();
            continue;
          }
          if ([400, 409, 422].includes(error.status)) {
            steps.shift(); error.refused = true;
            refused.push({ label: step.label, reason: error.message });
            replay(); changed(); step.reject(error);
            continue;
          }
          waiting = true; changed();
          await wait(retryMs[Math.min(step.attempt++, retryMs.length - 1)]);
          waiting = false; changed();
          continue;
        }
        inFlight = null;
        steps.shift(); accept(result);
        replay(); changed(); step.resolve(result);
      }
    } finally {
      running = false;
      start();
    }
  }

  function start() {
    if (running || stopped || !steps.length) return;
    running = true;
    void drain();
  }

  function push({ op, label, selection, local = null }) {
    let resolve, reject;
    const saved = new Promise((a, b) => { resolve = a; reject = b; });
    // Keep the original rejecting promise for callers, even when nobody awaits it.
    saved.catch(() => {});
    const id = `${now()}-${++sequence}`;
    const step = { id, op, label, selection, resolve, reject, attempt: 0 };
    steps.push(step);
    try { shownPlan = local || applyLocal(shownPlan, op)?.plan || shownPlan; }
    catch (error) {
      if (error instanceof LocalMissing) drop(step, error);
      else console.warn('Local preview failed', error);
    }
    changed(); start();
    return { id, saved };
  }

  function resume() {
    stopped = false;
    changed(); start();
  }

  return { base, push, shown: () => shownPlan, state, pending: () => steps.length, resume };
}
