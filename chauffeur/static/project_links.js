/* Record headers share one audience-filtered Part of line and project picker. */
(() => {
    if (window.chfPartOf) return;
    const base = () => window.chfBase !== undefined ? window.chfBase : '';
    const headers = () => {
        const token = window.chfPersonToken ? window.chfPersonToken() : localStorage.getItem('chauffeur_member_token');
        return {'Content-Type': 'application/json', ...(token ? {'X-Member-Token': token} : {})};
    };
    async function request(path, body) {
        const r = await fetch(base() + path, {headers:headers(), method:body === undefined ? 'GET' : 'POST',
            ...(body === undefined ? {} : {body:JSON.stringify(body)})});
        const d = await r.json();
        if (!r.ok || d.status === 'error') throw new Error(d.detail || d.message || 'Could not load projects.');
        return d;
    }
    window.chfPartOf = async function(kind, id, el, editable = true) {
        const key = kind + ':' + id;
        el.replaceChildren(); el.dataset.projectSubject = key;
        if (!id) return;
        try {
            const d = await request('api/subjects/' + encodeURIComponent(kind) + '/' + encodeURIComponent(id) + '/projects');
            if (el.dataset.projectSubject !== key) return;
            for (const p of d.projects || []) {
                const line = document.createElement('div');
                line.append(document.createTextNode('Part of: '));
                // The phone opens its own Projects view (one-list spec §5): a
                // button, never an anchor to the admin page.
                const phone = typeof window.chfPwaOpenProjects === 'function';
                const a = document.createElement(phone ? 'button' : 'a');
                if (phone) {
                    a.type = 'button';
                    a.onclick = () => { if (window.chfPwaOpenProjects() !== false) window.dispatchEvent(new CustomEvent('chf-project-open', {detail: {id: p.id}})); };
                } else a.href = base() + 'projects?id=' + encodeURIComponent(p.id);
                a.className = 'text-blue-400 underline underline-offset-2';
                a.textContent = p.title; line.append(a); el.append(line);
            }
            if (!editable || document.documentElement.hasAttribute('data-panel') || new URLSearchParams(location.search).get('kiosk') === 'true') return;
            const button = document.createElement('button'); button.type = 'button';
            button.className = 'text-xs font-semibold text-gray-500 underline underline-offset-2';
            button.textContent = 'Add to a project';
            button.onclick = async () => {
                button.disabled = true;
                try {
                    const projects = (await request('api/projects')).projects.filter(p => p.can_act);
                    if (!projects.length) { showGlobalAlert('No projects you can add this to yet.'); return; }
                    const pick = await promptChoice('Add to a project', '', projects.map(p => ({value:p.id,label:p.title})));
                    if (pick === null || el.dataset.projectSubject !== key) return;
                    await request('api/projects/' + encodeURIComponent(pick) + '/pieces', {kind, id});
                    await window.chfPartOf(kind,id,el,editable);
                } catch (e) { showGlobalAlert(e.message); }
                finally { button.disabled = false; }
            };
            el.append(button);
        } catch (e) {
            // A wall or an excluded viewer has no record/project words to draw.
            if (el.dataset.projectSubject === key) el.replaceChildren();
        }
    };
})();
