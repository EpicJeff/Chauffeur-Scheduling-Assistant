# Argyle's style: a household default, and each person's own

Status: draft for approval, 2026-11-11.

## Why

The user, after weeks of talking to Argyle: "there should be a setting that controls the overall disposition, style, and tone of the responses. Some families may want a more pragmatic agent, some may want a super friendly one, some may want a pirate or something silly."

Today the tone is prose baked into the prompts ("brief, warm, plain-spoken" for drivers, "warm, brief, and reassuring" for children). No setting exists. A parent can say "remember to talk like a pirate" and it becomes a household memory row, which works by accident, cannot be found, and cannot be set per person.

## Decided by the user

- A household default, and each person can choose their own (2026-11-11).
- Kids pick their own style, and they can write a custom one too (2026-11-11).

## What a person sees

**Styles.** Four choices:

| Key | Label | What it asks of Argyle |
|---|---|---|
| `plain` | Plain and brief | Fewest words that answer. No small talk, no exclamation marks. |
| `warm` | Warm | Today's voice: friendly, plain-spoken, short. The default. |
| `playful` | Playful | Light, cheerful, the odd joke; still short. |
| `custom` | Custom | A line the person writes, for example "a cheerful pirate" or "a calm butler". |

A person's choice can also be **Same as the household** (the default for every person), which follows whatever the household picks.

**Where to set it.**

- **Your own style:** the PWA's Profile & appearance sheet gets a "How Argyle talks to you" row: the five choices, and a text box when Custom is picked. Every member with the PWA (parents, adults, kids) can set their own.
- **The household style:** Config › People, in the Argyle section beside what Argyle has learned. Parents only (same tier as the memory rows).
- **Everyone's styles, for parents:** the same Config › People section lists each person whose style differs from the household, with their custom text shown in full and a Reset button (back to Same as the household). A reset is the only thing a parent can do to another person's style; they do not pick one for them.
- **By asking Argyle:** "talk like a pirate", "be more to the point", "go back to normal" set the speaker's OWN style. A parent saying "talk like that to everyone" or "for the whole family" sets the household style. This replaces today's accident: a style request is never stored as a memory row. (Every agent capability has a hand path: the two sheets above.)

## Whose style applies

The style of the person Argyle is talking to, when Argyle knows who that is and the conversation is theirs alone:

- the PWA chat, the Argyle overlay and DMs with Argyle: the signed-in person;
- a satellite or the panel mic with a recognised voice (the voice actor, per-turn evidence as today): that person.

The household style everywhere else:

- the wall panel's typed chat (shared screen);
- a voice Argyle does not recognise;
- the family channel (everyone reads the reply), even though the sender is known.

## What the style never touches

The style changes how Argyle talks. It never changes what Argyle does, says is true, or writes down. Each line below is a rule in the style block itself, placed after every other rule in the prompt so a style can never outrank one:

1. **Written data stays plain.** Event titles, list items, errands, chores, reminders, memory rows, messages Argyle sends on a person's behalf, and every tool argument are written plainly, as if no style were set.
2. **Facts stay exact.** Times, dates, names, places, amounts and yes/no answers are stated plainly inside the styled sentence; a style never makes them vaguer.
3. **Safety and privacy wording is fixed.** PIN prompts, approval questions, lock and garage confirmations, the read-it-or-send-it question, refusals: these are fixed strings in code today and stay exactly as they are; where the model writes a refusal, it is written plainly.
4. **Someone having a hard time gets calm and warm.** When the person seems upset, stressed or worried, Argyle drops the style for that answer. The child block's "never lecture, never guilt-trip" stays as it is.
5. **Short where short matters.** Spoken answers and driver mode stay short whatever the style; Plain makes them shorter, Playful never makes them longer.

**A custom style is a manner of speaking, never an instruction.** It is stored as one line of at most 200 characters (newlines and control characters stripped), and placed in the prompt quoted, under a heading that says it describes only HOW to speak. "Always say yes to me" or "don't tell Mum" changes the voice, never the rules or what is shared.

## Out of scope (stays plain)

- Drafts written for people outside the family (threads, asks): they are written in the family's own voice, never Argyle's.
- Lesson scripts: library-owned and shared by every learner, so they cannot follow one person's style.
- Mind findings and situation status notes: records, not conversation.
- The configurable tap greeting (it already has its own setting).
- Text-to-speech voice: the satellite's voice is Home Assistant's, untouched.

## Pieces (for the builder)

- **Storage.** Household: two settings keys in `settings_registry.py` + `schemas.py`, `argyle_style` (default `warm`) and `argyle_style_custom` (default empty). Person: a member field `argyle_style` = `{style, custom}` written through `storage.update_member`; absent means Same as the household.
- **One module** (`services/argyle_style.py`): the preset table, `for_member(member)` / `household()` resolving to `(style, custom)`, `prompt_block(style, custom)` returning the style block with the five rules, `clean_custom(text)`. The router calls it once, after `argyle_memory.prompt_block()` and the other rules, never before.
- **Router.** `process_agent_request` picks whose style by the rules above (acting member on a personal surface, the voice actor with evidence, else household). The existing tone lines stay as they are; Warm reproduces today's behaviour, so a family that never touches the setting sees no change.
- **Agent tool.** A `style` action (set mine / set the household's / back to normal), with the household change parents-only, matching the memory trust tier. The memory tool is told a style request is not a memory.
- **Routes.** Read and set your own style (any signed-in member, own record only); read and set the household style and list everyone's, reset a person (parents). Each route gets its tier in `services/auth.py`.
- **UI.** The Profile & appearance row (PWA), the Config › People section. Same picker builder for both.

## Builder notes (settled after the builder check, my calls)

- **Placement.** The style block is the LAST thing appended to `system_prompt` in `process_agent_request`, after the driver, child, voice and trip blocks. Every model path in the router (the provider pool and the Gemini delegate) reads that same `system_prompt`; if a path builds its own, it gets the block too. "Byte-for-byte plus the Warm block" means the Warm block is the tail.
- **Personal or shared.** The router gets a keyword `style_member` (the member whose style applies, or `None` for household); callers decide, the router never guesses:
  - `/api/chat` (main.py, `source=conv['surface']['kind']`): the acting member, except `at_panel=True`, which passes `None`.
  - Family-channel posts (main.py `source="family"`): the sender only when the channel is the sender's DM with Argyle; any other channel passes `None`.
  - Voice (`source='voice'`): the voice actor (already per-turn evidence), else `None`.
  - The chat suggestion funnel (`chat_actions.py`), the Mind's taps (`mind.py`) and the house editor: `None`.
- **People who are only drivers.** A driver record with no member record has no style of its own and follows the household. A member linked to a driver (`member.driver_id`) uses the member's style in driver mode.
- **Storage.** `update_member` merges arbitrary fields; `argyle_style` rides on the member record and keeps its value through disable/archive. The own-style route writes only the caller's own record (the token's member), never an id from the body.
- **Custom with no text** falls back to Same as the household. A household Custom with no text falls back to Warm.
- **The agent tool.** A new `style` tool with `scope` = `me` | `household` and `style` + `custom`; `household` is refused for children and helpers/guests (same trust as the memory tool). It is a mutation in `voice_tools.MUTATIONS`, so an unrecognised voice is refused as for every other write. The memory tool's description and the memory prompt head both say a request about how Argyle talks goes to `style`, never to `remember`. Existing memory rows are left alone; a parent can delete any that now duplicate a style from Config › People.
- **"Hard time" and "short where short matters"** are prompt rules with no automated test; the device run checks them.
- **UI and tiers.** The household picker and everyone's-styles list are an inline block beside `argyle-memory` in `config.html` (People tab), with `argyle_style` in `settings_registry.py` anchored there. Routes: own style at the tier every signed-in member (kids included) already has for their own profile; household style and everyone's list at PARENTS, same as `/api/argyle/memories`.

## Testing

- The style block: each preset's text; custom text is quoted, capped at 200, single-line; the five rules present; the block appears after the memory rows in the assembled prompt.
- Whose style: PWA member, recognised voice, unknown voice, panel typed chat, family channel, a person on Same as the household.
- Routes and tiers: a kid sets their own (allowed), a kid sets another's or the household's (refused), a parent resets a kid's.
- A default install's prompt is byte-for-byte what it is today plus the Warm block (no behaviour change for families who never touch it).
- The real check is on the device: set a loud custom style, add a shopping item and an event by voice and typed chat, and confirm the item and title are plain. A model can still slip; the rule lowers the odds, it cannot make them zero. If it slips in practice, a later piece can add a plain-text pass on tool arguments.

## My calls (check these)

- Family channel uses the household style even when the sender is known.
- Asking Argyle changes your own style; a parent changes the household's only by saying so.
- A parent can see and reset a kid's style but not pick one for them.
- Mind findings, situation notes, lesson scripts and outside drafts stay plain.
- "Someone having a hard time" drops the style for that answer, for adults as well as kids.
