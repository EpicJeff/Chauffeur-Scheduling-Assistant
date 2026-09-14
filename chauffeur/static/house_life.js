/* The room opens the family's existing cards; each card owns its teardown. */
window.houseLife = function () {
  var labels = { packing:'Packing', chores:'Chores', routines:'Routines',
    programs:'Programs', tasks:'Household tasks', errands:'Errands' };
  return {
    state: {}, active: null, t: null, error: '', loading: false, busy: false, trigger: null,
    apiBase: window.chfBase || '', generation: 0,
    collageSpan: function () { return ''; }, fillsHere: function () { return false; },
    link: function (url) { return this.apiBase + String(url || '').replace(/^\//, ''); },
    init: function () { if (window.chfHouseState) this.accept(window.chfHouseState() || {}); },
    accept: function (data) { this.state = data || {}; },
    title: function () { return labels[this.active] || ''; },
    explanation: function () {
      return ({ packing:'Ready for the next outing.', chores:'Choose a job, finish it, or check completed work.',
        routines:'Today’s steps, at your own pace.', programs:'Practice, lessons, and things worth celebrating.',
        tasks:'Household work, with due items first.', errands:'What needs a trip out of the house.' })[this.active] || '';
    },
    open: async function (key) {
      if (key === 'study') { this.study(); return; }
      if (!labels[key]) return;
      this.trigger = document.activeElement;
      this.active = key; this.t = null; this.error = ''; this.loading = false;
      var generation = ++this.generation;
      document.body.classList.add('house-card-open');
      this.$nextTick(() => this.$refs.panel.querySelector('header button').focus());
      if (key !== 'tasks' && key !== 'errands') return;
      this.loading = true;
      try {
        var response = await fetch(this.apiBase + 'api/home_board?widgets=' + key);
        if (!response.ok) throw new Error();
        var data = await response.json();
        if (generation !== this.generation) return;
        this.t = (data.tiles || []).find(t => t.type === key) || null;
        if (!this.t) this.error = 'Nothing on this list yet.';
      } catch (_) { if (generation === this.generation) this.error = 'Could not load this list. Please try again.'; }
      finally { if (generation === this.generation) this.loading = false; }
    },
    close: function () {
      this.active = null; this.t = null; ++this.generation;
      document.body.classList.remove('house-card-open');
      if (this.trigger && this.trigger.focus) this.trigger.focus();
      if (window.chfHouseRefresh) window.chfHouseRefresh();
    },
    trap: function (event) {
      var buttons = Array.from(this.$refs.panel.querySelectorAll('button,a[href],input,select,textarea,[tabindex="0"]'))
        .filter(el => !el.disabled && el.offsetWidth > 0);
      var first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    },
    study: async function (destination) {
      if (this.busy) return;
      this.busy = true;
      // Return focus to the house before opening the shared PIN prompt.
      if (this.active) this.close();
      try {
        var response = await fetch(this.apiBase + 'api/members');
        if (!response.ok) throw new Error();
        var parents = (await response.json()).filter(m => m.role === 'parent' && m.has_pin);
        if (!parents.length) { showGlobalAlert('Set a parent PIN in People before opening the Study.'); return; }
        var id = parents.length === 1 ? parents[0].id : await promptChoice('Open the Study', 'Which parent is here?',
          parents.map(p => ({ label:p.name, value:p.id })));
        var parent = parents.find(p => p.id === id);
        if (!parent) return;
        var pin = await promptInput('Open the Study', parent.name + '’s PIN', { type:'password', placeholder:'PIN', okText:'Unlock' });
        if (pin === null || pin === undefined) return;
        response = await fetch(this.apiBase + 'api/members/' + encodeURIComponent(parent.id) + '/auth', {
          method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({pin:pin,house_session:true})
        });
        var result = await response.json();
        if (!response.ok) { showGlobalAlert(result.detail || 'Could not unlock the Study.'); return; }
        window.chfHouseStartParent(result);
        location.href = this.apiBase + (destination === 'errands' ? 'errands' : 'study') + '?panel=false';
      } catch (_) { showGlobalAlert('Could not open the Study. Check the connection and try again.'); }
      finally { this.busy = false; }
    }
  };
};
