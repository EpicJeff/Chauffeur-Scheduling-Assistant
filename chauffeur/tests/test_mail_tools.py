"""search_mail / read_mail: the family's own mailbox, read-only, parent/adult
only, no cursor moved, no model called. Spec 2026-10-10 browse missions §3."""
import datetime
import email.utils

from harness import check  # noqa: F401
from services import storage, mail_search, email_ingest

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child'}
CURSOR = email_ingest._cursor_key('fam@example.com')


class FakeIMAP:
    """Enough of imaplib for search/read: uid SEARCH and uid FETCH."""
    def __init__(self, messages):
        self.messages = messages           # uid -> raw RFC822 bytes
        self.searches = []
        self.selected = None
        self.logged_out = False

    def login(self, u, p):
        return ('OK', [b'ok'])

    def select(self, box, readonly=False):
        self.selected = (box, readonly)
        return ('OK', [b'1'])

    def uid(self, cmd, *args):
        if cmd == 'SEARCH':
            # imaplib encodes every str criterion as ASCII; a non-ASCII word raises here, as it does there.
            for a in args:
                if isinstance(a, str):
                    a.encode('ascii')
            self.searches.append(args)
            crit = ' '.join(str(a) for a in args if a is not None)
            # Crude matcher: every quoted word in the criteria is a candidate.
            words = [w.strip('"') for w in crit.replace('(', ' ').replace(')', ' ').split()
                     if w.startswith('"')]
            uids = [u for u, raw in self.messages.items()
                    if any(w.lower() in raw.decode('utf-8', 'ignore').lower() for w in words)]
            return ('OK', [' '.join(str(u) for u in sorted(uids)).encode()])
        if cmd == 'FETCH':
            u = int(args[0])
            return ('OK', [(b'', self.messages[u])]) if u in self.messages else ('NO', [None])
        return ('NO', [None])

    def logout(self):
        self.logged_out = True


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
    storage.set_app_state(CURSOR, 13)
    res = mail_search.search('cafe dishwasher')
    check(res['status'] == 'success' and [h['uid'] for h in res['hits']] == [13, 11], f"newest first, matching only: {res}")
    h = res['hits'][1]
    check(len(h['snippet']) <= mail_search.SNIPPET_CHARS and 'CDT805P2N3S1' in h['snippet'], f"a capped snippet: {len(h['snippet'])}")
    check(h['from'] == 'orders@cafeappliances.com' and h['subject'] == 'Your Cafe order' and h['date'], "sender, subject, date")
    check(fake.selected == ('INBOX', True), "read-only select")
    check(storage.get_app_state(CURSOR) == 13, "the ingest cursor never moves")
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
    mail_search.search('word ' * 500 + 'z' * 300)
    crit = ' '.join(str(a) for a in fake.searches[-1])
    check(crit.count('TEXT "') <= mail_search.MAX_WORDS and len(crit) < 600, f"a runaway query is cut: {len(crit)} chars")


def scenario_non_ascii_query_is_folded_not_an_error():
    now = datetime.datetime.now(datetime.timezone.utc)
    fake = _reset({5: _raw('orders@cafeappliances.com', 'Your Cafe order', 'Model CDT805P2N3S1', now)})
    res = mail_search.search('café dishwasher')
    check(res['status'] == 'success' and [h['uid'] for h in res['hits']] == [5], f"an accent is folded, the search runs: {res}")
    crit = ' '.join(str(a) for a in fake.searches[-1])
    check('"cafe"' in crit and 'é' not in crit, f"cafe, 7-bit: {crit}")
    res = mail_search.search('日本')
    check(res['status'] == 'success', f"a word that folds to nothing is dropped, not an error: {res}")


def scenario_limit_is_capped():
    now = datetime.datetime.now(datetime.timezone.utc)
    _reset({i: _raw('a@b.c', f'hit {i}', 'word', now) for i in range(1, 30)})
    res = mail_search.search('word', limit=50)
    check(len(res['hits']) == mail_search.MAX_LIMIT, f"never more than {mail_search.MAX_LIMIT}: {len(res['hits'])}")


from services import agent_tools_v2 as tools, missions  # noqa: E402


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


def scenario_a_room_hears_headers_only():
    """Voice acts as the parent of record and is treated as a ROOM (triage
    arc): the mailbox's bodies are never read out; the headers may be."""
    now = datetime.datetime.now(datetime.timezone.utc)
    _reset({3: _raw('teacher@school.org', 'About Kate', 'Kate was in a fight today. Details: CDT805P2N3S1', now)})
    res = tools.search_mail('Kate', acting_member=MOM, spoken=True)
    check(res['status'] == 'success' and 'About Kate' in res['message'] and 'CDT805P2N3S1' not in res['message'],
          f"spoken: subject yes, snippet no: {res}")
    check(res['hits'] and 'snippet' not in res['hits'][0], "spoken hits carry no snippet either")
    res = tools.read_mail(3, acting_member=MOM, spoken=True)
    check(res['status'] == 'error' and 'out loud' in res['message'], f"spoken read is refused: {res}")
    res = tools.read_mail(3, acting_member=MOM)
    check(res['status'] == 'success', "typed read still works")


def scenario_registry_and_missions_know_the_tools():
    for name in ('search_mail', 'read_mail'):
        check(name in tools.TOOL_HANDLERS and name in tools.TOOL_SCHEMAS, f"{name} in the registry")
        check(name in {t['name'] for t in tools.get_available_tools()}, f"{name} offered to the model")
        check(name in missions.READ_TOOLS, f"{name} is a mission READ tool")
    src = open('services/agent_router.py', encoding='utf-8').read()
    check('"search_mail"' in src and '"read_mail"' in src, "the router dispatches both")
    now = datetime.datetime.now(datetime.timezone.utc)
    _reset({3: _raw('a@b.c', 'Hit', 'word', now)})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    out = tools.execute_tool('search_mail', {'query': 'word'})
    check(out.get('status') == 'success' and out.get('hits'), f"the registry executes it for a mission: {out}")


SCENARIOS = [scenario_search_returns_snippets_newest_first_and_moves_no_cursor, scenario_read_returns_the_body_capped,
             scenario_no_mailbox_is_an_honest_answer, scenario_query_is_quoted_for_imap, scenario_limit_is_capped,
             scenario_non_ascii_query_is_folded_not_an_error,
             scenario_tools_gate_and_read_through, scenario_a_room_hears_headers_only,
             scenario_registry_and_missions_know_the_tools]

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
