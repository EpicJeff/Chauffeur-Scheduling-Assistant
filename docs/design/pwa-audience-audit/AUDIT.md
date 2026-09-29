# Chauffeur PWA: audience, navigation and readability review

**29 September 2026 · Design proposal, not a replacement PWA.**

[Open the interactive mockups](index.html) · [Five-audience comparison](previews/five-audiences.png) · [Current screenshots](current/) · [Rendered proposals](previews/)

The main recommendation is **one product with five presentation profiles**: a restrained adult interface and a child interface that matures through the existing four stages. Changing colors alone will not solve the crowded header, competing priorities or buried functionality. Preserve the shared data, permissions and actions; tailor hierarchy, navigation, language, imagery and density.

## What was reviewed

- The actual `/app` template, theme tokens, stage capabilities, role-based tab routing, day and drive builders, routines, chores/rewards, lists, messages, map/music entry points, programs and approval surfaces.
- A real local browser rendering the shipped app with fictional fixtures in an isolated temporary database. Five profiles were captured at **390 × 844**: a parent/driver plus Sprout, Explorer, Navigator and Copilot. The adult Family, House, Messages, Map and Music tabs, and Explorer House, were also captured.
- Source-level review of non-driving adults/parents, helper drivers and guest rules. These roles were not all rendered in the current-app capture. The proposal has an adult role selector to illustrate parent/driver, adult/driver, non-driving parent and helper-driver layouts.
- The proposal has 24 main screens, extra adult role variations, working sample interactions, five dark previews, and responsive checks at 360, 390 and 768 pixels. [Verification record](previews/verification.json).

This is an expert review and a design prototype, not a study with family members or a complete accessibility certification. Live household data, real location freshness, push delivery, real media playback and every overlay were not tested. The current screenshots show controlled sample content; empty Map/Music states are not evidence of missing production data. The mockup content is also fictional. Its SVG companion and backpack are illustrative; production should reuse the existing avatar/critter assets and personal task photographs.

## What is already worth keeping

The current app is not completely identical for everyone. `applyRoleTabs()` scopes navigation, and `kidShell()` already changes glyph size and density. Copilot removes the large task glyph; Navigator and Copilot stop leading with points. Personalization, familiar faces, concrete task photos, named pickup drivers, program sessions integrated into a day, and the shared family conversation are strong foundations.

The stage service already provides the right authority. Default bands are **Sprout under 6, Explorer 6–11, Navigator 12–14, Copilot 15+**, but cutoffs are configurable. Stage transitions are parent-confirmed, capability overrides are supported, and earned history is retained. Those contracts should remain intact. [Stage definitions and capabilities](../../../chauffeur/services/stages.py#L1).

The theme comment says children default to light, but `themePref()` actually returns the saved device preference or `auto`; `applyKidShell()` reapplies that preference. Do not depend on the comment as evidence of an enforced child theme. Keep light/dark choice independent of audience.

## Findings and proposed changes

| Priority | Evidence in the current app | Recommendation | Mockup |
|---|---|---|---|
| P1 | The adult fixture's header is 96 px high, the name wraps, and the page has horizontal overflow at 390 px. Avatar, critter, push setup, notifications, sync, theme and identity switching compete for space. | Keep identity, search and one notification entry. Move appearance, account switching and sync status into named account/settings areas. Keep critters accessible through More/profile for every role. | Adults → Today; More |
| P1 | A fully scoped adult driver has **six tabs at 65 px each**. All four child stages show the same five destinations in the fixture, despite different capabilities. | Use five adult destinations; three for Sprout, four for Explorer, five for older children. Retain explicit labels and stable order within each profile. | Compare all five |
| P1 | Child My Day renders status/requests, greeting, progress rings, launch, all routine buckets and due-soon tasks before ride cards. In the captured Explorer view, the next activity is below the first viewport. | Put the next relevant ride/reassurance near the top. Show the current routine or next useful step; make completed and later groups expandable. Never hide a changed pickup behind rewards. | Sprout / Explorer / Navigator → Today |
| P1 | Dark `text-gray-500` is `#737373`. On `bg-gray-900` (`#171717`) it is **3.78:1**; on `bg-gray-950` it is **4.18:1**, below 4.5:1 for normal text. This combination occurs in labels/metadata and inactive navigation text. | Introduce semantic text roles with tested contrast. Essential times, drivers and locations should not use a faint metadata style. Validate composed/translucent surfaces separately. | All light/dark previews |
| P1 | Visible sync, notification, identity-switch, previous/next-day and assistant controls lack text, `aria-label` and `title` in the captured DOM. | Give every icon action a meaningful accessible name; use visible labels for unfamiliar actions. “View pickup” says more than “Where?”. | All proposal controls; Navigator pickup |
| P1 | The fixed assistant button visibly overlaps the lower-right portion of a task card and checkbox in the child captures. | Reserve a place for assistance in Messages, a labeled contextual action, and the adult search flow. If a floating button remains, reserve its full footprint in scroll content and test keyboard/overlay collisions. | Explorer → Today / Messages |
| P2 | Adults and children share neutral tokens, rounded cards, icon buttons, drop shadows and emoji section markers. Adult Today/Drives shortcuts use the same large graphical jump-button pattern. | Adult surfaces: flat fills, thin dividers, restrained accent, 8–12 px corners, aligned rows and one dominant action. Child surfaces: expressive imagery and softer geometry where they aid comprehension. | Adults compared with Sprout/Explorer |
| P2 | Even Copilot retains the full figure greeting, progress-ring strip and “Hatch a critter” entry above practical content. Only task glyph/density changes substantially. | Let the entire presentation mature: quiet header, agenda-led layout, optional character/rewards access. Preserve the assets and history rather than removing the feature. | Navigator / Copilot → Today / More |
| P2 | Family is the calendar plus intake and Argyle insights; House contains chores, rewards, lists and threads. Those labels do not expose their breadth. | Adult Plan becomes the family schedule and coordination view. Household visibly separates Tasks, Lists and Requests. More offers a searchable directory with names and short descriptions. | Adults → Plan / Household / More |
| P2 | Decisions live in separate areas: requests on My Day, intake on Family, chore verification/redemptions in House, insights on Family. | Add one deduplicated “Needs your review” summary with direct links to the existing decision surfaces. Rank by deadline and consequence; avoid decorating every destination with a badge. | Adults → Today → Needs your review |
| P2 | Program cards contain numerous 10–11 px step/session labels and actions. Driver/passenger chips truncate names; event rows can carry several independent badges. | Essential content 16 px by default; supporting details generally 13–14 px; 12 px reserved for secondary labels. Summarize one row and disclose details on tap. Keep full names and places available. | Plan, Tasks, Drive detail |
| P2 | Child routine buckets each promote a first unfinished task, potentially creating multiple large heroes; morning tasks remain before afternoon activities in the DOM. | One current-step hero for Sprout; short Now/Next/Later groups for Explorer; a compact personal timeline for older stages. Do not automatically complete or discard overdue tasks. | Four child Today views |
| P2 | My Day is selected through driver/passenger routing. Non-driving “keeping-up” adults land on Family; helpers get a narrow driving/messages world. | Presentation must be independent of driving status. Non-driving parents need a useful family/decision overview; helpers need only their assigned drives and authorized parent conversations. | Adults → Role selector |
| P3 | Photos/moments are attached to Messages, while programs are found through day content. Critter discovery relies heavily on a persistent egg/face and avatar context. | Keep existing contextual entries, and add named directory entries: Moments, My programs, My critter, Music, Family map. Do not make users remember an icon's meaning. | More / Messages |
| P3 | Routine completion can trigger streak messaging; reward balance is prominent for younger stages. | Emphasize effort and completion. Keep earned rewards, but avoid loss warnings, punishment, sibling ranking, or reward animations that delay the next step. Respect reduced motion. | Explorer → Tasks & rewards |

Runtime evidence: [metrics.json](current/metrics.json), [adult Today](current/adult-day.png), [Explorer Today](current/explorer-day.png), [Copilot Today](current/copilot-day.png). Contrast values above are calculations from the checked-in opaque color tokens, not a claim that every gray label fails in every theme.

## The five experiences

| Profile | Leading question | Style and content | Navigation proposal |
|---|---|---|---|
| Adults / parents / drivers | What needs my attention, and where do I need to be? | Neutral flat surfaces, restrained green, strong time hierarchy, chronological rows, compact status text. Parent approval actions remain role-gated. | Today · Plan · Household · Messages · More |
| Sprout | What do I do now, and who is with me? | Familiar picture, one instruction, large completion button, reassuring adult identity, minimal reading. Optional read-aloud would be new functionality; its entry is illustrative. | Today · My things · Family |
| Explorer | What comes next, and what can I do myself? | Playful purple, purposeful companion, small achievable checklist, pickup reassurance, optional rewards. A week is reachable from Today. | Today · Tasks · Messages · More |
| Navigator | How do I manage my own afternoon? | Personal accent, smaller illustrations, school deadlines and commitments, easy requests, no points-led hero. | Today · Plan · Tasks · Messages · More |
| Copilot | What am I responsible for today? | Near-adult organizer, own commitments, optional personalization, conditional driving detail. | Today · Plan · Tasks · Messages · More |

Do not infer reading skill, preferred animation, or independence solely from age. Use the configured stage and capability overrides, and offer presentation preferences without changing permissions. A parent should be able to help a child choose calmer visuals or larger text without changing the child's allowed actions.

## Destination and feature mapping

| Current destination / function | Adult proposal | Child proposal and constraints |
|---|---|---|
| My Day / driving timeline | Today; drive details open from the upcoming departure | Today; Copilot driving only if configured and permitted |
| Family calendar | Plan, with member filters and day/week controls | Personal Plan for Navigator/Copilot; Explorer week link. Sprout remains today-only. Do not expose the adult family-wide calendar by renaming a tab. |
| Intake + insights | Summary in Today; review queue with source, date, proposed effect and explicit decision | No parent approval controls; relevant child proposals retain their own acceptance flow |
| House chores + routines | Household → Tasks; My Day still includes timed personal commitments | Tasks/My things; only eligible choices, existing supervision rules and step photos |
| Lists | Household → Lists, with an explicit Groceries row | Tasks → Lists or My things when applicable; preserve server-granted access and personal lists |
| Reward requests + verification | Household → Requests and Today summary | Tasks → Rewards or a named Rewards entry; earned history persists |
| Messages | Messages; unread conversations lead | Family for Sprout, Messages for older stages; membership/invitation permissions unchanged |
| Map | More → Family map, plus a contextual “View pickup” shortcut | Same contextual pickup access where allowed. Show configured sharing and stale/unknown state honestly. |
| Music | More → Music; optional pinned shortcut if usage warrants it | My things or More → Music; avoid consuming a primary tab by default |
| Critters / avatar | Profile and More → My critter; adult participation remains available | Companion in younger stages; named entry in older stages. No loss of earned items on transition. |
| Programs / lessons | Timed sessions in Today; My programs in More | Same structure, with supervision from `practices_alone`, not device ownership |
| Moments | Messages preview and More → Moments | Same named path where allowed; do not conflate Add a moment with sending a text |
| Settings / theme / identity | Profile; theme follows saved preference/OS | Profile/parent-authorized controls; settings are not a child primary destination |

“More” is a tradeoff: map and music become one extra tap from the root. Keep a direct pickup-map shortcut on the ride card, show an active media mini-player while playback is running, and consider a user-selected quick action if observation shows frequent use. A searchable, labeled directory is more useful than an unexplained overflow menu. Do not hide a currently available feature merely to simplify a screenshot.

Helpers retain assigned drives and parent conversations; guests retain invited conversations. A non-driving parent retains parent decisions. Non-parent adults do not gain verification/approval rights. The mockup's role selector illustrates layout differences, not a new access-control system.

## Surface-level usability recommendations

- **Today:** time-critical change first, then next departure/ride, then a single decision summary and the day's sequence. Keep “leave at” distinct from “starts at.” Do not show an old morning launch as today's next action after it has passed.
- **Plan:** a visible Today reset, explicit previous/next controls, recognizable dates, member filters for adults, text status alongside color. Keep start time, location and driver in predictable columns. Preserve chronological order. At tablet widths use an optional master/detail layout instead of stretching every phone row edge to edge.
- **Household/Tasks:** separate “mine,” available work and review work. Label Claim as “Choose this job” for younger readers; label icon-only release/reject actions. Completion should be immediate, clearly acknowledged and undoable. Put lists in an obvious subsection.
- **Messages:** conversation list first, named compose action, clear recipient context, photo attachment label, and no assistant button over the composer. Moments can preview beneath conversations rather than displacing them.
- **Drive:** one prominent departure, destination and assigned car; explicit “Start this drive,” “Navigate,” and “Arrived” states. Details should be easy to scan while preparing to leave. Avoid animation and unnecessary information in the active-drive surface.
- **Map:** distinguish last-known location from live updates; display freshness and a text pickup answer. Explain what each role can see. A map should supplement “Alex picks you up at 3:15,” not be required to discover it.
- **Music:** selected playback device must be visible before Play. Pair volume and transport controls with generous hit areas and accessible names; keep active playback reachable after leaving the tab.
- **Empty/loading/offline:** explain whether there is nothing scheduled, data is loading, or cached data is shown. Preserve last known information with a timestamp and offer Retry. Avoid making an empty week look like a successful sync.

## Readability and accessibility targets

Use at least **4.5:1** for normal text and **3:1** for qualifying large text; meaningful controls/focus also need an appropriate visible contrast treatment. The dark gray token issue should be corrected before refining the palette. [W3C contrast guidance](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

The design target is **44–48 px adult controls and 48–56 px child primary actions**. These are product targets, not a claim that WCAG AA requires 44 px: WCAG 2.2's minimum target criterion is 24 × 24 CSS px with stated exceptions. [W3C target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html).

Keep icon labels, visible keyboard focus, meaningful selected-tab state, predictable dialog focus/return, readable error text, and reduced-motion behavior. Test 200% text resize and 320 px reflow in implementation; do not obtain density by shrinking the essential text. In the mockup the adult muted text on white is 5.83:1 and the Explorer muted text on its page background is 5.84:1; these spot checks do not certify all states.

The five-destination adult proposal is consistent with the established 3–5 destination bottom-navigation pattern. The four child presentations also reflect research that children's interfaces need finer differentiation than a single “kids” design. These sources support the direction, not a claim that this family has validated it. [Material navigation guidance](https://m1.material.io/components/bottom-navigation.html), [NN/g children's usability research](https://www.nngroup.com/articles/childrens-websites-usability-issues/).

## Implementation recommendation

1. **Fix the shared basics:** header overflow, accessible action names, contrast roles, text size and floating-action collisions. Keep feature permissions unchanged.
2. **Introduce presentation profiles:** role/stage sets semantic tokens and component variants. Light/dark and text size stay separate preferences. Do not fork the domain logic or create five independent applications.
3. **Reorder the home surfaces:** preserve data/actions; prioritize next relevant time, reassurance and action. Build the adult decision summary by deduplicating existing sources and respecting their authorization rules.
4. **Restructure navigation:** migrate saved tab/deep-link state; retain old push destinations and browser back behavior. Roll out the named More directory with contextual shortcuts before removing standalone tabs.
5. **Validate with the family:** compare current/proposed flows with at least one person representing each configured stage. Treat these designs as hypotheses, then refine.

Reuse precedents: shared day/drive data and action builders in [app.html](../../../chauffeur/templates/app.html), the [agenda row builder](../../../chauffeur/templates/components/agenda_row.html), [kid glyphs](../../../chauffeur/templates/components/kid_glyphs.html), current avatar/critter renderers, existing requests/approval endpoints, and the [stage service](../../../chauffeur/services/stages.py). The [current design guide](../../../chauffeur/docs/ui_design_guide.md) prescribes translucent rounded cards and a single visual vocabulary; adopting this requested direction would require a deliberate update to that guide for audience-specific variants. This proposal does not silently change that standard or ship a new PWA shell.

## Acceptance checks for a future implementation

| Task | Proposed success condition |
|---|---|
| Adult: find next departure, child, location and car | Correct answer from Today/one drive-detail tap; no hunt through Family |
| Parent: find and review a completed chore | Today summary opens the right item; no duplicate pending count |
| Non-driving parent: check pickup and approve work | Useful landing screen with no irrelevant driving controls |
| Helper: find assigned drive and contact parent | Both reachable; family-wide calendar and unrelated tools absent |
| Sprout: identify and complete next step | Understands picture/instruction with normal caregiver support; no need to scan all routine buckets |
| Explorer: find pickup, finish routine, find reward | Clear pickup answer and successful completion/undo; reward is discoverable without leading every task |
| Navigator: find a deadline and request a change | Personal plan and pending/confirmed distinction are understood |
| Copilot: manage commitments with/without driving | Same mature presentation; driving appears only for configured drivers |
| All: discover music, map, programs and critters | Named directory and relevant direct links; no feature lost through presentation changes |
| All: recover from loading/offline/error | Honest status, retained data where available, labeled recovery action |
| All: narrow width, dark mode, zoom, keyboard | No clipped action, overlapping assistant, contrast regression or lost focus |

Prototype verification checks layout and selected interactions; it does not prove those human success conditions. The next useful review is to walk through these specific tasks in the interactive mockups and choose the navigation/style direction before implementing it.
