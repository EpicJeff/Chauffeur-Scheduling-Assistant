/* Page presentation only; household permissions and lesson behavior stay shared. */
window.houseBookPages = function () {
  return {
    page: 'left', lessonOpen: false,
    init() { this.$watch('active', () => { this.turn('left'); }); },
    turn(side) {
      this.page = side;
      document.getElementById('hybrid-room-frame').dataset.bookPage = side;
    },
    get taskRows() { return this.t?.data?.tasks || []; },
    get taskTotal() { return this.t?.data?.total || this.taskRows.length; },
    dueLabel(row) {
      if (!row.due) return 'No due date';
      const date = new Date(row.due + 'T12:00:00');
      return (row.past_due ? 'Overdue · ' : 'Due ') + (Number.isNaN(+date) ? row.due : date.toLocaleDateString(undefined, {month:'short', day:'numeric'}));
    },
    lessonChanged(open, el) {
      this.lessonOpen = open;
      if (open) {
        this.lessonTrigger = document.activeElement;
        this.turn('right');
        this.$nextTick(() => el.querySelector('[aria-label="Close session"]').focus());
      } else if (this.active === 'programs' && this.lessonTrigger?.isConnected) {
        this.turn('left');
        this.$nextTick(() => this.lessonTrigger.focus({preventScroll:true}));
      }
    }
  };
};
window.houseProgramBook = function (base) {
  return Object.defineProperties(programsCard({data:{}}, base), Object.getOwnPropertyDescriptors({
    practicePage: 0, journalPage: 0,
    get practicePages() { return Math.max(1, Math.ceil(this.pgToday.length / 2)); },
    get practices() { return this.pgToday.slice(Math.min(this.practicePage, this.practicePages - 1) * 2, (Math.min(this.practicePage, this.practicePages - 1) + 1) * 2); },
    get journal() {
      return [
        ...(this.pgUpNext ? [{heading:'Coming up', line:this.pgUpNext.memberName + ' · ' + this.pgUpNext.title, detail:this.pgUpNext.milestone}] : []),
        ...this.pgCelebrated.map(p => ({heading:'Just reached', line:p.line, detail:''})),
        ...this.pgPracticed.map(p => ({heading:'This week', line:p.line, detail:''}))
      ];
    },
    get journalPages() { return Math.max(1, Math.ceil(this.journal.length / 3)); },
    get journalRows() { return this.journal.slice(Math.min(this.journalPage, this.journalPages - 1) * 3, (Math.min(this.journalPage, this.journalPages - 1) + 1) * 3); },
    startSession(w) { window.dispatchEvent(new CustomEvent('lesson-player:open', {detail:{window:w.raw, lesson:w.raw._lesson || null}})); }
  }));
};
window.chfBookCloseLesson = function () {
  const el = document.getElementById('house-book-lesson');
  const data = el && window.Alpine && Alpine.$data(el);
  if (!data?.openFlag) return false;
  data.close(); return true;
};
