# PWA audience design review

Open **[index.html](index.html)** in a browser. It works directly from disk and has no external dependencies.

- Choose Adults, Sprout, Explorer, Navigator or Copilot.
- On Adults, use the Role selector to compare parent/driver, adult/driver, non-driving parent and helper driver.
- Explore the screen links or the prototype's bottom tabs.
- Try task completion and undo, request/review sheets, directory search, family messages, and light/dark previews.
- Choose **Compare all five** for the overview.

[Written audit](AUDIT.md) · [Comparison image](previews/five-audiences.png) · [Current-screen evidence](current/) · [Rendered mockups](previews/)

All content is fictional. Actions are local simulations; no request is sent to the live application. Read-aloud, consolidated review summaries, search and the reorganized navigation are proposals. Existing permissions and stage capabilities remain requirements for any implementation.

## Reproduce the review

### Profile colors implemented in 2.499.214

**[Working profile-color examples](implementation/profile-colors/index.html)**

Adults and all four child stages now derive accents, background tints, tabs,
primary controls and sheets from the selected member's `color_code`. Fixed
audience palettes are removed. Light/dark variants adjust accent brightness
for readable contrast, including very light and very dark profile colors.
The audience layouts stay the same. Palette changes follow roster refreshes,
theme changes and identity switching; an unknown identity clears the palette.

The shared browser checks exercise each audience with multiple profile colors,
verify contrast and profile switching, and retain the existing navigation and
action checks. Set `PWA_PALETTE_OUTPUT` to an output directory when running
`chauffeur/tests/test_pwa_adult_shell_live.py` to capture the examples above.
The older galleries below document their release's appearance; their fixed
stage colors are superseded by this profile-based palette.

### All four child experiences implemented in 2.499.213

**[Working child screens, sheets and mockup comparison](implementation/children/index.html)**

Sprout now leads with one picture-based routine step, Explorer with a focused
checklist and pickup reassurance, Navigator with compact priorities and a
personal Plan, and Copilot with a restrained blue organizer. The children's
navigation, task/reward sections, messages, feature directory, profile and
detail sheets use the corresponding stage design. Configured Copilot drivers
also get compact drive rows, a next-departure summary and matching drive sheets.

Plan reads the selected child's own day and scheduled program sessions within
the server-provided horizon. Stage and capability overrides remain authoritative;
parent approval, program supervision and task eligibility are unchanged. Routine
substeps and direct completion are exercised through the existing actions. This
also fixes the old completion callback's reference to a nonexistent `members`
list, which saved progress but failed to refresh it. Older stages retain rewards
in their task sections without leading their day with points or oversized art.

The served-app suite now uses populated child fixtures, rather than merely
asserting that the old child UI is unchanged. It covers four stages plus a
configured Copilot driver, completion/refresh, detail sheets, future-day previews,
capability overrides, navigation, adult/child shell switching and light/dark
layouts at phone/tablet sizes with doubled text. Run
`chauffeur/tests/test_pwa_adult_shell_live.py` for the complete audience suite;
its child scenarios live in `chauffeur/tests/pwa_child_checks.py`.

These are presentation changes over existing actions. Prototype-only read-aloud,
new scheduling controls and simulated vehicle reservations are not added. The
fixtures do not send live messages or test real push, music or location tracking.

### Adult action sheets implemented in 2.499.211

[Working sheet gallery](implementation/sheets.html): event and drive details,
dark drive details, and a shared confirmation. The `.pwa-sheet` treatment
also covers shared input/choice/session/trip prompts, profile/review dialogs,
notifications, PIN and new chat. It follows the approved prototype's `.sheet`,
`.primary` and `.secondary` styles, with 56px drive action targets retained.
The browser check exercises real roll-call persistence, confirms the event
and departure agree on their rider/destination, tests prompt results and
dismissal, and verifies the child prompt styling remains unchanged. Captures
use fictional fixtures, not the live household.
Follow-up 2.499.212 sizes empty notifications to their content, lightens
profile descriptions, supplies distinct profile action icons, and flattens
the chat-recipient picker with a labeled 44px remove control. The gallery
includes these sheets in both themes. All nine profile checks now pass,
including Explorer, Navigator and Copilot; the earlier Windows loopback
failures are no longer an outstanding validation gap. The runner-only
socket workaround was not added to the application. Additional browser
checks cover recipient selection/removal, touch targets, overflow, empty
notifications and profile text hierarchy; all six stylesheet checks pass.

### Adult design implemented in 2.499.209

The adult UI now follows the proposal's typography, spacing, light/dark
palette, page headings and compact schedule rows. The earlier 2.499.208
foundation retained the old card stack and did not deliver that visual change.
The next drive is promoted once; remaining drives, appointments and programs
use aligned time columns and separators. Past items remain readable instead
of fading. A real review summary links to existing household and request
actions. Plan has a date strip, Household has section tabs, Messages has
conversation search, and More has a labeled feature directory.

**[Before / approved mockup / implementation comparison](implementation/comparison.html)**

[Actual Today, light](implementation/adult-today-light.png) ·
[Actual Today, dark](implementation/adult-today-dark.png) ·
[Past drives and an evening program](implementation/adult-driver-past-light.png) ·
[Plan](implementation/adult-plan-light.png) ·
[Household](implementation/adult-household-light.png) ·
[Messages](implementation/adult-messages-light.png) ·
[Actual More screen](implementation/adult-more-light.png)

These are served-app captures with fictional data. Run the focused browser
check to reproduce them:

```powershell
$env:PWA_REVIEW_OUTPUT='docs/design/pwa-audience-audit/implementation'
.\venv\Scripts\python.exe -X utf8 chauffeur/tests/test_pwa_adult_shell_live.py
```

The check covers parent/driver, adult/driver, non-driving parent, helper,
guest and all four child stages; directory filtering and scope restrictions;
profile keyboard dismissal, theme switching, drive actions/completion,
program disclosures, date selection, review navigation and verification,
conversation search, past-row contrast, and horizontal overflow at
phone/tablet widths and doubled root text size. Background integrations are
disabled in this isolated fixture server; scripts and styles have bounded
transport retries for loopback connection resets.
Real notifications, location tracking, routing estimates and music playback
are not exercised by these fixtures. The child profiles in that release were regression checks only; the four child
redesigns are implemented and separately exercised in 2.499.213 above.
The proposal's simulated cover requests, person filters and new-event flow
are not added by this visual pass; the application's existing actions and
permission rules remain authoritative.

### Standalone proposal

From the repository root, with its Python environment and Playwright installed:

```powershell
.\venv\Scripts\python.exe -X utf8 docs/design/pwa-audience-audit/tools/render_review.py
```

This renders the standalone mockups and checks selected interactions, role variations, 44 px minimum button heights and horizontal overflow. Results are in `previews/verification.json`. The small-target list is recorded for review; it is not a substitute for a complete accessibility audit.

The current-app evidence can be recaptured with:

```powershell
.\venv\Scripts\python.exe -X utf8 docs/design/pwa-audience-audit/tools/capture_current.py
```

The capture script sets `CHAUFFEUR_DATA_DIR` to a fresh temporary directory before importing the app, seeds fictional members, stubs selected responses, and runs only against that local instance. It does not use the live household database. These fixtures intentionally do not exercise real push delivery, routing estimates, location tracking or music playback.
