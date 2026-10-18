"""Admission and synchronous cancellation for a person's confirmed deletion.

Workers carry their sources through writes; maintenance removes their data after exit.
No storage imports at module initialization: storage's write fences call check().
"""
from contextvars import ContextVar
from collections import Counter
from copy import deepcopy
import hashlib
import json
import logging
import os
import re
import shutil
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
_cancelled_at = {}
ORPHAN_MAINTENANCE_S = 3600
_orphan_checked_at = None


class Cancelled(Exception):
    """Work whose source has gone must discard its result."""


def _load(kind, rid):
    from services import storage
    return getattr(storage, 'get_' + kind)(rid) if kind in KINDS else None


class acting_for:
    """Reserve before scheduling; enter in the worker and release after handling.

    A cancelled timer or a failed Thread.start releases its unused reservation
    with close(). Entered reservations release themselves, even on cancellation.
    """
    def __init__(self, kind, rid):
        self.key = (kind, rid)
        self.keys = tuple(dict.fromkeys(_sources.get() + (self.key,)))
        self.token = None
        self.closed = False
        with _workers_lock:
            _workers.update(self.keys)

    def __enter__(self):
        self.token = _sources.set(tuple(dict.fromkeys(_sources.get() + self.keys)))
        try:
            check()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        if self.token is not None:
            _sources.reset(self.token)
            self.token = None
        self.close()

    def close(self):
        with _workers_lock:
            if not self.closed:
                self.closed = True
                for key in self.keys:
                    _workers[key] -= 1
                    if not _workers[key]:
                        del _workers[key]

    release = close


def has_source():
    return bool(_sources.get())


def check():
    """Raise after explicit deletion of a carried source; no-op outside work."""
    for kind, rid in _sources.get():
        row = _load(kind, rid)
        # Retention pruning is not deletion. Read the ledger live, rather
        # than a read-surface cache that may predate admission.
        from services import storage
        if (row and row.get('deleting')) or any(
                d.get('state') == 'started' and [kind, rid] in d.get('closure', [])
                for d in storage.get_deletions()):
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
    _cancelled_at[did] = time.monotonic()
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


def _names(ref, keys):
    return isinstance(ref, dict) and (ref.get('kind'), ref.get('id')) in keys


def _clean_app_state(missing, program_ids=None):
    """Prune only deletion-owned markers; keep unrelated application state.

    missing(kind, id) means closure membership during cleanup, and actual
    absence during the orphan pass. Practice delivery uses hashed program ids.
    """
    from services import programs, storage, triage
    changed = 0
    if program_ids is None:
        program_ids = {p['id'] for p in storage.get_programs(include_finished=True)}
    programs_alive = {pid for pid in program_ids if not missing('program', pid)}
    push_keys = programs_alive | {hashlib.sha1(p.encode()).hexdigest()[:12] for p in programs_alive}
    for row in storage.app_state_table.all():
        key, value = row['key'], row.get('value')
        if key.startswith('mission_steer:') and missing('mission', key.split(':', 1)[1]):
            changed += len(storage.app_state_table.remove(doc_ids=[row.doc_id]))
            continue
        new = value
        if key == triage.FOCUS_KEY and isinstance(value, dict):
            new = {k: v for k, v in value.items()
                   if not (isinstance(v, dict) and missing(v.get('kind'), v.get('id')))}
        elif key == 'watcher_notified' and isinstance(value, dict):
            # Identities are kind-specific (thread_stall:<id>,
            # mission_waiting:<id>, program_drift:<id>, commitment:<id>:...).
            def keep(identity):
                bits = identity.split(':')
                kind = bits[0].split('_', 1)[0]
                if bits[0] in ('pc_cover', 'erosion'):
                    kind = 'commitment'
                return len(bits) < 2 or not missing(kind, bits[1])
            new = {k: v for k, v in value.items() if keep(k)}
        elif key == programs.PUSH_STATE_KEY and isinstance(value, list):
            new = [v for v in value if v.split('|', 1)[0] in push_keys]
        if new != value:
            storage.app_state_table.update({'value': new}, doc_ids=[row.doc_id])
            changed += 1
    return changed


def _survivors(keys, commitment_ids):
    from services import storage
    mids = {rid for kind, rid in keys if kind == 'mission'}
    tids = {rid for kind, rid in keys if kind == 'thread'}
    for kind in KINDS:
        table = getattr(storage, kind + 's_table')
        for original in table.all():
            if (kind, original['id']) in keys:
                continue
            row = deepcopy(original)
            # Drop pointer contents, but preserve the typed id and the explicit
            # flag. Missing alone must never hide retention-pruned history.
            if _names(row.get('subject'), keys):
                ref = row['subject']
                row['subject'] = {'kind': ref['kind'], 'id': ref['id'], 'gone': True}
            if 'subject_history' in row:
                row['subject_history'] = [
                    {'kind': ref['kind'], 'id': ref['id'], 'gone': True} if _names(ref, keys) else ref
                    for ref in row['subject_history'] or []]
            if (row.get('subject_kind'), row.get('subject_id')) in keys:
                row['subject'] = {'kind': row['subject_kind'], 'id': row['subject_id'], 'gone': True}
            if kind == 'thread':
                row['history'] = [h for h in row.get('history') or [] if h.get('mission_id') not in mids]
            if kind == 'project':
                for step in row.get('steps') or []:
                    if step.get('mission_id') not in mids:
                        continue
                    for field in list(step):
                        if field in ('mission_id', 'attempts', 'found', 'question', 'stage', 'stages') or field.startswith('stage_'):
                            step.pop(field, None)
                    if step.get('state') not in ('done', 'skipped'):
                        step.update(state='blocked', question='Its work was deleted.')
                if row.get('origin_mission_id') in mids:
                    row['origin_mission_id'] = None
                if _names(row.get('wrapped_from'), keys):
                    row['wrapped_from'] = None
                row['pieces'] = [p for p in row.get('pieces') or [] if not _names(p, keys)]
            if kind == 'program' and row.get('emissions'):
                em = row['emissions']
                em['thread_ids'] = [tid for tid in em.get('thread_ids') or [] if tid not in tids]
            patch = {k: v for k, v in row.items() if v != original.get(k)}
            if patch:
                if kind == 'project':
                    storage.update_project(row['id'], patch)
                else:
                    table.update(patch, storage.Query().id == row['id'])
    _clean_app_state(lambda kind, rid: (kind, rid) in keys
                     or (kind == 'commitment' and rid in commitment_ids))


def _remove_folder(folder):
    # rmtree is restartable after partially removing its children. Do not
    # swallow permissions/disk failures and then delete the owning record.
    from services import storage
    data_dir = os.path.realpath(os.path.dirname(storage.DB_PATH))
    target = os.path.realpath(folder)
    allowed = [os.path.join(data_dir, name) for name in ('browse', 'threads')]
    if not any(os.path.commonpath((root, target)) == root and target != root for root in allowed):
        raise ValueError(f'Cleanup folder outside record storage: {folder}')
    try:
        shutil.rmtree(folder)
    except FileNotFoundError:
        pass


def _cleanup(row):
    """Finish one durable closure, in spec section 5 order. Caller holds db_lock.

    Each write is through a table/helper, each operation is repeatable by id,
    and parents remain until every child operation has succeeded.
    """
    from services import programs, storage
    keys = {tuple(key) for key in row.get('closure', [])}
    ids = {kind: {rid for k, rid in keys if k == kind} for kind in KINDS}
    snapshots = row.get('emissions') or {}
    cids, exception_ids, finding_ids = set(), set(), set()
    for snapshot in snapshots.values():
        cids.update(snapshot.get('commitment_ids') or [])
        for cid, children in (snapshot.get('commitments') or {}).items():
            cids.add(cid)
            exception_ids.update(children.get('exception_ids') or [])
            finding_ids.update(children.get('finding_ids') or [])
    findings = [f for f in storage.findings_table.all()
                if (f.get('subject_type'), f.get('subject_id')) in keys
                or f.get('id') in finding_ids
                or (f.get('subject_type') == 'commitment' and str(f.get('subject_id') or '').split(':', 1)[0] in cids)]
    finding_ids.update(f['id'] for f in findings)
    asks = [a for a in storage.asks_table.all()
            if (a.get('situation_kind'), a.get('situation_id')) in keys
            or (a.get('situation_kind') == 'finding' and a.get('situation_id') in finding_ids)]
    proposals = [p for p in storage.agent_action_proposals_table.all()
                 if _names(p.get('source'), keys) or (p.get('origin_kind'), p.get('origin_id')) in keys]
    aids, pids = {a['id'] for a in asks}, {p['id'] for p in proposals}

    # 1: Gather ledger ids first. Delete an entire mixed message, never edit it.
    aids.update(s['id'] for s in storage.mission_steps_table.all()
                if s.get('kind') == 'ask' and s.get('mission_id') in ids['mission'])
    resolved = {}
    def copied(message):
        card = message.get('card') or {}
        return (any(card.get(kind + '_id') in ids[kind] for kind in KINDS)
                or card.get('ask_id') in aids or card.get('proposal_id') in pids
                or any(_names(ref, keys) for ref in message.get('refs') or [])
                or not storage.message_visible(message, resolved=resolved))
    from services import access
    with access.batch():
        storage.chat_messages_table.remove(copied)
    # 2: Ledgers, including asks whose parent is one of the findings below.
    storage.agent_action_proposals_table.remove(lambda p: p.get('id') in pids)
    storage.asks_table.remove(lambda a: a.get('id') in aids)
    # 3: Snapshot children survive a live emissions reset or a partial retry.
    storage.findings_table.remove(lambda f: f.get('id') in finding_ids)
    storage.protected_exceptions_table.remove(lambda e:
        e.get('commitment_id') in cids or f"{e.get('commitment_id')}:{e.get('date')}" in exception_ids)
    # 4: A failed release raises, retaining both the program and deletion row.
    for pid in ids['program']:
        snapshot = snapshots.get(pid) or {}
        programs.release_commitments(pid, commitment_ids=list(set(snapshot.get('commitment_ids') or [])
                                                            | set(snapshot.get('commitments') or {})))
        storage.delete_program_lessons(pid)
    # 5: Resolve legacy shared-archive photos BEFORE losing their history.
    data_dir = os.path.dirname(storage.DB_PATH)
    for mid in ids['mission']:
        _remove_folder(os.path.join(data_dir, 'browse', mid))
    for tid in ids['thread']:
        for entry in (storage.get_thread(tid) or {}).get('history') or []:
            media_id = entry.get('media_id')
            # Read without poster generation; cleanup must never recreate the
            # file it just removed. Keep the media-id traversal guard.
            if not re.fullmatch(r'[a-f0-9]{32}\.(mp4|webm|mov|m4v|jpg|png|webp)', media_id or ''):
                continue
            # Visit every possible copy once. On SMB, an accepted delete may
            # remain visible until another handle closes (delete-pending).
            paths = {os.path.join(root, layout, media_id)
                     for root in storage._media_roots()
                     for layout in ('', storage._shard(media_id))}
            paths.add(os.path.join(storage.media_scratch_dir(), media_id))
            for path in sorted(paths):
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
        _remove_folder(os.path.join(data_dir, 'threads', tid))
    # 6: Persist fail-closed pointers and remove summaries on surviving rows.
    _survivors(keys, cids)
    # 7: All steps before any mission; all missions before threads/programs.
    storage.mission_steps_table.remove(lambda s: s.get('mission_id') in ids['mission'])
    for kind in ('mission', 'thread', 'program'):
        getattr(storage, kind + 's_table').remove(lambda r, k=kind: r.get('id') in ids[k])
    # 8: Project holds and program commitments both change the schedule.
    removed = storage.projects_table.remove(lambda p: p.get('id') in ids['project'])
    if removed or ids['program']:
        import main
        main.trigger_background_refresh()
    # 9: No tombstone. Subsequent passes have nothing to finish.
    storage.delete_deletion(row['id'])
    _cancelled_at.pop(row['id'], None)


def _orphans():
    from services import storage
    parents = {kind: {r['id'] for r in getattr(storage, kind + 's_table').all()} for kind in KINDS}
    findings = storage.findings_table.all()
    parents['finding'] = {r['id'] for r in findings}
    parents['commitment'] = {r['id'] for r in storage.protected_commitments_table.all()}
    def missing(kind, rid):
        if kind == 'commitment':
            rid = str(rid or '').split(':', 1)[0]
        return kind in parents and bool(rid) and rid not in parents[kind]
    count = 0
    # Remove asks before findings, including asks about orphaned findings.
    orphan_findings = {f['id'] for f in findings
                       if missing(f.get('subject_type'), f.get('subject_id'))}
    def remove_matches(table, rows, predicate):
        doc_ids = [r.doc_id for r in rows if predicate(r)]
        return len(table.remove(doc_ids=doc_ids)) if doc_ids else 0
    count += remove_matches(storage.asks_table, storage.asks_table.all(), lambda a:
        missing(a.get('situation_kind'), a.get('situation_id'))
        or (a.get('situation_kind') == 'finding' and a.get('situation_id') in orphan_findings))
    count += remove_matches(storage.findings_table, findings, lambda f: f.get('id') in orphan_findings)
    parents['finding'].difference_update(orphan_findings)
    count += remove_matches(storage.mission_steps_table, storage.mission_steps_table.all(),
                            lambda s: missing('mission', s.get('mission_id')))
    count += remove_matches(storage.program_lessons_table, storage.program_lessons_table.all(),
                            lambda l: missing('program', l.get('program_id')))
    for folder, kind in (('browse', 'mission'), ('threads', 'thread')):
        root = os.path.join(os.path.dirname(storage.DB_PATH), folder)
        if not os.path.isdir(root):
            continue
        for rid in os.listdir(root):
            if not re.fullmatch(r'[a-fA-F0-9]{32}', rid):
                continue
            path = os.path.join(root, rid)
            if os.path.isdir(path) and missing(kind, rid):
                _remove_folder(path)
                count += 1
    count += _clean_app_state(missing, program_ids=parents['program'])
    return count


def maintain(*, force_orphans=False):
    """Finish idle deletions; sweep orphans at startup, after completion or hourly.

    Explicit callers/tests can request an immediate orphan sweep with
    force_orphans=True after creating an orphan between scheduled sweeps.
    """
    from services import storage
    # Maintenance owns its writes even if invoked by a source that was deleted.
    token = _sources.set(())
    try:
        with storage.db_lock:
            return _maintain_locked(force_orphans=force_orphans)
    finally:
        _sources.reset(token)


def _maintain_locked(*, force_orphans=False):
    global _orphan_checked_at
    from services import storage
    waiting, finished = 0, 0
    # COUNT on the tiny ledger avoids scanning/decoding any tables on an idle
    # tick whose hourly orphan sweep is not due.
    rows = storage.get_deletions() if len(storage.deletions_table) else []
    for row in rows:
        if row.get('state') != 'started':
            continue
        running = [(kind, rid) for kind, rid in row.get('closure', []) if active(kind, rid)]
        if not running:
            try:
                _cleanup(row)
                finished += 1
            except Exception:
                logging.getLogger(__name__).exception('Deletion cleanup will retry %s', row['id'])
            continue
        waiting += 1
        now = time.monotonic()
        since = _cancelled_at.setdefault(row['id'], now)
        if now - since >= 15 * 60:
            _cancelled_at[row['id']] = now
            for kind, rid in running:
                logging.getLogger(__name__).warning('Re-cancelling deletion worker %s %s; still waiting', kind, rid)
            _stop([(kind, rid, _load(kind, rid) or {}) for kind, rid in running])
    orphans = 0
    now = time.monotonic()
    if (force_orphans or finished or _orphan_checked_at is None
            or now - _orphan_checked_at >= ORPHAN_MAINTENANCE_S):
        _orphan_checked_at = now
        orphans = _orphans()
    return {'finished': finished, 'waiting': waiting, 'orphans': orphans}
