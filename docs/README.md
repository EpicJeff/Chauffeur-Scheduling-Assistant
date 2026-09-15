# Chauffeur documentation index

**Current baseline:** v2.499.4, 2026-09-14

Chauffeur has living references, binding design standards, and dated design history. Use this index to avoid reading an old implementation plan as current behavior.

## Living references

- [`../README.md`](../README.md) — product overview, architecture, local setup, and main routes.
- [`current_implementation.md`](current_implementation.md) — current implementation status, active development, priorities, and release gates.
- [`../chauffeur/system_capabilities.md`](../chauffeur/system_capabilities.md) — canonical detailed record of shipped behavior and invariants.
- [`../chauffeur/docs/roadmap.md`](../chauffeur/docs/roadmap.md) — future backlog and open product direction. Its older dated sections are retained as history.
- [`../chauffeur/docs/ui_design_guide.md`](../chauffeur/docs/ui_design_guide.md) — binding UI reuse and theme rules.
- [`house_style_bible.md`](house_style_bible.md) — binding art, geometry, composition, and performance rules for the 3D house.
- [`llm_request_budget.md`](llm_request_budget.md) — current Gemini request admission, retry, cooldown, and accounting behavior.
- [`../homeassistant/README.md`](../homeassistant/README.md) — Home Assistant voice and Argyle integration setup.
- [`../chauffeur/docs/ha_card_hosting.md`](../chauffeur/docs/ha_card_hosting.md) — hosted and native-converted Home Assistant card architecture.

## Design records

Files named `*_design.md` and `*_plan.md` under `chauffeur/docs/` describe individual feature arcs. They preserve requirements, decisions, rejected options, and implementation context. Check `system_capabilities.md` before assuming an unchecked box or future-tense statement remains current.

## Historical execution records

`docs/superpowers/specs/`, `docs/superpowers/plans/`, and `docs/superpowers/reports/` are dated work records. Keep them stable for provenance. They do not override living references or shipped code.

## Documentation rule

Every shipped behavior change updates `system_capabilities.md`. Changes to product scope, architecture, setup, current priorities, UI contracts, house art rules, or provider budgets also update the matching living reference above.
