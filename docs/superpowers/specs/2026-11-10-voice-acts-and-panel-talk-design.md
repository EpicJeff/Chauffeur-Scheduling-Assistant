# Recognised voices act, and panel tap-to-talk

Date: 2026-11-10. Projects 2 and 3 of the three that began with the HA control rulebook (v2.499.773, spec `2026-11-09-ha-control-permissions-design.md`).

## Why

The family wants to walk up to a wall panel, tap a button and talk to Argyle through the room's satellite, with no "Hey Argyle". Kids forget the name, some people feel silly saying it, and a wall TV or monitor has no microphone. The wake word stays for talking from across the room.

Tap-to-talk is only worth having if what you say gets done. Today a recognised voice is a lens for questions ("when do I leave") and nothing more. The user's ruling (2026-11-10): "If you are recognized by voice, you should be able to do whatever you can do in chat on your phone. That is the point of recognition. Otherwise, it is just a bit of flash with no substance."

So this is two pieces, built in order:

1. **A recognised voice acts as that person.** Same powers as that person's phone chat, by their role. A sign-off ends the recognised session.
2. **Panel tap-to-talk.** A panel belongs to a room, the room has a satellite, and a mic button in the panel's Argyle chat starts a conversation on that satellite.

## Goals

- A voice recognised by fingerprint (or verified by PIN) gets the tools, role prompt and permissions that person gets in their Argyle DM on their phone.
- Saying goodbye ends the session: the mic closes and the satellite forgets who was talking.
- A new conversation never inherits the previous conversation's speaker through a short reply.
- A panel can be given a room; the room's satellite is found automatically, with an override.
- One tap on the panel starts a satellite conversation; the panel shows that the satellite is listening, thinking and answering.

## Non-goals

- Showing the spoken words or Argyle's answer on the panel screen. Later, if wanted.
- Any change to what an unrecognised voice may do. It keeps today's household voice tools.
- Per-device exclusions in the HA grid (deferred in project 1).
- Schedule rebuilds being opt-in (separate, later, per the user).
- The panel microphone. The panel has none; the satellite is the microphone.

## Anti-goals

- A claimed name ("It's Jeff") acting as Jeff. A claim is a lens, never an actor. Only a fingerprint match or a PIN makes an actor.
- A fingerprint becoming proof. Anything that asks a phone user for nothing but is gated on proof (the HA grid's "Require authentication", booking approvals) still asks a recognised voice for its PIN. The user ruled 2026-11-09 that a fingerprint alone is not proof.
- Removing anything an unrecognised voice can do today.

## Piece 1: a recognised voice acts as that person

### Who counts as recognised

A satellite turn's speaker is the **actor** when `voice_context.level == 'verified'` (PIN) or the session is `named` with `recognized=True` **and** the voice was recognised on this turn (`recognized_this_turn`, which already covers the short-reply inheritance below). A `named` session from a claimed name, or a turn whose long sample was uncertain, is not an actor; it keeps the lens behaviour of today.

`VoiceContext` gains `actor()` returning the member for those two cases and `None` otherwise. `verified_member()` keeps its meaning (PIN only).

### What the actor gets

The router runs a recognised turn as that member's phone turn, spoken:

- `acting_member = voice_context.actor()`.
- The tool set is the one `source='family'` gets for that member's role (bridge tools for parents and adults, the child and helper rails for the rest), not `voice_tools.TOOLS`. `prepare_voice_approval` stays available.
- The role prompt is the family one for that member, plus the existing SHARED SPEAKER block reworded: the speaker is recognised by voice, is acting as themselves, and is not proven.
- Dispatch goes through the ordinary family path with `spoken=True`, not `voice_tools.dispatch`. `proven` stays `ctx.level == 'verified'`. `voice_context` is still passed so the HA rulebook (`who_from_agent`) sees a voice.
- Writes are recorded as the member, with provenance saying it came by voice (`actor_kind='member'`, `via='voice'`, the satellite). Messages are sent from the member with no "Household voice:" prefix.
- Gates that today demand `verified_member()` and have no phone equivalent move to `actor()`: teaching Argyle (memory), `act_on_situation` approve_plan/run_stage, `start_project`'s requester. Gates that ask a phone user for proof keep asking: booking/release approvals (`voice_approval` PIN path) and HA kinds with "Require authentication".

Unrecognised voices (unknown, claimed name, uncertain sample) are unchanged: `voice_tools.TOOLS`, `voice_tools.dispatch`, `parent_of_record` for the four household mutations, "Household voice:" messages.

Ruling (my call, 2026-11-10): **recognised never means less.** The actor's tool set is the role's phone set plus the household voice tools an unknown voice already has (`voice_tools.MUTATIONS`: assign/clear a driver, add/check shopping), dispatched as the actor instead of `parent_of_record`. The voice prompt tells the model to do these directly, never as a `propose_family_action` card. A recognised child is never weaker than a stranger.

### Things a phone shows that a speaker cannot

Some phone results are cards that need a tap (a proposal to apply, a request card). On a satellite there is no screen. A card produced on a recognised voice turn is posted into that member's Argyle DM, and the spoken answer says so in one short sentence ("I've put that in your Argyle chat."). A child's `propose_family_action` / `make_request` already lands with a parent; that is unchanged.

### Private answers: Argyle asks

On the phone, `app_voice.PhoneTurn` decides whether an answer is safe to speak (`speech_safe`) and keeps unsafe ones on screen. A satellite turn by an actor runs the same speech-safety checks (the same function, not a copy). When the answer is not safe to speak, Argyle holds it and asks: "That's private. Read it out, or send it to your chat?" (the user, 2026-11-10: "Can Argyle just ask whether to read it aloud or send it to the chat?").

- The held answer lives on the satellite's identity session, like the approval readback, for 60 seconds.
- The next turn decides, matched on words with one re-ask when unclear: "read it", "out loud", "tell me", "yes" read it aloud; "send it", "chat", "phone", "no" post it to the actor's Argyle DM with "Sent to your chat."
- The reply counts only from the same actor (a recognised or inheriting turn for the same member). A different recognised voice, an unknown voice, a sign-off, silence, the 60 s running out, or the conversation ending all post it to the DM. Nothing private is ever read out on someone else's say-so, and nothing is lost.
- An unrecognised voice never reaches private tools, so it never meets this question.

### Sign-off ends the session

`voice_conversation.is_sign_off` already closes the mic. It now also ends the identity session for that satellite: a new session generation at level `unknown`, so the next conversation starts with nobody. Argyle still answers the words ("Bye, Jeff."). This applies to verified and recognised sessions alike.

### No inheritance across conversations

Today a short reply (under 1.2 s, or no audio) inherits a recognised speaker for the whole 10-minute session, even after a new wake word. Inheritance now holds only inside one conversation. A short first turn of a new conversation is not recognised; a long one is fingerprinted as normal. The 10-minute session itself (which PIN verification relies on) is unchanged.

Ruling (my call, 2026-11-10): HA's `conversation_id` cannot be the boundary, because ESPHome satellites keep it across wake words for about 5 minutes. Chauffeur draws its own: a conversation ends when Chauffeur answered with `continue_conversation` false (sign-off, cap reached, conversation mode off), or when 30 seconds pass between turns (`voice_conversation.GAP_SECONDS`, which also covers the mic closing on silence). The next turn after either starts a new conversation.

The phone path (`app_voice`) is a personal device and is not affected.

## Piece 2: panel tap-to-talk

### A panel's room

A panel is a `trusted_devices` row with `kind='panel'`. The row gains two optional fields:

- `area_id`: the Home Assistant area this panel hangs in.
- `satellite_id`: an `assist_satellite.*` override; empty means automatic.

Both are set on the panel's row in the trusted devices list (Config, parents only), with a room picker from HA areas and a satellite picker of the satellites Chauffeur knows (Config › Voice identity rows), defaulting to Automatic. The panel's own settings drawer shows "This panel: Kitchen · Kitchen speaker" read-only, with where to change it. With HA absent, the pickers say so and the mic never appears.

### The room's satellite

`satellite_for_panel(device)`: the override if set and still known; otherwise the area's `announce_targets` pin if that pin is an `assist_satellite`; otherwise the first `assist_satellite` in the area (the order `announce.pick_target` already uses). None when nothing fits.

### The button

The panel's Argyle chat (control_center.html: the bar on desktop kiosk pages and the orb on `?panel=true`) gets a mic button when `GET /api/panel/talk` says this panel has a satellite. A tap calls `POST /api/panel/talk`:

- Auth tier WALL, identified by the panel device token (`control_rules.panel_device`). A non-panel caller is refused.
- The server calls `assist_satellite.start_conversation` on the panel's satellite with `preannounce: true` and no start message, so the satellite chimes and listens. The exact payload is confirmed by the spike below.
- One start per panel per 5 seconds; a second tap while the satellite is busy is ignored.

From then on it is an ordinary satellite conversation: fingerprint, the HA grid, piece 1's actor rules, conversation mode, sign-off. The panel adds no identity of its own; whoever is signed in on the panel does not become the speaker.

While active, the button polls `GET /api/panel/talk` (once a second, at most 2 minutes) which returns the satellite entity's state, and shows Listening / Thinking / Answering, returning to idle when HA reports `idle`. If the call fails, the panel shows the reason through `showGlobalAlert` ("The Kitchen speaker is offline").

Ruling (my call): the light follows the satellite only. In a room whose answers play through a room speaker (`answer_speaker`), the light may return to idle while the speaker is still talking; accepted.

### Spike first, and landing order

`assist_satellite.start_conversation` has never been used here, and the Voice PE runs the household's overlay firmware (conversation mode, `on_error` stop). Before building the button, one call is made against a real satellite to learn: does an empty start message work, does the overlay's continuous mode survive it, and does the turn reach Chauffeur's agent with satellite metadata. The call makes a speaker chime in the house, so it waits for the user's go-ahead.

Ruling (my call): piece 1 lands on main on its own, before the spike. If an empty start message fails, the button sends `start_message: "Yes?"`. Any change to the satellite firmware goes back to the user before it is made (it means reflashing every satellite).

## Constraints

- Every HA touchpoint degrades gracefully with no HA present.
- New routes need a rule in `services/auth.py`.
- No browser dialogs; Tailwind rebuilt after class changes.
- Entry points swallow exceptions: each critical path gets a test that runs it (a TestClient request, a router run with a stub model).
- Do not touch the schedule rebuild behaviour.

## Left to the builder

- How the family tool set is assembled for a voice actor, as long as it is the same function the phone path uses, not a copy.
- The exact provenance field names, matching what `ctx.provenance()` already writes.
- Button styling, following `docs/ui_design_guide.md` and the existing orb.
