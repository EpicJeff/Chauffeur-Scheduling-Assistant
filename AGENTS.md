# Working in this repository

This file is for Codex (in VS Code or through the Claude Code plugin) and any other agent that does not carry Claude Code's memory. Claude Code holds the project's long-term memory and the shipping conventions; the point of this file is to give you the same starting context before you read code.

## Read these first

1. `chauffeur/system_capabilities.md`, the first ~150 lines. It is the living record of what has shipped and the invariants behind it. Newest entries are at the top. Any change you make must be reflected there by whoever commits.
2. `C:\Users\ffejn\.claude\projects\e--repositories-Chauffeur\memory\MEMORY.md`. One line per memory. Open the linked arc file for whatever you are about to touch (browse missions, the house, auth, boards, voice, and so on). These files hold locked decisions and the device-found fixes that must not regress.
3. For any UI work: `chauffeur/docs/ui_design_guide.md`. Same concept means the same shared builder.

## The app in one paragraph

Chauffeur is a family logistics app that runs as a Home Assistant add-on (FastAPI in `chauffeur/main.py`, services under `chauffeur/services/`, Jinja templates under `chauffeur/templates/`, static JS under `chauffeur/static/`). A PWA for family phones, wall-panel boards (`?panel=true&kiosk=true`), admin pages, and an agent called Argyle (`services/agent_router.py` plus the tool registry in `services/agent_tools_v2.py`, the only agent stack). Auth enforcement is on: routes are classified by tier in `services/auth.py`, and every new route needs a rule there or the test suite flags it.

## Conventions that bite

- **Tests run from `chauffeur/`** as plain scripts: `python tests/test_x.py`. Unset `HA_BASE_URL` first; the dev shell exports it and several files go red under it. Run the change's own tests plus the named neighbours. Never run the whole suite; it takes far too long.
- **Entry points swallow exceptions.** Every critical path needs at least one test that actually runs it (a TestClient request, a node run of the JS), not a test that greps the source.
- **No browser dialogs.** Never `alert`, `confirm` or `prompt`. Use `showGlobalAlert`, `promptConfirm`, `promptInput` from `templates/components/control_center.html`.
- **New settings** go in `services/settings_registry.py` and the feature's own page or drawer, never `config.html`.
- **Tailwind is precompiled.** After any template class change run `python tools/build_tailwind.py`; a stale sheet fails silently.
- **Every HA touchpoint degrades gracefully** with no Home Assistant present.
- **Never remove anything a person can do** without approval first. Flagging it afterwards does not count.
- **Every agent capability needs a hand path.** If Argyle can do it, the UI must let a person do it too.
- **Kiosk and read-only variants share domain logic** through included components; only presentation differs.
- **Vendored Alpine** stamps `:disabled="x[loopVar.id]"` true on first render. Always coerce with `!!`.
- **PowerShell:** no double quotes in commit messages, and never round-trip source through `Get-Content`/`Set-Content` (it mangles UTF-8). Prefer the Bash tool or Python for file edits.
- Event, trip and solver semantics are locked in the memory files. Read before changing anything in `services/solver*`, trips, or the calendar feed.

## The hand-off contract with Claude Code

- **Do not bump `chauffeur/config.yaml` and do not commit.** Leave your changes in the working tree with a short note of what you changed, what you tested and how. Claude Code runs the gate tests, reviews the diff, updates `system_capabilities.md`, bumps the version and commits under its own rule.
- Reviews are read-only. Report findings as `path:line`, the defect, a concrete failure scenario, and the fix. Verify a finding against the code before reporting it.
- When a task names a test to make green, make that test green without weakening it, and keep the surrounding behaviour. If the test is wrong, say so instead of changing it.
- If you find a locked decision in the memory files that the task contradicts, stop and report the conflict rather than picking a side.
