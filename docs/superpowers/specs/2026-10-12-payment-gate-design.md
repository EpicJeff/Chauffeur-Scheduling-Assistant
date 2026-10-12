# Payment gate — approve the payment, then prove you are a parent

**Date:** 2026-10-12. **Status:** draft for review; not implemented.
**User decisions, 2026-10-12:** one parent is sufficient. Approval is explicit. A setting, **Always require PIN for purchases**, decides whether a fresh PIN is required even when the system already identifies a parent. PINs are entered in device chat or spoken in voice chat. With the setting off, an authenticated parent PWA session or a fresh confident fingerprint match to an enrolled parent can approve without another PIN. There is no second-parent requirement, including above a spending threshold.
**Builds on:** [Submit gate](2026-10-11-submit-gate-design.md). Device-chat payment has no voice dependency. Later, [Voice identity](2026-10-12-voice-identity-design.md) adds spoken-PIN payment; [Voice fingerprint](2026-10-12-voice-fingerprint-design.md) conditionally supplies recognized-parent proof if its F0/F2 gates pass. Recognition alone never initiates payment. The submit gate's built code must first pass its device acceptance; its current spec does not claim that verification has happened.

## The outcome

Chauffeur reaches a known checkout, presents exactly what will be paid, receives one parent's explicit approval with the identity proof required by the current setting, and performs one bounded payment attempt. It records whether the merchant accepted it. If the outcome is uncertain, it asks for verification and cannot try again until that uncertainty is resolved.

Illustrative example, not a verified merchant capability: “The repair visit needs a $114.95 deposit. Pay it?” The parent approves in chat and enters their PIN in the inline credential field, or says “approved” and speaks their PIN when asked. Correct PIN releases that specific payment. With the setting off, the same approval is sufficient from a signed-in parent in device chat or a freshly recognized parent's voice. Chauffeur reports “Paid $114.95; receipt …” only on confirmation. The observed dishwasher booking flow does not establish that Bodewell takes an online payment.

A mission spending cap limits the total at risk; it is not another approval layer. Every payment, even below the cap, needs explicit approval of that transaction. Proposed default for **Always require PIN for purchases** is on; its behavior is the user's requirement, while the default is a draft choice.

## Scope and the initial supported checkout

Support one-time fixed-total payments in a single explicit currency per mission, through tested checkout extraction and execution. **P0 must identify a real, useful target before P1/P2 are planned.** Inspect a checkout the household actually needs: establish when money moves, how the total is obtained, the payment provider, authentication/saved-method requirements and what work Chauffeur removes. A trip-charge disclosure or appointment confirmation is not evidence of an online checkout. No live charge is part of this inspection or an automated test.

Prefer a target where a usable saved method is already available or automation demonstrably removes substantial checkout work. Current browse contexts are fresh and nonpersistent; an existing account on the parent's phone does not imply a saved method exists in Chauffeur's browser. If the target needs login/session persistence, stop and specify that dependency separately before claiming it is supported. A card vault and account creation are outside this slice. Guest-card collection is conditional on P0 demonstrating value over entering the card directly at the merchant; it is not a required first release merely because it is possible.

The selected path includes receipt recording, uncertain-outcome verification and the phone hand path. Subscriptions, variable/postpaid charges, gratuities chosen after approval, installments, bank transfers, credit applications and automatic refund/cancellation are outside the first slice. Their terms require a distinct approval schema; they must not squeeze through as an ordinary payment.

An unsupported checkout remains a handoff. A general vision agent plus a payment-word exception is not the payment executor. The driver identifies the merchant, payable total, currency, line items, credential field origins and final control; if it cannot bind those facts, the automation offers the page and the prepared details without collecting a card or charging anything.

Separate reusable payment-field handling from merchant transaction extraction. Evaluate standard `autocomplete` field attributes and known hosted-provider frames at P0; share a tested provider adapter across merchants where it actually fits. Those attributes identify credential fields, not trustworthy payee, total, terms or final-action semantics. Provider/merchant origin allowlists and transaction extraction still need fixtures for each supported flow. Do not promise that one generic card-field adapter makes arbitrary checkouts supported.

## Delivery order and the handoff alternative

1. **Verify the built submit gate on device.** Record its approval, uncertain-outcome and lost-worker acceptance before implementation plans for these follow-ups.
2. **P0: confirm the task and choose the completion path.** Compare native merchant handoff, a separately designed remote-hand capability and device-chat payment on the actual target. Record the choice, saved-method/session availability, provider/field strategy and the steps it removes for the parent. If payment adds only another card form and PIN ritual, defer it; do not build a fake-merchant integration as a substitute for a useful target.
3. **Deliver the selected device path.** If remote hand supplies more value, specify and deliver it first. If bounded payment wins, implement P1–P3 below without waiting for voice identity. P0's result is required before that choice is treated as settled.
4. **Add voice identity/approval later.** Spoken-PIN payment uses the same ledger and policy. Fingerprint remains parked until F0 proves a real integration; only then consider its optional no-new-PIN voice path.

A native merchant handoff opens the merchant on the parent's device, where Chauffeur need not receive payment secrets, but it may require reconstructing checkout state. Remote hand means controlling the existing Chauffeur browser: it could address CAPTCHA, issuer challenges and unsupported forms, but card keystrokes and page state still pass through that browser/infrastructure. It cannot claim “no card data inside Chauffeur.” Its own design must provide a single human/controller owner, pause the agent, protect secret input/display and reconcile completion before automation resumes. This spec does not assume that remote hand already exists or add it implicitly to P2.

**Readiness at this draft:** submit device acceptance is unrecorded here; no real payment target, authenticated saved-method flow or remote-hand implementation is established. These are delivery gates, not completed capabilities.

## Reuse the existing rails

- `services/browse.py` currently splits `PAY_WORDS` from submit controls, blocks card fields and records submit attempts. Keep ordinary submit approval incapable of lifting the payment guard.
- `services/missions.py` owns pending ask IDs, current-browse checks, attempt claims, late evidence and human verification. Extend these invariants for payment rather than creating a second mission engine.
- `services/storage_sqlite.py` supports reentrant write transactions and SQLite is the active storage path. Money reservations, grant consumption and attempt creation need an actual database transaction; `db_lock` alone is not crash atomicity.
- Existing member tokens and PIN hashes supply device identity and fresh verification. Reuse PIN verification and durable throttling; the fingerprint service supplies the optional recognized-parent proof below. A household/admin surface, nominated parent of record, HA service token, spoken name or model-supplied member ID is never sufficient payment proof.

Proposed new module `services/payments.py` owns quotes, bound PIN challenges, reservations and execution claims. A narrow `services/payment_checkout.py` interface separates transaction extraction from reusable provider/field handling and private execution. Start with the P0-selected flow and its test fixture, not a plugin marketplace or a generic credential store.

## The quote is the thing approved

When the runner reaches a payment control or card form, return `needs_payment` only if payment is enabled and the supported driver can prepare a complete quote without sending money or handling card secrets. Otherwise preserve `blocked: payment` and the existing hand path. The driver may use already released household contact values to reach the review stage. New personal data still follows the contact-release gate.

```text
payment_quote = {
  id, version, mission_id, browse_step_id,
  merchant_id, merchant_display_name, merchant_origin,
  checkout_driver, driver_revision,
  checkout_ref, item_or_service, line_items,
  total_minor, currency,                   # integer minor units, never float
  taxes_minor, fees_minor, shipping_minor, # included in total; zero is explicit
  terms_summary,                          # one-time/deposit/cancellation terms
  appointment_or_delivery?,
  payment_method_ref?, masked_method?,     # safe identifier/display only
  fulfillment_digest, transaction_digest,
  final_control, allowed_payment_origins,
  created_at, last_checked_at,             # no arbitrary ten-minute ask expiry
  merchant_valid_until?,                  # only an actual merchant deadline
  state: pending|authorized|superseded|resolved|cancelled
}
```

Use an immutable quote version. Store no PAN, CVC, passwords, issuer PIN or bearer session URL in it. Canonical transaction digest includes payee, currency, exact payable total, items/service, quantity, selected appointment/delivery, released contact snapshot, chosen method reference and relevant terms. The browser snapshot remains additional evidence; a truncated model summary cannot stand in for the quote. Numeric totals are extracted by the driver with currency-specific minor-unit rules. Missing currency, ambiguous total, unknown extra charge or unsupported terms means no executable quote.

Any change to approved commercial facts, including a lower amount, creates a new quote and a new approval with the identity proof required by the setting. Ignore only explicitly identified non-transaction decorations in the driver's tested extraction; never globally strip numbers or dates. A checkout requiring payment details before it will reveal the total is a handoff in this slice.

The ask remains available until resolved, superseded or cancelled; a parent can answer hours later. Show when its facts were last checked and any actual merchant deadline. Approval is conditional on reconstructing the same transaction and revalidating the full digest before execution. Unchanged facts retain the same quote/approval even if the browser session must be rebuilt. Changed facts or an unavailable offer produce an updated ask; elapsed time alone does not create a new card or demand repeated approval. A merchant deadline requires refreshing availability, never ignoring the deadline.

## Spending cap and one-parent approval

A mission has `payment_limit = {currency, cap_minor, version}`. Set it in the payment card; if absent, propose the exact first quote total and establish it with the same authorized approval. This does not add another confirmation. Future payments consume the remaining mission allowance. Raising the cap is an explicit field on the new approval card/readback and is committed with that payment's required proof; it never silently follows a changed quote. No currency conversion or cross-mission allowance in this slice.

The card shows: merchant, purpose, item/service details, total including fees, currency, deposit/one-time terms, masked method, cap and remaining allowance, then **Approve payment** and **Cancel**. The payer must resolve to an active member with `role=parent`. Current submit/release permission for an adult does not implicitly grant payment authority.

1. The parent chooses **Approve payment**, types an explicit approval to the active payment card, or says “approved” in response to its readback. A deterministic controller creates a short-lived, single-use approval record bound to quote, digest, cap proposal, intended parent, policy revision and originating request. It never uses an LLM's interpretation of an unrelated “yes” as approval.
2. Evaluate the setting and channel under the table below. When required, prompt for a fresh PIN in the same interaction. With sufficient proof, atomically check the pending ask, active parent role, current policy, approval record and quote version, reserve the amount and create one grant in `preparing` state. The no-new-PIN path performs the same checks immediately after explicit approval; there is no extra confirmation. A retry of the same request returns its original disposition.

Proposed PIN challenge TTL: two minutes from explicit approval. Successful proof permits one bounded reconstruction job (proposed ten-minute preparation deadline), with the amount reserved and no authority to inject credentials or activate payment yet. When the worker reaches checkout and revalidates the unchanged transaction, recheck the parent's current role, credential/session revocation state, policy revision, live ask and cap. Atomically mark the grant `ready` and start its short execution lease (proposed two minutes, additionally bounded by any merchant deadline). The parent does not approve again or repeat the PIN just because normal reconstruction took several minutes. Fresh proof is bound to this one job; it is not a reusable ten-minute purchasing session.

If preparation fails or times out before reaching `ready`, expire the grant and release its reservation, retain the ask and show that no payment was attempted. A new job requires new approval/proof; do not retain hours-old authorization for later unattended retries. If the ready lease expires before claim, apply the same rule. Preparation must reach `ready` before `prepare_deadline`; claim and the single final activation must then occur before `execute_before`. Expiration before activation aborts, with outcome handled under the driver contract below. PIN format errors and wrong-PIN counting follow the shared credential rules documented in the identity spec; device payment implements these without depending on a satellite or voice session. All attempts use the existing durable member/IP throttling. Three wrong attempts lock payment PIN approval for that member until the existing rate-limit recovery permits it. Voice lockout is separate; unlocking voice must not clear payment throttling. A purchase-verification lock cannot be bypassed by flipping the setting off while locked.

A confirmed launch failure before the first browser/model turn, including exhausted Chromium launch fallbacks, immediately expires the `preparing` grant and releases its reservation in the same transaction; do not wait ten minutes. Scheduling rejection or confirmed failure to dispatch does likewise. An uncertain worker disappearance still uses the preparation deadline and exact-worker checks, so a late worker cannot execute an expired grant.

Track reconstruction rounds durably per mission, across quote changes and new approvals. Proposed initial limit: three scheduled reconstruction jobs; atomically allocate a round with its grant so retries of the same request do not add rounds and concurrent workers cannot exceed the limit. Record each round's grant/quote/worker IDs, model turns, token usage, duration, outcome and estimated model cost with its model/rate revision; mark missing usage or pricing as unknown, not zero. Reuse existing browse usage reporting rather than introducing another paid-key path. Failed launches have zero model turns and retain their round record. All three admitted jobs may complete normally. A request for a fourth pauses further reconstruction without creating a grant or reservation and offers manual completion once any existing attempt is resolved; neither a changed total nor another approval resets the count. Failed or superseded unclaimed jobs release their reservations under the existing rules. No automatic retry loop or implicit limit increase. P1/P2 measure the actual per-round cost; “roughly 30 turns” is an observation to validate, not a fixed cost assumption.

For device chat the actor comes from a personal member token; a shared house session cannot stand for a parent. Voice uses the authenticated satellite controller's PIN result or exact current speaker observation, never a request body's asserted role. An unknown speaker names a parent and proves that identity with a PIN; an ambiguous identity is clarified before approval. If another parent takes over, issue their own readback/approval for the still-current quote. Still only one parent is needed.

## Always require PIN for purchases

Register `purchases_always_require_pin` in parent-only Settings with the exact label **Always require PIN for purchases**. Proposed default: true. Base help text: “Ask for your PIN on every purchase. When off, a signed-in parent can approve without a new PIN.” Only for satellites with F2, enrollment and payment-grade calibration passed and recognition enabled, add: “A recognized parent's voice can also approve without a new PIN on: [ready satellite names].” Hide this clause when none are ready; unavailable satellites continue to require a fresh spoken PIN with either setting value. Changing this setting updates a policy revision and invalidates unclaimed grants/challenges; it cannot auto-complete a payment that was waiting for a PIN. Claimed attempts are reconciled normally, never re-executed.

| Setting | Device chat / PWA | Voice chat |
|---|---|---|
| On | Explicit approval, then a fresh PIN even if already signed in as a parent. | Explicit approval, then a fresh spoken PIN even if already verified or recognized by fingerprint. |
| Off | Explicit approval from a currently signed-in parent is sufficient. Without a parent session, identify/sign in as a parent and approve in that identity. | Explicit approval plus a fresh confident match of this utterance to an enrolled parent is sufficient. Without that match, ask for a fresh PIN; a spoken name or an old ten-minute PIN session alone does not substitute for the requested fingerprint path. |

For voice, bind a speech-safe readback to the ask and quote. Accept “approved” only on a later utterance for that active readback, not on the utterance that generated it. Use the matched member's current server-side role. Recognition evidence must be exact-run, unexpired, unconsumed and above the calibrated threshold/margin from the fingerprint spec. A missing/inconclusive match requests a PIN rather than charging. A confident different speaker cancels the original parent's readback; identify the new parent and read it back again before accepting approval.

A PIN is collected where the conversation is happening. Device chat renders an inline masked credential input bound to the challenge and sends it directly to the authorization endpoint. It does not appear as a message bubble or go to the LLM. If a person types a PIN into the ordinary composer while challenged, intercept the entire credential turn before message persistence and route it to that endpoint; never include it in history or a retry transcript. Voice consumes the PIN utterance deterministically before model/history/SSE handling as in the identity spec. Incorrect, malformed and cancelled PIN turns receive the same redaction.

When the setting is on, prior identification does not skip this fresh credential step. When off and the required existing identity proof is present, do not insert a PIN prompt. No extra post-PIN confirmation is required when the quote is unchanged. A fingerprint alone, without an explicit transaction-bound approval, never pays.

The device path remains available for noisy speech, locked satellites and private purchase descriptions that cannot be read aloud. A cloud STT delegate receives spoken PIN audio and HA may retain upstream debugging data; do not represent it as a secret confined to Chauffeur. Replayed/cloned speech is a known limitation of recognition, especially with the setting off. The setting controls this tradeoff explicitly; it is not silently overridden by an internal preference for PINs.

## Credentials: what the browser may type

The conversational model and normal computer-use tool loop never receive card credentials. The parent selects a merchant's existing masked method, or, only if P0 selects guest-card support, supplies a card through a dedicated authenticated phone form over an enforced secure connection. New card details are held only in a short-lived in-memory secret handle, scoped to parent, quote and allowed field origins. Do not place them in mission records, settings, logs, error strings, traces, screenshots, network capture or model requests. Proposed secret-handle lifetime: fifteen minutes, also ending on use, supersession, cancellation, failure or restart. The long-lived pending ask never extends secret retention. No “remember this card” in this slice.

For this household's cloudflared deployment, apply the following transport predicate to both the private credential endpoint and the device purchase-PIN endpoint:

| Path | Required evidence |
|---|---|
| Cloudflare tunnel | `CF-Connecting-IP` or `CF-Ray` is present, and `X-Forwarded-Proto` is `https`. The parent's browser connects to Cloudflare over TLS; cloudflared's local add-on hop need not itself be TLS. |
| HA ingress | `auth.arrived_via_ingress(headers)` is true, and the supervisor-forwarded `X-Forwarded-Proto` is `https`, reflecting HA's browser-facing TLS connection. |
| Anything else, including ordinary direct LAN HTTP | Refuse secret submission and offer the secure app URL or native merchant handoff. |

Normalize header casing/whitespace and require an unambiguous `https` scheme; missing, conflicting or malformed forwarded-scheme values fail closed. Do not use `arrived_via_tunnel` alone: its broader `X-Forwarded-For` check also matches supervisor traffic. `_account_link` already reads forwarded scheme for link generation, but this predicate must enforce it for secret endpoints and must be verified on both deployed front doors. Document the proxy's header replacement behavior; reassess the predicate if the front door changes.

This is deployment-specific header evidence, not independently authenticated TLS proof: a client reaching LAN HTTP can forge these headers and submit its own secrets over cleartext. The app must not offer the credential/PIN form from an insecure browser origin. The transport predicate never establishes parent identity or relaxes endpoint authentication, and ingress presence alone is insufficient without the HTTPS scheme.

The parent may prepare the secret handle before approval, but it has no execution authority. Bind its opaque reference into the quote before the explicit approval. Changing method invalidates the approval just like changing the amount. Each resume uses the exact approved handle or saved-method identifier, not a newly selected default card.

If a guest-card handle expires while the ask is waiting, the card form must be completed again and its new reference approved; do not pretend a volatile handle survives an hours-long delay. This friction is part of P0's value comparison and another reason not to select guest-card support by default.

| Input | Who may enter it |
|---|---|
| Already released name, billing/delivery address, email and phone | Existing browser typing rail, limited to the approved values and site. |
| Card number, cardholder name, expiry and CVC | Deterministic private executor only, using the one-use phone-supplied handle and tested fields on exact allowlisted origins. |
| A saved payment method | Driver selects the specific approved masked identifier; no silent default-method fallback. |
| Bank/issuer account password, ATM/card PIN, one-time code, recovery phrase, new credit or recurring-charge consent | Never typed by this slice; require the person's direct interaction. |
| Chauffeur member PIN | Authentication endpoint only; never typed into the merchant page. |

Entering credentials may itself transmit them to a payment provider through page scripts. The approved grant therefore precedes private injection, and the allowed provider origins are shown as part of the method setup. Revalidate the quote before sending secrets and immediately before the final activation. A changed recipient/amount/terms aborts without clicking, discards the handle and asks again.

Once the private phase begins, suspend the model and all general browser actions. Disable screenshots, page-source dumps, tracing, video and request-body capture before injection, including failure paths. Only the driver's allowlisted non-secret status/receipt extraction may leave that phase. Clear and close the browser at its end; return a sanitized result to the planner. Do not resume the vision loop on a page that may still contain card details. Hosted payment frames require explicit tested frame-origin handling; unsupported frames are a handoff, not a prompt to the model to inspect them.

`browse._new_context` already uses `browser.new_context()`, which creates a [nonpersistent context](https://playwright.dev/python/docs/api/class-browsercontext); this is not a persistent headed-Chromium profile. Preserve that isolation, never export storage state after private entry, and disable payment saving/autofill through supported controls for the pinned browser build as defense in depth. Verify actual behavior instead of assuming a guessed preference/flag works. P2 must scan temporary profile directories and crash artifacts as well as app output and prove no card autofill appears in a subsequent context.

The [PCI SSC guidance on verification codes](https://www.pcisecuritystandards.org/faqs/1319/) prohibits retaining them after authorization even encrypted. This design retains no card credentials after the attempt at all. This document defines a data-handling boundary, not a claim of PCI certification or a blanket compliance assessment.

## Execution and the money ledger

Reuse the submit attempt's stable step ID and verification ask-ID discipline; add `kind: payment` and payment fields rather than overloading a booking confirmation as proof of money movement.

```text
payment_grant = {
  id, quote_id, quote_digest, ask_id, mission_id, reconstruction_round_id,
  approved_by, approval_channel, policy_revision,
  proof: {kind: fresh_pin|parent_session|parent_fingerprint,
          verified_at, session_or_observation_ref?},
  cap_version, total_minor, currency,
  approved_at, prepare_deadline, ready_at?, execute_before?,
  state: preparing|ready|claimed|expired|cancelled,
  browse_step_id?, attempt_step_id?
}
payment_attempt = {
  step_id, kind: payment, grant_id, quote_id, browse_step_id,
  merchant, total_minor, currency, masked_method,
  phase: private_entry|activation_started|outcome_recorded,
  outcome: null|confirmed|rejected|unknown,
  receipt_ref?, merchant_payment_ref?, evidence?,
  resolved_by?, resolved_at?, detail?, late_reports: []
}
```

Represent reservation/grant state durably in storage and link it to the mission's attempt step. Both `preparing` and `ready` hold the same reservation; the transition does not reserve twice. In a transaction, allow only one live reservation/attempt for a quote and one active payer challenge claim. Two parents racing with their own valid approvals still produce at most one grant and one attempt. Different quotes on a mission also contend for its cap. Expiration/cancellation atomically releases only an unclaimed reservation, including after worker loss; a claimed attempt is never freed merely by a timer.

Remaining allowance is `cap - confirmed charges - unresolved attempts - live reservations`, in one currency, with each amount counted once as it changes state. A failed/rejected attempt releases its amount only on conclusive rejection or explicit parent verification of non-payment. An unknown charge holds the allowance. Refunds do not automatically restore it in this slice; a later explicit cap change can account for them. A confirmed payment remains in the ledger when the mission is stopped or deleted from the active view.

The browser's final authorization callback checks under the durable transaction: live mission and exact worker, payment switch, current parent role and proof revocation state, unchanged proof policy, current quote/digest/cap, `ready` grant within its execution lease, reservation, no unresolved previous attempt and unspent authority. Atomically consume the grant and create the attempt before private credential injection; a second callback is refused. The one-use observation is consumed when authorizing, not expected to remain reusable by the browser; the durable grant is its bounded authority. Immediately before the single final click, the driver verifies current transaction values and the execution deadline again and records `activation_started`. Clicking is one activation even if the model requested a double-click. No general submit grant may call this path.

The secret handle is volatile. After restart, an unused reservation can expire and release its amount; a claimed attempt must be reconciled. A crash before `activation_started` can be resolved not charged only when the driver contract proves no payment-capable operation happened during private entry. Otherwise leave unknown. A crash after activation began is always unknown until evidence resolves it. Do not infer failure from an expired browser session or missing receipt.

An external merchant call cannot be made atomic with the local database. Use a merchant idempotency key only when that driver/provider actually supports it; never claim generic exactly-once execution. The local guarantee is one attempt per grant and no automatic retry after uncertainty.

## Outcomes, manual completion and late workers

The private driver returns a normalized outcome and supporting non-secret evidence:

- **Confirmed:** an explicit accepted/paid result for this merchant transaction, amount and currency; record receipt/reference when available. Distinguish authorized/pending capture from settled if the merchant says so. Create a `paid` note and continue the mission with that fact. Do not infer payment merely from a booking confirmation.
- **Rejected:** explicit decline or failure proving this attempt was not accepted. Release the reservation, keep the failure, return to planning. Trying another method creates a new quote and needs a new approval under the current PIN policy.
- **Unknown:** timeout, conflicting amount/reference, unsupported issuer challenge after activation, missing confirmation or worker loss. Keep the amount reserved and produce a payment-specific `verify` card. Say “The payment may have gone through; check the merchant or your account before paying again.” Never say “finish the payment” while uncertainty remains.

The verification question carries its own ask ID and references `attempt_step_id` server-side, including unasked attempts. A signed-in parent may report paid, verified not paid, or unsure with receipt/detail. This resolves evidence, not authority to charge again; retry still needs a new approval and whatever proof the current setting requires. Preserve the original machine outcome and add the human resolution. A stale verification card changes nothing. An unasked payment records its observed or unknown amount, bars further automated spending on that mission and asks for reconciliation; never invent a zero amount to release budget.

For a handoff before any possible payment, record `manual_pending` and prevent an overlapping automated charge until the parent reports completion or abandons the handoff. If paid manually, record the actual amount/currency and receipt; record an over-cap manual amount honestly and stop further automation. The app cannot constrain a payment made independently on the merchant's site.

Late reports append evidence to their own attempt, preserve human resolution and do not move a newer browse or mission. An active-attempt check uses the exact step ID, not just `status=browsing`. Cancellation before claim revokes the grant and frees its reservation. Cancellation after private execution started does not promise that money movement stopped; report the attempt's actual or unknown outcome. Once claim is durable, prohibit granting a replacement while the old worker may still execute; expiry of a grant is not cancellation of a claimed attempt.

The payment switch off prevents new claims, invalidates unused grants and leaves in-flight attempts visible for reconciliation. A normal submit switch cannot re-enable payments. A driver/model/site change that invalidates quote extraction disables that driver's automated payment until its fixtures pass again.

## Surfaces and endpoints

The shared mission/thread transcript and device chat render `payment` and `verify(kind=payment)` cards; device chat includes the inline PIN input when required. Voice gives a short readback and collects spoken approval/PIN in place. Payment details obey existing visibility and speech rules; merchant/item descriptions marked private are not spoken or put on a wall display. Parent-only Settings has the payment enable switch, Always require PIN for purchases, and supported-checkout status; the mission card carries the cap. No second-parent setting.

Proposed endpoints, all classified in `auth.RULES` and enforcing their own actual identity even in auth audit mode:

- `POST /api/missions/{id}/payment/intent` with pending ask ID and cap proposal: creates a parent-bound challenge, no payment.
- `POST /api/missions/{id}/payment/authorize` with approval/challenge ID, PIN when required and idempotency request ID: evaluates the current policy and creates a grant; actor and existing-session proof are resolved server-side. A request cannot set `pin_required=false` or supply its own fingerprint proof.
- `POST /api/missions/{id}/payment/method` with quote ID and private credential payload, or selection of a known saved-method reference: returns only an opaque handle and masked display, no execution.
- Existing mission verification endpoint, extended with payment-specific resolution and stable attempt references.

Route body redaction covers credentials and PIN on success, validation error and exception. Service/voice callers cannot impersonate a personal token. The authenticated deterministic voice controller calls the same internal authorize operation with a server-owned fresh-PIN or current-parent-fingerprint proof as the setting requires; the LLM never receives an `authorize_payment(pin=...)` tool. Device chat's approval intent can immediately invoke that operation when the setting permits its existing parent session.

## Builds and proof

0. **P0 — target and value proof:** after submit device acceptance, record the real checkout and choose payment versus handoff as above. Verify the necessary method/session can exist in Chauffeur's browser. If there is no useful supported target, stop payment planning here.
1. **P1 — device-chat quote and authorization, no money:** build a local fixture representing the P0 target; one parent approves under both setting values and gets exactly one `preparing` grant. Exercise inline PIN redaction, currency/cap arithmetic, superseded cards, role changes, throttling, policy toggles, duplicate requests and concurrent parents. Prove hours-later approval of an unchanged quote and multi-minute reconstruction without another PIN; changed facts require new approval. Record per-round usage/cost and prove a flapping total reaches the mission reconstruction limit without scheduling another job. Launch failure immediately releases its reservation. Check that Settings advertises voice recognition only for ready satellites. Keep payment execution off.
2. **P2 — private executor and outcomes:** local merchant counts network POSTs and can accept, decline, change total, timeout after accepting and require an issuer challenge. Prove one activation, preparation/lease expiry, durable reservations, no retry after uncertainty, human verification and late-worker behavior. Plant recognizable fake secrets when testing guest-card support and scan screenshots, transcripts, logs, exception output, stored records, temporary profiles and crash artifacts for leaks. Terminate the worker around each preparation/ready/claim/entry/activation/result boundary and verify restart behavior. Verify the transport matrix on actual Cloudflare and HA ingress routes, refusal on ordinary LAN HTTP, no secret form on insecure origins, and the documented limit of spoofable LAN headers without any authentication bypass. Prove a new browser context cannot autofill prior credentials.
3. **P3 — the confirmed real target:** pin the selected extraction/provider adapter against the flow established in P0. Use provider sandbox/test mode when available. Validate complete quote extraction, secure credential transport, privacy boundaries and device handoff. A real-money pilot requires the user's actual transaction-specific approval and the identity proof required by their setting; development sign-off is not permission to charge.
4. **Later voice extension:** after V1/V2, exercise spoken PIN, readback binding and all voice policy cases below against the same ledger. Recognized-parent approval is conditional on F0/F2 and satellite calibration; it is not a P1–P3 acceptance dependency.

Acceptance: a single parent pays the exact approved total under a mission cap; a second parent is never requested. With the setting on, a signed-in parent and a recognized/verified voice both require a fresh PIN. With it off, the signed-in parent approves in device chat with no PIN prompt, and an enrolled parent's freshly matched voice says “approved” with no PIN prompt. An unrecognized or merely named voice must prove parent identity with a PIN. A missing required PIN, wrong PIN, child/adult-only member, superseded quote, failed revalidation, expired grant or changed total prevents execution. Quote age alone does not: an hours-old unchanged ask can still be approved and revalidated. A policy toggle invalidates an unused grant and does not auto-approve a pending payment. Two valid requests execute once. Unknown consumes budget and asks for verification. Parent-confirmed non-payment permits a new approval under current policy; old approval cannot be replayed. An approved saved method never changes to another one. PINs and raw payment fields never reach the model or persistent artifacts. A payment confirmation lands as Paid, while an appointment-only confirmation remains Booked.

Device payment remains off until P0–P3 pass; each voice path remains off until its own additional gates pass. The limit is tested checkout support, not a promise that arbitrary websites are safely payable through vision alone.
