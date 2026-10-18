"""Admission and synchronous cancellation for a person's confirmed deletion.

Visibility, worker call sites and physical cleanup land in the following tasks.
No storage imports at module initialization: storage's write fences call check().
"""
from contextlib import contextmanager
from contextvars import ContextVar
from collections import Counter
from copy import deepcopy
import hashlib
import json
import logging
import threading
import time
import uuid


ASK_A_PARENT = 'Ask a parent to delete this.'
CHANGED = 'This project changed. Look again.'
TOKEN_REQUIRED = 'A confirmation is required.'
KINDS = ('project', 'thread', 'mission', 'program')
_sources = ContextVar('deletion_sources', default=())
_workers = Counter()
_workers_lock = threading.RLock()


class Cancelled(Exception):
    """Work whose source has gone must discard its result."""


def _load(kind, rid):
    from services import storage
    return getattr(storage, 'get_' + kind)(rid) if kind in KINDS else None


@contextmanager
def acting_for(kind, rid):
    """Register work for its whole lifetime and carry its source in copied contexts."""
    key = (kind, rid)
    with _workers_lock:
        _workers[key] += 1
    token = _sources.set(_sources.get() + (key,))
    try:
        check()
        yield
    finally:
        _sources.reset(token)
        with _workers_lock:
            _workers[key] -= 1
            if not _workers[key]:
                del _workers[key]


def check():
    """Raise after a carried source disappears or is admitted for deletion."""
    for kind, rid in _sources.get():
        row = _load(kind, rid)
        if not row or row.get('deleting'):
            raise Cancelled(f'{kind} {rid} was deleted')


def active(kind, rid):
    with _workers_lock:
        return bool(_workers[(kind, rid)])


def closure(kind, rid):
    """Authoritative homes, kit threads and thread origins; never project pieces."""
    from services import storage
    if kind not in KINDS:
        return []
    with storage.db_lock:
        rows = {'project': {r['id']: r for r in storage.get_projects()},
                'thread': {r['id']: r for r in storage.get_threads(include_closed=True)},
                'mission': {r['id']: r for r in storage.get_missions()},
                'program': {r['id']: r for r in storage.get_programs(include_finished=True)}}
        pending, found = [(kind, rid)], set()
        while pending:
            key = pending.pop()
            if key in found:
                continue
            k, record_id = key
            row = rows[k].get(record_id)
            if not row or row.get('deleting'):
                continue
            found.add(key)
            if k == 'project':
                pending.extend((pk, r['id']) for pk in ('thread', 'mission', 'program')
                               for r in rows[pk].values() if r.get('project_id') == record_id)
            elif k == 'thread':
                pending.extend(('mission', m['id']) for m in rows['mission'].values()
                               if m.get('origin_kind') == 'thread' and m.get('origin_ref') == record_id)
            elif k == 'program':
                pending.extend(('thread', tid) for tid in (row.get('emissions') or {}).get('thread_ids', []))
        return sorted(found)


def _refused():
    return {'status': 'refused', 'message': ASK_A_PARENT}


def _prepare(kind, rid, actor):
    """Run under db_lock; re-read both authority and the displayed snapshot."""
    from services import access, projects, storage
    if not actor or access.is_house(actor):
        return None, _refused()
    actor = storage.get_member(actor.get('id'))
    if not projects._active(actor):
        return None, _refused()
    root = _load(kind, rid)
    if not root or root.get('deleting'):
        return None, {'status': 'gone', 'message': f'No such {kind}'}
    if kind == 'project':
        allowed = projects.can_see(root, actor) and (
            actor['id'] == root.get('owner_member_id') or projects._parent(actor))
    elif kind in ('thread', 'mission'):
        allowed = actor.get('role') in access.WRITE_ROLES and access.record_actable(kind, root, actor, 'delete')
    elif kind == 'program':
        home = storage.get_project(root.get('project_id')) or {}
        allowed = access.record_visible(kind, root, actor) and (
            actor['id'] == home.get('owner_member_id') or projects._parent(actor))
    else:
        allowed = False
    if not allowed:
        return None, _refused()
    records = [(k, record_id, _load(k, record_id)) for k, record_id in closure(kind, rid)]
    for k, _, row in records:
        readable = (projects.can_see(row, actor) if k == 'project'
                    else access.record_view(k, row, actor) is not None)
        if not readable:
            return None, _refused()
    items = [{'kind': k, 'id': record_id,
              'title': (row.get('goal') if k == 'mission' else row.get('title')) or k}
             for k, record_id, row in records if k != 'project']
    triples = sorted((i['kind'], i['id'], i['title']) for i in items)
    token = hashlib.sha256(json.dumps(triples, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    links = sum(1 for p in root.get('pieces', []) if p.get('kind') not in ('thread', 'mission', 'program')) if kind == 'project' else 0
    return {'actor': actor, 'records': records,
            'preview': {'status': 'ok', 'items': items, 'token': token, 'links': links}}, None


def preview(kind, rid, actor):
    from services import storage
    with storage.db_lock:
        prepared, error = _prepare(kind, rid, actor)
        return error or prepared['preview']


def _emissions(records):
    """Capture provenance before a pause; cleanup must not depend on live emissions."""
    from services import storage
    snapshots = {}
    commitments = storage.get_protected_commitments(include_inactive=True)
    exceptions = storage.get_protected_exceptions()
    findings = storage.get_findings()
    for kind, rid, row in records:
        if kind != 'program':
            continue
        snapshot = deepcopy(row.get('emissions') or {})
        cids = set(snapshot.get('commitment_ids') or [])
        cids.update(c['id'] for c in commitments
                    if (c.get('source') or {}).get('kind') == 'program'
                    and (c.get('source') or {}).get('id') == rid)
        snapshot['commitment_ids'] = sorted(cids)
        snapshot['commitments'] = {
            cid: {'exception_ids': [f"{cid}:{e['date']}" for e in exceptions if e.get('commitment_id') == cid],
                  'finding_ids': [f['id'] for f in findings if f.get('subject_type') == 'commitment'
                                  and (f.get('subject_id') == cid or str(f.get('subject_id') or '').startswith(cid + ':'))]}
            for cid in sorted(cids)}
        snapshots[rid] = snapshot
    return snapshots


def _stop(records):
    from services import missions, planned, storage
    # Deletion owns these writes, even if called from a source being stopped.
    token = _sources.set(())
    try:
        for kind, rid, row in records:
            try:
                if kind == 'mission':
                    planned.cancel_for_delete(rid)
                    if row.get('status') == 'browsing':
                        storage.set_app_state(f'mission_steer:{rid}', {'text': 'Stopped', 'ts': time.time()})
                    if row.get('status') in missions.LIVE:
                        storage.update_mission(rid, {'status': 'dropped', 'finished_at': time.time()})
                elif kind == 'program' and row.get('state') == 'active':
                    # Ordinary pause releases commitments; deletion retains them for cleanup.
                    storage.update_program(rid, {'state': 'paused'})
            except Exception:
                logging.getLogger(__name__).exception('Deletion could not stop %s %s', kind, rid)
    finally:
        _sources.reset(token)


def start(kind, rid, actor, token):
    from services import home_board, storage
    with storage.db_lock:
        with storage.db.transaction():
            prepared, error = _prepare(kind, rid, actor)
            if error:
                # Keep start's existing refused/changed service contract for a
                # repeated tap, while letting HTTP distinguish a gone root.
                if error['status'] == 'gone':
                    return {**error, 'status': 'refused', 'reason': 'gone'}
                return error
            if not token:
                return {'status': 'confirmation_required', 'message': TOKEN_REQUIRED}
            if token != prepared['preview']['token']:
                return {'status': 'changed', 'message': CHANGED}
            records = prepared['records']
            did = storage.add_deletion({
                'id': uuid.uuid4().hex, 'kind': kind, 'root_id': rid,
                'closure': [[k, record_id] for k, record_id, _ in records],
                'actor_id': prepared['actor']['id'], 'started_at': time.time(),
                'state': 'started', 'emissions': _emissions(records)})
            for k, record_id, _ in records:
                storage.stamp_deleting(k, record_id, did)
    try:
        _stop(records)
    finally:
        try:
            home_board.invalidate_for_deletion()
        finally:
            storage.mark_all_daily_schedules_dirty()
    return {'status': 'ok', 'deletion_id': did, 'schedule_dirty': True}


def delete(kind, rid):
    """Compatibility for the old internal helpers, which carry no actor argument.

    HTTP callers must use start with the authenticated actor and their token.
    Resolve a real authorized keeper/owner or parent for legacy internal calls.
    """
    from services import storage
    with storage.db_lock:
        row = _load(kind, rid)
        if not row or row.get('deleting'):
            return {'status': 'not_found'}
        home = storage.get_project(row.get('project_id')) or {}
        preferred = (home.get('owner_member_id'), row.get('owner_member_id'), row.get('created_by'))
        actors = [storage.get_member(mid) for mid in preferred if mid]
        actors.extend(m for m in storage.get_all_members() if m.get('role') == 'parent')
        for actor in actors:
            result = preview(kind, rid, actor)
            if result['status'] == 'ok':
                return start(kind, rid, actor, result['token'])
        return _refused()


def maintain():
    """Task 5 supplies worker-aware cleanup and the orphan pass."""
    return {'finished': 0, 'waiting': 0, 'orphans': 0}
