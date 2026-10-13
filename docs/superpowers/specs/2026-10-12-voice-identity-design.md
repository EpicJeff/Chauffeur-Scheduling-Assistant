# Voice identity — a person on a satellite, with a bounded authority

**Date:** 2026-10-12. **Status:** V1/V2 implemented locally for v2.499.402; real-satellite/device acceptance remains pending. Identity and voice approval both default off.
**Builds on:** [Submit gate](2026-10-11-submit-gate-design.md). That gate is built through v2.499.399 but its spec still marks it not device-verified. Its approval, verification and lost-worker scenarios must pass before voice may invoke its approval rail.
**Original delivery order (implementation order superseded below):** device-verify the submit gate, then establish the useful device-chat payment/handoff path described in [Payment gate](2026-10-12-payment-gate-design.md), before voice approval. Device-chat payment does not depend on this spec. [Voice fingerprint](2026-10-12-voice-fingerprint-design.md) is a separate follow-up with its own device gates; it must not block PIN-based voice identity. A ten-minute voice session alone does not authorize spending.

**Updated authorization, 2026-10-12:** the user authorized implementation while device checks run, then selected voice identity as the active slice because it is useful independently of payment. Payment P0's target is left to the user. This supersedes the earlier implementation-order gate for V1/V2; approval activation and device acceptance remain required.

**Scope clarification, 2026-10-12:** the intended independent value includes automatic speaker recognition, not just spoken name/PIN identity. The fingerprint follow-up now implements enrollment, named recognition and PIN-session continuity through component 1.4.1 for HA 2026.10.x, guarded by the controller signature. It is off until enrollment and real family/device checks. Recognition does not provide approval authority or a payment-grade proof; see the fingerprint spec's implementation decision and remaining acceptance.

## Local implementation and remaining acceptance

`services/voice_identity.py` intercepts identity/PIN turns before persistence or model dispatch, owns bounded sessions and replay results, and stores durable voice locks. `services/voice_tools.py` supplies the explicit speech-safe tool rail and atomic household provenance. `services/voice_approval.py` owns readbacks and supplies server-only approval context to the existing release/submit services. The parent control is Config → People → Voice identity; configuration and lock counters use existing SQLite app-state storage, independently of general settings saves.

The initial tool allowlist covers shared calendar/list reads, the four shared mutations, internal family/direct messages, household mission research and preparation of release/submit readbacks. Other tools, including external sends and private situation/mail reads, retain phone handoff. Voice-created requests retain an unknown requester until verified; Argyle relays unattributed internal messages with an explicit Household voice label. Voice-approved contact values remain bound on later browser resumes.

The HA component is version 1.3.0: registry-validated satellite/device IDs, stable HA instance ID, request UUID and timestamp. Older HA may configure device-to-satellite mappings in the component's options. The installed household HA version and actual satellite pipeline still need device acceptance; source/interface tests and the local browser check do not establish microphone/STT behavior or that metadata reaches the deployed server. Setup and activation instructions are in [the integration guide](../../../homeassistant/README.md#voice-identity-and-approval).

Google Calendar's [source visibility marker](https://developers.google.com/workspace/calendar/api/v3/reference/events) is now preserved through merged Event models and the cache so private/confidential entries can be withheld by the speech projection. Existing caches need Sync Now after update; the source privacy propagation is covered by the local regression suite. The adapter also forwards continuation requests for PIN/readback replies when the installed HA result interface supports them.

Focused automated proof covers PIN redaction, numeric parsing, session isolation/revocation, durable locks and phone recovery, tool bypass attempts, room-safe data, exact readback binding, changed contact/booking records and replay. The served desktop/phone Settings check exercises identity enablement, verification, revoke and lock recovery. No real release, booking or payment was executed during verification.

## Outcome and scope

A person can tell a satellite who they are, get the appropriate non-sensitive family context, verify with their member PIN, and approve a pending contact release or booking after hearing the exact request. Identity is resolved before the conversational model runs. The model may help select a mission; it cannot verify a person or manufacture approval.

There are three levels: unknown, named and verified. Before speaker recognition ships, a verified session establishes that someone at this satellite knew the PIN. It cannot establish that every subsequent speaker is that same person. Keep this limitation explicit in setup; the fingerprint slice supplies continuity checks, not a claim of biometric certainty. A named lens and a current fingerprint observation are separate facts: naming yourself never supplies the recognized-parent proof that payment may accept when its Always require PIN for purchases setting is off.

## What exists and what changes

- `homeassistant/custom_components/chauffeur_conversation/conversation.py` currently forwards text, language and conversation ID, authenticated with `X-Service-Token`. It does not forward the satellite or device identity.
- `chauffeur/main.py`'s `ConverseRequest` and `/api/v2/converse` save the raw utterance and use it as a conversation title before calling `process_agent_request`.
- `services/agent_router.py` defaults to `source='admin'` and several dispatch paths fall back to `situations.parent_of_record()` when no member is supplied. An asserted name must never activate that fallback.
- `storage.verify_member_pin` already checks salted member PIN hashes. Reuse it and the existing PIN setup; do not introduce a second PIN for this slice. A missing PIN is not verification. PIN checking must not mint a reusable browser/member token for a satellite.
- `missions.release`, `missions.submit` and `missions.verify` already bind requests to an ask ID. Voice release/submit use the same domain operations. Verification of an uncertain external outcome remains on the phone in this slice.

## The user experience

| Level | How it starts | What it grants |
|---|---|---|
| Unknown | An authenticated satellite with no current identity | Shared, speech-safe information and the narrow household actions below, recorded as household voice. No personal identity or approval. |
| Named | “It's Jeff,” resolved uniquely against active members and configured aliases | Jeff's lens for information already safe to say in the room. No private access or write authority gained just by naming Jeff. |
| Verified | The named member supplies the correct PIN | That member's permitted non-sensitive actions and, for a parent/adult, release and submit approval through the readback flow below. |

Example:

1. “It's Jeff.” → “Hi Jeff.”
2. “Book the dishwasher appointment.” → resolve the relevant pending ask, then “I need your PIN before you can approve that.” No action is queued merely by identifying the mission.
3. “My PIN is …” → deterministic verification; “Verified here for ten minutes.”
4. Readback: “Book Bodewell for Tuesday, October 20, 8 AM to noon, with a $114.95 trip charge? Say ‘approve booking’ or ‘cancel.’”
5. “Approve booking.” → bind to that readback, call the existing submit service, then say “Approved. I'll check whether the booking went through.” Completion is announced only from the recorded outcome.

“Enter my information,” “yes” without a pending readback, and a PIN utterance by itself execute nothing. A release readback names the site and the categories of data; if exact values cannot be spoken under the speech policy, direct the person to the private card instead of approving a partially described release.

“Forget who I am” clears identity, focus and any readback on this satellite. “It's someone else” immediately drops verification before resolving the new name. Ambiguous names ask for clarification; approximate LLM name matching is not an authentication decision.

## Transport and session contract

Extend the HA payload with adapter-generated metadata:

```text
voice = {
  satellite_id, device_id?, ha_instance_id,
  request_id, observed_at,
  fingerprint_ref?                 # reserved for the fingerprint spec
}
```

Use `ConversationInput.satellite_id` where the installed HA version provides it, with a configured device-to-satellite mapping as the compatibility path. Validate both against HA's registry. The server pairs the HA installation and its allowed satellites with the service credential. Client claims such as member, role or verified are not accepted. Missing device metadata permits the unknown read/draft path, never a verification session. A conversation ID alone is not a satellite ID.

Require an actual enrolled service credential for identity/approval operations even if the general auth layer is running in audit mode or allows local-origin grace. Keep ordinary legacy conversation working without granting approval. Reject stale metadata outside a proposed 60-second delivery window; deduplicate requests by installation and request ID so a network retry cannot execute an approval twice. Return the original result for a duplicate; do not run the model again.

Proposed `services/voice_identity.py` owns sessions and deterministic authentication parsing. Store sessions in process memory; a restart logs everyone out. Durable failure counters and PIN hashes remain in storage.

```text
session = {
  id, generation, ha_instance_id, satellite_id,
  member_id?, level: unknown|named|verified,
  named_at?, verified_at?, expires_at?,
  pin_revision?, fingerprint_anchor_ref?,
  readback?: {id, mission_id, ask_id, kind, record_digest,
             member_id, generation, issued_at, expires_at, state}
}
```

Verified lifetime is ten minutes from PIN success, not a sliding timeout. Named identity also expires after ten minutes without an explicit re-identification, avoiding a room remembering Jeff indefinitely. A successful new PIN starts a new generation. PIN change/reset, member disablement or role change, service revocation, explicit logout and restart invalidate affected sessions. Re-read member status and role at each privileged operation. Expiry removes approval authority and clears the readback before dispatch.

Serialize identity transitions per satellite; never hold a storage lock over an LLM or network call. Scope history and triage focus to installation, satellite, conversation and identity generation. Name changes and verification loss must not expose another person's retained focus or history.

## PIN handling and lockout

Recognize a narrow grammar before title creation, conversation storage, event publication or agent dispatch: an explicit “my PIN is” phrase, or a numeric reply while a PIN challenge is pending. Use a deterministic, locale-specific parser, never an LLM. Support digit strings and digit words (preserving leading zeros), unambiguous grouped numbers (“twelve thirty-four” → `1234`), and a complete cardinal phrase (“one thousand two hundred thirty-four” → `1234`). Group boundaries must come from the supported grammar; ambiguous parses ask “Say it one digit at a time.” Do not pad, guess a missing zero or try multiple candidate PINs. Consume the entire credential turn, including any trailing instruction, as authentication only.

Store protected `pin_length` metadata when setting a PIN; keep it out of ordinary member/roster responses. Existing hashes cannot reveal their length: populate it only after a successful PIN verification or reset, never by guessing or changing existing credentials. With known length, a mismatch is a redacted format error and requests digit-by-digit speech without incrementing the wrong-PIN counter. With unknown length, accept a supported parse and use the existing verifier; an incorrect candidate counts as a failure. Malformed/ambiguous inputs do not increment the credential-failure counter, but all requests remain rate-limited.

The distinct format-error response can reveal PIN length to someone probing the satellite; this limited disclosure is an accepted tradeoff for avoiding lockouts on transcription errors, with request throttling still applied.

Do not log, echo, publish to `CHAT_EVENTS`, put in traces or persist the PIN. The model sees only an authentication result. A malformed credential turn is redacted too. Do not globally strip unrelated numbers from ordinary conversation.

The selected STT provider necessarily receives the utterance. HA may also expose transcript/audio through its own pipeline debugging before the conversation adapter runs. Document this boundary and keep audio debugging off for normal use; this slice does not claim to erase upstream records. A spoken PIN is a knowledge check and may be overheard or replayed. It is not proof of liveness.

**Explicit draft choice: retain the existing member PIN.** It also protects member authentication and parent switching on devices. Anyone who overhears it can reuse it there wherever that PIN is accepted; voice verification does not make it a voice-only secret. Setup must explain this cross-channel exposure. A separate voice PIN would change credential setup and recovery and is outside this draft, not an assumed protection. The user's choice to speak a PIN remains supported.

Persist consecutive failures for both `(installation, satellite)` and the claimed member. Three wrong PINs lock voice verification at the satellite and for the affected member; switching names, satellites or restarting cannot reset the respective counter. Correct verification clears only the matching unlocked counters, not another member's lock. Apply the existing broader request throttling as well.

An authenticated parent on their personal phone can inspect and clear the relevant voice locks by tap; this does not clear web PIN throttles or establish a verified satellite session. A new spoken PIN is still required. Keep audit records to member, satellite, outcome and timestamp, never credentials. Child/helper verification cannot acquire parent privileges.

Someone in the room, including a child, can deliberately trigger this lock with three wrong attempts. That denial of voice verification is an accepted limitation of the lockout rule; the signed-in phone path and its recovery control remain usable.

## Authorization and speech

Pass an explicit server-owned `VoiceContext` into `process_agent_request`; use `source='voice'`. It carries level, real member when verified, named lens when unverified, satellite, generation and speech audience. Neither model tool arguments nor a missing actor can upgrade it to admin.

Enforce this capability map at tool dispatch; V1 maps existing tools to it rather than deciding the policy during implementation:

| Capability | Unknown or named | Verified |
|---|---|---|
| Shared schedule, household lists and speech-safe information | Allowed. A named lens changes relevant context, not permissions. | Allowed. |
| Send an internal household message to active family members | Allowed, attributed to household voice; no claim that Jeff sent it and no private reply/history readback. | Allowed with the verified sender's identity. |
| Explicitly assign/remove a driver on a shared household event; add/check off a shared list item | Allowed as a household action, with actor provenance and normal change history. No private event/item access. | Allowed within the member's permissions. |
| Draft a message, create a household request or start mission research | Allowed with unknown requester; “get the dishwasher fixed” can research and propose. | Allowed. |
| Send an external message, release contact data or commit a booking | Require verification; external send also follows its existing approval policy. Release/submit require the exact readback below. | Allowed only under the relevant member permissions and approval rail. |
| Pay | Never through household delegation or a spoken name. | Payment's own parent-proof and fresh-PIN policy applies; session verification alone is insufficient. |
| Private reads, security/settings changes, uncertain-outcome verification | Phone path. | Phone path; verification does not make private data speech-safe. |

Any tool outside this allowlist denies voice execution and offers the phone path. Internal delivery is restricted to existing family recipients; an external contact cannot enter through the internal-message tool. Shared actions must not implicitly trigger an external send, release or commitment.

The two `agent_router.py` parent-of-record fallbacks (viewer construction and action dispatch) must take `VoiceContext`. For unknown/named voices, retain the nominated parent-of-record as the storage execution principal for exactly four shared mutations: assign a driver, remove a driver assignment, add a shared-list item, and check off a shared-list item. This is an explicit, limited retention of the fallback for storage compatibility. It does not apply to internal-message authorship, draft/request ownership, mission approval, or general viewer construction; messages and requests retain a household/unknown actor instead of borrowing a parent identity.

For those four mutations, store the compatibility member ID together with `actor_kind=household_voice`, satellite and request ID, while preserving `verified_member=None` in `VoiceContext`. Change-history rendering must prefer the provenance and say “Household voice,” not attribute the request to that parent or the spoken name. Scope checks use the household capability map before invoking storage, not the nominated parent's general permissions. If no active nominated parent exists, offer the phone path for those mutations; never select an arbitrary member. This makes the retained delegation explicit rather than a V1 implementation judgment.

Filter context and tool results before they reach the speaking model. Named and verified parents still get a room-safe projection: no DM bodies, sensitive insights, gifts/surprises, credentials, private shopping items or private member notes. Extend the existing `spoken=True` filtering beyond insight lists to direct lookups, search and focus injection. Do not rely on a last-minute instruction to hide data the model has already seen. A private result returns “That needs your phone,” without reading its title aloud.

Leave HA built-in intent routing unchanged, including the conversation entity's deliberate omission of `CONTROL`. This spec governs Chauffeur, not HA's own light/lock permissions.

## Exact voice approval

The router may propose a mission reference, but a deterministic controller loads the current pending ask, checks visibility and role, and renders a speech-safe readback. Ambiguity gets a choice, not an arbitrary most-recent ask. Bind the challenge to ask ID, canonical approved-record digest, member, satellite and generation. Proposed readback TTL: 60 seconds, bounded by session expiry. Only a later request with an explicit allowlisted confirmation phrase can consume it; never consume on the same turn that creates it.

Under the identity lock, mark the challenge dispatching and create one invocation ID. Invoke the existing ask-ID-bound service without holding the identity lock; duplicate delivery returns the same invocation's status. If the server dies, in-memory sessions vanish and the underlying mission ledger is authoritative. A moved ask or changed record cancels the readback and requires a new readback. Never choose new ask contents while processing an old confirmation.

Add a server-only approval context to the release/submit domain operations: channel, member, session generation, readback ID and approved digest. A model cannot supply it. For release, require the contact values to match the readback snapshot too; the current release path's “use the current contact card” behavior must not silently release values changed after speech. Persist the grant on the mission once accepted: normal session expiry after approval does not revoke a job already authorized. Explicit mission cancellation still prevents an unclaimed browser attempt.

The existing tap paths remain valid. Typed chat cannot use the satellite session. `verify` of an uncertain outcome and payment flows have separate contracts. Payment accepts an explicit “approved” for its active readback, then a fresh spoken PIN when its setting requires one; with the setting off, a current enrolled-parent fingerprint can supply the identity proof. That scoped exception does not make the named level generally privileged or permit a generic “yes” with no pending readback.

## Surfaces, builds and acceptance

Parent Settings gains Voice identity: enabled satellites, active member/level/expiry, revoke session and clear voice lock. The phone uses existing member PIN setup. Start with voice approval disabled until the household enables it after the device check; disabling revokes sessions and readbacks, not already accepted mission grants. The phone remains a complete hand path.

1. **V1 — identity before conversation:** HA metadata, explicit voice context, the capability map above, credential interception, lockout, history partition and speech projections. Prove no unrestricted parent fallback and no PIN in app artifacts. No approval yet.
2. **V2 — approve one pending thing:** readback controller, release/submit adapters, replay handling, Settings and phone recovery. Run the built submit-gate scenarios unchanged.
3. **Device acceptance:** the real satellite names two people, verifies one, reads back and approves a non-payment local test booking, expires, and refuses a stale confirmation. Record HA version, satellite and trace IDs without credentials. No real booking is required for tests.

Required regressions: two satellites cannot borrow sessions; two users sharing a conversation cannot borrow history; unknown/named/child requests cannot approve; three failures survive restart; missing/disabled member PIN refuses; sensitive direct lookup and focus do not speak; no PIN reaches history/title/SSE/model/logs; stale/repeated confirmations execute once; contact card change requires new release readback; changed booking state still re-asks; timeout is reported as pending/unknown rather than booked. Existing HA local commands still work.

Also prove the unknown household message, drive assignment and shared-list paths still work with household provenance; external recipients and private data cannot use that delegation. Cover each numeric grammar, leading zeros, ambiguous groups, known wrong length, legacy missing length, malformed-input throttling and deliberate lockout plus phone recovery.

## References and limits

The [HA conversation entity interface](https://developers.home-assistant.io/docs/core/entity/conversation/) is the integration entry point. Inspect and pin the installed HA version in V1; upstream development source is not a promise about the household's installation. No new speaker model, payment permission, general private-data voice mode or voice resolution of uncertain transactions ships here.

## Recognition review policy, 2026-10-12

Missing, late, short or uncertain evidence preserves identity and readback until their original expiry; only usable, confident contradictory evidence clears them. Correct PIN success without an embedding still establishes the bounded verified room session, clears the request-rate counter, and explicitly reports unavailable matching. Never anchor on a later arbitrary speaker. These are best-effort room semantics, not a fresh purchase fingerprint proof. Guided phone enrollment and app voice conversations are specified in [App voice](2026-10-12-app-voice-design.md).
