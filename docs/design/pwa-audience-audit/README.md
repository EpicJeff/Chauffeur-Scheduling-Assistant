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
