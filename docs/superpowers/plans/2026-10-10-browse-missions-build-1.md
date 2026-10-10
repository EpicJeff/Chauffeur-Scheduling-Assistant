# Browse missions, build 1 — mail search and a photo on a thread — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Argyle can search the family's own mailbox (`search_mail`, `read_mail`) from a mission or a chat, and a thread can take a photo whose label text is read once by the vision tier and can answer a waiting mission.

**Architecture:** `services/mail_search.py` opens a read-only IMAP connection with the intake mailbox's credentials, runs one SEARCH, and returns snippets; nothing moves the ingest cursor. Two registry tools wrap it with the parent/adult gate and join the missions' READ set. `threads.add_photo` stores the image beside moments (`storage.save_media_file`), appends a `photo` history entry, runs one capped vision call (`threads.read_photo`) and, when the thread's mission is waiting on a question, answers it with the transcription. The thread card's details and the PWA House card get a camera button; the /threads timeline draws the thumbnail.

**Tech Stack:** as the situations builds (FastAPI, TinyDB-over-SQLite, Alpine + vanilla JS, precompiled Tailwind, scenario test scripts, `live_app` + playwright for live tests). `imaplib` from the standard library; `model_pools.call_pool_json(..., images=[...])` for vision.

**Spec:** `docs/superpowers/specs/2026-10-10-browse-missions-design.md` §3 (and §5 for settings, tests). Build 2 (the browse step) and build 3 (the conversation) have their own plans.

## Global Constraints

- Run from `E:\repositories\Chauffeur\chauffeur` with `..\venv\Scripts\python.exe`; tests with `HA_BASE_URL` unset.
- Gate for this build: `python tools/test.py mail_tools thread_photo missions_engine missions_pins threads email_ingest situation agent_v2_bridge tailwind_build` plus the live test of Task 4. Never the full sweep.
- Mail tools are parent/adult only, read-only, move no cursor, make no LLM call, skip attachments; a 400-character snippet and a 6,000-character body cap (spec §3).
- One vision call per photo, under `thread_cap_photo_reads` (default 20/day); a failed or capped read leaves "photo added (not read)".
- `tests/test_agent_v2_bridge.py` pins the registry only grows; `tests/test_missions_pins.py` pins that `missions.py` never names the mailer and that only `model_pools.api_key_for_pool` reads the paid key.
- `python tools/build_tailwind.py` after any template class change; `tests/test_tailwind_build.py` must pass.
- Every commit bumps `config.yaml` (`2.499.343` onward, +1 per commit; v2.499.342 is the plan commit), message ends `(vX.Y.Z)`, push. Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Persisted prose is normal English.

## Review Focus

1. **A mailbox that is not configured** (no `ingest_email_user`): `search_mail` says so plainly and never raises into the mission step. Pinned in Task 1 (`scenario_no_mailbox_is_an_honest_answer`).
2. **A query with IMAP-special characters** (quotes, parentheses, non-ASCII): the search string is quoted and escaped; no injection, no crash. Pinned in Task 1 (`scenario_query_is_quoted_for_imap`).
3. **A child uploading a photo to a thread they do not own**: refused with 403; the owner child may. Pinned in Task 3 (`scenario_photo_gates`).
4. **A photo that is not an image** (PDF, text): refused with 400 before any storage or vision call. Pinned in Task 3 (`scenario_non_image_is_refused`).
5. **A waiting mission on another thread**: a photo on thread A never answers a mission waiting on thread B. Pinned in Task 3 (`scenario_photo_answers_only_its_own_mission`).

---

### Task 1: `services/mail_search.py`

**Files:**
- Create: `services/mail_search.py`
- Test: `tests/test_mail_tools.py` (new)

**Interfaces:**
- Consumes: `email_ingest._mailbox(settings)` (host, user, password), `email_ingest._read_uid(conn, uid)` (uid, from, subject, text, message_id), `email_ingest._decode_header`.
- Produces:
  - `mail_search.search(query: str, since_days: int = 365, limit: int = 5, settings=None) -> dict` → `{'status': 'success', 'hits': [{uid, from, date, subject, snippet}]}` or `{'status': 'error', 'message': str}`.
  - `mail_search.read(uid: int, settings=None) -> dict` → `{'status': 'success', 'from', 'date', 'subject', 'text'}` (text capped at 6,000 chars) or error.
  - `mail_search._connect(settings) -> imaplib.IMAP4` (test seam: tests replace it with a fake).
  - `mail_search.SNIPPET_CHARS = 400`, `BODY_CHARS = 6000`, `MAX_LIMIT = 10`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mail_tools.py
"""search_mail / read_mail: the family's own mailbox, read-only, parent/adult
only, no cursor moved, no model called. Spec 2026-10-10 browse missions §3."""
import datetime
import email.utils

from harness import check  # noqa: F401
from services import storage, mail_search

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child'}


class FakeIMAP:
    """Enough of imaplib for search/read: uid SEARCH and uid FETCH."""
    def __init__(self, messages):
        self.messages = messages           # uid -> raw RFC822 bytes
        self.searches = []
        self.selected = None
        self.logged_out = False

    def login(self, u, p): return ('OK', [b'ok'])
    def select(self, box, readonly=False):
        self.selected = (box, readonly); return ('OK', [b'1'])
    def uid(self, cmd, *args):
        if cmd == 'SEARCH':
            self.searches.append(args)
            crit = ' '.join(str(a) for a in args if a is not None).lower()
            uids = [u for u, raw in self.messages.items()
                    if any(w.strip('"').lower() in raw.decode('utf-8', 'ignore').lower()
                           for w in crit.replace('or', ' ').replace('text', ' ').replace('from', ' ').replace('subject', ' ').split()
                           if w and w[0] == '"')]
            return ('OK', [' '.join(str(u) for u in sorted(uids)).encode()])
        if cmd == 'FETCH':
            u = int(args[0])
            return ('OK', [(b'', self.messages[u])]) if u in self.messages else ('NO', [None])
        return ('NO', [None])
    def logout(self): self.logged_out = True


def _raw(from_addr, subject, body, when):
    return (f"From: {from_addr}\r\nSubject: {subject}\r\nDate: {email.utils.format_datetime(when)}\r\n"
            f"Message-ID: <{subject.replace(' ', '')}@x>\r\nContent-Type: text/plain\r\n\r\n{body}").encode()


def _reset(messages=None):
    storage.app_state_table.truncate()
    storage.get_settings = lambda: {'ingest_email_host': 'imap.example', 'ingest_email_user': 'fam@example.com',
                                    'ingest_email_password': 'pw'}
    fake = FakeIMAP(messages or {})
    mail_search._connect = lambda settings: fake
    return fake


def scenario_search_returns_snippets_newest_first_and_moves_no_cursor():
    now = datetime.datetime.now(datetime.timezone.utc)
    fake = _reset({
        11: _raw('orders@cafeappliances.com', 'Your Cafe order', 'Model CDT805P2N3S1 shipped. ' + 'x' * 900, now - datetime.timedelta(days=30)),
        12: _raw('school@example.org', 'Field trip', 'Permission slip due', now - datetime.timedelta(days=2)),
        13: _raw('orders@cafeappliances.com', 'Cafe warranty', 'Your dishwasher warranty', now - datetime.timedelta(days=1)),
    })
    storage.set_app_state('email_ingest_last_uid:fam@example.com', 13)
    res = mail_search.search('cafe dishwasher')
    check(res['status'] == 'success' and [h['uid'] for h in res['hits']] == [13, 11], f"newest first, matching only: {res}")
    h = res['hits'][1]
    check(len(h['snippet']) <= mail_search.SNIPPET_CHARS and 'CDT805P2N3S1' in h['snippet'], f"a capped snippet: {len(h['snippet'])}")
    check(h['from'] == 'orders@cafeappliances.com' and h['subject'] == 'Your Cafe order' and h['date'], "sender, subject, date")
    check(fake.selected == ('INBOX', True), "read-only select")
    check(storage.get_app_state('email_ingest_last_uid:fam@example.com') == 13, "the ingest cursor never moves")
    check(fake.logged_out, "the connection is closed")


def scenario_read_returns_the_body_capped():
    now = datetime.datetime.now(datetime.timezone.utc)
    _reset({7: _raw('a@b.c', 'Long one', 'y' * 9000, now)})
    res = mail_search.read(7)
    check(res['status'] == 'success' and len(res['text']) == mail_search.BODY_CHARS and res['subject'] == 'Long one', f"capped body: {res.get('status')}")
    res = mail_search.read(99)
    check(res['status'] == 'error', "a missing uid is an honest error")


def scenario_no_mailbox_is_an_honest_answer():
    _reset()
    storage.get_settings = lambda: {}
    res = mail_search.search('anything')
    check(res['status'] == 'error' and 'mailbox' in res['message'].lower(), f"no mailbox configured: {res}")


def scenario_query_is_quoted_for_imap():
    fake = _reset({})
    mail_search.search('caf"é (dish)washer', since_days=10)
    crit = ' '.join(str(a) for a in fake.searches[-1])
    check('"' in crit and '(dish)washer' not in crit.replace('"(dish)washer"', ''), f"words are quoted, specials neutralised: {crit}")
    check('SINCE' in crit, "the window is a SINCE clause")
    check(not any(len(str(a)) > 400 for a in fake.searches[-1]), "a runaway query is cut")


def scenario_limit_is_capped():
    now = datetime.datetime.now(datetime.timezone.utc)
    _reset({i: _raw('a@b.c', f'hit {i}', 'word', now) for i in range(1, 30)})
    res = mail_search.search('word', limit=50)
    check(len(res['hits']) == mail_search.MAX_LIMIT, f"never more than {mail_search.MAX_LIMIT}: {len(res['hits'])}")


SCENARIOS = [scenario_search_returns_snippets_newest_first_and_moves_no_cursor, scenario_read_returns_the_body_capped,
             scenario_no_mailbox_is_an_honest_answer, scenario_query_is_quoted_for_imap, scenario_limit_is_capped]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

Check the real cursor key first: `email_ingest._cursor_key(user)` returns it; use that in the test (`from services import email_ingest; email_ingest._cursor_key('fam@example.com')`) instead of the literal if they differ.

- [ ] **Step 2: Run it to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_mail_tools.py`
Expected: `ImportError: cannot import name 'mail_search'`.

- [ ] **Step 3: Create `services/mail_search.py`**

```python
"""The family's own mailbox, searched. Spec: docs/superpowers/specs/2026-10-10-browse-missions-design.md §3.

Read-only: a fresh IMAP connection, SELECT INBOX readonly, one SEARCH, a few
FETCHes, logout. The ingest cursor (email_ingest) is never touched; no model
is called; attachments are not read. The tools in agent_tools_v2 gate who
may ask (parent/adult); this module trusts its caller.
"""
import datetime
import email
import imaplib
import logging
import re
from typing import Optional

from services import storage

logger = logging.getLogger(__name__)

SNIPPET_CHARS = 400
BODY_CHARS = 6000
MAX_LIMIT = 10
QUERY_CHARS = 200


def _connect(settings: dict):
    """Test seam: tests replace this with a fake IMAP object."""
    from services.email_ingest import _mailbox
    host, user, password = _mailbox(settings)
    conn = imaplib.IMAP4_SSL(host)
    conn.login(user, password)
    return conn


def _configured(settings: dict) -> bool:
    from services.email_ingest import _mailbox
    _, user, password = _mailbox(settings)
    return bool(user and password)


def _quote(word: str) -> str:
    # IMAP quoted-string: backslash-escape quotes and backslashes; drop control chars.
    w = re.sub(r'[\x00-\x1f]', '', word).replace('\\', '\\\\').replace('"', '\\"')
    return f'"{w}"'


def _criteria(query: str, since_days: int) -> list:
    words = [w for w in re.split(r'\s+', (query or '').strip()[:QUERY_CHARS]) if w]
    since = (datetime.date.today() - datetime.timedelta(days=max(1, int(since_days or 365)))).strftime('%d-%b-%Y')
    if not words:
        return ['SINCE', since]
    # Each word may match FROM, SUBJECT or TEXT; words are OR'd so a model's
    # natural query ("cafe dishwasher") finds either.
    terms = []
    for w in words:
        q = _quote(w)
        terms.append(f'(OR (OR FROM {q} SUBJECT {q}) TEXT {q})')
    expr = terms[0]
    for t in terms[1:]:
        expr = f'(OR {expr} {t})'
    return ['SINCE', since, expr]


def _parse(raw: bytes, uid: int) -> dict:
    from services.email_ingest import _decode_header, _from_address, _body_text
    msg = email.message_from_bytes(raw)
    date = ''
    try:
        d = email.utils.parsedate_to_datetime(msg.get('Date', ''))
        date = d.isoformat()
    except Exception:
        pass
    return {'uid': uid, 'from': _from_address(msg), 'date': date,
            'subject': _decode_header(msg.get('Subject', '')) or '(no subject)',
            'text': _body_text(msg)}


def _fetch(conn, uid: int) -> Optional[dict]:
    status, data = conn.uid('FETCH', str(uid), '(RFC822)')
    if status != 'OK' or not data or data[0] is None:
        return None
    return _parse(data[0][1], uid)


def search(query: str, since_days: int = 365, limit: int = 5, settings: dict = None) -> dict:
    settings = settings if settings is not None else (storage.get_settings() or {})
    if not _configured(settings):
        return {'status': 'error', 'message': 'No family mailbox is set up (Intake settings).'}
    limit = max(1, min(int(limit or 5), MAX_LIMIT))
    try:
        conn = _connect(settings)
        try:
            conn.select('INBOX', readonly=True)
            status, data = conn.uid('SEARCH', None, *_criteria(query, since_days))
            if status != 'OK':
                return {'status': 'error', 'message': f'mailbox search failed: {status}'}
            uids = sorted((int(u) for u in (data[0].split() if data and data[0] else [])), reverse=True)[:limit]
            hits = []
            for u in uids:
                m = _fetch(conn, u)
                if not m:
                    continue
                hits.append({'uid': u, 'from': m['from'], 'date': m['date'], 'subject': m['subject'],
                             'snippet': ' '.join(m['text'].split())[:SNIPPET_CHARS]})
            return {'status': 'success', 'hits': hits}
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[mail_search] search failed: {e}")
        return {'status': 'error', 'message': f'mailbox error: {str(e)[:120]}'}


def read(uid: int, settings: dict = None) -> dict:
    settings = settings if settings is not None else (storage.get_settings() or {})
    if not _configured(settings):
        return {'status': 'error', 'message': 'No family mailbox is set up (Intake settings).'}
    try:
        conn = _connect(settings)
        try:
            conn.select('INBOX', readonly=True)
            m = _fetch(conn, int(uid))
            if not m:
                return {'status': 'error', 'message': 'No such message.'}
            return {'status': 'success', 'uid': int(uid), 'from': m['from'], 'date': m['date'],
                    'subject': m['subject'], 'text': m['text'][:BODY_CHARS]}
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[mail_search] read failed: {e}")
        return {'status': 'error', 'message': f'mailbox error: {str(e)[:120]}'}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_mail_tools.py`
Expected: `5/5 scenarios passed`. If `scenario_query_is_quoted_for_imap` trips on the FakeIMAP's crude matcher, fix the fake's parsing, not the criteria: the assertion is about quoting.

- [ ] **Step 5: Commit**

Bump `config.yaml` to `2.499.343`.

```bash
git add services/mail_search.py tests/test_mail_tools.py config.yaml
git commit -m "feat(mail): read-only search and read of the family mailbox, cursor untouched, no model (v2.499.343)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 2: The tools — `search_mail`, `read_mail` in the registry, the router and the missions' READ set

**Files:**
- Modify: `services/agent_tools_v2.py` (tool functions beside the situation tools; schemas in `get_available_tools`; Pydantic models; `TOOL_SCHEMAS`; handlers; `TOOL_HANDLERS`)
- Modify: `services/agent_router.py` (the situation-tools dispatch tuple gains the two names)
- Modify: `services/missions.py` (`READ_TOOLS`)
- Test: `tests/test_mail_tools.py`

**Interfaces:**
- Produces: `agent_tools_v2.search_mail(query, since_days=365, limit=5, acting_member=None)`, `agent_tools_v2.read_mail(uid, acting_member=None)`; `handle_search_mail`, `handle_read_mail` for the registry (trusted admin context, as `handle_list_situations`); registry names `search_mail`, `read_mail`; both in `missions.READ_TOOLS`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_mail_tools.py`)

```python
from services import agent_tools_v2 as tools, missions, agent_router  # noqa: E402


def scenario_tools_gate_and_read_through():
    now = datetime.datetime.now(datetime.timezone.utc)
    _reset({3: _raw('orders@cafeappliances.com', 'Your Cafe order', 'Model CDT805P2N3S1', now)})
    res = tools.search_mail('cafe', acting_member=MOM)
    check(res['status'] == 'success' and 'CDT805P2N3S1' in res['message'] and res['hits'], f"a parent searches: {res}")
    res = tools.search_mail('cafe', acting_member=KID)
    check(res['status'] == 'error' and 'parent or adult' in res['message'], "a child is refused")
    res = tools.search_mail('cafe', acting_member=None)
    check(res['status'] == 'error', "no actor is refused (an anonymous panel)")
    res = tools.read_mail(3, acting_member=MOM)
    check(res['status'] == 'success' and 'CDT805P2N3S1' in res['message'], f"read through: {res}")


def scenario_registry_and_missions_know_the_tools():
    for name in ('search_mail', 'read_mail'):
        check(name in tools.TOOL_HANDLERS and name in tools.TOOL_SCHEMAS, f"{name} in the registry")
        check(name in {t['name'] for t in tools.get_available_tools()}, f"{name} offered to the model")
        check(name in missions.READ_TOOLS, f"{name} is a mission READ tool")
    src = open('services/agent_router.py', encoding='utf-8').read()
    check('"search_mail"' in src and '"read_mail"' in src, "the router dispatches both")
    now = datetime.datetime.now(datetime.timezone.utc)
    _reset({3: _raw('a@b.c', 'Hit', 'word', now)})
    out = tools.execute_tool('search_mail', {'query': 'word'})
    check(out.get('status') == 'success' and out.get('hits'), f"the registry executes it for a mission: {out}")
```

Add both to `SCENARIOS`.

- [ ] **Step 2: Run to verify they fail**

Run: `..\venv\Scripts\python.exe tests\test_mail_tools.py`
Expected: FAIL with `AttributeError: module 'services.agent_tools_v2' has no attribute 'search_mail'`.

- [ ] **Step 3: The tool functions** — in `services/agent_tools_v2.py`, after `answer_ask`:

```python
# --- The family's mailbox (browse missions §3): read-only, parents and adults. --

def _mail_reader(acting_member: dict):
    """ALLOWLIST: a resolved parent or adult. An anonymous panel (actor None)
    and a child, helper or guest are refused the same way."""
    if not (acting_member or {}).get('id') or (acting_member or {}).get('role') not in ('parent', 'adult'):
        return {"status": "error", "message": "Only a signed-in parent or adult can search the family mailbox."}
    return None


def search_mail(query: str, since_days: int = 365, limit: int = 5, acting_member: dict = None) -> Dict[str, Any]:
    refusal = _mail_reader(acting_member)
    if refusal:
        return refusal
    from services import mail_search as _ms
    res = _ms.search(query or '', since_days=since_days or 365, limit=limit or 5)
    if res.get('status') != 'success':
        return {"status": "error", "message": res.get('message') or 'mailbox error'}
    hits = res['hits']
    if not hits:
        return {"status": "success", "message": f"Nothing in the family mailbox matches '{query}'.", "hits": []}
    lines = [f"- uid {h['uid']} · {h['date'][:10]} · {h['from']} · {h['subject']}: {h['snippet'][:160]}" for h in hits]
    return {"status": "success", "message": "Found in the family mailbox:\n" + '\n'.join(lines), "hits": hits}


def read_mail(uid: int, acting_member: dict = None) -> Dict[str, Any]:
    refusal = _mail_reader(acting_member)
    if refusal:
        return refusal
    from services import mail_search as _ms
    res = _ms.read(uid)
    if res.get('status') != 'success':
        return {"status": "error", "message": res.get('message') or 'mailbox error'}
    return {"status": "success", "message": f"{res['subject']} — from {res['from']} {res['date'][:10]}\n\n{res['text']}", **res}
```

- [ ] **Step 4: Schemas offered to the model** — in `get_available_tools()`, after the `answer_ask` entry:

```python
        {
            "name": "search_mail",
            "description": "Search the family's own mailbox for a thing's details: an order confirmation, a model number, a warranty, a school letter ('find the email about the dishwasher', 'what did the school send about the trip?'). Parent/adult only. Returns sender, date, subject and a snippet per hit; use read_mail for the whole message.",
            "parameters": {"type": "object",
                           "properties": {"query": {"type": "string", "description": "A few words to match in sender, subject or body."},
                                          "since_days": {"type": "integer", "description": "How far back, default 365."},
                                          "limit": {"type": "integer", "description": "How many, default 5, max 10."}},
                           "required": ["query"]}
        },
        {
            "name": "read_mail",
            "description": "Read one message from the family mailbox by the uid search_mail returned. Parent/adult only.",
            "parameters": {"type": "object", "properties": {"uid": {"type": "integer"}}, "required": ["uid"]}
        },
```

- [ ] **Step 5: Registry models, schemas, handlers** — near `AnswerAskTool`:

```python
class SearchMailTool(BaseModel):
    """Search the family's own mailbox for a thing's details; returns sender, date, subject, snippet per hit."""
    query: str = Field(..., description="A few words to match in sender, subject or body.")
    since_days: Optional[int] = Field(365, description="How far back.")
    limit: Optional[int] = Field(5, description="How many, max 10.")

class ReadMailTool(BaseModel):
    """Read one message from the family mailbox by uid."""
    uid: int
```

In `TOOL_SCHEMAS`: `"search_mail": SearchMailTool.model_json_schema(), "read_mail": ReadMailTool.model_json_schema(),`.

Handlers near `handle_answer_ask`:

```python
def handle_search_mail(args: dict) -> dict:
    # Registry context is the trusted admin/mission loop: the parent of record reads.
    return search_mail(args.get('query') or '', since_days=args.get('since_days') or 365,
                       limit=args.get('limit') or 5, acting_member=_registry_parent())

def handle_read_mail(args: dict) -> dict:
    return read_mail(int(args.get('uid') or 0), acting_member=_registry_parent())
```

In `TOOL_HANDLERS`: `"search_mail": handle_search_mail, "read_mail": handle_read_mail,`.

- [ ] **Step 6: Router and missions** — in `services/agent_router.py` the situation-tools branch tuple becomes:

```python
                elif func_name in ("list_situations", "next_situation", "explain_situation", "act_on_situation",
                                   "start_ask", "mark_ask_sent", "answer_ask", "search_mail", "read_mail"):
```

(the branch already resolves the actor, substitutes the parent of record for voice, and filters kwargs by signature). In `services/missions.py` add `'search_mail', 'read_mail',` to `READ_TOOLS`.

- [ ] **Step 7: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_mail_tools.py` and `..\venv\Scripts\python.exe tools\test.py agent_v2_bridge missions_engine missions_pins triage situation`
Expected: `7/7 scenarios passed`; the related files green (the registry grew by two; the missions catalog lists two more READ tools).

- [ ] **Step 8: Commit**

Bump `config.yaml` to `2.499.344`.

```bash
git add services/agent_tools_v2.py services/agent_router.py services/missions.py tests/test_mail_tools.py config.yaml
git commit -m "feat(mail): search_mail and read_mail tools for parents, in the registry, the router and the missions' READ set (v2.499.344)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 3: A photo on a thread — storage, the vision read, the waiting mission

**Files:**
- Modify: `services/threads.py` (`add_photo`, `read_photo`, `PHOTO_SYSTEM`)
- Modify: `main.py` (`POST /api/threads/{thread_id}/photo`)
- Modify: `models/schemas.py`, `services/settings_registry.py`, `templates/components/missions_page.html` (`thread_cap_photo_reads`)
- Modify: `services/auth.py` RULES if `/api/threads/*` POSTs are not already SIGNED_IN (check `auth.resolve('POST', '/api/threads/x/note')` first; mirror it)
- Test: `tests/test_thread_photo.py` (new)

**Interfaces:**
- Consumes: `storage.save_media_file(data, mime) -> {'id','url','mime'}`, `storage.append_thread_history`, `storage.update_thread_history_entry(thread_id, match, fields)`, `model_pools.call_pool_json('vision', key, system, prompt, images=[{'mime','b64'}], ...)`, `situations._bump_call(kind, cap)`.
- Produces:
  - `threads.add_photo(thread_id, data: bytes, mime: str, who: str | None, caption: str = '') -> dict` → `{'status': 'ok', 'entry': {...}, 'read': bool}`; appends `{kind: 'photo', url, media_id, text, who, caption}`; runs the read; answers a waiting mission on this thread.
  - `threads.read_photo(thread_id, media_id, data, mime) -> str | None` — the transcription, or None (cap, no key, failure). `threads._pool_call` is the seam (already exists).
  - `threads.PHOTO_SYSTEM`, `threads.CAP_PHOTO_DEFAULT = 20`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_thread_photo.py
"""A photo on a thread: stored beside moments, read once by the vision tier,
answers a waiting mission on that thread. Spec 2026-10-10 browse missions §3."""
import base64
import time

from harness import check  # noqa: F401
from services import storage, threads, situations, missions

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
CALLS = []


def _reset():
    CALLS.clear()
    for t in (storage.threads_table, storage.members_table, storage.app_state_table, storage.missions_table,
              storage.mission_steps_table):
        t.truncate()
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


def _fake_pool(reply):
    def f(tier, key, system, prompt, **kw):
        CALLS.append({'tier': tier, 'kw': kw}); return reply
    return f


def scenario_photo_is_stored_read_and_logged():
    _reset()
    threads._pool_call = _fake_pool({'text': 'Model CDT805P2N3S1\nSerial LS758759B'})
    tid = threads.create('Pest control', owner_member_id='mom', created_by='mom')
    res = threads.add_photo(tid, PNG, 'image/png', 'mom', caption='the label')
    check(res['status'] == 'ok' and res['read'] is True, f"stored and read: {res}")
    h = storage.get_thread(tid)['history'][-1]
    check(h['kind'] == 'photo' and h['url'].startswith('/api/media/') and h['media_id'] and 'CDT805P2N3S1' in h['text'],
          f"the entry carries the url and the transcription: {h}")
    check(h['caption'] == 'the label' and h['who'] == 'mom', "caption and who")
    check(len(CALLS) == 1 and CALLS[0]['tier'] == 'vision' and CALLS[0]['kw'].get('images'), f"one vision call with the image: {CALLS}")
    check(storage.media_file_path(h['media_id']), "the file exists under the media root")
    check(threads.is_stalled(storage.get_thread(tid)) is None, "a photo is movement")


def scenario_cap_failure_and_no_key_leave_not_read():
    _reset()
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    storage.get_settings = lambda: {'thread_stall_days': 7}
    threads._pool_call = _fake_pool({'text': 'x'})
    res = threads.add_photo(tid, PNG, 'image/png', 'mom')
    check(res['read'] is False and storage.get_thread(tid)['history'][-1]['text'] == 'photo added (not read)' and not CALLS, "no key: stored, not read")
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7, 'thread_cap_photo_reads': 1}
    threads.add_photo(tid, PNG, 'image/png', 'mom')
    check(len(CALLS) == 1, "under the cap: read")
    res = threads.add_photo(tid, PNG, 'image/png', 'mom')
    check(len(CALLS) == 1 and res['read'] is False, "over the cap: stored, not read")
    def boom(*a, **k): raise RuntimeError('timeout')
    threads._pool_call = boom
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7}
    res = threads.add_photo(tid, PNG, 'image/png', 'mom')
    check(res['status'] == 'ok' and res['read'] is False, "a failed read is still a stored photo")


def scenario_photo_answers_only_its_own_mission():
    _reset()
    threads._pool_call = _fake_pool({'text': 'Serial LS758759B'})
    a = threads.create('A', owner_member_id='mom', created_by='mom')
    b = threads.create('B', owner_member_id='mom', created_by='mom')
    ma = storage.add_mission({'goal': 'fix A', 'origin_kind': 'thread', 'origin_ref': a, 'created_by': 'mom', 'status': 'waiting_user'})
    storage.add_mission_step(ma, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Send me a photo of the label'}})
    mb = storage.add_mission({'goal': 'fix B', 'origin_kind': 'thread', 'origin_ref': b, 'created_by': 'mom', 'status': 'waiting_user'})
    storage.add_mission_step(mb, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Which Friday?'}})
    threads.add_photo(a, PNG, 'image/png', 'mom')
    check(storage.get_mission(ma)['status'] == 'running', "the mission on A resumes")
    last = storage.get_mission_steps(ma)[-1]
    check(last['kind'] == 'note' and last['name'] == 'user_answer' and 'LS758759B' in last['result_json']['text'], f"the transcription is the answer: {last}")
    check(storage.get_mission(mb)['status'] == 'waiting_user', "the mission on B is untouched")


SCENARIOS = [scenario_photo_is_stored_read_and_logged, scenario_cap_failure_and_no_key_leave_not_read,
             scenario_photo_answers_only_its_own_mission]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_thread_photo.py`
Expected: FAIL with `AttributeError: module 'services.threads' has no attribute 'add_photo'`.

- [ ] **Step 3: `threads.add_photo` and `read_photo`** — append to `services/threads.py`:

```python
# --- a photo on a thread (browse missions §3) --------------------------------------

CAP_PHOTO_DEFAULT = 20
PHOTO_SYSTEM = (
    "You transcribe what a photo says that a repair, order or school office "
    "would ask for: model and serial numbers, dates, amounts, names, reference "
    "numbers, addresses. Verbatim, line by line, nothing inferred, nothing "
    "added. If the image shows none of that, say what it shows in one line. "
    'Return STRICT JSON: {"text": "..."}'
)
NOT_READ = 'photo added (not read)'


def read_photo(thread_id: str, media_id: str, data: bytes, mime: str) -> Optional[str]:
    """One vision-tier call under thread_cap_photo_reads; None when there is
    no key, the cap is reached, or the call fails. Never raises."""
    import base64
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return None
    from services import situations as _sit
    if not _sit._bump_call('photo', int(settings.get('thread_cap_photo_reads', CAP_PHOTO_DEFAULT))):
        return None
    thread = storage.get_thread(thread_id) or {}
    prompt = f"Thread: {thread.get('title') or ''}. The attached photo was added to it."
    try:
        res = _pool_call('vision', api_key, PHOTO_SYSTEM, prompt, timeout_s=60,
                         images=[{'mime': mime or 'image/jpeg', 'b64': base64.b64encode(data).decode()}])
    except Exception as e:
        print(f"[threads] photo read failed: {e}")
        return None
    text = (res or {}).get('text') if isinstance(res, dict) else None
    return ' '.join(str(text).split())[:2000] if text else None


def add_photo(thread_id: str, data: bytes, mime: str, who: Optional[str], caption: str = '') -> dict:
    """Store the image beside moments, log it on the thread, read it once,
    and answer a mission waiting on THIS thread with the transcription."""
    thread = storage.get_thread(thread_id)
    if not thread:
        return {'status': 'not_found'}
    saved = storage.save_media_file(data, mime)
    if not saved:
        return {'status': 'error', 'reason': 'unsupported image'}
    entry = {'kind': 'photo', 'url': saved['url'], 'media_id': saved['id'], 'text': NOT_READ,
             'who': who, 'caption': (caption or '').strip()[:200]}
    storage.append_thread_history(thread_id, entry)
    text = read_photo(thread_id, saved['id'], data, mime)
    if text:
        storage.update_thread_history_entry(thread_id, {'media_id': saved['id']}, {'text': text})
        entry['text'] = text
    # A mission waiting on a question on this thread takes the photo as the answer.
    for m in storage.get_missions(status='waiting_user'):
        if m.get('origin_kind') == 'thread' and m.get('origin_ref') == thread_id:
            answer = f"(photo) {text or NOT_READ}" + (f" — {entry['caption']}" if entry['caption'] else '')
            storage.add_mission_step(m['id'], {'kind': 'note', 'name': 'user_answer',
                                               'result_json': {'text': answer, 'photo_url': saved['url']}})
            storage.update_mission(m['id'], {'status': 'running'})
            from services import situations as _sit
            _sit.touched('mission', m['id'])
    from services import situations as _sit
    _sit.touched('thread', thread_id)
    return {'status': 'ok', 'entry': entry, 'read': bool(text)}
```

Check that `_pool_call` in `threads.py` forwards `**kw` to `model_pools.call_pool_json` (it does: `def _pool_call(tier, api_key, system, prompt, **kw)`).

- [ ] **Step 4: Run the test**

Run: `..\venv\Scripts\python.exe tests\test_thread_photo.py`
Expected: `3/3 scenarios passed`. `storage.save_media_file` writes under the harness's temp data dir; if `media_file_path` returns None for a `.png`, check `_MEDIA_ID_RE` (it allows png).

- [ ] **Step 5: The endpoint and its gates** — in `main.py`, after `send_thread_message`:

```python
@app.post("/api/threads/{thread_id}/photo")
async def thread_photo(thread_id: str, file: UploadFile = File(...), caption: str = Form(''),
                       member_id: Optional[str] = Form(None), request: Request = None):
    """A photo on a thread (browse missions §3): a parent or adult, or the
    thread's owner whatever their role. Images only; read once by the vision
    tier; answers a mission waiting on this thread."""
    thread = storage.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="No such thread")
    actor_id = _acting_id(request, member_id)
    actor = storage.get_member(actor_id) if actor_id else None
    is_owner = bool(actor and thread.get('owner_member_id') == actor.get('id'))
    if actor and actor.get('role') in ('child', 'helper', 'guest') and not is_owner:
        raise HTTPException(status_code=403, detail="Only a parent, an adult or the thread's owner can add a photo")
    if actor is None and not _is_admin_surface(request):
        raise HTTPException(status_code=403, detail="Sign in to add a photo")
    mime = (file.content_type or '').lower()
    if not mime.startswith('image/'):
        raise HTTPException(status_code=400, detail="Images only")
    data = await file.read()
    if not data or len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="The image is empty or over 15 MB")
    from services import threads as _threads
    res = _threads.add_photo(thread_id, data, mime, (actor or {}).get('id'), caption=caption)
    if res.get('status') != 'ok':
        raise HTTPException(status_code=400, detail=res.get('reason') or 'could not store the photo')
    return res
```

Confirm `UploadFile`, `File`, `Form` are imported in `main.py` (grep `from fastapi import`); add them if not. Confirm `auth.resolve('POST', '/api/threads/{id}/photo')` lands SIGNED_IN like `/note` (grep `'/api/threads'` in `services/auth.py` RULES); if the existing rule is a prefix rule it already covers it.

Add the endpoint gate scenarios to `tests/test_thread_photo.py` the way `tests/test_threads_endpoints.py` drives endpoints (read its `_client()`/TestClient idiom and identity headers first):

```python
def scenario_photo_gates():
    """Through the app: a parent may; the owner child may; another child may not; a PDF is refused."""
    _reset()
    threads._pool_call = _fake_pool({'text': 'ok'})
    from tests.test_threads_endpoints import _client  # the file's own TestClient helper; copy it if it is not importable
    c = _client()
    tid = threads.create('Kate thread', owner_member_id='kid', created_by='mom')
    other = threads.create('Mom thread', owner_member_id='mom', created_by='mom')
    files = {'file': ('label.png', PNG, 'image/png')}
    r = c.post(f'/api/threads/{tid}/photo', files=files, data={'member_id': 'mom'})
    check(r.status_code == 200, f"a parent may: {r.status_code} {r.text[:120]}")
    r = c.post(f'/api/threads/{tid}/photo', files=files, data={'member_id': 'kid'})
    check(r.status_code == 200, "the owner child may")
    r = c.post(f'/api/threads/{other}/photo', files=files, data={'member_id': 'kid'})
    check(r.status_code == 403, f"another child may not: {r.status_code}")


def scenario_non_image_is_refused():
    _reset()
    from tests.test_threads_endpoints import _client
    c = _client()
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    r = c.post(f'/api/threads/{tid}/photo', files={'file': ('x.pdf', b'%PDF-1.4', 'application/pdf')}, data={'member_id': 'mom'})
    check(r.status_code == 400 and not [h for h in storage.get_thread(tid)['history'] if h['kind'] == 'photo'], "a PDF is refused before storage")
```

If `test_threads_endpoints.py` has no importable client helper, copy its TestClient construction (3–6 lines) into this file as `_client()` and note it in the ledger.

- [ ] **Step 6: The cap setting, three places**

`models/schemas.py` after `reply_cap_reads`: `thread_cap_photo_reads: Optional[int] = 20   # threads: photo reads per day`.

`services/settings_registry.py` after `mission_cap_pro_calls`:

```python
    _e('thread_cap_photo_reads', 'missions', 'Daily photo-read cap',
       "Hard ceiling on photos Argyle reads off a thread per day (default 20). Over the cap a photo is "
       "kept but not read.",
       page='work?tab=missions', anchor='missions-settings'),
```

`templates/components/missions_page.html`: a tile beside "Daily pro-call cap" (`x-model.number="s.thread_cap_photo_reads"`, label "Daily photo-read cap"), the default (`thread_cap_photo_reads: 20,`) and the save payload line, mirroring `mission_cap_pro_calls`. Run `..\venv\Scripts\python.exe tools\build_tailwind.py`.

- [ ] **Step 7: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_thread_photo.py` and `..\venv\Scripts\python.exe tools\test.py threads missions_engine missions_endpoints settings_registry tailwind_build`
Expected: `5/5`; related green.

- [ ] **Step 8: Commit**

Bump `config.yaml` to `2.499.345`.

```bash
git add services/threads.py main.py models/schemas.py services/settings_registry.py templates/components/missions_page.html static/tailwind.css static/tailwind-app.css tests/test_thread_photo.py config.yaml
git commit -m "feat(threads): a photo on a thread, stored beside moments, read once by the vision tier, answering a waiting mission (v2.499.345)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 4: The camera button on the thread card and the PWA House card; the timeline thumbnail

**Files:**
- Modify: `templates/components/threads_page.html` (a "Photo" button in the details' button row + a hidden file input; the timeline draws `photo` entries with a thumbnail)
- Modify: `templates/app.html` (`renderHouseThreads` `extraHtml` gains a camera input; `houseAddThreadPhoto`)
- Test: `tests/test_thread_photo_live.py` (new)

**Interfaces:** consumes `POST /api/threads/{id}/photo` (multipart `file`, `caption`, `member_id`).

- [ ] **Step 1: Write the failing live test**

```python
# tests/test_thread_photo_live.py
"""The camera button on /threads and the PWA House card; the timeline shows
the thumbnail and the transcription."""
import base64
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='thread_photo_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    storage.update_settings({'llm_gemini_api_key': '', 'thread_stall_days': 7})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    from services import threads
    threads.create('Pest control', owner_member_id='mom', counterparty_name='Pest Co', created_by='mom')
    open(os.path.join(os.environ['CHAUFFEUR_DATA_DIR'], 'label.png'), 'wb').write(PNG)


def main():
    served = live_app(seed)
    if served is None:
        return
    png_path = os.path.join(os.environ['CHAUFFEUR_DATA_DIR'], 'label.png')
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            page.wait_for_selector('#threads .situation-card', timeout=15000)
            page.locator('#threads details summary').first.click()
            page.wait_for_timeout(300)
            check(page.locator('#threads details[open] button:has-text("Photo")').count() == 1, "the Photo button is in the details")
            page.locator('#threads details[open] input[type=file][data-thread-photo]').first.set_input_files(png_path)
            page.wait_for_timeout(2500)
            row = [t for t in storage.get_threads() if t['title'] == 'Pest control'][0]
            photos = [h for h in row['history'] if h['kind'] == 'photo']
            check(len(photos) == 1 and photos[0]['text'] == 'photo added (not read)', f"stored through the page (no key: not read): {photos}")
            page.wait_for_selector('#threads details[open] img.thread-photo', timeout=10000)
            tl = page.locator('#threads details[open] .thread-photo-text').first.inner_text()
            check('not read' in tl, f"the timeline shows the photo line: {tl}")
            check(not b.errors, f"script errors: {b.errors}")

        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('app'), wait_until='networkidle')
            page.evaluate("localStorage.setItem('chauffeur_member_id', 'mom');")
            page.goto(served.url('app'), wait_until='networkidle')
            page.evaluate("async () => { await fetchHouseThreads(); }")
            page.wait_for_selector('#house-threads .situation-card', state='attached', timeout=15000)
            check(page.locator('#house-threads input[type=file][data-thread-photo]').count() == 1, "the House card has a camera input")
            page.locator('#house-threads input[type=file][data-thread-photo]').first.set_input_files(png_path)
            page.wait_for_timeout(2500)
            row = [t for t in storage.get_threads() if t['title'] == 'Pest control'][0]
            check(len([h for h in row['history'] if h['kind'] == 'photo']) == 2, "stored through the PWA too")
            check(not b.errors, f"PWA script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print('PASS test_thread_photo_live')
```

- [ ] **Step 2: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_thread_photo_live.py`
Expected: FAIL at "the Photo button is in the details".

- [ ] **Step 3: The thread page** — in `templates/components/threads_page.html`, in the details' button row (after the "Research" button), add:

```html
                                            <button @click="$refs['photo-' + t.id].click()"
                                                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">Photo</button>
                                            <input type="file" accept="image/*" capture="environment" class="hidden" data-thread-photo
                                                   :x-ref="'photo-' + t.id" @change="uploadPhoto(t, $event)">
```

(Alpine `x-ref` cannot be bound dynamically; instead give the input `:data-thread-id="t.id"` and have the button do `$el.parentElement.querySelector('input[data-thread-photo]').click()`. Use whichever the page's Alpine version supports; the test only needs the button and the input inside the open details.)

In the history timeline (the `x-for="(h, i) in (t.history || [])"` block), after the reading span:

```html
                                                    <template x-if="h.kind === 'photo'">
                                                        <div class="mt-1">
                                                            <img class="thread-photo rounded-lg max-h-40 border border-gray-800" :src="apiBase + h.url.replace(/^\//, '')" alt="">
                                                            <div class="thread-photo-text text-gray-400 mt-0.5" x-text="(h.caption ? h.caption + ' — ' : '') + h.text"></div>
                                                        </div>
                                                    </template>
```

In the page script, beside `submitNote`:

```javascript
                async uploadPhoto(t, ev) {
                    const f = ev.target.files && ev.target.files[0];
                    if (!f) return;
                    const fd = new FormData();
                    fd.append('file', f);
                    fd.append('caption', '');
                    try {
                        const r = await fetch(this.apiBase + `api/threads/${t.id}/photo`, { method: 'POST', body: fd });
                        const d = await r.json().catch(() => ({}));
                        if (!r.ok) { showGlobalAlert(d.detail || "Couldn't add that photo."); return; }
                        showGlobalAlert(d.read ? 'Photo added and read.' : 'Photo added (not read).');
                        await this.load();
                    } catch (e) { showGlobalAlert("Couldn't add that photo."); }
                    finally { ev.target.value = ''; }
                },
```

Picture URLs on admin pages must carry the token where the page is walled (`chfAuthUrl`, see the v2.499.323 rule for `<img>` sources); the /threads page is an admin page behind the gate with the fetch wrapper, but an `<img>` sends no header: wrap the `:src` in `window.chfAuthUrl ? chfAuthUrl(url) : url`. The structural test `test_template_js.scenario_a_picture_carries_the_token_on_its_query_string` will say if it is needed.

- [ ] **Step 4: The PWA House card** — in `templates/app.html` `renderHouseThreads`, extend `extraHtml` so the note form is followed by:

```javascript
                    + `<label class="inline-flex items-center gap-1 text-xs text-gray-400 mt-1.5 cursor-pointer">📷 Add a photo
                         <input type="file" accept="image/*" capture="environment" class="hidden" data-thread-photo
                                onchange="houseAddThreadPhoto(event, '${mfEscape(s.id)}')"></label>`
```

and add beside `houseAddThreadNote`:

```javascript
        async function houseAddThreadPhoto(ev, threadId) {
            const f = ev.target.files && ev.target.files[0];
            if (!f) return;
            const fd = new FormData();
            fd.append('file', f); fd.append('caption', '');
            if (selectedMemberId) fd.append('member_id', selectedMemberId);
            try {
                const r = await fetch(`${apiBase}api/threads/${threadId}/photo`, { method: 'POST', body: fd, headers: chfAuthHeaders ? chfAuthHeaders() : {} });
                const d = await r.json().catch(() => ({}));
                if (!r.ok) { showGlobalAlert(d.detail || "Couldn't add that photo."); return; }
                showGlobalAlert(d.read ? 'Photo added and read.' : 'Photo added (not read).');
                fetchHouseThreads();
            } catch (e) { showGlobalAlert("Couldn't add that photo."); }
            finally { ev.target.value = ''; }
        }
```

Use whatever helper the PWA already uses to attach the member token to a `fetch` (grep `X-Member-Token` in `app.html`); if the fetch wrapper adds it globally, drop the `headers` argument. Run `..\venv\Scripts\python.exe tools\build_tailwind.py`.

- [ ] **Step 5: Run the live test and the related tests**

Run: `..\venv\Scripts\python.exe tests\test_thread_photo_live.py` then `..\venv\Scripts\python.exe tools\test.py threads_page_live situations_lane_live template_js tailwind_build`
Expected: PASS; related green.

- [ ] **Step 6: Commit**

Bump `config.yaml` to `2.499.346`.

```bash
git add templates/components/threads_page.html templates/app.html static/tailwind.css static/tailwind-app.css tests/test_thread_photo_live.py config.yaml
git commit -m "feat(threads): the Photo button on the thread card and the PWA House card; the timeline shows the thumbnail and what it says (v2.499.346)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 5: Capabilities and roadmap

**Files:** `system_capabilities.md`, `docs/roadmap.md`.

- [ ] **Step 1:** Bump "Current through v2.499.347" and add an entry at the top, house style:

```markdown
**Browse missions, build 1: the family mailbox searched, a photo on a thread (v2.499.343–.346; `services/mail_search.py`, `services/agent_tools_v2.py` `search_mail`/`read_mail`, `services/missions.py` READ_TOOLS, `services/threads.py` `add_photo`/`read_photo`, `main.py` `/api/threads/{id}/photo`, `templates/components/threads_page.html`, `templates/app.html`; spec `docs/superpowers/specs/2026-10-10-browse-missions-design.md`, plan `docs/superpowers/plans/2026-10-10-browse-missions-build-1.md`; tests `test_mail_tools.py`, `test_thread_photo.py`, `test_thread_photo_live.py`).** First of three builds toward a DIY Dots.

- **`search_mail(query, since_days, limit)` / `read_mail(uid)`.** A fresh read-only IMAP connection to the intake mailbox, words OR'd across FROM/SUBJECT/TEXT inside a SINCE window, newest first, 400-character snippets, a 6,000-character body; the ingest cursor never moves; no model call; no attachments. Parents and adults only (an anonymous panel and a child are refused); a mission reads as the parent of record. In the registry, the router and the missions' READ set.
- **A photo on a thread.** `POST /api/threads/{id}/photo` (parent/adult, or the thread's owner whatever their role; images only, 15 MB) stores the image beside moments and appends a `photo` history entry; one vision-tier call under `thread_cap_photo_reads` (20/day, Missions drawer) transcribes what a repair, order or school office would ask for; a failed, capped or keyless read leaves "photo added (not read)". A mission waiting on a question on that thread takes the photo as its answer and resumes. The /threads details have a Photo button and the timeline draws the thumbnail with the text; the PWA House card has "Add a photo".
- **Not device-verified.**
```

`docs/roadmap.md`: one line under the Needs-you entry: "Browse missions build 1 SHIPPED v2.499.343–.346 (2026-10-10): mail search and a photo on a thread. Spec: `docs/superpowers/specs/2026-10-10-browse-missions-design.md`."

- [ ] **Step 2: Run the gate**

Run: `..\venv\Scripts\python.exe tools\test.py mail_tools thread_photo missions_engine missions_pins threads email_ingest situation agent_v2_bridge tailwind_build`
Expected: all green.

- [ ] **Step 3: Commit**

Bump `config.yaml` to `2.499.347`.

```bash
git add system_capabilities.md docs/roadmap.md config.yaml
git commit -m "docs(mail,threads): browse missions build 1 wrap-up (v2.499.347)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

## Self-review notes

- **Spec coverage (§3):** `search_mail`/`read_mail` with gates, caps and no cursor (Tasks 1–2); photo endpoint, storage, vision read, cap, "not read", the waiting mission (Task 3); camera button on the card and the PWA House card, the timeline (Task 4); registry entry for the cap (Task 3).
- **Type consistency:** `mail_search.search/read` return dicts with `status`; the tools wrap them; `threads.add_photo` returns `{'status','entry','read'}`; the endpoint returns that dict.
- **Review Focus** 1–5 pinned in Tasks 1 (two), 3 (three).
- **Not in this build:** the browse step (build 2), the conversation and DMs (build 3).
