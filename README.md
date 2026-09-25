# Chauffeur

Chauffeur is a family operations system built for wall panels, phones, and Home Assistant. It combines a constraint-based family driving scheduler with the daily work around the schedule: packing, routines, chores, errands, meals, shopping, messages, trips, household administration, and guided personal programs.

The wall experience offers an interactive 3D house or a photographic house with connected rooms. Config > Boards lets the household choose the new House experience and independently make The House its Home page. Family members can read the next activity at a distance, enter rooms to reach related features, and use familiar household objects instead of navigating a conventional app menu. The PWA provides personal day, ride, family, and task views. The Study provides parent-only administration inside the same house.

## Current product

- **Schedule and transportation:** Google Calendar sync, OR-Tools CP-SAT driver and vehicle assignment, travel-time constraints, manual overrides, covered rides, trip exclusions, departure timing, and car telemetry.
- **At-a-glance coordination:** clock and compact next-activity card on the house exterior, Family Day and packing views, driver/car status, and attention states for unfinished household work.
- **Family hub:** messages, map, chores, routines, rewards, errands, meals, groceries, shopping lists, occasions, moments, music, and trips.
- **Intelligence:** intake proposals from email, calendar feeds, and images; the Mind executive loop; household findings and negotiations; missions; and researched or generated personal programs with interactive lessons.
- **House interface:** touch-first room markers, room lean-ins, tap-empty-space exit, independent architectural cutaways, persistent feature icons, night lighting, and a fully integrated Study protected by a parent PIN.
- **Home Assistant:** add-on packaging, panel/iframe support, person and vehicle state, Music Assistant, hosted or converted HA cards, notifications, and the Argyle conversation integration.

For detailed shipped behavior and invariants, read [system_capabilities.md](chauffeur/system_capabilities.md). For document status and design history, read [docs/README.md](docs/README.md).

## Main surfaces

| Surface | Route | Purpose |
| --- | --- | --- |
| House | `/house` | Shared wall-panel home and spatial feature navigation |
| Family PWA | `/app` | Personal and family mobile experience |
| Schedule | `/home` | Operational schedule and solver dashboard |
| Configuration | `/config` | People, calendars, cars, rules, integrations, and feature settings |
| Study | entered through the house | Parent-only administration, findings, programs, household work, and intake |

Most feature pages also support `?panel=true` when rendered inside a house card or wall panel.

## Architecture

- **Server:** Python 3.11, FastAPI, Uvicorn, Pydantic, and Jinja2.
- **Scheduling:** OR-Tools CP-SAT with route and continuity scoring.
- **Storage:** SQLite by default, with a compatibility path for legacy TinyDB data and automatic first-boot migration.
- **Client:** server-rendered HTML, vanilla JavaScript, precompiled Tailwind CSS, and vendored Three.js for the house and Study.
- **Integrations:** Google Calendar, Home Assistant, Music Assistant, Mapbox, web push, optional search/image providers, and Walmart cart/search support.
- **Deployment:** Home Assistant add-on container or a local Uvicorn process.

## Run locally

From the repository root on Windows:

```powershell
.\venv\Scripts\Activate.ps1
cd chauffeur
python main.py
```

Then open [http://localhost:8000](http://localhost:8000). `main.py` starts Uvicorn with reload enabled on port 8000.

Install dependencies when needed:

```powershell
cd chauffeur
python -m pip install -r requirements.txt
```

Configuration is managed in the application. Home Assistant add-on secrets and provider keys belong in add-on options; local credentials and generated data must remain outside source control. Google Calendar service-account setup is exposed through the configuration surface.

## Frontend and validation

Tailwind is compiled and checked against template content. After adding or changing Tailwind classes, run:

```powershell
cd chauffeur
python tools/build_tailwind.py
python tests/test_tailwind_build.py
```

Run focused tests for the subsystem changed. House work also requires rendered browser checks at desktop wall resolution and a touch-sized viewport; geometry and cutaway bugs are often invisible to unit tests.

## Documentation

- [Documentation index](docs/README.md)
- [Implementation status and forward plan](docs/current_implementation.md)
- [Shipped capability reference](chauffeur/system_capabilities.md)
- [Family-hub roadmap](chauffeur/docs/roadmap.md)
- [UI design guide](chauffeur/docs/ui_design_guide.md)
- [House style bible](docs/house_style_bible.md)
- [Gemini request accounting](docs/llm_request_budget.md)
- [Home Assistant voice integration](homeassistant/README.md)
