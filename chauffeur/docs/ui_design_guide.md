# Chauffeur UI design guide

*This file is handed verbatim to any agent building or touching UI. It is not
advice; it is the house style, extracted from the shipped surfaces. Where this
guide and a shipped sibling disagree, read the sibling — then fix whichever of
the two is wrong rather than inventing a third way.*

## The one rule

**Never invent a visual language. Find the sibling that already solved this
shape and reuse its builder or copy its markup exactly.** Chauffeur's look is
not a palette, it is a set of shipped components. A new surface that "looks
designed" but matches nothing else is a defect, even when it is pretty.

## Shared builders come first

When two surfaces draw the same concept, they share ONE builder (the
kiosk-shares-logic / TripLogic pattern — an included component both consumers
load). Existing shared pieces:

- **`components/agenda_row.html`** — `window.agendaEventRow(ev, opts)`: THE way
  an event renders as a row, anywhere. Time label, 4px left color bar, bold
  title, badge slot (driver chip, car chip incl. amber car-swap, covered
  `🤝 name` teal chip, needs-driver red, conflict amber, errand), past events
  at `opacity-45`. Also owns the `.agenda-day` / `.agenda-event` /
  `.agenda-today` CSS and their ha-theme overrides. Consumers: the calendar
  card's agenda view (`family_calendar.html`) and the Family Day card
  (`packing_card.html`).
- **A container of events** (a day on the agenda, an outing on Family Day) is
  an `agenda-day rounded-2xl p-3 flex flex-col gap-2` panel: header line
  (bold identity + chips + status), then `agendaEventRow` children.

If the thing you are drawing is an event, a list of events, or a container of
events — you are not designing anything. You are calling these.

## The vocabulary (with the canonical source)

- **Panels / cards:** `rounded-2xl`, translucent fill + hairline border
  (`.agenda-day`: `rgba(30,41,59,0.5)` + `1px solid rgba(255,255,255,0.08)`),
  never opaque flat boxes. Highlight variant = colored border + soft glow
  (`.agenda-today`).
- **Rows inside a panel:** `rounded-lg px-2.5 py-1.5`, one tier lighter fill
  (`.agenda-event`), 4px left color bar carrying the entity's color.
- **Chips / badges:** `text-[10px] font-bold px-1.5 py-0.5 rounded` on a
  muted fill (`bg-gray-700 text-gray-300`); semantic tints stay translucent
  (`bg-teal-500/20 text-teal-300`, `bg-amber-500/20 text-amber-300`). Pills
  that must catch the eye are the exception and there is at most ONE saturated
  element on a resting row (Family Day's amber `N to pack` pill).
- **Type scale:** big identity numerals/titles `font-extrabold text-white`;
  secondary `text-sm font-bold text-gray-300`; metadata
  `text-[11px] font-semibold text-gray-400`; empty states
  `text-xs text-gray-500 italic`.
- **State treatments:** past/suppressed = opacity (45–50%), never removal;
  canceled = greyed + `line-through`; interactive-off = controls absent from
  the DOM (`x-if`), never hidden.
- **Theming:** wall cards render inside `html[data-panel]` where the
  gray-scale classes are remapped by `panel_skin.html`; HA-embedded surfaces
  get `body.ha-theme` overrides via CSS variables (`--ha-card-bg`,
  `--ha-primary-text`, `color-mix` tints). Never hardcode a one-theme color
  where a sibling uses the remappable vocabulary. PWA surfaces use the token
  layer (shade roles are contracts).
- **Empty states:** an honest sentence in the muted empty style — never a
  blank panel (rule 1: hide only what is not set up).
- **Dialogs:** never `alert()`/`confirm()`/`prompt()` —
  `showGlobalAlert` / `promptConfirm` / `promptInput`.
- **Tailwind is precompiled:** any new class needs
  `python tools/build_tailwind.py` or it silently does nothing.

## Process contract for UI agents

1. Read this file, then read the sibling component nearest your shape END TO
   END before writing markup.
2. Every styling choice cites a sibling precedent (file:line) in your report.
3. If no sibling has solved the shape, STOP and say so instead of inventing —
   the controller decides whether a new pattern enters this guide.
4. Prove the result with a rendered screenshot (playwright harness, dark
   theme, wall viewport) — markup that passes tests can still look wrong.
5. Screenshot fixtures must be realistic AND sorted the way the server sorts;
   a demo that misorders data reads as a product bug.
