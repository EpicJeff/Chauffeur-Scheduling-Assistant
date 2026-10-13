# Model provider selector — Gemini, Claude or OpenAI behind the whole agent

**Date:** 2026-10-13. **Revised:** 2026-10-13 after a Codex adversarial review (fourteen findings, every one confirmed against the code; each is resolved in place and listed in **Review resolutions** at the end). **Status:** draft for review. Nothing here is implemented.
**Builds on:** the model pools (`services/model_pools.py`), the Gemini admission layer (`services/llm_budget.py`), the two wire branches in `services/llm.py`, Gemini search grounding in `services/web.py`, and the Gemini computer-use runner in `services/browse.py`.

## Outcome

Config › AI has one selector: **Gemini**, **Claude**, **OpenAI**, or **Ollama**. Picking Claude or OpenAI and pasting that provider's key moves every model call the app makes — Argyle's chat turns, every background workflow, the Mind, vision intake, the house photo pipeline, missions, web research and browse missions — onto that provider. Nothing a person could do before stops working; nothing changes shape in the UI beyond the selector and its key field. The Gemini column keeps every free-tier mechanism it has today. A household that wants to mix (chat on Claude, free background work on Gemini) can still do it through the existing pool overrides.

## Today

- `llm_provider` (gemini | ollama) is honoured only by the trip planner, rule deduction in `main.py`, conversation naming and `model_pools.pooled_or_direct`. Everything else, Argyle included, hardcodes `'gemini'` into `_call_llm_json` through `call_pool_json` (31 call sites) and `call_gemma_with_fallback`.
- Routing is tier → pool chain → ordered Gemini model ids (`TIER_CHAINS`, `DEFAULT_POOLS`). Per-model cooldowns, Gemma discovery, the paid key for the pro and cu pools, and the "ask a parent" paid fallback are all built around Gemini's free tier.
- `llm_budget.urlopen` meters only `generativelanguage.googleapis.com` and guesses per-model daily allowances from Gemini model names.
- Web research "with the model" is Gemini search grounding; browse missions are Gemini Computer Use through the `google-genai` SDK.

## Design

### 1. A provider is a column of the tier table, not one model

The tier chains stay exactly as they are. What changes is where a pool's model list comes from: each provider has its own pool table, and the selector picks the table.

| pool | Gemini (unchanged) | Claude | OpenAI |
|---|---|---|---|
| lite | gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemini-2.5-flash-lite | claude-haiku-5-5 | gpt-6-luna |
| flash | gemini-3.8-flash, gemini-3.6-flash, gemini-2.5-flash | claude-sonnet-5-5 | gpt-6.1-sol |
| gemma | discovered daily | (empty) | (empty) |
| pro | gemini-3.1-pro-preview (paid key) | claude-opus-5-5 | gpt-6.1-sol |
| cu | gemini-3.8-flash (paid key) | claude-sonnet-5-5 | gpt-6.1-sol |

So `interactive` on Claude is `[haiku]`, `heavy` is `[sonnet, haiku]`, `mission` is `[opus]`, `browse` is `[sonnet]`; an empty Gemma pool simply contributes nothing to a chain. The Claude ids are current as of the API skill's model table (2026-10-06). The OpenAI ids are from OpenAI's models and pricing pages read on 2026-10-13 (Luna: "most efficient model for focused, high-volume tasks"; GPT-6.1 Sol is the id the computer-use guide uses). **At build, both OpenAI ids are confirmed against `GET /v1/models` with the real key before the table is committed; a missing id is a stop, never a guess.** (The web-search guide's prose still names `gpt-5.5` as its recommendation; if `gpt-6.1-sol` refuses the `web_search` tool at build, `gpt-5.5` is the research model and the table says so.)

**Model ids carry their provider.** A pool entry is `claude-haiku-5-5` under the Claude table, but the id that travels through `models_for`, cooldowns, `attempts` lists, `_model` fields and `llm_budget` is the prefixed form `anthropic:claude-haiku-5-5` / `openai:gpt-6-luna`. A bare id is a Gemini id, as every stored setting and test already assumes. `model_pools.split_model(id) -> (provider, bare_id)` is the one parser; nothing else inspects the prefix by hand.

**Overrides mix.** `model_pool_lite` / `_flash` / `_gemma` / `_pro` stay comma lists and still win outright, but their entries may carry a prefix: `anthropic:claude-sonnet-5-5,gemini-3.5-flash-lite` is Claude first, Gemini fallback. That is the whole "mixed household" story; no new setting for it.

**Keys.** `api_key_for(model_id, pool, settings)` is the precise helper: Gemini, the paid key for pro and cu and the free key otherwise, exactly as today (the source-pin test that keeps every paid-key read inside `model_pools` still holds); Claude, `llm_anthropic_api_key`; OpenAI, `llm_openai_api_key`. One key per provider; the pro/cu distinction is a Gemini free-tier artefact. **`api_key_for_pool(pool, settings)` keeps its signature** and returns the key for the pool's first model under the selected table, so its ten live callers (`missions.py` launch and research, `agent_tools_v2.py`, `browse.py`, `paid_fallback.py`, `web.py`, `house_facade.py`) keep working unchanged; it is the one place they already go for a key.

**One credentials helper replaces the fifteen "no Gemini key" preflights.** `planner_intake.py:123`, `email_ingest.py` (four reads), `house_facade.py` (two), `mind.py` (five), `meals.py`, `threads.py` and `main.py:7901` each read `llm_gemini_api_key` straight from settings and fail before reaching the pool. They become `model_pools.credentials(tier, settings) -> (model_id, api_key)`, and the "is the AI set up at all" checks become `model_pools.has_credentials(settings)`: true when the selected provider's key is present. Intake's usage and readiness reads (`email_ingest.py:193`, `:1046`, `mind.py:1056`) hash the same resolved key, so a household on Claude sees and caps its own account, not an empty Gemini one.

**`resolve_model` / `models_for`** are unchanged in signature; they return prefixed ids when the chosen table is not Gemini. `is_gemma` is false for any prefixed id. The phone-voice branch of `models_for` (today: lite entries containing `flash-lite`) becomes "the provider's lite pool", so a voice turn on Claude runs on Haiku and on OpenAI runs on Luna. The matching guard at the top of `_call_llm_json` (today: `provider != 'gemini' or 'flash-lite' not in model`) becomes "the model is in the provider's lite pool".

### 2. Two new wire branches in `services/llm.py`

`_call_llm_json(provider, url, api_key, model, ...)` gains `provider == 'anthropic'` and `provider == 'openai'`. Same style as the two branches it joins: `urllib`, JSON, `llm_budget.urlopen`, no SDK. A new thin entry `llm.call_model(model_id, api_key, ...)` splits the prefix and dispatches, so pool code never spells a provider string; `_call_candidates`, `call_gemma_with_fallback` and the surviving direct call sites use it. It takes `text=True` for the one caller that wants prose, not JSON: `auto_name_conversation` asks for a plain title and today reads the raw Gemini text itself; through the JSON extractor a title like "Dishwasher repair appointment" would raise and be swallowed, leaving the conversation unnamed. With `text=True` the branch returns `{'text': ...}` and skips the extractor.

**Claude** — `POST https://api.anthropic.com/v1/messages`, headers `x-api-key`, `anthropic-version: 2023-06-01`, `content-type: application/json`.
- `system` is the top-level field (always; the Gemma concatenation trick is Gemini-only). `messages` is one user turn whose content is `[{"type":"text","text":user_prompt}]` plus one `{"type":"image","source":{"type":"base64","media_type":mime,"data":b64}}` per image.
- **No `temperature`**: Sonnet 5.5 and Haiku 5.5 return 400 for non-default sampling. The parameter is accepted by the function and dropped for this provider.
- **No `thinking` field** (adaptive is the default on the 5.5 family and the only accepted shape). `thinking_level` maps to `output_config.effort`: low → `low`, medium → `medium`, high → `high`; `None` → `low` for lite and flash models (chat and extraction are the workloads where `low` holds) and `medium` for the pro pool (a mission's reasoning is the point of paying for Opus). The same two defaults apply to OpenAI's `reasoning.effort`.
- `max_tokens` = `max_output_tokens` when given, else 8192.
- `response_schema` → `output_config.format = {"type":"json_schema","schema":schema}`. `strict_json` without a schema keeps the prompt's own JSON instruction and the existing extractor; there is no bare JSON mode on this API.
- Response: text is the concatenation of `text` blocks; `thinking` blocks are ignored. `stop_reason == "refusal"` → `{"error": "refused: <stop_details.category>"}` (not transient). `stop_reason == "max_tokens"` with `strict_json` → the same "incomplete JSON" RuntimeError the Gemini branch raises. `usage.input_tokens` / `output_tokens` go into `metrics` as `promptTokenCount` / `candidatesTokenCount` so every existing reader of metrics keeps working; `metrics['modelVersion']` = the bare id.
- HTTP 429 → `{"error": "429 ..."}` as today; other HTTPError → RuntimeError with the body, as today.
- Not sent: the `fallbacks` parameter (server-side refusal fallback). A refused extraction is an error the pool reports, the same as any other; adding a second model inside one call would hide which model answered. Easy to add later if refusals turn out to matter.

**OpenAI** — `POST https://api.openai.com/v1/responses`, header `Authorization: Bearer <key>`.
- `instructions` = system prompt. `input` = one user item with `[{"type":"input_text","text":...}]` plus `{"type":"input_image","image_url":"data:<mime>;base64,<b64>","detail":"auto"}` per image.
- `reasoning.effort` from `thinking_level` with the same map, `None` → `low`. `gpt-6.1-sol` does not accept `none` or `minimal`; the map never produces them. No `temperature` (reasoning models reject it).
- `max_output_tokens` when given, else 8192.
- `response_schema` → `text.format = {"type":"json_schema","name":"result","schema":schema,"strict":false}` (the app's schemas are not all strict-shaped: optional fields, no `additionalProperties:false`). `strict_json` without a schema → `text.format = {"type":"json_object"}`.
- Response: the first `message` output item's `output_text` content joined; `status == "incomplete"` with `strict_json` → the incomplete-JSON RuntimeError; `usage.input_tokens` / `output_tokens` → metrics as above.
- 429 and other errors as for Claude.

**`test_llm_connection`** gains both providers and costs no tokens: `GET https://api.anthropic.com/v1/models` (header `x-api-key`) and `GET https://api.openai.com/v1/models` (bearer). Success says how many models the key lists and whether the table's ids are among them; a table id the key cannot see is reported in the message, loudly.

**Ollama** is untouched.

### 3. Admission and spend: `services/llm_budget.py`

`urlopen` meters three hosts. The model id comes from the request body (`model` field) for the two new hosts, from the URL for Gemini, and is recorded in prefixed form. `_limit` returns `None` for any prefixed id: paid providers publish no free daily allowance and the app never guesses one. Pauses work as today: a 429 pauses the model for two minutes (never until midnight — there is no daily free quota to wait for), a 404 for six hours, a 5xx in background pauses the workflow. `model_pools.note_failure` mirrors this: the "per day" text match that cools a Gemini model until midnight Pacific applies only to bare ids.

**A per-provider daily request cap**, because every Claude and OpenAI call is billed and a background workflow that loops is a bill. Settings `llm_anthropic_daily_cap` and `llm_openai_daily_cap`, default 500 requests per local day, counted in `_reserve` over `attempts` rows whose model carries that prefix (failed attempts included, as the paid fallback counts them). The count is over `started >= the household's last local midnight`, not over the `day` label: that label is Pacific by design (Gemini's quotas reset there) and a New York household would otherwise stay capped past its own midnight. Reaching the cap raises `Deferred(..., scope='allowance')` until the next local midnight, so a foreground call fails with the same honest "allowance used up" message the Gemini flash cap produces and background work defers. `0` means no cap. Gemini's Pacific accounting is untouched.

**The Gemini paid fallback stays Gemini-only.** `with_paid_fallback` returns `call_chain(api_key, False)` unchanged whenever the tier's first candidate is a prefixed id. Its three settings and the parent DM keep working for households on Gemini; on Claude or OpenAI there is nothing to fall over to, and the cap above is the guard.

The `_account(key)` hash and the attempts table need no schema change; the model column simply holds prefixed ids.

### 4. Settings and the Config page

**Where they live.** The AI group's owning page is Config › AI: every `ai` entry in the registry already points there (`page=_CONFIG`), and that is where the Gemini key, the paid-fallback controls and the Ollama fields are. The "never `config.html`" rule exists so that a feature's settings go on the feature's page; for the model provider that page is this tab. This is stated as the explicit exception the build relies on, not an oversight.

New registry entries, group `ai`, page `config`, anchor `general`, each with a control in the AI section of `config.html` (so the reachability audit passes) **and a typed field with a default on `Settings` in `models/schemas.py`** (`/api/settings` serializes that model and silently drops any key it does not declare; a key that only the page knows would test green and never save):

- `llm_anthropic_api_key`, `llm_openai_api_key` — "Claude API key", "OpenAI API key", `Optional[str] = None`.
- `llm_anthropic_daily_cap`, `llm_openai_daily_cap` — "Claude requests per day", "OpenAI requests per day", `int = 500`, 0 for none.
- `model_pool_lite`, `model_pool_flash`, `model_pool_gemma` — today these are unregistered escape hatches that `_pool` reads but no field declares and no control shows, so "chat on Claude, background on Gemini" could not be entered anywhere. They become registered (`Optional[str] = ''`, like `model_pool_pro`) with three text fields under an "Advanced: model pools" row on the same tab, help text: comma-separated ids, an entry may be `anthropic:<id>` or `openai:<id>`, blank means the selected provider's default.

`llm_provider` keeps its key; its help text and the selector gain the two options (`gemini` | `anthropic` | `openai` | `ollama`). The page shows only the chosen provider's key field and cap, plus the existing Gemini model dropdown only under Gemini and the Ollama fields only under Ollama. The Test connection button posts the chosen provider and its key. The paid-fallback controls stay visible only under Gemini. `python tools/build_tailwind.py` after the template change. A TestClient round trip (save through `/api/settings`, read back) covers every new field.

No migration: stored `llm_provider` values are a subset of the new set, stored pool overrides are bare Gemini ids and stay valid.

### 5. The dead `llm_provider` readers come alive

The trip planner's six sites already go through `model_pools.pooled_or_direct`, which sends Gemini through the tier's pool chain (retries, cooldowns, fallback) and Ollama to its one model. That helper becomes provider-aware: anything that is not Ollama goes through `call_pool_json` on the selected table, so a transient failure on the first Claude or OpenAI candidate still tries the next one exactly as Gemini does today. Rule deduction in `main.py` (which calls `_call_llm_json` directly with `llm_gemini_model`) moves onto the same helper on the `heavy` tier. `auto_name_conversation` uses `call_model(..., text=True)` on the `interactive` tier's first model. `llm_gemini_model` stays as the trip planner's Gemini override exactly where it is read today.

### 6. Web research on the chosen provider (`services/web.py`)

`research()`'s "with the model" route dispatches on the provider of `resolve_model('heavy')`. The Ollama refusal text stays for Ollama. Two new grounded calls beside `_gemini_grounded`, same contract (`{'answer','sources':[{'title','url'}],'suggestions_html'}` or `{'error'}`), both through `llm_budget.urlopen`:

- `_anthropic_grounded(question, key, model)` — Messages API with `tools: [{"type":"web_search_20260209","name":"web_search","max_uses":3}]` on the flash-pool model (Sonnet; Haiku 5.5 is not in the list of models the `_20260209` tool runs on). Answer = the text blocks; sources = each text block's `citations[].url/title` plus each `web_search_tool_result` block's `content[].url/title`, deduplicated in order. Server-tool errors arrive as HTTP 200 with an error object in place of the result list; that is `{'error': error_code}`.
- `_openai_grounded(question, key, model)` — Responses API with `tools: [{"type":"web_search","search_context_size":"low"}]` and `include: ["web_search_call.action.sources"]`. Answer = the message item's text; sources = its `annotations[]` of type `url_citation` (`url`, `title`), then the consulted sources list.
- `suggestions_html` is empty for both (the search-suggestions chip is Google's display requirement for grounding).
- A mission's own key (`own_key`) is the provider's single key for Claude and OpenAI; the "flash by name, paid project" special case is Gemini-only.
- The monthly research cap and the cache apply as today. The `web_research_via` help text no longer says Gemini searches Google "itself" without naming the others: "Your main AI model searches the web itself (Gemini, Claude and OpenAI all can)".

### 7. Browse missions on the chosen provider (`services/browse.py`)

`_model_step` dispatches on the provider of the cu pool's first model: `_model_step_live` (Gemini, unchanged) or one of two new steps. The runner, its 25 device-found guards, the neutral `contents` list, submit gate, release flow, screenshots, caps and report are untouched; an adapter only translates between the neutral list and a provider's wire, and hands back `{'calls':[{'name','args'}], 'text', 'content', 'tokens'}` in the runner's own action vocabulary with **permille coordinates** (the runner's `_px` divides by 1000; both new providers speak screenshot pixels of the 1440×900 viewport, so the adapter multiplies by 1000/W and 1000/H on the way in).

Neutral entries the adapters must read: `{'role':'user','parts':[{'text'},{'image':png}]}` and `{'function_responses':[(name, response, shot), ...]}`; the entry an adapter appends as `content` is its own provider's assistant turn and is replayed as-is.

**Claude** — `tools: [{"type":"computer_toolset_20260801","configs":{"zoom":{"enabled":false}}}, navigate, go_back]` where `navigate(url)` and `go_back()` are ordinary function tools (the toolset has no address bar; the runner's domain gate already governs `navigate`). Member → runner action: `left_click`→`click_at`, `double_click`→`double_click_at`, `type`→`type` (the runner's coordinate-free type), `key`→`key_combination` (keys split on `+`), `scroll`→`scroll_at` (`scroll_direction`, `scroll_amount` × 100 px), `mouse_move`→`hover_at`, `left_click_drag`→`drag_and_drop`, `wait`→`wait`, `screenshot`→ no action, a fresh screenshot in the result. Any other member (`right_click`, `middle_click`, `triple_click`, `hold_key`, `left_mouse_down/up`, `cursor_position`) is answered with a tool_result saying it is not available here; the model is told so in the system text. Results: one `tool_result` per `tool_use` by id, every one carrying `"toolset_name":"computer"`, the screenshot as an image block for `screenshot` and for every action (the runner already takes one after each act), `OK` otherwise. Thinking stays adaptive with `output_config.effort: "low"`; the model's whole assistant content (thinking blocks included) is replayed unchanged, and the adapter never prunes earlier screenshots (doing so invalidates later thinking blocks). Tokens from `usage`.

**OpenAI** — `tools: [{"type":"computer"}, navigate, go_back]` on `gpt-6.1-sol`, `reasoning.effort: "low"`, `truncation: "auto"`. The adapter keeps `previous_response_id` inside its appended `content` entry and sends only the new input items each turn. A `computer_call` item's `actions[]` map: `click`→`click_at` (`button` other than left answered as unavailable), `double_click`, `type`→`type`, `keypress`→`key_combination`, `scroll`→`scroll_at` (`scroll_x/scroll_y` → direction and magnitude), `move`→`hover_at`, `drag`→`drag_and_drop` (first and last path points), `wait`→`wait`, `screenshot`→ none. Each handled call is answered with `computer_call_output` whose `output` is `{"type":"computer_screenshot","image_url":"data:image/png;base64,...","detail":"original"}`; the function tools with `function_call_output`. Pending safety checks, if the API returns any, are acknowledged only when the runner's own gates allowed the action (the runner is the authority; the adapter never acknowledges on its own).

The system text (`RUNNER_SYSTEM`) is shared. Its Gemini-specific sentence about `type_text_at` is kept for Gemini and swapped for a provider-neutral line ("type into the focused box; click it first") in the two adapters.

**Five runner changes the adapters need, all provider-neutral and all kept for Gemini:**

1. **Coordinate-free typing meets the release rule.** Today the field-label check (`_field_at`, "the page's email box wants the family's email; nothing was typed") runs only when the type action carries `x`/`y`; `_personal_violation` catches a released value but cannot recognise an invented one against an empty card. Both new providers type into the focused box without coordinates, so a click on a postal-code box followed by `type 35203` would run with nothing released. The runner reads the **focused field's label** for a coordinate-free type (the same `_field_at` policy on `document.activeElement`) and applies the same gate. The empty-card scenario runs through both adapters in the tests.
2. **An observation turn is not completion.** The runner finishes whenever a step returns no `calls`. A Claude `screenshot` member, or a turn made only of members the adapter refuses, must instead be answered: a step may return `calls=[]` with `replies=[(name, response), ...]`; the runner appends the `function_responses` entry with those replies and a fresh screenshot of the current page, executes nothing, and continues. Three such turns in a row end the run as `capped` ("the model kept looking without acting"), so an idle model cannot spend the turn cap for nothing.
3. **Each result carries its own screenshot and URL.** The tuple list `results` is turned into `function_responses` with the final `shot` and `page.url` stamped on every entry, and each action's screenshot overwrites the same `turn_NN.png`. Two actions in one turn that both change the screen therefore show the model one picture twice. The runner captures `(url, shot)` right after each action into its tuple, and names the file `turn_NN_i.png`. Gemini gets the more accurate replay too.
4. **Refusals and errors reach the model.** The runner already answers a repeated action, a forbidden navigation, an action after the press, a typing refusal and an execution failure with `{'error': ...}` in the response; the adapters pass that response's text (error or `url`) into the provider's tool result beside the image, keyed by the originating `tool_use_id` / `call_id`, so "the press is done; report what the page says" arrives where it did under Gemini. A refused action followed by a corrective turn is a test.
5. **Challenge consent and the attempt cap.** Gemini marks a challenge click with `safety_decision.decision == 'require_confirmation'`, which the runner uses for the CAPTCHA consent gate and the three-attempt cap (`_has_captcha` deliberately ignores ordinary in-page widgets). Neither new provider sends such metadata. The adapters' system text tells the model to write a `CHALLENGE:` line before any click on a verification widget; the adapter turns that line into the same `safety_decision` on the call, so the existing gate and cap run unchanged. A click on a widget with no `CHALLENGE:` line is the model's own misreport, the same exposure Gemini has today, and the page-level interstitial check still catches the hard cases. Consent-off and capped-challenge scenarios run through both adapters.

### 8. What stays Gemini-only, by design

- Gemma discovery, the per-day/per-minute 429 split, the midnight-Pacific reset, the flash background allowance and the paid "ask a parent" fallback: free-tier machinery, inert on paid providers.
- The Google search-suggestions chip.
- `llm_gemini_model` (trip planner override) and `llm_gemini_paid_api_key`.

### 9. Cost, stated once

Prices per million tokens, standard tier, as read on 2026-10-13 (Claude from the API skill table, OpenAI from its pricing page):

| role | Claude | OpenAI |
|---|---|---|
| lite (chat, background) | haiku-5-5 $0.10 / $0.50 | gpt-6-luna $0.10 / $0.50 |
| flash (heavy, mind, vision, browse, research) | sonnet-5-5 $2 / $10 | gpt-6.1-sol $2 / $10 |
| pro (missions) | opus-5-5 $4 / $20 | gpt-6.1-sol $2 / $10 |

Web search on OpenAI is also billed per call ($10 per 1,000). The 500-a-day default cap exists so a wedged workflow costs dollars, not hundreds. Before a household flips, a day's attempt count from the `llm_budget` attempts table on the device is the sizing number.

## Testing

Tests are written first (Claude) and the implementation is built against them (split below). All run as plain scripts from `chauffeur/` with `HA_BASE_URL` unset; every critical path has one test that runs it, not one that greps it.

- `tests/test_llm_providers.py` — a fake `llm_budget.urlopen` keyed by host records bodies and returns canned responses. Claude: top-level `system`, no `temperature`, no `thinking`, effort map, image block, `output_config.format` from a schema, text joined across blocks, refusal → error, `max_tokens` + strict → RuntimeError, 429 → error dict, metrics mapped. OpenAI: `instructions`, `input_text`/`input_image`, `reasoning.effort`, `text.format` json_schema (strict false) and json_object, `incomplete` + strict → RuntimeError, usage mapped. `test_llm_connection` for both via the models listing, including the "table id not in the key's list" message. `call_model` dispatch and `split_model`.
- `tests/test_model_pool_providers.py` — the three tables produce the expected chains per tier; empty Gemma contributes nothing; prefixed overrides mix and win; `api_key_for` routing per provider (and the paid-key source pin still holds); `is_gemma` false on prefixed ids; the phone-voice branch yields the provider's lite pool; `with_paid_fallback` is a pass-through when the first candidate is prefixed; a 429 with "per day" text cools a prefixed id two minutes, not until midnight; `_call_candidates` sends the prefixed id to `call_model` and records it in `attempts`.
- `tests/test_llm_budget.py` gains scenarios: the two hosts are metered with the model read from the body; `_limit` is None for prefixed ids; the per-provider daily cap defers with scope `allowance` until local midnight, counts failures, and `0` disables it; Gemini metering is byte-for-byte as before.
- `tests/test_web_research.py` gains: dispatch by provider; canned Claude and OpenAI grounded responses parse to the same `sources` contract; a server-tool error object → `{'error'}`; Ollama still gets the "can't search" message; the suggestions chip is empty off Gemini.
- `tests/test_browse_runner.py` gains: each adapter turns a canned provider turn into runner calls with permille coordinates and the right names; unsupported members are answered, not executed; results echo `toolset_name` (Claude) / `computer_call_output` with a screenshot (OpenAI); `navigate` arrives as a function tool; the neutral `function_responses` entry becomes the provider's user turn; `_model_step` dispatches on the cu pool's provider. The existing runner scenarios still pass with the Gemini fake step.
- `tests/test_settings_registry.py` — the seven new keys are reachable on the Config page (existing audit).
- A TestClient scenario: `GET /config` renders the four selector options; `POST /api/settings/test_llm` with `provider: anthropic` reaches the Claude branch; every new field survives a save and read through `/api/settings`.
- `tests/test_browse_runner.py` also covers the five runner changes with the Gemini fake step: the focused-field gate on coordinate-free typing with an empty card, an observation turn that continues and the third that caps, per-action screenshots and URLs in `function_responses`, a refusal text reaching the next turn, and a `CHALLENGE:`-marked click meeting the consent gate.
- The keyless-preflight entry points (intake photo, house analysis, a Mind action, meal extraction, thread photo) each run once with only the Claude key present and reach the pool dispatch.
- `auto_name_conversation` stores a plain title on Claude and OpenAI.
- `tests/test_agent_llm_errors.py`, `test_model_pool_overload.py`, `test_missions_pools.py`, `test_trip_planner*.py` (the sites rerouted in §5) are the named neighbours for the gate.

Device verification afterwards, in this order: Test connection on each key; one chat turn per provider; one research question per provider (sources visible); the dishwasher browse mission on Claude (`nothing booked`, as the submit-gate arc requires), then on OpenAI.

## Build split (the standing coordination rule)

- **Codex first**: adversarial review of this spec against the code and the locked rules (every arc file this touches: browse missions, agent-reads-the-owning-module, watcher policy). Findings are resolved in the spec before any code.
- **Claude**: the test files above, then `model_pools` (tables, `split_model`, `api_key_for`, voice branch, cooldown rule, paid-fallback pass-through), `settings_registry` + `config.html` + Tailwind, the §5 reroutes, `system_capabilities.md`, the bump and the commits.
- **Codex** (via `/codex:rescue`, against Claude's tests): the two wire branches and `test_llm_connection` in `llm.py`, host metering and the per-provider cap in `llm_budget.py`, the two grounded calls in `web.py`, the two browse adapters.
- **Codex** reviews Claude's diff; Claude reviews Codex's. Review gate stays off.

## Review resolutions

Codex's adversarial review, 2026-10-13, fourteen findings, all confirmed against the code:

1. The new keys and caps would not persist (`Settings` in `models/schemas.py` drops undeclared keys) → §4 adds typed fields and a round-trip test.
2. Coordinate-free typing bypassed the release rule → §7 runner change 1.
3. Fifteen Gemini-only key preflights would fail a Claude household before the pool → §1 `credentials` / `has_credentials`.
4. Renaming `api_key_for_pool` orphaned ten callers → §1 keeps it, provider-aware, beside the precise helper.
5. Screenshot-only or refused-only turns read as completion → §7 runner change 2.
6. No challenge-consent metadata off Gemini → §7 runner change 5.
7. One final screenshot and URL stamped on every result → §7 runner change 3.
8. Refusal and execution errors lost in translation → §7 runner change 4.
9. The trip-planner reroute dropped the pool chain → §5 makes `pooled_or_direct` provider-aware instead.
10. Conversation naming cannot go through the JSON extractor → §2 `text=True`.
11. A local-day cap counted on Pacific day labels → §3 counts over `started` from local midnight.
12. Intake usage and Mind readiness hashed the Gemini key → §1 routes them through the same credentials.
13. The lite/flash/gemma pool overrides had no field or control → §4 registers them.
14. Adding settings to `config.html` conflicts with the placement rule → §4 states the exception (the AI group's owning page is this tab) for the owner to confirm.

## Out of scope

- Image generation (the app generates none today; Claude offers none).
- Cross-provider fallback inside one call (a Claude failure trying Gemini). Overrides can express it; the default tables do not.
- Streaming, prompt caching, batch APIs. The app's calls are single-shot JSON; caching is a later cost lever.
- Moving the AI settings off `config.html`. That page's AI tab is the AI settings page today.
