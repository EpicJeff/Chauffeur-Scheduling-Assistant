# The auth pass — design brief

Decided 2026-08-15. The app is published publicly by the cloudflared add-on
with no Cloudflare Access in front, and it has no authentication. 417 routes;
5 check `require_parent_token`. Anyone who knows the hostname can read and
write the whole family dataset — messages, kids' schedules and school hours,
the home address, moments photos, member locations — and can reach a parent
token in two unauthenticated calls (`/api/members/{id}/pin/clear` then
`/api/members/{id}/auth`, which mints freely once `pin_hash` is gone).

The only thing in front of it today is that nobody has guessed the hostname.

## The finding under the finding

**Identity in this app is client-asserted.** The PWA sends
`selectedMemberId` as an ordinary parameter and the server believes it. The
per-device token minted by `/api/members/{id}/auth` exists, but only five
routes ever look at it. So the work is not "add a login" — there IS a login.
The work is **making the token the identity everywhere, and making every
route say who it is for.**

That reframing matters for scope: this is not a feature bolted to the side,
it is a change to how every surface names its user. Which is exactly why it
gets a brief instead of a patch.

## What must not break

The rule that shapes every decision below
([[never-drop-functionality-unasked]] in practice):

1. **The wall panel comes up with nobody logged in.** A panel is a place, not
   a person — the line the music arc already settled. It cannot be behind a
   member login, and it must survive a reboot at 6am with no human present.
2. **Parents sometimes administer remotely** (confirmed 2026-08-15). So the
   answer for the dashboard is a real login, NOT a LAN-only lockdown. Blocking
   remote admin would be taking away something in use.
3. **Argyle keeps working.** The HA custom component calls
   `http://local-chauffeur:8000` — it arrives on the internal hostname, never
   through the tunnel, and it has no credential to present today.
4. **Kids keep their surfaces.** The kid lens, My Day, chores and routines are
   reached by children who may have no PIN set.
5. **Android's share target keeps ingesting.** `/share` is POSTed by the OS
   share sheet, which attaches no headers of ours.

## The model

Five trust tiers, resolved once per request:

| Tier | Who | How it proves itself |
|---|---|---|
| `public` | nobody in particular | no proof — the tier is the allowlist |
| `member` | a signed-in family member | member token (existing mechanism) |
| `parent` | a member with `role='parent'` | member token + role check |
| `device` | an enrolled wall panel | long-lived device token, parent-issued |
| `service` | the HA component / agent stack | service token, local-origin grace |

### Decision 1 — default-deny, enforced centrally

A dependency (or middleware) that **denies unless the route is classified**.
With 417 routes, opt-in gating guarantees drift: the next route somebody adds
would be public by accident, which is precisely how this state was reached.
Route → tier lives in one table, and **a test fails on any unclassified
route** — the same discipline `settings_registry.audit()` already applies to
settings, for the same reason (an index that quietly falls behind the model is
worse than none).

### Decision 2 — ship in AUDIT MODE first, then flip

The classification ships **logging what it *would* deny and denying nothing**.
Then the family uses the house normally — the wall panel, phones, Argyle, the
Android share sheet, the kiosk boards — and the log says which real callers the
table got wrong. Then one setting flips to enforce.

This is the whole safety story for a change that touches every surface. The
alternative is discovering the panel can't reach `/api/board` at 6:40am on a
school morning.

### Decision 3 — the token is the identity; client-asserted ids stop being trusted

`sender_member_id` and friends become derived, not supplied. This closes the
impersonation hole (today any caller can post a message as any member) and is
the part that must land before enforcement means anything.

### Decision 4 — real accounts: adding a person IS creating a user

Decided by the household 2026-08-15, and it supersedes the picker-and-PIN
model this brief originally proposed. **If we are shipping a native app, this
is a real service and it gets real accounts**: a parent adds a person with an
email address, that person receives a link, verifies, and sets a password.

The reasoning that makes it more than convention: the load arc deliberately
brought outsiders into the model — helpers, carpool parents, grandparents —
and the native app track exists because *those* are the people who will only
ever install one app. "Pick your face off a list and type four digits" is a
kitchen-tablet gesture. It does not survive contact with a public origin or
with a grandparent two states away, and no amount of rate limiting makes it
into an account.

**The account IS the `FamilyMember`.** One entity gains `email`,
`password_hash`, and verification state — no parallel `User` table, which
would drift from the member record within a release (the app already treats
the member as the identity everywhere; a second identity object would just be
two things to keep in sync). `AssistContact` is unaffected: a contact is
someone the household records, not someone who signs in. Promoting a contact
to a helper still means creating a member, which now means sending an invite.

### Decision 4b — not everyone has an email, and that is fine

A seven-year-old has no inbox, and making one a prerequisite for appearing on
the family's schedule would be absurd. So:

- **Members with an email** get the full flow: invite → verify → password.
- **Members without one** are parent-created and parent-managed. Their
  credential is a PIN, set and reset by a parent, and they never receive mail.
- Which one a child gets follows the **stage** primitive A4 already shipped —
  Sprout and Explorer are PIN-only by default, Navigator and Copilot can hold
  an email and a password. Growing up is granted, exactly as A4 says.

### Decision 4c — the PIN survives, demoted to what it is good at

PINs do not die; they stop being the front door. The pattern every banking app
uses: **the password establishes the account on a device, the PIN re-opens it
on a device already trusted.** That keeps the thing the family actually does
every day — fast identity switching on the shared tablet and the wall — while
the credential that faces the internet is a real password.

Consequence, accepted: **parents must have a password** (their own answer to
the same question), and `/api/members/{id}/pin/clear` becomes parent-gated in
the slice that gives the dashboard an identity. Gating it before then would
silently remove the parent's PIN reset —
[config.html](../templates/config.html) calls it with no token today.

### Decision 4d — email plumbing: its own sender, reuse optional

Outbound mail does not exist yet; inbound does. Intake stores
`ingest_email_host` / `ingest_email_user` / `ingest_email_password` for a
dedicated Gmail polled over IMAP, and **a Gmail app password authenticates
SMTP just as well** — so reusing it is possible and costs no new credential.

**But the sender is its own setting** (decided by the household 2026-08-15),
with an explicit "use the intake mailbox" toggle that greys the fields and
mirrors the values. Reuse is offered, never forced.

The reason is stronger than preference, and it is a real defect avoided:
**the intake mailbox analyses every message that arrives in it** — that is
the design, the mailbox IS the filter. Invites sent from that address would
bring their own delivery noise home: bounces, out-of-office autoreplies, and
"did you actually send me this?" replies would all land in the mailbox and be
extracted into event proposals. A grandparent's vacation autoresponder would
become a proposal on the family's queue. Separating the sender keeps the
proposal queue fed only by what the family deliberately forwards.

Settings, registered per the config decentralisation rule (registry entry
first, on the feature's own surface, never appended to config.html), owned by
the surface where invites are sent rather than by a settings dump:
`smtp_host` / `smtp_port` / `smtp_user` / `smtp_password` / `smtp_from`, plus
`smtp_use_intake` as the mirror toggle. Secrets show as set/not-set, as the
registry already requires.

One constraint to surface in the UI rather than discover in a bounce: most
providers refuse to send from a `From` address the authenticated account does
not own. So `smtp_from` is validated against `smtp_user` (equal, or a
configured alias) with a plain warning rather than a silent failure.

Links are built from the `public_base_url` setting the cloudflared hostname
already populates.

**Email must not become a hard dependency**, in the same spirit as the
standing rule that every HA touchpoint degrades gracefully. With no mail
configured, an invite produces a **copyable one-time link** the parent hands
over however they like. Same token, same expiry, one less moving part.

**Noted honestly:** password reset by email makes the intake mailbox a master
key to the household. That mailbox is already a curated forwarding address
rather than a personal inbox, which helps, but it belongs in the security
section rather than in a footnote.

### Decision 5 — panels enrol as devices

A parent enrols a panel once from the dashboard; the panel stores a
long-lived device token. `device` grants board reads and the interactive board
actions a wall legitimately performs (claim a chore, check a routine, play
music) and **never** grants admin. A panel is a place: it gets the powers of
the room it is bolted to, not the powers of whoever last touched it.

### Decision 6 — a service token for HA, with a local-origin grace

The component gets a token in its config flow. Because that requires a
component update and a reconfigure, requests arriving on the internal
hostname keep working during a **grace window controlled by a setting**, so
nothing breaks the day this ships. The grace is a dated migration step, not a
permanent tier — a permanently trusted LAN is a second open door.

### Decision 7 — the bootstrap stands on HA ingress, not on the LAN

Corrected 2026-08-15 during S4. S3 shipped with "allowed from the LAN,
parent-only from the internet", which was weaker than it looked: a LAN is
every guest phone and smart plug on the wifi, and it also forced the owner to
be at home to set the house up.

**Home Assistant's ingress is a real identity claim.** Supervisor does not
serve ingress to an anonymous browser, so a request arriving that way has
already been authenticated by HA — opening Chauffeur from the sidebar is
proof enough to claim the first parent account.

**The safety rule that makes this sound, and it is not optional**: the ingress
headers (`X-Ingress-Path`, `X-Hass-User-ID`, `X-Hass-Is-Admin`) are trivially
forged by anyone who can reach the app, so through the tunnel a stranger could
simply claim to be the owner. `arrived_via_ingress()` therefore refuses to
believe those headers on any request that arrived through cloudflared.
Supervisor is on the other side of that boundary and nothing outside can put
itself there. Header trust without the origin check would be a worse hole than
the one this arc closes.

**And the grace closes by itself.** `_any_parent_has_password()` gates it, so
the moment one parent holds a password the household has an owner and the
bootstrap shuts permanently — no dated switch for anybody to remember.

### Decision 8 — sessions: 90 days, PIN as the fast re-auth

Settled with the household 2026-08-15. Sign-in-once depends on a long-lived
token, and the trade is real in both directions: short expiry means
grandparents re-typing passwords they have forgotten, long expiry means a
stolen phone stays signed in until somebody revokes it. So: **90 days**, with
the PIN re-opening a trusted device (Decision 4c) so the common case is four
digits rather than a password, plus **"sign out everywhere"** on each member
card for the stolen-phone case. Built in S8 with the rest of the token work.

### Decision 9 — S8 refuses to flip while anyone would be locked out

A switch that can lock a family out of their own house is not a bare
checkbox. Enforcement will not turn on while any active member holds neither
a password nor a PIN, and it names them instead. The audit report
(`/api/admin/auth_audit`) is the other half of the same idea: flip on
evidence, not on a hunch.

## Settled by the household 2026-08-15

- **Accounts, not a picker** (Decision 4). The member-name leak that the
  picker created is settled by deleting the picker as the front door: with a
  login, `/api/members` no longer has to answer before authentication.
- **Parents hold a real password**, not a longer PIN.
- **Argyle gets a grace window, then a service token** (Decision 6) — nothing
  breaks in the sitting where enforcement flips.

~~Still to fix, not a question: rate limiting is in-memory.~~ **Done in S4**
(v2.250.0): persisted in storage, per-IP as well as per-identity, doubling
backoff. The IP is read from `CF-Connecting-IP` only — `X-Forwarded-For` is
client-supplied, and a rate limit keyed on something the attacker can rotate
is decoration.

## Slices

- **S1 — the spine.** Tiers, the classification table, the default-deny
  dependency, audit-mode logging, the every-route-classified test. Nothing
  user-visible.
- **S2 — identity from the token.** Derive the member; stop trusting supplied
  ids. Impersonation closes here.
- **S3 — accounts.** `email` / `password_hash` / verification state on
  `FamilyMember`; invite, verify, set-password and reset flows with signed
  expiring tokens; its own SMTP sender settings with the reuse-intake toggle,
  and the copyable-link fallback when no mail is configured; the sign-in page
  that replaces the picker.
- **S4 — the parent login on the admin surface.** Dashboard/config sessions,
  parent passwords mandatory, `pin/clear` gated, rate limiting persisted and
  per-IP.
- **S5 — PIN demoted to device re-auth**, so shared-device switching stays
  fast; stage-driven defaults for children (Sprout/Explorer PIN-only).
- **S6 — device enrolment** for panels.
- **S7 — the service token** and the component update; grace window ends.
- **S8 — flip enforcement**, tighten CORS off `*`, token expiry and
  revocation, and the security section in `system_capabilities.md`.
  **BUILT DARK v2.260.0–v2.265.0** (route-table fixes from the live audit,
  query-string tokens for headerless channels, 90-day expiry + sign-out-
  everywhere, Decision 9 guard, the Enforcement control with the audit
  beside it, login-replaces-picker on untrusted ground, Alpine on every
  page so a refused screen can always draw its way in, CORS removed). The
  flip itself is the household's act, on evidence — the checklist lives in
  `system_capabilities.md` → "Flip-day checklist".

Accounts grew this from six slices to eight, and S3 is the largest single
piece of work in it. That is the honest cost of the decision, and it buys the
thing the native app track needs anyway: a person who holds this app has an
account, not a seat at a kitchen tablet.

## Deliberately out

- **Multi-household / real user accounts.** Everything assumes one family per
  install and that does not change here.
- **Cloudflare Access.** Considered as a stopgap and not taken: it puts a
  login wall in front of the PWA for every helper and complicates
  service-worker fetches. It remains available as a belt over these braces.
- **Encrypting data at rest.** A different threat model (a stolen HA box), not
  this one.
