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
    (ANY, '/health', ANYONE, None),
    (ANY, '/manifest.json', ANYONE, None),
    # HA's icon-shape chunks, proxied for the REAL ha-icon the hosted
    # built-in cards render — it fetches them relative to the page. The
    # content is SVG path data, the same files HA serves any browser before
    # sign-in; nothing about the household rides in an icon's outline.
    ('GET', '/static/mdi/{fname}', ANYONE, None),
    # Same class: HA's fingerprinted UI translation files, fetched
    # page-relative by the borrowed frontend chunks. Strings, served to any
    # browser by HA itself before sign-in.
    ('GET', '/static/translations/{path:path}', ANYONE, None),
    (ANY, '/sw.js', ANYONE, None),
    (ANY, '/api/vapid_public_key', ANYONE, None),
    # Sign-in itself. `/auth` mints the token, so it cannot require one; it is
    # the single most attackable route in the app and S4 gives it persistent,
    # per-IP rate limiting to match.
    ('POST', '/api/members/{member_id}/auth', ANYONE, None),
    # The picker's data (S8, Decision 4 built at last). ANYONE in the TABLE,
    # gated in the HANDLER: `_gate_family_listing` answers a caller with any
    # tier, or anonymous on trusted ground (vouched device / LAN / ingress) —
    # which is the only place the faces picker exists any more. Off trusted
    # ground the front door is the login page, which needs no list. The tier
    # table cannot express "trusted ground", so the handler owns the rest.
    ('GET', '/api/members', ANYONE, None),
    ('GET', '/api/drivers', ANYONE, None),
    # "Where am I standing?" — one boolean about the caller's own ground,
    # which is how the PWA picks its front door. Open like this-device: the
    # answer contains nothing the request did not arrive with.
    ('GET', '/api/account/ground', ANYONE, None),
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
    (ANY, '/account/set-password', ANYONE, None),
    ('GET', '/api/account/link/{token}', ANYONE, None),
    # First-run: both are guarded by the INGRESS check inside the handler,
    # not by a tier — the whole point is that they answer to somebody who has
    # no account yet. `/setup` reports only whether a household is claimed and
    # which parents exist by name, and `/claim` closes permanently the moment
    # one parent holds a password.
    ('GET', '/api/account/setup', ANYONE, None),
    ('POST', '/api/account/claim', ANYONE, None),
    # Echoes back only the caller's OWN headers; says nothing about the
    # household. Open so it can answer when nothing else will.
    ('GET', '/api/account/env', ANYONE, None),
    # Pairing (S6). The two the DEVICE calls are open by necessity — a screen
    # with no credential is exactly who calls them — and neither grants
    # anything on its own: the request only produces a code somebody still has
    # to approve, and the status poll is keyed on a device id the screen
    # minted and nobody else knows. Approval itself is parent-only, below.
    ('POST', '/api/account/devices/pair-request', ANYONE, None),
    ('GET', '/api/account/devices/pair-status', ANYONE, None),
    # "What am I called?", answered for the caller's OWN device and nothing
    # else. Open for the same reason as the two above: the id in the header is
    # one the screen minted, so the answer contains nothing it did not arrive
    # with, and a wall panel naming itself to Music Assistant has no
    # credential to offer. Deliberately NOT under /api/account/devices/, which
    # is the parent-only list a lost tablet gets revoked from.
    ('GET', '/api/account/this-device', ANYONE, None),
    # The device list is where a lost tablet gets revoked, so it is admin —
    # as is saying yes to a screen, and minting Argyle's credential.
    (ANY, '/api/account/devices', PARENTS, None),
    (ANY, '/api/account/devices/*', PARENTS, None),
    ('POST', '/api/account/service-token', PARENTS, None),
    ('POST', '/api/account/set-password', ANYONE, None),
    ('POST', '/api/account/login', ANYONE, None),
    ('POST', '/api/account/forgot', ANYONE, None),

    # --- parent-only: administration and anything that hands over the house --
    # These are the routes where "open" was worth a whole compromise.
    (ANY, '/api/download_db', PARENTS, None),
    (ANY, '/api/debug_db', PARENTS, None),
    (ANY, '/api/debug/*', PARENTS, None),
    (ANY, '/api/admin/*', PARENTS, None),
    (ANY, '/api/test/*', PARENTS, None),
    (ANY, '/api/cache/*', PARENTS, None),
    (ANY, '/api/members/{member_id}/pin/clear', PARENTS, None),
    (ANY, '/api/members/{member_id}/pin', SIGNED_IN, None),   # own PIN; S4 tightens
    ('POST', '/api/members/*', PARENTS, None),                # create/edit members
    ('PUT', '/api/members/*', PARENTS, None),
    ('PATCH', '/api/members/*', PARENTS, None),
    ('DELETE', '/api/members/*', PARENTS, None),
    (ANY, '/api/settings/*', PARENTS, None),
    (ANY, '/api/scope/*', PARENTS, None),   # S14: the editor's metadata
    (ANY, '/api/settings', PARENTS, None),
    (ANY, '/api/ics_feeds/*', PARENTS, None),
    ('GET', '/api/calendar_health', PARENTS, None),   # which calendars are being skipped
    (ANY, '/api/drivers/*', PARENTS, None),
    (ANY, '/api/passengers/*', PARENTS, None),
    (ANY, '/api/rules/*', PARENTS, None),
    (ANY, '/api/priority_rules/*', PARENTS, None),
    (ANY, '/api/errand_rules/*', PARENTS, None),
    (ANY, '/api/status-tiers/*', PARENTS, None),
    (ANY, '/api/stages/*', PARENTS, None),
    (ANY, '/api/themes/*', PARENTS, None),
    (ANY, '/api/calendars/*', PARENTS, None),
    (ANY, '/api/walmart/*', PARENTS, None),
    (ANY, '/api/ha_sensors/*', PARENTS, None),
    # The music card's HA lanes, carved out ABOVE the admin prefix below
    # (first hit wins): the board's music card lists players and sends
    # transport commands from a wall, and the artwork proxy is drawn as a bare
    # <img> by panels and the PWA alike — an image request can carry no header,
    # so the token rides the query string (identify() reads it there).
    # Everything else under /api/ha stays administration.
    ('GET', '/api/ha/media_players', WALL, 'music'),
    ('POST', '/api/ha/media_players/{entity_id}/command', WALL, 'music'),
    ('GET', '/api/ha/image64/{encoded}', WALL, 'music'),
    # The hosted built-in cards' lanes (services/ha_frontend), carved out the
    # same way and for the same reason: a wall panel is what mounts HA's own
    # cards, and the bundle, its chunks, the theme and a sensor's history are
    # all read on the panel's own tier. The chunk files and the icon shapes
    # are the same unauthenticated statics HA hands any browser pre-sign-in —
    # but everything above them stays behind the wall tier because history
    # and registries ARE household data.
    ('GET', '/api/ha/frontend/*', WALL, None),
    # The hosted camera elements' two lanes — a frame and the MJPEG stream —
    # drawn as bare <img> by panels, same as the artwork proxy above them.
    # HA additionally validates its own per-camera access token.
    ('GET', '/api/camera_proxy/{entity_id}', WALL, None),
    ('GET', '/api/camera_proxy_stream/{entity_id}', WALL, None),
    (ANY, '/api/ha/*', PARENTS, None),
    (ANY, '/api/telemetry/*', PARENTS, None),
    (ANY, '/api/push_subscriptions/*', PARENTS, None),
    # NOTE: the admin PAGES are public shells; their DATA is parent-gated
    # above and below. See the shell-vs-data note in the wall section.
    (ANY, '/config', ANYONE, None),
    (ANY, '/dashboard', ANYONE, None),
    (ANY, '/dashboard_v2', ANYONE, None),
    (ANY, '/settings', ANYONE, None),
    (ANY, '/mind', ANYONE, None),
    # Threads: same admin-page shape as Mind — a shell anyone can load, the
    # data behind it gated at /api/threads/* above (SIGNED_IN to read, the
    # handler's `_mind_actor` refusing a child/helper/guest write).
    (ANY, '/threads', ANYONE, None),
    # Programs: same admin-page shape as Threads/Mind — a shell anyone can
    # load, the data behind it gated at /api/programs* above.
    (ANY, '/programs', ANYONE, None),

    # FastAPI's generated docs. Found UNCLASSIFIED by the S1 test, which is
    # the first thing it caught and on its own worth the file: `/docs` is a
    # complete, interactive map of all 417 routes with a try-it-out console
    # attached, and it has been served to the public internet next to an app
    # with no authentication. Parents-only here; S8 should consider switching
    # them off outright, since nobody in this household reads them.
    (ANY, '/docs', PARENTS, None),
    (ANY, '/docs/*', PARENTS, None),
    (ANY, '/redoc', PARENTS, None),
    (ANY, '/openapi.json', PARENTS, None),

    # --- Argyle ------------------------------------------------------------
    # NOT robots-only, and the live audit is what said so: the Argyle bar is
    # drawn on member surfaces (the PWA's FAB) and on wall panels, and each of
    # those callers POSTs /api/chat as itself. Anonymous is the only refusal.
    (ANY, '/api/chat/*', WALL_OR_SERVICE, 'chat.agent'),
    # The bar's read side is an EventSource, which can set no headers — the
    # token rides the query string. /api/v2/converse below stays robots-only:
    # it is the HA Assist webhook, and no browser surface posts it.
    ('GET', '/api/v2/chat/stream', WALL_OR_SERVICE, 'chat.agent'),
    (ANY, '/api/v2/*', ROBOTS, 'chat.agent'),
    (ANY, '/api/announce/*', ROBOTS, 'music'),

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
    (ANY, '/', ANYONE, None),
    (ANY, '/home', ANYONE, None),
    (ANY, '/board/{slug}', ANYONE, None),
    (ANY, '/api/home_board/*', WALL, None),
    (ANY, '/api/panel/*', WALL, None),
    (ANY, '/api/schedule/*', WALL, None),
    (ANY, '/api/weather/*', WALL, None),
    (ANY, '/api/presence/*', WALL, 'presence.moments'),
    (ANY, '/api/moments/*', WALL, 'presence.moments'),
    # The generic photo-in endpoint (routine items, shopping items) — before
    # the media wildcard so it does not inherit the moments facet: attaching
    # a product photo is list work, not a moment.
    (ANY, '/api/media/photo', WALL, None),
    (ANY, '/api/media/*', WALL, 'presence.moments'),
    (ANY, '/api/music/*', WALL, 'music'),
    # The panel screen player: the app's one WebSocket. A browser's WebSocket
    # API can set no headers, so the token rides the query string — identify()
    # reads query params for exactly this class of caller.
    (ANY, '/api/sendspin/ws', WALL, 'music'),
    # Trip backgrounds are CSS/<img> urls drawn by the trip pages AND the trip
    # kiosk; no header is possible there either, so the token rides the query.
    ('GET', '/api/unsplash/background', WALL, None),
    (ANY, '/api/announce', WALL, 'music'),
    # Kiosk-capable destinations: a parent opens these in a browser and a panel
    # draws the same page with ?panel=true. Both, therefore, or one of the two
    # is a lie (see property 3 above).
    (ANY, '/chores', ANYONE, None),
    (ANY, '/routines', ANYONE, None),
    (ANY, '/meals', ANYONE, None),
    (ANY, '/lists', ANYONE, None),
    (ANY, '/shopping', ANYONE, None),   # redirects to /meals
    (ANY, '/calendar', ANYONE, None),
    (ANY, '/errands', ANYONE, None),
    (ANY, '/occasions', ANYONE, None),
    (ANY, '/moments', ANYONE, None),
    (ANY, '/moment', ANYONE, None),
    (ANY, '/map', ANYONE, None),
    (ANY, '/music', ANYONE, None),
    (ANY, '/trips', ANYONE, None),
    (ANY, '/trip', ANYONE, None),
    (ANY, '/intake', ANYONE, None),
    (ANY, '/app', ANYONE, None),
    # Interactive board actions — a wall may claim a chore and check a routine;
    # that is the whole point of `interactive` tiles.
    (ANY, '/api/chores/*', WALL, 'chores.board'),
    (ANY, '/api/routines/*', WALL, 'routines'),
    # Avatars: a panel may READ a look (boards draw them) but the write is
    # gated a second time inside the endpoint, per-member, by PIN or token.
    # The ledger, not this table, decides what a person may actually wear.
    ('GET', '/api/avatar/*', WALL, None),
    (ANY, '/api/avatar/*', SIGNED_IN, None),
    # Pets, gated exactly like avatars and for the same reasons: a panel READS
    # them because boards draw the family's critters, and every write is gated
    # a second time inside the endpoint, per-member, by PIN or parenthood.
    # Nothing a pets write can reach is earned -- species, look, name and
    # element are free -- so there is nothing here for a tier to protect
    # beyond "this is mine to change".
    ('GET', '/api/pets', WALL, 'pets'),
    ('GET', '/api/pets/*', WALL, 'pets'),
    (ANY, '/api/pets', SIGNED_IN, 'pets'),
    (ANY, '/api/pets/*', SIGNED_IN, 'pets'),
    (ANY, '/api/points/*', WALL, 'points.balances'),
    (ANY, '/api/rewards/*', WALL, 'rewards'),
    (ANY, '/api/redemptions/*', WALL, 'rewards'),
    (ANY, '/api/shopping/*', WALL, 'lists.shopping'),
    (ANY, '/api/kid-tasks/*', WALL, 'lists.kid_tasks'),
    (ANY, '/api/kids/*', WALL, None),
    (ANY, '/api/meals/*', WALL, 'meals.plan'),
    (ANY, '/api/prep-kits/*', WALL, 'meals.prep'),
    (ANY, '/api/prep_status/*', WALL, 'meals.prep'),
    (ANY, '/api/packing/*', WALL, 'meals.prep'),
    (ANY, '/api/stream/*', WALL, None),

    # --- signed-in members: the ordinary app ------------------------------
    (ANY, '/api/messages/*', SIGNED_IN, None),
    (ANY, '/api/channels/*', SIGNED_IN, None),
    (ANY, '/api/events/*', SIGNED_IN, 'calendar.events'),
    # The cancellation record: what was called off, when, why — the
    # reschedule memory. Calendar-shaped, so it wears the calendar facet.
    (ANY, '/api/cancellations', SIGNED_IN, 'calendar.events'),
    (ANY, '/api/errands/*', SIGNED_IN, 'lists.errands'),
    (ANY, '/api/overrides/*', SIGNED_IN, 'schedule.assignment'),
    (ANY, '/api/occasions/*', SIGNED_IN, 'occasions'),
    (ANY, '/api/trip/*', SIGNED_IN, 'trips.detail'),
    (ANY, '/api/trips/*', SIGNED_IN, 'trips.gallery'),
    (ANY, '/api/proposals/*', SIGNED_IN, None),
    (ANY, '/api/action-proposals/*', SIGNED_IN, None),
    (ANY, '/api/ingest/*', SIGNED_IN, None),
    (ANY, '/api/status/*', SIGNED_IN, 'presence.status'),
    (ANY, '/api/requests/*', SIGNED_IN, None),
    (ANY, '/api/household-tasks/*', SIGNED_IN, 'lists.household_tasks'),
    (ANY, '/api/household-load/*', SIGNED_IN, None),
    (ANY, '/api/commitments/*', SIGNED_IN, None),
    # Needs You. SIGNED_IN at the route, because a helper is a signed-in member
    # and the route guard is not where role is decided here — the handlers
    # refuse a child/helper/guest by role (`_needs_you_actor`), the same
    # discipline the cancel routes use. The findings themselves carry a child's
    # care gaps and an adult's protected time, so this pair of gates is the
    # point rather than belt-and-braces.
    (ANY, '/api/findings/*', SIGNED_IN, None),
    (ANY, '/api/findings', SIGNED_IN, None),
    # Mind insight lane: same discipline — SIGNED_IN at the route, role
    # decided in the handler (`_mind_actor`) for dismiss/act/admin.
    (ANY, '/api/mind/*', SIGNED_IN, None),
    # Threads: open loops with somebody outside the family. Same discipline —
    # SIGNED_IN at the route, `_mind_actor` (reused, not rebuilt) refuses a
    # child/helper/guest in the handler for every write; reads are open to
    # any signed-in member, same as the findings list.
    (ANY, '/api/threads/*', SIGNED_IN, None),
    (ANY, '/api/threads', SIGNED_IN, None),
    # Negotiation's hand path (task 8): SIGNED_IN at the route, same
    # `_needs_you_actor` reused (not rebuilt) in every handler to refuse a
    # child/helper/guest — the deal surface is parent/adult work end to end.
    (ANY, '/api/negotiation/*', SIGNED_IN, None),
    # Programs (task 5): SIGNED_IN at the route. Unlike Threads and
    # Negotiation, role alone does not gate a write in the handler —
    # OWNERSHIP does (`_program_permission_or_refuse`, main.py): a child
    # acts freely on their OWN program (proposes, logs a session, marks a
    # milestone, pauses/resumes/drops), and acting on somebody ELSE's, or
    # approving (claims the week) at all, reuses `_mind_actor` +
    # `_approver_of_record`, exactly as Mind's approve tap does.
    # The ONE program route a wall panel may call, and it has to come before
    # the wildcard below to be reachable at all. It is a celebration-only
    # PROJECTION (`programs.celebrations`) — whose milestone is close, what got
    # practised, who just reached one — never the program payload, which
    # carries somebody's aim in their own words, their curated plan and every
    # session they logged. A panel is a place in a hallway anybody walks past,
    # so what it may read is decided by what the endpoint returns, not by
    # widening the read it was refused.
    ('GET', '/api/programs/celebrations', WALL, None),
    # WHEN the household's practice windows are, for the surfaces that draw a
    # day -- the wall's calendar card included, which is why this is WALL and
    # not SIGNED_IN. It carries a title, a name and an hour, which is the same
    # disclosure `celebrations` above already makes, plus the time; it carries
    # no session log, no counts and no commitments that did not come from a
    # program.
    ('GET', '/api/practice-windows', WALL, None),
    (ANY, '/api/programs/*', SIGNED_IN, None),
    (ANY, '/api/programs', SIGNED_IN, None),
    (ANY, '/api/coverage/*', SIGNED_IN, 'schedule.carpool_contacts'),
    (ANY, '/api/assist-contacts/*', SIGNED_IN, 'schedule.carpool_contacts'),
    (ANY, '/api/assist-coverage/*', SIGNED_IN, None),
    (ANY, '/api/assist-history/*', SIGNED_IN, None),
    (ANY, '/api/cars/*', SIGNED_IN, None),
    (ANY, '/api/places/*', SIGNED_IN, None),
    (ANY, '/api/maps/*', SIGNED_IN, None),
    (ANY, '/api/calendar/*', SIGNED_IN, 'calendar.events'),
    (ANY, '/api/school/*', SIGNED_IN, 'lists.kid_tasks'),
    (ANY, '/api/drive_status/*', SIGNED_IN, 'drives.status_writes'),
    (ANY, '/api/drive_sheet/*', SIGNED_IN, 'drives.sheet'),
    (ANY, '/api/family/*', SIGNED_IN, 'presence.location'),
    (ANY, '/api/unsplash/*', SIGNED_IN, None),
    (ANY, '/api/push_subscribe/*', SIGNED_IN, None),
    (ANY, '/api/members/*', SIGNED_IN, None),   # reads; the writes are gated above
    (ANY, '/api/sendspin/*', SIGNED_IN, 'music'),
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
    for rule in RULES:
        if _rule_matches(rule[0], rule[1], method, path_template):
            return rule[2]
    return None


def resolve_facet(method: str, path_template: str) -> Optional[str]:
    """The scope facet a route serves, or None — which is EXPLICIT here
    (family-network S7): every RULES row carries a fourth element, either a
    facet name from scope.FACETS or None for auth/infra/administration/shells
    and the welded payloads whose enforcement lives in their assemblers (S9).
    A test refuses any row that answers neither."""
    for rule in RULES:
        if _rule_matches(rule[0], rule[1], method, path_template):
            return rule[3] if len(rule) > 3 else None
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
    scope_rows = [{'method': m, 'path': p, 'facet': f, 'count': e['n'],
                   'saw': sorted(e['saw']), 'last': e['last']}
                  for (m, p, f), e in _SCOPE_AUDIT.items()]
    scope_rows.sort(key=lambda r: -r['count'])
    return {'would_deny': rows, 'routes': len(rows),
            'capped': len(_AUDIT) >= _AUDIT_CAP,
            'scope_would_deny': scope_rows,
            'identity': dict(_IDENTITY)}


_SCOPE_AUDIT = {}    # (method, path_template, facet) -> {'n', 'saw', 'last'}


def record_scope(method: str, path_template: str, facet: str, member) -> None:
    """A person whose scope does not reach this route's facet was here
    (family-network S7). Same job as record(): evidence for the flip, thrown
    away after. Every row is a surface some preset will lose at enforcement —
    quiet is the evidence, and a loud row is either a table error or a shell
    still showing somebody a door they may not open."""
    key = (method, path_template, facet)
    entry = _SCOPE_AUDIT.get(key)
    if entry is None:
        if len(_SCOPE_AUDIT) >= _AUDIT_CAP:
            return
        entry = _SCOPE_AUDIT[key] = {'n': 0, 'saw': set(), 'last': 0.0}
    entry['n'] += 1
    entry['saw'].add((member or {}).get('id') or 'unknown')
    entry['last'] = time.time()


def reset_audit() -> None:
    _AUDIT.clear()
    _SCOPE_AUDIT.clear()
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
        return _check_scope(method, path_template, who)

    if who.get('tier') in allowed:
        return _check_scope(method, path_template, who)

    record(method, path_template, allowed, who.get('tier'))
    if not enforcing():
        return None
    return {'status': 401 if who.get('tier') is None else 403,
            'needs': sorted(allowed), 'saw': who.get('tier')}


def _check_scope(method: str, path_template: str, who: dict) -> Optional[dict]:
    """Family-network S7: the facet check, run only after the tier passes.

    Only a resolved MEMBER has a scope — a panel is a place and Argyle is a
    robot; tiers already govern them. Only a hard reach of 'none' can refuse,
    and only for a route-kind facet: field-kind facets are enforced where
    their data is assembled (S9) and instance-kind ones on the object (S8),
    so here they are recorded and never denied — a route refusal would break
    exactly the instance grants §7 promises are additive. Dark until
    `auth_enforce` flips, same as everything else in this file."""
    member = who.get('member')
    if member is None:
        return None
    facet = resolve_facet(method, path_template)
    if not facet:
        return None
    try:
        from services import scope
        if scope.reach(member, facet) != scope.NONE:
            return None
        record_scope(method, path_template, facet, member)
        if scope.FACETS.get(facet, {}).get('kind') != 'route':
            return None
        if not enforcing():
            return None
        return {'status': 403, 'needs': [facet], 'saw': who.get('tier'),
                'facet': facet}
    except Exception:
        # Scope must never take the house down.
        return None
