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

### Decision 4d — email plumbing, and the fallback when there is none

Outbound mail does not exist yet; inbound does. Intake already stores
`ingest_email_host` / `ingest_email_user` / `ingest_email_password` for a
dedicated Gmail polled over IMAP, and **a Gmail app password authenticates
SMTP just as well** — so invites, verifications and resets go out from the
family's own address with no new credential and no third-party mail service.
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

## Settled by the household 2026-08-15

- **Accounts, not a picker** (Decision 4). The member-name leak that the
  picker created is settled by deleting the picker as the front door: with a
  login, `/api/members` no longer has to answer before authentication.
- **Parents hold a real password**, not a longer PIN.
- **Argyle gets a grace window, then a service token** (Decision 6) — nothing
  breaks in the sitting where enforcement flips.

Still to fix, not a question: **rate limiting is in-memory**
(`_PIN_ATTEMPTS`) and resets on every add-on restart. It must be persisted,
and per-IP as well as per-identity, before anything faces the internet.

## Slices

- **S1 — the spine.** Tiers, the classification table, the default-deny
  dependency, audit-mode logging, the every-route-classified test. Nothing
  user-visible.
- **S2 — identity from the token.** Derive the member; stop trusting supplied
  ids. Impersonation closes here.
- **S3 — accounts.** `email` / `password_hash` / verification state on
  `FamilyMember`; invite, verify, set-password and reset flows with signed
  expiring tokens; SMTP send over the existing intake credentials, with the
  copyable-link fallback; the sign-in page that replaces the picker.
- **S4 — the parent login on the admin surface.** Dashboard/config sessions,
  parent passwords mandatory, `pin/clear` gated, rate limiting persisted and
  per-IP.
- **S5 — PIN demoted to device re-auth**, so shared-device switching stays
  fast; stage-driven defaults for children (Sprout/Explorer PIN-only).
- **S6 — device enrolment** for panels.
- **S7 — the service token** and the component update; grace window ends.
- **S8 — flip enforcement**, tighten CORS off `*`, token expiry and
  revocation, and the security section in `system_capabilities.md`.

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
