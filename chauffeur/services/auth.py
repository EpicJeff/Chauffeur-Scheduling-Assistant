"""Trust tiers and the default-deny guard (the auth arc, slice S1).

Full brief: `docs/auth_design.md`. The state this replaces: the app is
published publicly by the cloudflared add-on with no Cloudflare Access, 417
routes are registered, and five of them check anything at all. The only thing
in front of the family's messages, schedules, home address and photos is that
nobody has guessed the hostname.

Three properties are load-bearing here, and all three are about not breaking
the house on the way to locking it:

  1. **Default deny, but only once we know the table is right.** Every route
     is classified in `RULES` below and `resolve()` returns None for anything
     unmatched. A test fails on any unclassified route, so the next route
     somebody adds cannot be public by accident — which is exactly how this
     state was reached. That discipline is `settings_registry.audit()`'s,
     pointed at routes instead of settings.

  2. **Audit mode first.** With `auth_enforce` off (the default, and the only
     behaviour S1 ships) the guard refuses NOTHING. It records what it would
     have refused, so the family can use the house normally — the wall panel
     at 6am, phones, Argyle, the Android share sheet — and the record says
     which real callers the table got wrong. Flipping to enforce before that
     evidence exists means discovering the panel cannot reach its board on a
     school morning.

  3. **A tier is a SET, not a rank.** The kiosk pages are read by a parent in
     a browser AND by a panel bolted to a wall; `/api/chat` is Argyle's and
     nobody else's. Ranking those on one axis forces a lie in one direction or
     the other, so a rule names exactly who may call it.

Identity is resolved but NOT yet enforced or derived from — S2 makes the token
the identity everywhere and stops trusting the client-asserted member id the
PWA sends today.
"""
import hmac
import time
from typing import Optional

# --- tiers ------------------------------------------------------------------

PUBLIC = 'public'    # no proof; the tier IS the allowlist
MEMBER = 'member'    # a signed-in family member
PARENT = 'parent'    # a member whose role is parent
DEVICE = 'device'    # an enrolled wall panel: a place, not a person
SERVICE = 'service'  # the HA component / agent stack

# Allow-sets, named for what they mean rather than built ad hoc at each rule.
ANYONE = frozenset()                              # public
SIGNED_IN = frozenset({MEMBER, PARENT})           # any family member
WALL = frozenset({MEMBER, PARENT, DEVICE})        # people and panels
WALL_OR_SERVICE = frozenset({MEMBER, PARENT, DEVICE, SERVICE})
PARENTS = frozenset({PARENT})                     # admin
ROBOTS = frozenset({SERVICE, PARENT})             # Argyle, and a human debugging it

# --- the table --------------------------------------------------------------
# (method_or_ANY, path_template_or_prefix, allowed_tiers)
#
# Matched in order, first hit wins, so a specific rule sits above the prefix it
# carves out of. A path ending in '*' is a prefix match on the ROUTE TEMPLATE
# (e.g. '/api/members/{member_id}/auth'), never on the concrete path — matching
# raw paths would make a member id containing a slash into an auth decision.
ANY = '*'

RULES = [
    # --- public: the things that must answer before anyone can sign in ------
    (ANY, '/health', ANYONE),
    (ANY, '/manifest.json', ANYONE),
    (ANY, '/sw.js', ANYONE),
    (ANY, '/api/vapid_public_key', ANYONE),
    # Sign-in itself. `/auth` mints the token, so it cannot require one; it is
    # the single most attackable route in the app and S4 gives it persistent,
    # per-IP rate limiting to match.
    ('POST', '/api/members/{member_id}/auth', ANYONE),
    # The picker's data (S8, Decision 4 built at last). ANYONE in the TABLE,
    # gated in the HANDLER: `_gate_family_listing` answers a caller with any
    # tier, or anonymous on trusted ground (vouched device / LAN / ingress) —
    # which is the only place the faces picker exists any more. Off trusted
    # ground the front door is the login page, which needs no list. The tier
    # table cannot express "trusted ground", so the handler owns the rest.
    ('GET', '/api/members', ANYONE),
    ('GET', '/api/drivers', ANYONE),
    # "Where am I standing?" — one boolean about the caller's own ground,
    # which is how the PWA picks its front door. Open like this-device: the
    # answer contains nothing the request did not arrive with.
    ('GET', '/api/account/ground', ANYONE),
    # Accounts (S3). All public by necessity — every one of these is reached
    # by somebody who has no credential yet, which is the entire point of
    # them. Their protection is the token in the link, not a tier:
    #   * `/account/set-password` + `/api/account/link` carry a single-use,
    #     expiring token that only we could have mailed to that address.
    #   * `/api/account/login` is the front door.
    #   * `/api/account/forgot` answers identically whether or not the address
    #     exists, so it leaks nothing to probe.
    # `/api/members/{id}/invite` is NOT here — issuing an account is
    # administration and stays parent-only under the members rules below.
    (ANY, '/account/set-password', ANYONE),
    ('GET', '/api/account/link/{token}', ANYONE),
    # First-run: both are guarded by the INGRESS check inside the handler,
    # not by a tier — the whole point is that they answer to somebody who has
    # no account yet. `/setup` reports only whether a household is claimed and
    # which parents exist by name, and `/claim` closes permanently the moment
    # one parent holds a password.
    ('GET', '/api/account/setup', ANYONE),
    ('POST', '/api/account/claim', ANYONE),
    # Echoes back only the caller's OWN headers; says nothing about the
    # household. Open so it can answer when nothing else will.
    ('GET', '/api/account/env', ANYONE),
    # Pairing (S6). The two the DEVICE calls are open by necessity — a screen
    # with no credential is exactly who calls them — and neither grants
    # anything on its own: the request only produces a code somebody still has
    # to approve, and the status poll is keyed on a device id the screen
    # minted and nobody else knows. Approval itself is parent-only, below.
    ('POST', '/api/account/devices/pair-request', ANYONE),
    ('GET', '/api/account/devices/pair-status', ANYONE),
    # "What am I called?", answered for the caller's OWN device and nothing
    # else. Open for the same reason as the two above: the id in the header is
    # one the screen minted, so the answer contains nothing it did not arrive
    # with, and a wall panel naming itself to Music Assistant has no
    # credential to offer. Deliberately NOT under /api/account/devices/, which
    # is the parent-only list a lost tablet gets revoked from.
    ('GET', '/api/account/this-device', ANYONE),
    # The device list is where a lost tablet gets revoked, so it is admin —
    # as is saying yes to a screen, and minting Argyle's credential.
    (ANY, '/api/account/devices', PARENTS),
    (ANY, '/api/account/devices/*', PARENTS),
    ('POST', '/api/account/service-token', PARENTS),
    ('POST', '/api/account/set-password', ANYONE),
    ('POST', '/api/account/login', ANYONE),
    ('POST', '/api/account/forgot', ANYONE),

    # --- parent-only: administration and anything that hands over the house --
    # These are the routes where "open" was worth a whole compromise.
    (ANY, '/api/download_db', PARENTS),
    (ANY, '/api/debug_db', PARENTS),
    (ANY, '/api/debug/*', PARENTS),
    (ANY, '/api/admin/*', PARENTS),
    (ANY, '/api/test/*', PARENTS),
    (ANY, '/api/cache/*', PARENTS),
    (ANY, '/api/members/{member_id}/pin/clear', PARENTS),
    (ANY, '/api/members/{member_id}/pin', SIGNED_IN),   # own PIN; S4 tightens
    ('POST', '/api/members/*', PARENTS),                # create/edit members
    ('PUT', '/api/members/*', PARENTS),
    ('PATCH', '/api/members/*', PARENTS),
    ('DELETE', '/api/members/*', PARENTS),
    (ANY, '/api/settings/*', PARENTS),
    (ANY, '/api/settings', PARENTS),
    (ANY, '/api/ics_feeds/*', PARENTS),
    (ANY, '/api/drivers/*', PARENTS),
    (ANY, '/api/passengers/*', PARENTS),
    (ANY, '/api/rules/*', PARENTS),
    (ANY, '/api/priority_rules/*', PARENTS),
    (ANY, '/api/errand_rules/*', PARENTS),
    (ANY, '/api/status-tiers/*', PARENTS),
    (ANY, '/api/stages/*', PARENTS),
    (ANY, '/api/themes/*', PARENTS),
    (ANY, '/api/calendars/*', PARENTS),
    (ANY, '/api/walmart/*', PARENTS),
    (ANY, '/api/ha_sensors/*', PARENTS),
    # The music card's HA lanes, carved out ABOVE the admin prefix below
    # (first hit wins): the board's music card lists players and sends
    # transport commands from a wall, and the artwork proxy is drawn as a bare
    # <img> by panels and the PWA alike — an image request can carry no header,
    # so the token rides the query string (identify() reads it there).
    # Everything else under /api/ha stays administration.
    ('GET', '/api/ha/media_players', WALL),
    ('POST', '/api/ha/media_players/{entity_id}/command', WALL),
    ('GET', '/api/ha/image64/{encoded}', WALL),
    (ANY, '/api/ha/*', PARENTS),
    (ANY, '/api/telemetry/*', PARENTS),
    (ANY, '/api/push_subscriptions/*', PARENTS),
    # NOTE: the admin PAGES are public shells; their DATA is parent-gated
    # above and below. See the shell-vs-data note in the wall section.
    (ANY, '/config', ANYONE),
    (ANY, '/dashboard', ANYONE),
    (ANY, '/dashboard_v2', ANYONE),
    (ANY, '/settings', ANYONE),

    # FastAPI's generated docs. Found UNCLASSIFIED by the S1 test, which is
    # the first thing it caught and on its own worth the file: `/docs` is a
    # complete, interactive map of all 417 routes with a try-it-out console
    # attached, and it has been served to the public internet next to an app
    # with no authentication. Parents-only here; S8 should consider switching
    # them off outright, since nobody in this household reads them.
    (ANY, '/docs', PARENTS),
    (ANY, '/docs/*', PARENTS),
    (ANY, '/redoc', PARENTS),
    (ANY, '/openapi.json', PARENTS),

    # --- Argyle ------------------------------------------------------------
    # NOT robots-only, and the live audit is what said so: the Argyle bar is
    # drawn on member surfaces (the PWA's FAB) and on wall panels, and each of
    # those callers POSTs /api/chat as itself. Anonymous is the only refusal.
    (ANY, '/api/chat/*', WALL_OR_SERVICE),
    # The bar's read side is an EventSource, which can set no headers — the
    # token rides the query string. /api/v2/converse below stays robots-only:
    # it is the HA Assist webhook, and no browser surface posts it.
    ('GET', '/api/v2/chat/stream', WALL_OR_SERVICE),
    (ANY, '/api/v2/*', ROBOTS),
    (ANY, '/api/announce/*', ROBOTS),

    # --- the wall: pages and payloads a panel legitimately draws ------------
    #
    # SHELL vs DATA, and it is a rule rather than a convenience: **every HTML
    # page is public; the family's information lives behind /api.** Forced by
    # the fact that the ways IN are drawn by the shells themselves — the
    # sign-in overlay lives in the admin pages, and the pairing screen lives
    # in nav. Gate the page and a refused browser gets a bare 403 with no way
    # to fix it: a wall panel could never show the code that would let it in,
    # and a parent could never reach the box that would sign them in. The
    # templates carry no household data of their own; every one of them
    # fetches what it draws.
    (ANY, '/', ANYONE),
    (ANY, '/home', ANYONE),
    (ANY, '/board/{slug}', ANYONE),
    (ANY, '/api/home_board/*', WALL),
    (ANY, '/api/panel/*', WALL),
    (ANY, '/api/schedule/*', WALL),
    (ANY, '/api/weather/*', WALL),
    (ANY, '/api/presence/*', WALL),
    (ANY, '/api/moments/*', WALL),
    (ANY, '/api/media/*', WALL),
    (ANY, '/api/music/*', WALL),
    # The panel screen player: the app's one WebSocket. A browser's WebSocket
    # API can set no headers, so the token rides the query string — identify()
    # reads query params for exactly this class of caller.
    (ANY, '/api/sendspin/ws', WALL),
    # Trip backgrounds are CSS/<img> urls drawn by the trip pages AND the trip
    # kiosk; no header is possible there either, so the token rides the query.
    ('GET', '/api/unsplash/background', WALL),
    (ANY, '/api/announce', WALL),
    # Kiosk-capable destinations: a parent opens these in a browser and a panel
    # draws the same page with ?panel=true. Both, therefore, or one of the two
    # is a lie (see property 3 above).
    (ANY, '/chores', ANYONE),
    (ANY, '/routines', ANYONE),
    (ANY, '/shopping', ANYONE),
    (ANY, '/calendar', ANYONE),
    (ANY, '/errands', ANYONE),
    (ANY, '/occasions', ANYONE),
    (ANY, '/moments', ANYONE),
    (ANY, '/moment', ANYONE),
    (ANY, '/map', ANYONE),
    (ANY, '/music', ANYONE),
    (ANY, '/trips', ANYONE),
    (ANY, '/trip', ANYONE),
    (ANY, '/intake', ANYONE),
    (ANY, '/app', ANYONE),
    # Interactive board actions — a wall may claim a chore and check a routine;
    # that is the whole point of `interactive` tiles.
    (ANY, '/api/chores/*', WALL),
    (ANY, '/api/routines/*', WALL),
    (ANY, '/api/points/*', WALL),
    (ANY, '/api/rewards/*', WALL),
    (ANY, '/api/redemptions/*', WALL),
    (ANY, '/api/shopping/*', WALL),
    (ANY, '/api/kid-tasks/*', WALL),
    (ANY, '/api/kids/*', WALL),
    (ANY, '/api/meals/*', WALL),
    (ANY, '/api/prep-kits/*', WALL),
    (ANY, '/api/prep_status/*', WALL),
    (ANY, '/api/stream/*', WALL),

    # --- signed-in members: the ordinary app ------------------------------
    (ANY, '/api/messages/*', SIGNED_IN),
    (ANY, '/api/channels/*', SIGNED_IN),
    (ANY, '/api/events/*', SIGNED_IN),
    (ANY, '/api/errands/*', SIGNED_IN),
    (ANY, '/api/overrides/*', SIGNED_IN),
    (ANY, '/api/occasions/*', SIGNED_IN),
    (ANY, '/api/trip/*', SIGNED_IN),
    (ANY, '/api/trips/*', SIGNED_IN),
    (ANY, '/api/proposals/*', SIGNED_IN),
    (ANY, '/api/action-proposals/*', SIGNED_IN),
    (ANY, '/api/ingest/*', SIGNED_IN),
    (ANY, '/api/status/*', SIGNED_IN),
    (ANY, '/api/requests/*', SIGNED_IN),
    (ANY, '/api/household-tasks/*', SIGNED_IN),
    (ANY, '/api/household-load/*', SIGNED_IN),
    (ANY, '/api/commitments/*', SIGNED_IN),
    (ANY, '/api/assist-contacts/*', SIGNED_IN),
    (ANY, '/api/assist-coverage/*', SIGNED_IN),
    (ANY, '/api/assist-history/*', SIGNED_IN),
    (ANY, '/api/cars/*', SIGNED_IN),
    (ANY, '/api/places/*', SIGNED_IN),
    (ANY, '/api/maps/*', SIGNED_IN),
    (ANY, '/api/calendar/*', SIGNED_IN),
    (ANY, '/api/school/*', SIGNED_IN),
    (ANY, '/api/drive_status/*', SIGNED_IN),
    (ANY, '/api/family/*', SIGNED_IN),
    (ANY, '/api/unsplash/*', SIGNED_IN),
    (ANY, '/api/push_subscribe/*', SIGNED_IN),
    (ANY, '/api/members/*', SIGNED_IN),   # reads; the writes are gated above
    (ANY, '/api/sendspin/*', SIGNED_IN),
    # The Android share target. The OS posts it with none of our headers, so
    # it will show up in the audit as a would-deny; S3 decides whether the
    # service worker attaches the token or the route lands on a signed-in page.
    (ANY, '/share', SIGNED_IN),
]


def _rule_matches(rule_method, rule_path, method, path):
    if rule_method != ANY and rule_method != method:
        return False
    if rule_path.endswith('/*'):
        return path.startswith(rule_path[:-1]) or path == rule_path[:-2]
    return path == rule_path


def resolve(method: str, path_template: str) -> Optional[frozenset]:
    """The allowed tiers for a route, or None if it is unclassified.

    None is not 'deny' and not 'allow' — it means the table has not been
    taught about this route, which is a bug in the table that the test catches
    before it can become a hole in the app."""
    for rule_method, rule_path, tiers in RULES:
        if _rule_matches(rule_method, rule_path, method, path_template):
            return tiers
    return None


# --- who is calling ---------------------------------------------------------

def arrived_via_tunnel(headers) -> bool:
    """Did this request come in off the public internet?

    cloudflared sets `CF-Connecting-IP` on everything it forwards, and an
    outside caller cannot strip it — they have no other way in. So the ABSENCE
    of it (and of any forwarding header) means the request reached us directly,
    which on this deployment means the LAN. Conservative on purpose: anything
    that looks forwarded counts as external, so a misread fails toward
    requiring credentials rather than away from it."""
    return bool(headers.get('cf-connecting-ip')
                or headers.get('x-forwarded-for')
                or headers.get('cf-ray'))


def caller_ip(headers) -> Optional[str]:
    """The caller's address, for rate limiting.

    `CF-Connecting-IP` is the only one worth believing: cloudflared sets it
    and an outside caller cannot overwrite it. `X-Forwarded-For` is
    client-supplied and would let an attacker rotate the header to get a fresh
    budget per guess, so it is deliberately NOT consulted — a rate limit keyed
    on something the attacker controls is decoration."""
    return (headers.get('cf-connecting-ip') or '').strip() or None


def arrived_via_ingress(headers) -> bool:
    """Did this request come through Home Assistant's ingress?

    This is the strongest identity claim available before anybody has an
    account, and it is what the first-run bootstrap stands on: supervisor does
    not serve ingress to an anonymous browser, so **arriving here means HA
    already authenticated the person.** That is a verified claim, unlike "it
    came from the LAN", which is every guest phone and smart plug on the wifi.

    THE SAFETY RULE, and it is the whole reason this is not a one-line header
    check: these headers are trivially forged by anyone who can reach the app.
    Through the cloudflared tunnel a stranger could simply send
    `X-Hass-Is-Admin: true` and claim to be the owner. So the headers are only
    believed when the request did NOT arrive through the tunnel — supervisor
    is on the other side of that boundary, and nothing outside can put itself
    there. Header trust without the origin check would be a hole far worse
    than the one this arc is closing.
    """
    # NOT `arrived_via_tunnel` — that treats `X-Forwarded-For` as evidence of
    # the public internet, and **supervisor sets X-Forwarded-For itself when
    # it proxies ingress to the add-on**. Using it here made every genuine
    # ingress request look external, so the first-run panel could never
    # appear: the header the check leaned on is one the proxy we are trying to
    # RECOGNISE also sends.
    #
    # The discriminator that actually works on this deployment is Cloudflare's
    # own: cloudflared stamps `CF-Connecting-IP` and `CF-Ray` on everything it
    # forwards, and an outside caller cannot remove them because they have no
    # other way in. Supervisor never sends them. So: an ingress signal, and no
    # sign of the tunnel.
    #
    # Worth knowing if the front door ever changes: behind a plain reverse
    # proxy that sets no CF headers, `X-Ingress-Path` could be forged from
    # outside. This is sound for cloudflared specifically, which is what the
    # household runs.
    if headers.get('cf-connecting-ip') or headers.get('cf-ray'):
        return False
    # Header names for the user identity differ by supervisor version, so all
    # the plausible spellings count — being wrong about which one is why this
    # needed `/api/account/env` to answer from the box rather than from a
    # guess.
    return bool(headers.get('x-ingress-path')
                or headers.get('x-hass-user-id')
                or headers.get('x-remote-user-id')
                or headers.get('x-remote-user-name'))


def ingress_is_admin(headers) -> bool:
    """An HA ADMIN specifically. Supervisor forwards `X-Hass-Is-Admin` with
    ingress requests; a household where everyone has an HA login should not
    have every one of them able to claim the first parent account."""
    if not arrived_via_ingress(headers):
        return False
    flag = str(headers.get('x-hass-is-admin') or '').strip().lower()
    # Absent is treated as allowed, and that is doing real work rather than
    # being lax: supervisor may not send an admin flag at all, and refusing on
    # its absence would make first-run impossible on exactly the installs
    # where it is missing — the failure the household just hit. The ingress
    # boundary is what is actually being trusted; the flag only narrows it
    # further when it happens to be there.
    return flag in ('', '1', 'true', 'yes')


def identify(headers, query) -> dict:
    """Best available identity for a request. S1 only OBSERVES this — nothing
    is enforced and nothing derives from it yet (S2 does that).

    Query-parameter fallbacks are not laziness: `EventSource` cannot set
    headers, so the SSE routes under /api/stream have no other way to carry a
    token."""
    from services import storage

    # VALIDATED, not merely present (fixed in S6). S1 returned the device tier
    # for anybody who sent the header at all, which would have made the header
    # its own password — the exact shape of hole this arc exists to close. It
    # was dark, so it was never reachable, but it must be right before the flip
    # rather than at it.
    device = headers.get('x-device-token') or query.get('device_token')
    if device:
        try:
            row = storage.get_device_by_token(device)
        except Exception:
            row = None
        if row:
            return {'tier': DEVICE, 'device': row, 'member': None}

    service = headers.get('x-service-token') or query.get('service_token')
    if service:
        try:
            expected = (storage.get_settings() or {}).get('service_token')
        except Exception:
            expected = None
        if expected and hmac.compare_digest(str(service), str(expected)):
            return {'tier': SERVICE, 'member': None}

    token = headers.get('x-member-token') or query.get('member_token')
    if token:
        try:
            member = storage.get_member_by_token(token)
        except Exception:
            member = None
        if member:
            tier = PARENT if member.get('role') == 'parent' else MEMBER
            return {'tier': tier, 'member': member}

    # The local-origin grace for Argyle (Decision 6). Dated, not permanent:
    # S7 gave the component a real service token, and `service_local_grace`
    # ends this once it has actually been updated and reconfigured. Ending it
    # is a deliberate act rather than a side effect of deploying, because the
    # alternative is an Argyle that goes quiet with no obvious cause.
    if not arrived_via_tunnel(headers):
        try:
            grace = (storage.get_settings() or {}).get('service_local_grace', True)
        except Exception:
            grace = True
        if grace:
            return {'tier': SERVICE, 'member': None, 'via': 'local-grace'}

    return {'tier': None, 'member': None}


def acting_member(headers, query, claimed_id: Optional[str] = None) -> dict:
    """Who is really making this request (auth arc S2).

    The hole this closes: identity in this app has been CLIENT-ASSERTED. The
    PWA sends `sender_member_id` in the body and the server believes it, so
    any caller could post a message as any member — a child as a parent, an
    outsider as anyone. The token that would have settled it existed all along
    and was read by five routes.

    Precedence, and the reasoning for each step:

      * **A valid token wins, always.** It is the only thing here that was
        issued by us.
      * **Token present but naming somebody else** is impersonation with no
        legitimate caller behind it, so it is recorded and — once enforcing —
        refused. There is no surface that signs in as one member and acts as
        another; if one appears, it needs its own tier, not a loophole.
      * **No token falls back to the claim**, recorded. This is the whole
        installed base on the day S2 ships: the PWA sends its token on a
        handful of privileged calls and nothing else. Refusing here would log
        the family out of their own house to fix a bug they did not have.
    """
    from services import storage

    token = headers.get('x-member-token') or query.get('member_token')
    member = None
    if token:
        try:
            member = storage.get_member_by_token(token)
        except Exception:
            member = None

    if member:
        if claimed_id and claimed_id != member.get('id'):
            record_identity('mismatch', claimed_id, member.get('id'))
            return {'member': member, 'id': member.get('id'), 'source': 'token',
                    'mismatch': True, 'claimed': claimed_id}
        return {'member': member, 'id': member.get('id'), 'source': 'token',
                'mismatch': False}

    if claimed_id:
        record_identity('claimed', claimed_id, None)
        try:
            member = storage.get_member(claimed_id)
        except Exception:
            member = None
        return {'member': member, 'id': claimed_id, 'source': 'claimed',
                'mismatch': False}

    return {'member': None, 'id': None, 'source': 'none', 'mismatch': False}


def impersonation_refused(acting: dict) -> bool:
    """Should this act be stopped? Only a token that names someone else, and
    only once enforcing — same dark-ship discipline as the route guard."""
    return bool(acting.get('mismatch')) and enforcing()


# --- the audit record -------------------------------------------------------
# Deliberately in memory and deliberately small. Its whole job is to answer one
# question once — "what would break if we flipped this on?" — and then be
# thrown away. Persisting it would mean a schema and a migration for a thing
# with a two-week life.

_AUDIT = {}          # (method, path_template) -> {'n', 'tiers', 'saw', 'last'}
_AUDIT_CAP = 500     # a runaway route cannot eat the add-on's memory
_IDENTITY = {'claimed': 0, 'mismatch': 0, 'examples': []}


def record_identity(kind: str, claimed, resolved) -> None:
    """How often identity still comes from the client rather than the token.

    `claimed` counts are the migration's progress bar — they should fall to
    zero as surfaces start sending their token, and S8 must not flip while
    they are high. `mismatch` counts are different in kind: every one of them
    is a caller acting as somebody they are not."""
    _IDENTITY[kind] = _IDENTITY.get(kind, 0) + 1
    if kind == 'mismatch' and len(_IDENTITY['examples']) < 20:
        _IDENTITY['examples'].append({'claimed': claimed, 'token_says': resolved})


def record(method: str, path_template: str, allowed, saw) -> None:
    key = (method, path_template)
    entry = _AUDIT.get(key)
    if entry is None:
        if len(_AUDIT) >= _AUDIT_CAP:
            return
        entry = _AUDIT[key] = {'n': 0, 'tiers': sorted(allowed) if allowed else [],
                               'saw': set(), 'last': 0.0}
    entry['n'] += 1
    entry['saw'].add(saw or 'anonymous')
    entry['last'] = time.time()


def audit_report() -> dict:
    """What would have been refused, worst first. Read this before flipping
    `auth_enforce` on — that is the entire point of shipping S1 dark."""
    rows = [{'method': m, 'path': p, 'count': e['n'],
             'needs': e['tiers'], 'saw': sorted(e['saw']),
             'last': e['last']}
            for (m, p), e in _AUDIT.items()]
    rows.sort(key=lambda r: -r['count'])
    return {'would_deny': rows, 'routes': len(rows),
            'capped': len(_AUDIT) >= _AUDIT_CAP,
            'identity': dict(_IDENTITY)}


def reset_audit() -> None:
    _AUDIT.clear()
    _IDENTITY.update(claimed=0, mismatch=0, examples=[])


# --- the guard --------------------------------------------------------------

def enforcing() -> bool:
    """Is the guard refusing anything yet?

    `auth_enforce` is a declared `Settings` field and a registry entry as of
    S8, with its control on Config → People (the Enforcement panel), drawn
    next to the audit report because the arc's rule is flip on evidence. The
    settings POST guards the transition (Decision 9): it refuses to turn this
    on while any active member holds neither a password nor a PIN, and names
    them. Absent reads as False, which is audit mode — the only safe reading
    of a missing key, and what every install predating the arc has.
    """
    try:
        from services import storage
        return bool((storage.get_settings() or {}).get('auth_enforce'))
    except Exception:
        # A settings read that fails must not lock the family out of the house.
        return False


def check_request(method: str, path_template: str, headers, query) -> Optional[dict]:
    """Returns None to allow, or a dict describing the refusal.

    In audit mode it always returns None, having written down what it would
    have said."""
    allowed = resolve(method, path_template)
    who = identify(headers, query)

    if allowed is None:
        # Unclassified: the table is wrong. Record it loudly; never deny on it,
        # because a table gap is our bug and the family should not pay for it.
        record(method, path_template, None, who.get('tier'))
        return None

    if allowed is ANYONE or not allowed:
        return None

    if who.get('tier') in allowed:
        return None

    record(method, path_template, allowed, who.get('tier'))
    if not enforcing():
        return None
    return {'status': 401 if who.get('tier') is None else 403,
            'needs': sorted(allowed), 'saw': who.get('tier')}
