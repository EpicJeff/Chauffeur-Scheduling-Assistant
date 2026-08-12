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
  exist as loadable resources. The tile refuses these **by name** rather than
  failing to load, because the YAML looks identical and "could not load" would
  send somebody hunting for a file that was never the problem.

  Built-in cards need the other approach: read the config and draw it natively.
  That is easier, not harder — a built-in card's config fully describes it —
  but it is a different piece of work.
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
