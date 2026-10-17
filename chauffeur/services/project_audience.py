"""Project audiences on the shared model: wrapper derivation and the one-time conversion (spec §3 rev 3)."""
from services import storage

REV = 2


def _sees(kind, row, member):
    from services import access
    return access.record_view(kind, row, member, skip_project=True) is not None


def audience_from_set(viewer_ids, owner_id):
    from services import projects
    members = [m for m in storage.get_all_members() if projects._active(m)]
    parents = {m['id'] for m in members if projects._parent(m)}
    ids = set(viewer_ids) | ({owner_id} if owner_id else set())
    if parents <= ids:
        rest = sorted(ids - parents - {owner_id})
        return ('shared', rest) if rest else ('parents', [])
    return 'private', [owner_id] + sorted(ids - {owner_id})


def _new_owner(kind, row, viewer_ids):
    from services import access, projects
    keeper = access.keeper_id(kind, row) if row else None
    if keeper in viewer_ids:
        return keeper
    members = [m for m in storage.get_all_members() if projects._active(m) and m['id'] in viewer_ids]
    for test in (projects._parent, lambda m: m.get('role') == 'adult'):
        for m in members:
            if test(m):
                return m['id']
    return None


def derive_for_record(kind, row, owner_id):
    """(owner_id, audience, shared_with, retitle) for a wrapper around this record."""
    from services import access, projects
    if row is None:
        return owner_id, 'private', [owner_id], False
    members = [m for m in storage.get_all_members() if projects._active(m)]
    grown = [m for m in members if projects._parent(m) or (m.get('role') == 'adult' and not projects._child(m))]
    if _sees(kind, row, access.HOUSE) and all(_sees(kind, row, m) for m in grown):
        return owner_id, 'household', [], False
    seen = {m['id'] for m in members if _sees(kind, row, m)}
    if owner_id not in seen:
        new = _new_owner(kind, row, seen)
        if not new:
            return owner_id, 'private', [owner_id], True
        owner_id = new
    audience, rest = audience_from_set(seen, owner_id)
    return owner_id, audience, rest, False


def _convert(project):
    from services import projects
    owner = project.get('owner_member_id')
    if project.get('body_goal'):
        return {'audience': 'private', 'shared_with': [owner]}
    src = project.get('wrapped_from') or {}
    if src.get('kind') in projects._ADOPT_TABLES and src.get('id'):
        record = projects._ADOPT_TABLES[src['kind']][0](src['id'])
        new_owner, audience, rest, retitle = derive_for_record(src['kind'], record, owner)
        patch = {'owner_member_id': new_owner, 'audience': audience, 'shared_with': rest}
        if retitle:
            patch.update(title='Untitled project', goal='')
        return patch
    row = {'audience': project.get('audience') if project.get('audience') in projects.AUDIENCES else 'private',
           'owner_member_id': owner, 'shared_with': None}
    projects.normalize_audience(row, False)
    return {'audience': row['audience'], 'shared_with': row['shared_with']}


def convert_all():
    with storage.db_lock:
        rows = [p for p in storage.get_projects() if p.get('audience_rev') != REV]
        for p in rows:
            storage.update_project(p['id'], {**_convert(p), 'audience_rev': REV})
        return {'converted': len(rows), 'skipped': 0}


def narrow_on_bind(kind, row):
    """A wrapped record got a new subject: narrow its wrapper once, never widen (spec §3 'Binding narrows once')."""
    from services import access, projects
    project = storage.get_project((row or {}).get('project_id'))
    if not project or not project.get('wrapped_from') or project.get('body_goal'):
        return
    new_owner, audience, rest, _ = derive_for_record(kind, row, project.get('owner_member_id'))
    candidate = {**project, 'owner_member_id': new_owner, 'audience': audience, 'shared_with': rest}
    viewers = [m for m in storage.get_all_members() if projects._active(m)] + [access.HOUSE]
    now = {m['id'] for m in viewers if access.project_visible(project, m)}
    after = {m['id'] for m in viewers if access.project_visible(candidate, m)}
    if after < now:
        storage.update_project(project['id'], {'owner_member_id': new_owner, 'audience': audience,
                                               'shared_with': rest, 'audience_rev': REV})
