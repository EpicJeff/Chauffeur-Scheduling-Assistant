/* The habitat displays the board's public projection; shared gates own all edits. */
window.houseHabitat = function () {
  return {
    selectedKey: '', pending: false, touchX: null, suppressClickUntil: 0,
    init() { this.$watch('active', () => { if (this.active !== 'pets') this.selectedKey = ''; }); },
    get residents() { return this.t?.data?.members || []; },
    key(row) { return row.pet?.id || row.member_id + ':' + row.kind; },
    get index() { const i = this.residents.findIndex(row => this.key(row) === this.selectedKey); return Math.max(0, i); },
    get selected() { return this.residents[this.index] || null; },
    get figures() {
      const rows = this.residents, i = this.index;
      if (!rows.length) return [];
      const out = [{row:rows[i], slot:'center'}];
      if (rows.length > 1) out.push({row:rows[(i + 1) % rows.length], slot:'right'});
      if (rows.length > 2) out.push({row:rows[(i + rows.length - 1) % rows.length], slot:'left'});
      return out;
    },
    get interactive() { return !!this.t?.data?.interactive && !this.pending; },
    name(row) { return row?.pet?.name || (row?.kind === 'buy' ? 'Room for another' : 'Ready to hatch'); },
    turn(delta) { if (this.residents.length) this.selectedKey = this.key(this.residents[(this.index + delta + this.residents.length) % this.residents.length]); },
    choose(figure) { if (figure.slot === 'center') this.act('edit'); else this.selectedKey = this.key(figure.row); },
    swipe(event) {
      if (this.touchX === null) return;
      const delta = event.changedTouches[0].clientX - this.touchX;
      this.touchX = null;
      if (Math.abs(delta) > 45) {
        this.turn(delta < 0 ? 1 : -1); this.suppressClickUntil = Date.now() + 350;
        if (event.cancelable) event.preventDefault();
      }
    },
    async act(action) {
      const row = this.selected;
      if (!row || !this.interactive) return;
      this.pending = true;
      const member = {id:row.member_id, name:row.name, has_pin:row.has_pin, petId:row.pet?.id, newPet:row.kind === 'empty'};
      try {
        if (action === 'battle' && row.pet) await window.openPetBattle(member);
        else if (row.kind === 'buy') await window.buyPetSlot(row);
        else await window.openPetEditor(member);
        if (!this.habitatMode()) window.chfHabitatCloseOverlay();
      } finally { this.pending = false; }
    },
    refresh() {
      const overlayOpen = ['pet-battle-panel', 'pet-editor-panel'].some(id => {
        const el = document.getElementById(id); return el && Alpine.$data(el).show;
      });
      if (this.habitatMode()) this.open('pets', !overlayOpen);
    }
  };
};
window.chfHabitatCloseOverlay = function () {
  for (const id of ['pet-battle-panel', 'pet-editor-panel']) {
    const el = document.getElementById(id), panel = el && window.Alpine && Alpine.$data(el);
    if (panel?.show) { panel.close(); document.getElementById('house-habitat')?.focus({preventScroll:true}); return true; }
  }
  return false;
};
window.addEventListener('chf-house-close', () => {
  if (document.getElementById('hybrid-room-frame')?.dataset.view === 'pets') window.chfHabitatCloseOverlay();
});
window.addEventListener('pet-overlay-closed', () => {
  if (document.getElementById('hybrid-room-frame')?.dataset.view === 'pets') document.getElementById('house-habitat')?.focus({preventScroll:true});
});
