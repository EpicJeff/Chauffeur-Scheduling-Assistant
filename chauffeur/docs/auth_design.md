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

### Decision 4 — the dashboard gets a real parent login

Not a LAN check. Parents administer remotely, so `/dashboard` and `/config`
get the same member-token session the PWA has, with a parent role gate.
Consequence, accepted: **parents must have a PIN** — the "members without a
PIN authenticate freely" default is right for a household and wrong for the
public internet, so it survives for kids and ends for parents.

`/api/members/{id}/pin/clear` becomes parent-gated in the same slice, because
gating it before the dashboard has an identity would silently remove the
parent's PIN reset ([config.html](../templates/config.html) calls it with no
token today).

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

## Open questions for the household

- **The member picker leaks names.** `/api/members` must answer before anyone
  can sign in, so family first names and avatars are readable by anyone with
  the hostname. Options: accept it (they are first names), or put a household
  passphrase in front of the whole origin (one more secret to share with
  helpers, and it weakens the per-member story).
- **Parent credential strength.** A 4-digit PIN is thin as the only barrier on
  a public origin. Options: require 6–8 digits for parents, or a real password
  for the parent role while kids keep PINs.
- **Rate limiting is in-memory** (`_PIN_ATTEMPTS`) and resets on every add-on
  restart. It should be persisted and per-IP as well as per-member.

## Slices

- **S1 — the spine.** Tiers, the classification table, the default-deny
  dependency, audit-mode logging, the every-route-classified test. Nothing
  user-visible.
- **S2 — identity from the token.** Derive the member; stop trusting supplied
  ids. Impersonation closes here.
- **S3 — the parent login.** Dashboard/config session, mandatory parent PINs,
  `pin/clear` gated, persistent and per-IP rate limiting.
- **S4 — device enrolment** for panels.
- **S5 — the service token** and the component update; grace window ends.
- **S6 — flip enforcement**, tighten CORS off `*`, token expiry and
  revocation, and the security section in `system_capabilities.md`.

## Deliberately out

- **Multi-household / real user accounts.** Everything assumes one family per
  install and that does not change here.
- **Cloudflare Access.** Considered as a stopgap and not taken: it puts a
  login wall in front of the PWA for every helper and complicates
  service-worker fetches. It remains available as a belt over these braces.
- **Encrypting data at rest.** A different threat model (a stolen HA box), not
  this one.
