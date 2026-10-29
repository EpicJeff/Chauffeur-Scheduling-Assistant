"""What the family taught Argyle, kept as rows and read on every surface.

2026-10-29: "remember X" wrote one text blob (settings['ai_memory']) that only the
solver's pattern-deduction prompt ever read. Argyle's chat and voice never saw it,
every save overwrote the last, and no page listed it. A correction made in one
typed chat therefore never reached the next spoken one.

Rows: {id, kind, text, phrase, entity_ids, by, by_name, source, ts}.
  preference  - how to answer ("say which car", "every lock, never a summary").
  vocabulary  - what a phrase means in this house: `phrase` names `entity_ids`,
                and the house tool answers to the phrase as a name.
Parents and adults teach; anyone may ask what was taught. The old blob is
migrated into one row the first time the rows are read; it stays in settings
for the solver prompt that still reads it.
"""
import time
import uuid

from services import storage

KINDS = ('preference', 'vocabulary')
PROMPT_ROWS = 60


def _trusted(member) -> bool:
    from services import access
    return bool((member or {}).get('id')) and not access.is_house(member) and member.get('role') in ('parent', 'adult')


def _migrate():
    settings = storage.get_settings()
    blob = str(settings.get('ai_memory') or '').strip()
    if not blob or settings.get('ai_memory_migrated'):
        return
    storage.add_argyle_memory({'id': uuid.uuid4().hex, 'kind': 'preference', 'text': blob, 'phrase': '',
                               'entity_ids': [], 'by': 'legacy', 'by_name': 'earlier memory',
                               'source': 'settings', 'ts': time.time()})
    settings['ai_memory_migrated'] = True
    storage.update_settings(settings)


def list_memories():
    _migrate()
    rows = storage.get_argyle_memories()
    rows.sort(key=lambda r: r.get('ts') or 0)
    return rows


def vocabulary():
    """{entity_id: [phrase, ...]} from the vocabulary rows; the house tool reads it as names."""
    out = {}
    try:
        for row in list_memories():
            if row.get('kind') == 'vocabulary' and row.get('phrase'):
                for eid in row.get('entity_ids') or []:
                    out.setdefault(eid, []).append(row['phrase'])
    except Exception:
        return {}
    return out


def prompt_block() -> str:
    try:
        rows = list_memories()
    except Exception:
        rows = []
    lines = []
    for row in rows[-PROMPT_ROWS:]:
        if row.get('kind') == 'vocabulary' and row.get('phrase'):
            ids = ', '.join(row.get('entity_ids') or [])
            lines.append(f"- '{row['phrase']}' means: {row.get('text') or row['phrase']} (entities: {ids})")
        else:
            lines.append(f"- {row.get('text')}")
    head = ("\nWHAT THE FAMILY TAUGHT ME (a parent or adult said these; follow them on every surface, typed or "
            "spoken). When a parent or adult corrects what a word means, or how to answer, or says 'remember', "
            "call memory(action='remember') without being asked, with kind='vocabulary' and the entity ids from "
            "find when it is what a phrase means, and say what you remembered. A child's correction is answered, "
            "never stored.\n")
    return head + ('\n'.join(lines) + '\n' if lines else '- nothing yet.\n')


def remember(text='', kind='preference', phrase='', entity_ids=None, acting_member=None, source=''):
    if not _trusted(acting_member):
        return {'status': 'refused', 'message': 'Only a parent or adult can teach me that; ask one to say it.'}
    text = str(text or '').strip()
    kind = kind if kind in KINDS else 'preference'
    phrase = ' '.join(str(phrase or '').split())
    entity_ids = [str(e) for e in (entity_ids or []) if e]
    if kind == 'vocabulary':
        if not phrase or not entity_ids:
            return {'status': 'error', 'message': 'A vocabulary memory needs the phrase and the entity ids it means.'}
        from services import ha_api
        known = {s.get('entity_id') for s in ha_api.get_states()}
        missing = [e for e in entity_ids if e not in known]
        if missing:
            return {'status': 'error', 'message': f"Not Home Assistant entities: {', '.join(missing)}."}
        text = text or f'{phrase} means these'
    if not text:
        return {'status': 'error', 'message': 'What should I remember?'}
    for row in list_memories():
        if row.get('kind') == kind and row.get('text') == text and (row.get('phrase') or '') == phrase:
            return {'status': 'success', 'memory': row, 'message': 'I already had that.'}
    row = {'id': uuid.uuid4().hex, 'kind': kind, 'text': text, 'phrase': phrase, 'entity_ids': entity_ids,
           'by': acting_member.get('id'), 'by_name': acting_member.get('name') or acting_member.get('id'),
           'source': source or 'chat', 'ts': time.time()}
    storage.add_argyle_memory(row)
    if kind == 'vocabulary':
        # A phrase the house did not understand is a gap the family closed by hand;
        # kept so the fix can be generalised (services/argyle_gaps.py).
        try:
            from services import argyle_gaps
            argyle_gaps.record('taught', asked=f"'{phrase}'", source=source or 'chat', acting_member=acting_member,
                               tool='house', message=text, detail=', '.join(entity_ids))
        except Exception:
            pass
    what = f"'{phrase}' means {text}" if kind == 'vocabulary' else text
    return {'status': 'success', 'memory': row, 'message': f'Remembered: {what}.'}


def forget(memory_id='', text='', acting_member=None):
    if not _trusted(acting_member):
        return {'status': 'refused', 'message': 'Only a parent or adult can make me forget that.'}
    rows = list_memories()
    if memory_id:
        hit = [r for r in rows if r.get('id') == memory_id]
    else:
        words = set(str(text or '').casefold().split())
        hit = [r for r in rows if words and words <= set(
            f"{r.get('phrase') or ''} {r.get('text') or ''}".casefold().split())] if words else []
    if not hit:
        return {'status': 'error', 'message': 'I have no memory like that.'}
    if len(hit) > 1:
        return {'status': 'error', 'message': 'Which one? ' + '; '.join(f"{r['id'][:8]}: {r.get('text')}" for r in hit)}
    storage.delete_argyle_memory(hit[0]['id'])
    return {'status': 'success', 'memory': hit[0], 'message': f"Forgot: {hit[0].get('text')}."}


def handle(action='remember', text='', kind='preference', phrase='', entity_ids=None, memory_id='',
           acting_member=None, source=''):
    try:
        if action == 'list':
            rows = list_memories()
            return {'status': 'success', 'memories': rows,
                    'message': 'Nothing taught yet.' if not rows else f'{len(rows)} things the family taught me.'}
        if action == 'forget':
            return forget(memory_id=memory_id, text=text, acting_member=acting_member)
        if action == 'remember':
            return remember(text=text, kind=kind, phrase=phrase, entity_ids=entity_ids,
                            acting_member=acting_member, source=source)
        return {'status': 'error', 'message': 'Unknown memory action. Use remember, forget or list.'}
    except Exception:
        return {'status': 'error', 'message': 'I could not reach my memory just now.'}
