/* The room opens the family's existing cards; each card owns its teardown. */
window.houseLife = function () {
  var kitchenCalendar = null, calendarPending = null, busMap=null, busTimer=null;
  var labels = { bus:'School buses', packing:'Packing', chores:'Chores', routines:'Routines',
    programs:'Programs', tasks:'Household tasks', errands:'Errands',
    moments:'Moments', meals:'Meals', lists:'Shopping list', calendar:'Calendar',
    weather:'Weather', cars:'Cars', pets:'Critters', schedule:'Next up', music:'Music', study_preview:'Study' };
  return Object.assign(window.kitchenTileIsland ? window.kitchenTileIsland() : {}, {
    state: {}, active: null, t: null, error: '', loading: false, busy: false, trigger: null, quickView: false,
    apiBase: window.chfBase || '', generation: 0,
    collageSpan: function () { return ''; }, fillsHere: function () { return false; },
    link: function (url) { return this.apiBase + String(url || '').replace(/^\//, ''); },
    init: function () { if (window.chfHouseState) this.accept(window.chfHouseState() || {}); },
    accept: function (data) { this.state = data || {}; },
    title: function () {
      if(document.body.dataset.houseScene==='kitchen') {
        if(this.active==='weather')return 'Forecast';
        if(this.active==='lists')return 'Groceries';
      }
      return labels[this.active] || '';
    },
    bookMode: function () { return !this.quickView && document.body.dataset.houseRender === 'hybrid' && ['tasks', 'programs'].includes(this.active); },
    habitatMode: function () { return !this.quickView && document.body.dataset.houseRender === 'hybrid' && this.active === 'pets'; },
    explanation: function () {
      return ({ packing:'Ready for the next outing.', chores:'Choose a job, finish it, or check completed work.',
        routines:'Today’s steps, at your own pace.', programs:'Practice, lessons, and things worth celebrating.',
        tasks:'Household work, with due items first.', errands:'What needs a trip out of the house.' })[this.active] || '';
    },
    kitchenCalendarMode: function () { return this.active==='calendar' && document.body.dataset.houseScene==='kitchen'; },
    calendarTitle: '',
    busRows: [],
    showBus: async function (generation) {
      this.loading=true; this.error='';
      try {
        var widgets=[{id:'house-buses',type:'map',config:{people:false,cars:false,buses:true,interactive:true}}];
        var response=await fetch(this.apiBase+'api/home_board?widgets='+encodeURIComponent(JSON.stringify(widgets)));
        if(!response.ok)throw new Error('Bus data unavailable');
        var payload=await response.json();
        if(generation!==this.generation)return;
        var data=(payload.tiles||[]).find(t=>t.type==='map')?.data||{};
        this.busRows=data.people||[];
        await this.$nextTick();
        if(generation!==this.generation)return;
        await FamilyMap.ensureLeaflet();
        if(generation!==this.generation)return;
        var map=busMap;
        if(!map){
          map=busMap=FamilyMap.create(document.getElementById('house-bus-map'),{
            interactive:true,fallbackCenter:data.center?[data.center.latitude,data.center.longitude]:null
          });
          await map.ensure();
        }
        if(generation!==this.generation){map.destroy();return;}
        await map.refresh(this.busRows);
      } catch (_) { if(generation===this.generation)this.error='Bus locations could not load. Close and reopen to try again.'; }
      finally {
        if(generation===this.generation){
          this.loading=false;
          clearTimeout(busTimer);
          busTimer=setTimeout(()=>{if(this.active==='bus')this.showBus(generation);},20000);
        }
      }
    },
    mountKitchenCalendar: async function () {
      var generation=this.generation;
      await this.$nextTick();
      try {
        if(!kitchenCalendar){
          calendarPending=calendarPending || FamilyCalendar.mount({targetContainerId:'kitchen-wall-calendar',view:'dayGridMonth',toolbar:false,legend:false,details:true,base:this.apiBase});
          kitchenCalendar=await calendarPending;calendarPending=null;
        }
        // Let Alpine reveal the retained calendar before FullCalendar measures it.
        await new Promise(resolve=>requestAnimationFrame(resolve));
        if(generation!==this.generation){FamilyCalendar.pause('kitchen-wall-calendar',true);return;}
        FamilyCalendar.pause('kitchen-wall-calendar',false);kitchenCalendar.updateSize();kitchenCalendar.refetchEvents();
        this.calendarTitle=kitchenCalendar.calendar.view.title;
      } catch (_) { calendarPending=null;this.error='The calendar could not load. Reopen it to try again.'; }
    },
    calendarMove: function (direction) {
      if(!kitchenCalendar)return;
      kitchenCalendar.calendar[direction]();this.calendarTitle=kitchenCalendar.calendar.view.title;
    },
    open: async function (key, focus = true) {
      if (key === 'study') { this.study(); return; }
      if (!labels[key]) return;
      this.quickView = ['exterior', 'garage'].includes(document.body.dataset.houseScene);
      if (focus) this.trigger = document.activeElement;
      this.active = key; this.t = null; this.error = ''; this.loading = false;
      var generation = ++this.generation;
      document.body.classList.add('house-card-open');
      if(this.kitchenCalendarMode()){this.mountKitchenCalendar();return;}
      if(key==='bus'){this.busRows=[];this.showBus(generation);}
      if (focus) this.$nextTick(() => (this.bookMode() ? document.querySelector('#house-book h2') : this.habitatMode() ? document.getElementById('house-habitat') : this.$refs.panel.querySelector('header button'))?.focus({preventScroll:true}));
      if (key === 'music') {
        this.$nextTick(() => {
          if (this.active !== 'music') return;
          var widget = document.getElementById('music-widget');
          this.musicHome = widget.parentNode; this.$refs.music.appendChild(widget);
          var host = document.getElementById('overlay-music');
          if (!host.__started && window.startMusicWidget) { host.__started = true; window.startMusicWidget(); }
        });
        return;
      }
      var tiles = {tasks:'tasks',errands:'errands',moments:'moments',meals:'meals',lists:'shopping_list',
        weather:'weather',cars:'cars',pets:'pets',schedule:'hero'};
      if (key === 'meals' && document.body.dataset.houseScene === 'kitchen') tiles.meals = 'meals_week';
      if (!tiles[key]) return;
      this.loading = true;
      try {
        var response = await fetch(this.apiBase + 'api/home_board?widgets=' + tiles[key]);
        if (!response.ok) throw new Error();
        var data = await response.json();
        if (generation !== this.generation) return;
        this.hero = data.hero || {};
        this.t = key === 'schedule' ? {type:'hero',data:{}} : (data.tiles || []).find(t => t.type === tiles[key]) || null;
        if (!this.t) this.error = ({meals:'No meals added yet.',moments:'No family moments yet.',weather:'Weather data is unavailable.'})[key] || 'Nothing on this list yet.';
      } catch (_) { if (generation === this.generation) this.error = 'Could not load this list. Please try again.'; }
      finally { if (generation === this.generation) this.loading = false; }
    },
    heroCardHtml: function () { return window.HeroCard && this.hero.next ? HeroCard.html(this.hero.next, {compact:true}) : ''; },
    close: function () {
      clearTimeout(busTimer);busTimer=null;if(busMap){busMap.destroy();busMap=null;}
      if(kitchenCalendar)FamilyCalendar.pause('kitchen-wall-calendar',true);
      if (this.musicHome) { this.musicHome.appendChild(document.getElementById('music-widget')); this.musicHome = null; }
      this.active = null; this.t = null; ++this.generation;
      document.body.classList.remove('house-card-open');
      if (this.trigger && this.trigger.focus) this.trigger.focus({preventScroll:true});
      if (window.chfHouseRefresh) window.chfHouseRefresh();
      window.dispatchEvent(new CustomEvent('chf-house-closed'));
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
        if (destination !== 'errands' && window.chfHouseParent && window.chfHouseParent()) {
          await window.chfHouseUnlockStudy(); return;
        }
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
        if (destination === 'errands') location.href = this.apiBase + 'errands?panel=false';
        else await window.chfHouseUnlockStudy();
      } catch (_) { showGlobalAlert('Could not open the Study. Check the connection and try again.'); }
      finally { this.busy = false; }
    }
  });
};
