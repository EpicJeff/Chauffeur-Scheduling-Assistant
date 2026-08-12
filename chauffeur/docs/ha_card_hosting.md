# Running a real Home Assistant card in a Chauffeur tile

The `ha_dashboard` tile frames Home Assistant's own page, and its comments make
the flat claim that a Lovelace card cannot run outside HA's frontend. That claim
was too strong. This is what replaced it, what it actually costs, and where it
stops.

## The claim, narrowed

A **custom** card — one installed through HACS, shipping as its own JavaScript
file — can be run outside Home Assistant. It is an ordinary custom element, and
HA's frontend gives it exactly four things:

| It needs | Where it comes from here |
|---|---|
| `hass.states` | The board payload. `ha_cards.entity_ids` reads the card's config, `states_for` sends only those entities. |
| `setConfig(config)` | The YAML pasted into the tile, parsed server-side. |
| CSS custom properties | `ha_card_host.js` maps them from the panel's own tokens. |
| `ha-card`, `ha-icon`, `hui-warning`, … | Defined by `ha_card_host.js`. |

The third row is the reason to do this at all rather than framing HA. **A Home
Assistant theme is nothing but CSS custom properties**, and custom properties
inherit across shadow boundaries. Set `--primary-text-color` on the tile and a
card that has never heard of Chauffeur draws itself in Chauffeur's colours — in
light mode, dark mode, and the sun-follows-sunset setting — with no cooperation
from its author and no fork of its code.

## What it cannot do

- **Built-in cards.** `type: gauge` resolves to `hui-gauge-card`, compiled into
  HA's frontend bundle. There is no file to fetch. Only `type: custom:…` cards
  exist as loadable resources.

  Built-in cards need the other approach: read the config and draw it natively.
  That is easier, not harder — a built-in card's config fully describes it.
  **That work landed in v2.192.0; see the section at the end of this file.**
  The tile routes them there, and refuses the ones it cannot draw by name.
- **Cards that reach into HA's frontend.** Anything calling `loadCardHelpers()`
  or extending `hui-*` classes. It will fail to define, and the tile says so
  after an eight-second wait rather than spinning forever.
- **Cards driven by the statistics websocket** — the official energy dashboard
  cards. `hass.connection.subscribeMessage` rejects, which lets a card fall
  back or complain; a promise left unsettled would leave a spinner on the wall.
- **A card's own visual editor.** Configs are edited as YAML here. The editor
  half of a card bundle wants `ha-form`, `ha-entity-picker` and friends, and
  those are frontend internals.

Everything that fails falls back to the framed `ha_dashboard` tile, which is
still there and still works. That is why both exist.

## What was actually proven

Two real bundles, downloaded untouched from their own repositories, mounted in
jsdom against `ha_card_host.js` with a states snapshot and no Home Assistant
anywhere:

**tesla-style-solar-power-card 1.4** — mounted, defined, rendered 6.8 KB of
shadow DOM, used the `ha-card` shim, requested `mdi:solar-panel-large` from the
icon endpoint, and displayed `0 kW / 3.3 kW / 3.3 kW` from the states it was
given. Its entire `hass` surface is `hass.states`, five references. This is
close to the best case and it is also the card this work was requested for.

**power-flow-card-plus 0.3.7** — mounted, rendered 17 KB of shadow DOM, showed
`3.3 kW`, `Home`, `87 %`. It uses `hass.localize` (answered `''`, which is HA's
own behaviour for an unknown key and what the `localize(...) || fallback`
pattern every card is written around expects), `hass.user`, and
`hass.connection`.

Two failures during that run were **jsdom artifacts, not host gaps**, and are
worth writing down so nobody re-diagnoses them:

- `e.line.getTotalLength is not a function` — jsdom does not implement
  `SVGGeometryElement.getTotalLength`. The solar card's flow animation calls it
  every frame. Real browsers have it. **The animation path is therefore
  unverified**; the static render is not.
- `ResizeObserver is not defined` — jsdom again. Present in every real browser.

`power-flow-card-plus` also ships as an ES module, which `window.eval` cannot
run; the harness strips the trailing `export{…}`. In the browser this is a
non-issue — the loader honours the resource type HA registered and uses
`<script type="module">`.

## The proxy, and why its allowlist is the whole security story

`/api/ha/card/resource` fetches with the supervisor token. Anything it will
fetch, anyone who can reach the panel can read out of Home Assistant. So it
serves **only** these prefixes, and rejects absolute URLs outright:

    /hacsfiles/        HACS installs
    /local/            /config/www, hand-installed cards
    /community_plugin/ where HACS put things before 2021

A resource pointing at a CDN is something the browser can load by itself;
routing it through an authenticated proxy buys nothing and risks everything.

`/api/ha/card/service` is allowlisted to the same domains as the entity tile's
toggle (`light`, `switch`, `fan`, `input_boolean`). The tile's own "let the card
control things" switch defaults off and is enforced in the browser too — two
locks, because a hosted card is a stranger's code running on a screen in a
kitchen.

## Icons

`ha-icon` resolves through `/api/ha/card/mdi/{name}`, which reads Home
Assistant's own MDI chunks (`/static/mdi/iconMetadata.json`, then the
alphabetical chunk file). The icon set therefore cannot drift from the one the
household sees in HA. Names are validated against `^[a-z0-9-]+$` before they
reach HA; whole chunks are cached in memory once fetched, misses included.

This also removes the constraint recorded in `home_board._HA_DOMAIN_GLYPH` —
that this app has no way to draw an mdi icon. It now does, and the per-domain
emoji in the plain entity tile could use it.

---

## Built-in cards, converted (v2.192.0)

The "built-in cards are out of reach" section above is still true about
*hosting* them, and always will be. What changed is where that leads.

A built-in card's config **completely describes it**. `type: entities` with
four ids is not a program, it is a request for four rows of name-and-reading.
So `services/ha_card_convert.py` reads the config and draws it in the panel's
own vocabulary, and the `ha_card` tile now has two modes:

| Config | Mode | How |
|---|---|---|
| `type: custom:…` | `host` | fetch the card's file, shim `hass` and `ha-card` |
| a supported built-in | `native` | convert the config, draw it ourselves |
| anything else built-in | error | refused by name, dashboard tile offered |

**Converting is better than hosting, not a consolation prize.** No borrowed CSS
variables, no element shims, nothing to break when a card author ships an
update — and the result can be told to fit its tile, which a hosted card
cannot.

Supported: `entities`, `glance`, `tile`, `gauge`, `markdown`,
`picture-entity`, `button`, `sensor`, `thermostat`, `area`, and the three
stacks (`vertical-stack`, `horizontal-stack`, `grid`) that hold them.

Three of those need more than a config to draw:

- **`sensor`** is the only card here that is not a pure function of a config
  and a state - it needs history. `ha_api.get_history` caches for five minutes,
  because the board rebuilds every twenty seconds and a graph card would
  otherwise run a history query per sensor per rebuild forever. The line is
  downsampled server-side (at most 96 buckets). `graph: none` never queries
  history at all.
- **`thermostat`** carries the mode AND the action, because they disagree
  constantly - one set to heat is idle most of the time. Read-only unless the
  tile's interactive switch is on, and even then only the setpoint moves.
  `POST /api/ha/card/climate` takes a DIRECTION, not a temperature: the step
  size and the permitted range are read off the entity server-side, and
  dual-setpoint thermostats are refused rather than guessed at.
- **`area`** names no entities at all; it names an area, and the entities come
  from HA's registry via `ha_api.get_area_map` (which uses HA's own
  `area_entities()`, so entities inheriting their area from their device are
  picked up).

Not supported, and why:

- `history-graph`, `statistic`, `energy-*` - a multi-entity chart, and the
  statistics websocket, which is different plumbing.
- `light`, `media-control` - control surfaces with their own interaction
  models, needing a careful think about what a mis-tap costs.
- `conditional`, `entity-filter` — logic rather than layout. The honest place
  for that is a tile option.

An unsupported built-in is **refused by name** with the dashboard tile offered
as the way round. That is what stops "we support most of them" from becoming a
blank box on a wall.

### Two things worth knowing about the implementation

**Entity discovery is schema-aware here.** `ha_cards.entity_ids` walks a custom
card's config looking for anything entity-*shaped*, which is right when the
schema belongs to somebody else. The built-in schema is known, so
`ha_card_convert.entity_ids` reads the fields that actually hold ids — and a
row whose `name:` happens to look like an entity id does not become a state
request.

**Escaping is the renderer's job, and the renderer is a string builder.** The
converter passes text through unchanged; `drawCard` in home.html escapes on the
way into markup. The sharp case is an entity id, which goes into an
*attribute*, where a single quote would end the attribute and start whatever
the name felt like. Markdown is the exception — it is escaped server-side
first, then a fixed set of patterns is allowed back in, so nothing can widen
that set by containing angle brackets. Both halves are tested
(`test_ha_card_convert.py`, including a node run of the real renderer against
hostile names, states and entity ids).
