"""Where Argyle fell short, kept as rows so the gaps get fixed instead of noticed.

2026-10-29: a tool error vanished into the reply, an unknown tool was a dict nobody
stored, and a wrong confident answer left no trace. Finding gaps was a person using
the app and hoping to notice. Three signals land here:

  deterministic  - the router records every tool result that errored, every tool the
                   model named that does not exist, and every turn that ended with no
                   answer (kinds tool_error, no_tool, no_answer); no model cooperation.
  model-reported - the `report_gap` tool: the model calls it BEFORE telling a person it
                   cannot do something (cannot), when a person says the last answer
                   was wrong (wrong), or when it answered with less than was asked
                   (unhelpful). The person's words and the surface come from the
                   router, never from the model.
  family-taught  - a vocabulary memory (services/argyle_memory.py) is a gap the family
                   closed by hand; it is kept here as kind `taught` so the fix can be
                   generalised.

Rows: {id, kind, status open|fixed|dismissed, asked, source, who, who_name, tool,
       message, detail, prior, first_at, last_at, count, fixed_version}.
The same gap twice is one row with count 2. Service trouble (HA offline, the AI
overloaded, a permission refusal, an honest 'which one') is not a gap and is never
recorded. Nothing here may ever break a reply: every entry point swallows.
"""
import re
import time
import uuid

from services import storage

KINDS = ('tool_error', 'no_tool', 'no_answer', 'cannot', 'wrong', 'unhelpful', 'taught')
STATUSES = ('open', 'fixed', 'dismissed')
# Not capability gaps: the service was down, the person was not allowed, or the
# tool asked an honest question back.
NOISE = ('not connected', 'overloaded', 'try again', 'budget', 'not available to this account',
         'needs your phone', 'needs a parent', 'only a parent', 'not exposed', 'which ', 'session',
         'token')


def _norm(text):
    return re.sub(r'\d+', '#', re.sub(r'\s+', ' ', str(text or '').casefold())).strip()[:160]


def prior_tail(history):
    """The last thing Argyle said in this conversation, for a 'that was wrong'."""
    for msg in reversed(history or []):
        if (msg or {}).get('role') == 'assistant' and msg.get('content'):
            return str(msg['content'])[:500]
    return ''


def _noise(message):
    m = str(message or '').casefold()
    return any(n in m for n in NOISE)


def record(kind, asked='', source='', acting_member=None, tool='', message='', detail='', prior=''):
    """One gap, deduplicated by what it is: the same tool failing the same way, or the
    same thing being asked for that nothing covers, counts up instead of piling up."""
    try:
        if kind not in KINDS:
            return None
        if kind in ('tool_error', 'no_tool', 'no_answer') and _noise(message):
            return None
        key = f"{kind}|{tool}|{_norm(message or detail or asked)}"
        now = time.time()
        rows = storage.get_argyle_gaps()
        for row in rows:
            if row.get('fingerprint') == key and row.get('status') != 'dismissed':
                patch = {'count': int(row.get('count') or 1) + 1, 'last_at': now, 'asked': asked or row.get('asked'),
                         'source': source or row.get('source')}
                if row.get('status') == 'fixed':
                    patch['status'] = 'open'       # it came back after a fix: open again
                    patch['reopened'] = True
                storage.update_argyle_gap(row['id'], patch)
                return {**row, **patch}
        row = {'id': uuid.uuid4().hex, 'kind': kind, 'status': 'open', 'fingerprint': key,
               'asked': str(asked or '')[:500], 'source': source or '', 'who': (acting_member or {}).get('id') or '',
               'who_name': (acting_member or {}).get('name') or '', 'tool': tool or '',
               'message': str(message or '')[:500], 'detail': str(detail or '')[:1000], 'prior': str(prior or '')[:500],
               'first_at': now, 'last_at': now, 'count': 1, 'fixed_version': ''}
        storage.add_argyle_gap(row)
        return row
    except Exception:
        return None


def record_turn(asked='', source='', acting_member=None, executed_results=None, no_answer=False):
    """The deterministic signals of one agent turn. Called by the router after the tool
    loop; never raises, never changes the reply."""
    try:
        for sig, res in (executed_results or {}).items():
            tool = str(sig).split(':', 1)[0]
            if tool == 'report_gap' or not isinstance(res, dict):
                continue
            err = res.get('error')
            if err and str(err).startswith('Unknown tool'):
                record('no_tool', asked=asked, source=source, acting_member=acting_member, tool=tool, message=str(err))
            elif err:
                record('tool_error', asked=asked, source=source, acting_member=acting_member, tool=tool,
                       message=res.get('message') or str(err), detail=str(res.get('traceback') or '')[-600:])
            elif res.get('status') == 'error':
                record('tool_error', asked=asked, source=source, acting_member=acting_member, tool=tool,
                       message=res.get('message') or 'error')
        if no_answer:
            record('no_answer', asked=asked, source=source, acting_member=acting_member, message=asked)
    except Exception:
        pass


def report(what_was_asked='', what_was_missing='', kind='cannot', asked='', prior='', acting_member=None, source=''):
    """The model's own note. `asked` and `prior` come from the router."""
    kind = kind if kind in ('cannot', 'wrong', 'unhelpful') else 'cannot'
    missing = ' '.join(str(what_was_missing or '').split())
    said = asked or what_was_asked
    if not said and not missing:
        return {'status': 'error', 'message': 'Say what was asked and what was missing.'}
    row = record(kind, asked=said, source=source, acting_member=acting_member, tool='',
                 message=missing or said, detail=what_was_asked, prior=prior)
    if not row:
        return {'status': 'error', 'message': 'I could not note that.'}
    if kind == 'wrong':
        return {'status': 'success', 'gap': row,
                'message': 'Noted that the last answer was wrong; it will be looked at. Answer again from the tools, not from memory.'}
    return {'status': 'success', 'gap': row,
            'message': f"Noted for the developer: {missing or said}. Tell the person plainly that you cannot do that yet and that it is noted."}


def list_gaps(status='open'):
    rows = storage.get_argyle_gaps()
    if status and status != 'all':
        rows = [r for r in rows if r.get('status') == status]
    rows.sort(key=lambda r: (-(r.get('last_at') or 0)))
    return rows


def set_status(gap_id, status, version=''):
    if status not in STATUSES:
        return {'status': 'error', 'message': 'Status is open, fixed or dismissed.'}
    row = next((r for r in storage.get_argyle_gaps() if r.get('id') == gap_id), None)
    if not row:
        return {'status': 'error', 'message': 'No such gap.'}
    patch = {'status': status, 'fixed_version': version if status == 'fixed' else row.get('fixed_version', ''),
             'reopened': False}
    storage.update_argyle_gap(gap_id, patch)
    return {'status': 'success', 'gap': {**row, **patch}}


def report_markdown(status='open'):
    """The list as a note a developer can read: paste it to whoever fixes the tools."""
    rows = list_gaps(status)
    out = [f"# Argyle gaps ({status}, {len(rows)})", '']
    for r in rows:
        when = time.strftime('%Y-%m-%d', time.localtime(r.get('last_at') or 0))
        out.append(f"- **{r.get('kind')}** x{r.get('count') or 1} ({r.get('source') or '?'}, {when}"
                   f"{', ' + r['who_name'] if r.get('who_name') else ''}): asked \"{r.get('asked') or ''}\""
                   + (f"; tool `{r['tool']}`" if r.get('tool') else '')
                   + (f"; {r['message']}" if r.get('message') else '')
                   + (f"; last answer: \"{r['prior']}\"" if r.get('prior') else '')
                   + f"  [{r.get('id')}]")
    return '\n'.join(out) + '\n'
