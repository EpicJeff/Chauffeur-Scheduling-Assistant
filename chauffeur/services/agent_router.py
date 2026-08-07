import json
import logging
from typing import Dict, Any, Optional, List

from services.agent_tools_v2 import (
    get_available_tools,
    get_bridged_v1_tools,
    BRIDGED_V1_TOOLS,
    SCHEDULE_MUTATING_V1_TOOLS,
    get_calendar_events,
    assign_driver_to_event_fuzzy,
    add_trip_poi,
    clear_trip_itinerary,
    auto_schedule_trip_itinerary
)
from services.llm import _call_llm_json

logger = logging.getLogger(__name__)

class RateLimitException(Exception):
    pass

def call_gemma_with_fallback(prompt: str, tools: list, system_prompt: str) -> Dict[str, Any]:
    """
    Interactive agent LLM call over the free-tier model pools (see
    services/model_pools.py): flash-lite pool first (answers in seconds,
    ~1,000 requests/day pooled), overflowing into the gemma pool (slow but
    ~28,800/day). The scarce 20/day gemini-*-flash models are reserved for the
    heavy tier and never burned on chat turns. 429s put a model on cooldown so
    the next turn skips straight to one with quota left. Pools are
    overridable via the model_pool_lite / model_pool_gemma settings keys.
    """
    from services.storage import get_settings
    from services import model_pools
    settings = get_settings()
    api_key = settings.get('llm_gemini_api_key', '')
    provider = 'gemini'
    url = ''

    import json
    # Inject tools into system prompt because Gemma on Gemini API doesn't support native tool calling payload
    system_prompt += "\n\nYou MUST respond ONLY in valid JSON. Your JSON must match this exact structure:\n"
    system_prompt += "{\n"
    system_prompt += '  "message": "A concise, helpful message about what you did.",\n'
    system_prompt += '  "tool_calls": [\n'
    system_prompt += '    {\n'
    system_prompt += '      "name": "tool_name",\n'
    system_prompt += '      "arguments": {"arg1": "value"}\n'
    system_prompt += '    }\n'
    system_prompt += '  ]\n'
    system_prompt += "}\n\n"
    system_prompt += "AVAILABLE TOOLS:\n"
    system_prompt += json.dumps(tools, indent=2)
    system_prompt += "\n\nIf you do not need to call a tool, return an empty list for tool_calls."
    
    def _is_transient(err_str: str) -> bool:
        return any(code in err_str for code in ("429", "500", "502", "503", "504"))

    last_err = "no models available"
    transient = False
    # Cap at 4 candidates: lite models fail a 429 in ~1s, so a fully-exhausted
    # lite pool still reaches gemma well inside HA Assist's 120s budget.
    for model in model_pools.models_for('interactive', settings)[:4]:
        # 60s cap on the fast models: slower than that is already useless to
        # the 120s HA pipeline. Gemma gets 90s — it measured 44-180s and is
        # the last resort, so give it what remains of the budget.
        timeout_s = 90 if model_pools.is_gemma(model) else 60
        try:
            res = _call_llm_json(provider, url, api_key, model, system_prompt, prompt, tools=None, timeout_s=timeout_s)
        except Exception as e:
            last_err = str(e)
            model_pools.note_failure(model, last_err)
            # 5xx = overloaded right now (the call layer already retried with
            # backoff) — the next pool model may still work.
            if not _is_transient(last_err):
                logger.error(f"Error calling agent LLM ({model}): {e}")
                return {"error": last_err}
            transient = True
            logger.warning(f"{model} unavailable ({e}), trying next pool model...")
            continue
        if res.get("error") and "429" in str(res.get("error")):
            last_err = str(res["error"])
            model_pools.note_failure(model, last_err)
            transient = True
            logger.warning(f"{model} rate limited, trying next pool model...")
            continue
        res["_model"] = model
        return res
    logger.error(f"All agent pool models failed; last error: {last_err}")
    return {"error": last_err, "transient": transient}

def _is_admin_member(member) -> bool:
    """Parents/adults may drive the scheduling-core (bridge) tools; children and
    helpers may not. Used to scope @argyle in the family chat by who is asking."""
    return bool(member) and member.get('role') in ('parent', 'adult')


def process_agent_request(user_prompt: str, context: Optional[Dict] = None, history: Optional[List[Dict]] = None,
                          source: str = "admin", driver_id: Optional[str] = None,
                          acting_member: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Main entrypoint for the Agent Orchestrator.
    Decides whether to route to Gemma (tools) or Gemini (heavy lifting).
    source/driver_id come from the chat payload: the PWA sends source='pwa'
    plus the logged-in driver's id, which switches on driver context.
    acting_member (the resolved family member) is set for @argyle in the family
    chat: it supplies a known identity for 'me'/from_member resolution and gates
    the admin scheduling tools to parents/adults.
    """
    # Resolve driver context (PWA chat only). The driver must actually exist —
    # a stale localStorage id must not grant driver tools acting on nobody.
    driver = None
    if source == "pwa" and driver_id:
        from services.storage import get_all_drivers
        driver = next((d for d in get_all_drivers() if d.get("id") == driver_id), None)

    system_prompt = f"""You are Argyle, an intelligent family assistant.
You help manage schedules, trips, and errands.
You MUST use your provided tools to fetch data or perform actions.
Respond with a concise, helpful message about what you did.

CRITICAL INSTRUCTIONS FOR TRIP PLANNING:
1. If the user asks you to *generate* or *plan* a massive 10-day trip (e.g. "plan my trip to France"), you must output `{{"delegate_to_gemini": true}}` so the heavy lifter can generate the initial ideas.
2. If the user asks you to "add my attractions to the itinerary" or "schedule the attractions", DO NOT delegate! This means they want you to take the ALREADY SAVED attractions (listed in your context) and place them onto the calendar itinerary. You MUST use the `auto_schedule_trip_itinerary` tool to instantly bulk-schedule all of them into the timeline based on their distances and opening hours.
3. If the user asks to add, suggest, or find flights and did NOT give specific flight details, you MUST immediately call `manage_trip_flights` with action 'generate'. NEVER reply asking for flight numbers, times, dates, or airports — the system already knows the home location, destination, and trip dates and will add editable estimates. Ignore any earlier assistant messages in the history that asked for flight details; they were wrong.
"""
    import datetime as _dt
    _now = _dt.datetime.now().astimezone()
    system_prompt += (f"\nCURRENT DATE & TIME: {_now.strftime('%A, %Y-%m-%d %H:%M')} ({_now.tzname() or 'local time'}).\n"
                      "Resolve relative dates ('today', 'tonight', 'tomorrow', weekday names) against this "
                      "before calling tools, and pass tool dates as YYYY-MM-DD.\n")

    if not driver:
        if acting_member is not None:
            _nm = acting_member.get('name') or 'this family member'
            _role = acting_member.get('role') or 'adult'
            system_prompt += (f"\nYou are speaking with {_nm} (role: {_role}) in the family chat. "
                              f"Resolve 'me', 'my', 'I', and 'mine' to {_nm}. For messaging and chore tools, "
                              f"pass from_member/member_name as \"{_nm}\" automatically — never ask who is "
                              f"speaking, you already know.\n"
                              "When the request would CHANGE the schedule (reassign a driver, mark someone "
                              "unavailable, add/remove a routing or priority rule, or add an errand), call "
                              "propose_family_action with a clear one-sentence summary instead of doing it "
                              "silently — a parent approves it with one tap. Answer questions, read the "
                              "schedule, send messages, and claim chores directly.\n")
            if not _is_admin_member(acting_member):
                system_prompt += ("This person is NOT a parent/admin: answer questions, send their messages, and "
                                  "manage their own chores, but you cannot change global scheduling (routing/priority "
                                  "rules, the solver, or errands) — those tools are not available to them.\n")
            if (acting_member.get('role') or '') == 'child':
                system_prompt += (
                    "SPEAKING WITH A CHILD — they are often the FIRST to know about logistics changes, "
                    "so treat their reports as valuable. When they report schedule information (practice "
                    "moved or cancelled, a new event, needing money or supplies by a date, a ride "
                    "arrangement they heard about), call propose_family_action so a parent can approve "
                    "it with one tap — create_event for new events and date-bound needs, add_errand for "
                    "things to buy, reassign_driver/clear_assignment for driver facts — and in your reply "
                    "tell them you've flagged it for their parents. Ask at most ONE short clarifying "
                    "question; if they don't know, propose with what you have and note the gap in the "
                    "summary. Be warm, brief, and reassuring. Never lecture, never guilt-trip about "
                    "chores, points, or streaks. You never change the schedule directly for a child — "
                    "always the proposal card.\n"
                    "SCHOOL LIST: they manage their OWN school/deadline list directly with "
                    "add_kid_task / complete_kid_task / get_kid_tasks (homework, tests, projects, "
                    "things to bring) — no approval needed, it's their list. For a big project weeks "
                    "away, OFFER to break it into a few smaller tasks with staggered due dates, and "
                    "add them only if they say yes. Never nag about overdue tasks — mention them only "
                    "when asked.\n"
                    "SHOPPING LIST: if they mention the family is out of something ('we're out of "
                    "cereal', 'we need more shampoo'), add it with add_shopping_items right away and "
                    "tell them it's on the list. No approval needed and no parent required — noticing "
                    "is genuinely useful and it costs nothing.\n")
        else:
            system_prompt += ("\nFAMILY MESSAGING & CHORES: you can send family/direct messages and claim chores, "
                              "but you do NOT know who is speaking in this context. If the speaker has identified "
                              "themselves (or the request implies it: 'tell Mom Dad is on his way' -> from Dad), pass "
                              "from_member/member_name. Otherwise ask who it is BEFORE sending or claiming — never guess.\n")

    if driver:
        system_prompt += f"""
DRIVER MODE (PWA):
You are speaking directly to {driver.get('name')}, a family driver, on their phone while on the go.
Be brief, warm, and plain-spoken — no technical jargon, short sentences, mobile-friendly replies.
Their drives for TODAY are listed below; use get_my_route for other days.
When they say they are leaving or heading out, call start_route. When they say they picked up,
dropped off, arrived, or finished, call complete_route with the matching action.
Never ask them which driver they are — you already know.
Messages and chore claims act as {driver.get('name')} automatically — never ask who is
sending or claiming, and never pass from_member/member_name for them.
"""
        try:
            from services.agent_tools_v2 import get_my_route
            today = get_my_route(driver_id)
            evs = today.get("events", [])
            if evs:
                system_prompt += "\nYOUR DRIVES TODAY:\n"
                for ev in evs:
                    system_prompt += (f"- {ev.get('title')} at {ev.get('location') or 'no location'} "
                                      f"({ev.get('start', '')[11:16]}-{ev.get('end', '')[11:16]}) "
                                      f"[{ev.get('drive_status')}]\n")
            else:
                system_prompt += "\nYOUR DRIVES TODAY: none assigned.\n"
        except Exception as e:
            logger.warning(f"Could not inject driver schedule: {e}")

    if history:
        system_prompt += "\n\nCONVERSATION HISTORY:\n"
        # Take last 5 turns to keep context window small
        for msg in history[-5:]:
            system_prompt += f"{msg.get('role').upper()}: {msg.get('content')}\n"
            
    if context:
        system_prompt += f"\n\nUSER CONTEXT:\n{json.dumps(context)}\n"
        trip_id = None
        import urllib.parse
        if "search" in context and "event_id=" in context["search"]:
            qs = urllib.parse.parse_qs(context["search"].lstrip("?"))
            if "event_id" in qs:
                trip_id = qs["event_id"][0]
        elif "pathname" in context and "/trip/" in context["pathname"]:
            trip_id = context["pathname"].split("/trip/")[-1].split("/")[0]
            
        if trip_id:
            system_prompt += f"The current active trip_id is: {trip_id}\n"
            from services.storage import get_trip_metadata
            meta = get_trip_metadata(trip_id)
            if meta:
                pois = meta.get("pois", [])
                accs = meta.get("accommodations", [])
                if pois:
                    system_prompt += "Currently Saved Attractions/POIs for this trip:\n"
                    for p in pois:
                        system_prompt += f"- {p.get('name')} (Duration: {p.get('duration_mins')}m, Valid Days: {p.get('valid_days_of_week')})\n"
                if accs:
                    system_prompt += "Currently Saved Accommodations for this trip:\n"
                    for a in accs:
                        system_prompt += f"- {a.get('name')} (Check in: {a.get('check_in_date')})\n"
                flights = meta.get("flights", [])
                if flights:
                    # route + id only: draft trips live on mock calendar dates
                    # that must never leak into user-facing replies
                    system_prompt += "Currently Saved Flights for this trip:\n"
                    for f in flights:
                        system_prompt += (f"- {f.get('airline') or 'TBD'} {f.get('flight_number') or ''} "
                                          f"{f.get('origin')} -> {f.get('destination')} (id: {f.get('id')})\n")
                        
    # Bridge (admin scheduling) tools are offered when NOT in driver mode and the
    # asker is authorized: either a legacy call with no acting_member (admin
    # dashboard / HA voice) or an acting_member who is a parent/adult. Children
    # and helpers using @argyle never get them.
    bridge_ok = (not driver) and (acting_member is None or _is_admin_member(acting_member))
    tools = get_available_tools()
    if driver:
        from services.agent_tools_v2 import get_driver_tools
        tools = tools + get_driver_tools()
    elif bridge_ok:
        # Full-parity v1 bridge tools (routing/priority rules, errands, solver,
        # memory, places, deep trip planning).
        tools = tools + get_bridged_v1_tools()

    import time as _time
    request_start = _time.time()
    llm_calls = 0

    # Tools that complete the user's request on their own and return a spoken
    # confirmation. When a round of tool calls consists only of these and they
    # all succeeded, the request is done: skip the concluding LLM round-trip.
    # Timing data showed each Gemma call costs 40-80s, and given the chance the
    # model re-issues the same action instead of concluding (observed writing a
    # duplicate override), so the extra round is both slow and harmful.
    # get_point_balances is a query, but its message is already the complete
    # spoken answer — treating it terminal saves a 40-80s concluding round.
    TERMINAL_ACTION_TOOLS = {"assign_driver_to_event_fuzzy", "remove_override_for_event_fuzzy",
                             "add_trip_poi",
                             "clear_trip_itinerary", "auto_schedule_trip_itinerary",
                             "manage_trip_rules", "manage_trip_flights",
                             "start_route", "complete_route",
                             "adjust_points", "get_point_balances", "reopen_chore",
                             "get_family_goals", "contribute_to_family_goal",
                             # Family-hub tools: sends are actions; the reads
                             # return a message that IS the complete spoken
                             # answer (same reasoning as get_point_balances).
                             "send_family_message", "send_direct_message",
                             "get_family_messages", "list_chores",
                             "claim_chore", "get_routine_status",
                             "post_weekly_digest", "get_drive_digest",
                             "get_kid_tasks", "add_kid_task", "complete_kid_task",
                             # Shopping list (M1): adds/checks are actions, and
                             # the read's message IS the complete spoken answer.
                             "add_shopping_items", "get_shopping_list_items",
                             "check_off_shopping_item", "remove_shopping_item_by_name",
                             # M2/M3: each message IS the complete spoken answer.
                             "get_eating_plan", "suggest_dinner",
                             "add_meal_to_repertoire", "add_meal_ingredients_to_list",
                             "mark_meal_served", "mark_leftovers", "clear_leftovers",
                             "refine_meal_dish", "get_tonights_plate",
                             "change_tonights_plate", "add_dishes",
                             # M6: the week read and its one-shot approval are
                             # both complete spoken answers on their own.
                             "get_week_dinners", "approve_week_dinners",
                             # M7: the trip read and its creation likewise.
                             "get_shopping_trip", "schedule_shopping_trip",
                             # M8: prep-ahead reads and writes are complete on
                             # their own too.
                             "set_dish_prep", "clear_dish_prep", "get_prep_ahead",
                             # M9: pairing reads back as a complete sentence.
                             "pair_dishes", "unpair_dishes",
                             "plan_specific_dinner", "unlock_dinner",
                             # M11: how the household eats.
                             "set_meal_rule", "get_meal_rules"}

    def _is_terminal_success(func_name, res):
        return (func_name in TERMINAL_ACTION_TOOLS and isinstance(res, dict)
                and res.get("status") == "success" and bool(res.get("message")))

    executed_results = {}

    agent_scratchpad = ""
    max_iterations = 3

    target_id = None
    ui_action = None
    target_driver_id = None
    schedule_dirty = False
    card = None
    agent_message = "I have processed your request."
    
    for iteration in range(max_iterations):
        current_system_prompt = system_prompt
        if agent_scratchpad:
            current_system_prompt += "\n\nTOOL EXECUTION SCRATCHPAD:\n" + agent_scratchpad
            
        call_start = _time.time()
        llm_response = call_gemma_with_fallback(user_prompt, tools, current_system_prompt)
        llm_calls += 1
        logger.info(f"[agent-timing] LLM call {llm_calls} ({llm_response.get('_model', 'unknown-model')}) "
                    f"took {_time.time() - call_start:.1f}s")

        # An LLM failure must never masquerade as success ("I have processed
        # your request") — tell the user what actually happened.
        if llm_response.get("error"):
            err = str(llm_response["error"])
            transient = llm_response.get("transient") or any(
                code in err for code in ("429", "500", "502", "503", "504"))
            logger.error(f"Agent LLM call failed (iteration {iteration + 1}): {err}")
            if transient:
                agent_message = ("The AI service is overloaded right now, so I couldn't "
                                 "process your request. Please try again in a minute or two.")
            else:
                agent_message = ("I ran into an error talking to the AI service and couldn't "
                                 "process your request. Please try again — if it keeps "
                                 "happening, check the server logs.")
            if iteration > 0:
                agent_message = ("I completed part of your request, but the AI service "
                                 "failed before I could finish. " + agent_message)
            return {
                "status": "error",
                "message": agent_message,
                "target_element_id": target_id,
                "ui_action": ui_action,
                "target_driver_id": target_driver_id,
                "schedule_dirty": schedule_dirty
            }

        # Check for Delegation to the heavy lifter (flash pool)
        if llm_response.get("delegate_to_gemini"):
            logger.info("Delegating massive trip generation to the heavy-tier flash pool")
            return {
                "status": "delegated", 
                "message": "I'm delegating this massive trip to my heavy lifter module. I'll get to work generating accommodations and points of interest. One moment!",
                "ui_action": "generate_massive_trip"
            }
            
        tool_calls = llm_response.get("tool_calls", [])
        
        # If no tools were called, we are done
        if not tool_calls:
            if llm_response.get("message"):
                agent_message = llm_response["message"]
            break
            
        # We have tool calls, execute them and append to scratchpad
        if llm_response.get("message"):
            agent_scratchpad += f"\nAssistant Message: {llm_response['message']}\n"

        round_all_terminal = True
        for tool_call in tool_calls:
            func_name = tool_call.get("name")
            args = tool_call.get("arguments", {})
            agent_scratchpad += f"\nTool Call: {func_name}({json.dumps(args)})"

            sig = f"{func_name}:{json.dumps(args, sort_keys=True, default=str)}"
            if sig in executed_results:
                # The model repeated an identical call instead of concluding —
                # reuse the result rather than executing (and mutating) twice.
                res = executed_results[sig]
                logger.info(f"[agent-timing] tool {func_name} repeated verbatim — reused previous result")
                agent_scratchpad += f"\nTool Result (already executed, NOT re-run — do not call again): {json.dumps(res)}\n"
                if not _is_terminal_success(func_name, res):
                    round_all_terminal = False
                continue

            res = {"error": f"Unknown tool: {func_name}"}
            tool_start = _time.time()

            try:
                if func_name == "get_calendar_events":
                    res = get_calendar_events(args.get("start_date"), args.get("end_date"))
                elif func_name == "assign_driver_to_event_fuzzy":
                    from services.agent_tools_v2 import assign_driver_to_event_fuzzy
                    res = assign_driver_to_event_fuzzy(args.get("event_name"), args.get("driver_name"), args.get("target_date"))
                    # The override was written straight to storage — the caller
                    # must re-solve or dashboards keep serving the stale cache.
                    if res.get("status") == "success": schedule_dirty = True
                    if res.get("target_element_id"): target_id = res["target_element_id"]
                    if res.get("message"): agent_message = res["message"]
                    if res.get("ui_action"): ui_action = res["ui_action"]
                    if res.get("target_driver_id"): target_driver_id = res["target_driver_id"]
                elif func_name == "remove_override_for_event_fuzzy":
                    from services.agent_tools_v2 import remove_override_for_event_fuzzy
                    res = remove_override_for_event_fuzzy(args.get("event_name"), args.get("target_date"))
                    # target_element_id is only present when an override was
                    # actually deleted — the found-but-no-override case needs
                    # no re-solve.
                    if res.get("status") == "success" and res.get("target_element_id"):
                        schedule_dirty = True
                    if res.get("target_element_id"): target_id = res["target_element_id"]
                    if res.get("message"): agent_message = res["message"]
                    if res.get("ui_action"): ui_action = res["ui_action"]
                elif func_name == "add_trip_poi":
                    res = add_trip_poi(args.get("trip_id"), args.get("title"), args.get("start_time"), args.get("duration_mins"), args.get("location"))
                    if res.get("target_element_id"): target_id = res["target_element_id"]
                    if res.get("message"): agent_message = res["message"]
                    if res.get("status") == "success": ui_action = "sync"
                elif func_name == "clear_trip_itinerary":
                    res = clear_trip_itinerary(args.get("trip_id"), args.get("action", "unlink"))
                    if res.get("target_element_id"): target_id = res["target_element_id"]
                    if res.get("ui_action"): ui_action = res["ui_action"]
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "auto_schedule_trip_itinerary":
                    res = auto_schedule_trip_itinerary(args.get("trip_id"))
                    if res.get("target_element_id"): target_id = res["target_element_id"]
                    if res.get("ui_action"): ui_action = res["ui_action"]
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "manage_trip_rules":
                    from services.agent_tools_v2 import manage_trip_rules
                    res = manage_trip_rules(args.get("trip_id"), args.get("action"),
                                            rule=args.get("rule"), rule_id=args.get("rule_id"))
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "manage_trip_flights":
                    from services.agent_tools_v2 import manage_trip_flights
                    res = manage_trip_flights(args.get("trip_id"), args.get("action"),
                                              prompt=args.get("prompt", ""), flight=args.get("flight"))
                    if res.get("message"): agent_message = res["message"]
                    if res.get("ui_action"): ui_action = res["ui_action"]
                elif func_name == "get_point_balances":
                    from services.agent_tools_v2 import get_point_balances
                    res = get_point_balances()
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "reopen_chore":
                    from services.agent_tools_v2 import reopen_chore
                    res = reopen_chore(args.get("chore_title", ""))
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "get_family_goals":
                    from services.agent_tools_v2 import get_family_goals
                    res = get_family_goals()
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "contribute_to_family_goal":
                    from services.agent_tools_v2 import contribute_to_family_goal
                    res = contribute_to_family_goal(args.get("reward_title", ""),
                                                    args.get("amount"),
                                                    member_name=args.get("member_name"),
                                                    sender_driver_id=driver_id if driver else None)
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "send_family_message":
                    from services.agent_tools_v2 import send_family_message
                    # sender_driver_id: only trusted in PWA driver chat.
                    res = send_family_message(args.get("message_text", ""),
                                              sender_driver_id=driver_id if driver else None,
                                              from_member=args.get("from_member"))
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "send_direct_message":
                    from services.agent_tools_v2 import send_direct_message
                    res = send_direct_message(args.get("recipient_name", ""),
                                              args.get("message_text", ""),
                                              sender_driver_id=driver_id if driver else None,
                                              from_member=args.get("from_member"))
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "get_family_messages":
                    from services.agent_tools_v2 import get_family_messages
                    res = get_family_messages(limit=args.get("limit", 10),
                                              requester_driver_id=driver_id if driver else None)
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "list_chores":
                    from services.agent_tools_v2 import list_chores
                    res = list_chores()
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "claim_chore":
                    from services.agent_tools_v2 import claim_chore
                    res = claim_chore(args.get("chore_title", ""),
                                      member_name=args.get("member_name"),
                                      sender_driver_id=driver_id if driver else None)
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "get_routine_status":
                    from services.agent_tools_v2 import get_routine_status
                    res = get_routine_status(args.get("member_name", ""),
                                             args.get("target_date", "today"))
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "post_weekly_digest":
                    from services.agent_tools_v2 import post_weekly_digest_now
                    # The role gate needs an actor: family chat supplies
                    # acting_member; PWA driver chat resolves the logged-in
                    # driver's member (a HELPER driver must not broadcast);
                    # None (dashboard/HA voice) is the trusted open-admin
                    # context.
                    actor = acting_member
                    if actor is None and driver:
                        from services import storage as _st
                        actor = _st.get_member_by_driver_id(driver_id)
                    res = post_weekly_digest_now(acting_member=actor)
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "get_drive_digest":
                    from services.agent_tools_v2 import get_drive_digest
                    # Driver context with no named member = their own digest;
                    # a named member always wins (a driver may ask about
                    # another driver's day).
                    res = get_drive_digest(
                        target_date=args.get("target_date", "") or "today",
                        member_name=args.get("member_name", "") or "",
                        driver_id=driver_id if (driver and not args.get("member_name")) else None)
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "adjust_points":
                    from services.agent_tools_v2 import adjust_points
                    # by_member_id: only trustworthy in PWA driver chat, where
                    # the logged-in member is resolved server-side.
                    res = adjust_points(args.get("member_name"),
                                        delta=args.get("delta"), set_to=args.get("set_to"),
                                        note=args.get("note", ""),
                                        by_member_id=driver_id if driver else None)
                    if res.get("message"): agent_message = res["message"]
                elif func_name in ("get_my_route", "start_route", "complete_route") and driver:
                    # driver_id is always the logged-in driver — never taken from the LLM
                    from services.agent_tools_v2 import get_my_route, start_route, complete_route
                    if func_name == "get_my_route":
                        res = get_my_route(driver_id, args.get("target_date", "today"))
                    elif func_name == "start_route":
                        res = start_route(driver_id, args.get("event_name", ""), args.get("target_date", "today"))
                    else:
                        res = complete_route(driver_id, args.get("event_name", ""),
                                             args.get("action", "completed"), args.get("target_date", "today"))
                    if res.get("message"): agent_message = res["message"]
                elif func_name in ("get_kid_tasks", "add_kid_task", "complete_kid_task"):
                    from services import agent_tools_v2 as _atv2
                    # Actor: family chat supplies acting_member; PWA driver
                    # chat resolves the logged-in driver's member (a parent
                    # managing a kid's list from their phone); None
                    # (dashboard/HA voice) is the trusted open-admin context.
                    actor = acting_member
                    if actor is None and driver:
                        from services import storage as _st
                        actor = _st.get_member_by_driver_id(driver_id)
                    if func_name == "get_kid_tasks":
                        res = _atv2.get_kid_tasks(args.get("member_name", "") or "",
                                                  acting_member=actor)
                    elif func_name == "add_kid_task":
                        res = _atv2.add_kid_task(args.get("title", "") or "",
                                                 args.get("due_date", "") or "",
                                                 member_name=args.get("member_name", "") or "",
                                                 kind=args.get("kind", "") or "other",
                                                 acting_member=actor)
                    else:
                        res = _atv2.complete_kid_task(args.get("task_title", "") or "",
                                                      member_name=args.get("member_name", "") or "",
                                                      acting_member=actor)
                    if res.get("message"): agent_message = res["message"]
                elif func_name in ("get_tonights_plate", "change_tonights_plate",
                                   "add_dishes", "get_week_dinners",
                                   "approve_week_dinners", "get_shopping_trip",
                                   "schedule_shopping_trip", "set_dish_prep",
                                   "clear_dish_prep", "get_prep_ahead",
                                   "pair_dishes", "unpair_dishes",
                                   "plan_specific_dinner", "unlock_dinner",
                                   "set_meal_rule", "get_meal_rules"):
                    from services import agent_tools_v2 as _atv2
                    actor = acting_member
                    if actor is None and driver:
                        from services import storage as _st
                        actor = _st.get_member_by_driver_id(driver_id)
                    if func_name == "get_tonights_plate":
                        res = _atv2.get_tonights_plate(
                            args.get("target_date", "today") or "today",
                            acting_member=actor)
                    elif func_name == "get_week_dinners":
                        res = _atv2.get_week_dinners(acting_member=actor)
                    elif func_name == "approve_week_dinners":
                        res = _atv2.approve_week_dinners(acting_member=actor)
                    elif func_name == "set_meal_rule":
                        res = _atv2.set_meal_rule(
                            args.get("description", "") or "",
                            args.get("kind", "frequency_cap") or "frequency_cap",
                            args.get("tags", "") or "",
                            args.get("dish_names", "") or "",
                            bool(args.get("takeout")),
                            int(args.get("max_servings") or 1),
                            int(args.get("window_days") or 7),
                            int(args.get("dwell_days") or 3),
                            args.get("except_dishes", "") or "", acting_member=actor)
                    elif func_name == "get_meal_rules":
                        res = _atv2.get_meal_rules(acting_member=actor)
                    elif func_name == "plan_specific_dinner":
                        res = _atv2.plan_specific_dinner(
                            args.get("target_date", "") or "",
                            args.get("dish_names", "") or "",
                            args.get("note", "") or "", acting_member=actor)
                    elif func_name == "unlock_dinner":
                        res = _atv2.unlock_dinner(args.get("target_date", "") or "",
                                                  acting_member=actor)
                    elif func_name == "pair_dishes":
                        res = _atv2.pair_dishes(args.get("dish_name", "") or "",
                                                args.get("partner_names", "") or "",
                                                bool(args.get("exclusive")),
                                                acting_member=actor)
                    elif func_name == "unpair_dishes":
                        res = _atv2.unpair_dishes(args.get("dish_name", "") or "",
                                                  args.get("partner_name", "") or "",
                                                  acting_member=actor)
                    elif func_name == "add_occasion":
                        res = _atv2.add_occasion(
                            args.get("title", "") or "",
                            args.get("anchor_date", "") or "",
                            args.get("kind", "gathering") or "gathering",
                            args.get("window_start", "") or "",
                            args.get("window_end", "") or "",
                            args.get("dish_tags", "") or "", acting_member=actor)
                    elif func_name == "get_occasion":
                        res = _atv2.get_occasion(args.get("occasion_name", "") or "",
                                                 acting_member=actor)
                    elif func_name == "get_occasion_insights":
                        res = _atv2.get_occasion_insights(
                            args.get("occasion_name", "") or "", acting_member=actor)
                    elif func_name == "get_occasion_gaps":
                        res = _atv2.get_occasion_gaps(
                            args.get("occasion_name", "") or "", acting_member=actor)
                    elif func_name == "set_occasion_attendance":
                        res = _atv2.set_occasion_attendance(
                            args.get("occasion_name", "") or "",
                            args.get("who", "") or "",
                            bool(args.get("coming", True)), acting_member=actor)
                    elif func_name == "add_occasion_guests":
                        res = _atv2.add_occasion_guests(
                            args.get("occasion_name", "") or "",
                            args.get("who", "") or "",
                            int(args.get("headcount") or 1),
                            args.get("cannot_eat", "") or "", acting_member=actor)
                    elif func_name == "source_for_occasion":
                        res = _atv2.source_for_occasion(
                            args.get("occasion_name", "") or "",
                            args.get("needed", "") or "", acting_member=actor)
                    elif func_name == "get_run_sheet":
                        res = _atv2.get_run_sheet(
                            args.get("target_date", "today") or "today",
                            args.get("serve_at", "") or "", acting_member=actor)
                    elif func_name == "set_hosting":
                        res = _atv2.set_hosting(
                            args.get("target_date", "") or "",
                            int(args.get("serving_for") or 0),
                            int(args.get("cooks") or 0), acting_member=actor)
                    elif func_name == "set_dish_categories":
                        res = _atv2.set_dish_categories(
                            args.get("dish_name", "") or "",
                            args.get("categories", "") or "",
                            args.get("whole_meal"),
                            args.get("serves"),
                            args.get("whole_units"), acting_member=actor)
                    elif func_name == "set_dish_scope":
                        occ = args.get("occasion_only")
                        res = _atv2.set_dish_scope(
                            args.get("dish_name", "") or "",
                            True if occ is None else bool(occ),
                            acting_member=actor)
                    elif func_name == "set_dish_prep":
                        res = _atv2.set_dish_prep(
                            args.get("dish_name", "") or "",
                            args.get("action", "") or "",
                            args.get("when", "hours_before") or "hours_before",
                            args.get("hours", 1) or 1, acting_member=actor)
                    elif func_name == "clear_dish_prep":
                        res = _atv2.clear_dish_prep(args.get("dish_name", "") or "",
                                                    args.get("action", "") or "",
                                                    acting_member=actor)
                    elif func_name == "get_prep_ahead":
                        res = _atv2.get_prep_ahead(acting_member=actor)
                    elif func_name == "get_shopping_trip":
                        res = _atv2.get_shopping_trip(args.get("list_name", "") or "",
                                                      acting_member=actor)
                    elif func_name == "schedule_shopping_trip":
                        res = _atv2.schedule_shopping_trip(
                            args.get("store", "") or "",
                            args.get("list_name", "") or "",
                            args.get("weekly", True), acting_member=actor)
                    elif func_name == "change_tonights_plate":
                        res = _atv2.change_tonights_plate(
                            args.get("dish_name", "") or "",
                            action=args.get("action", "add") or "add",
                            target_date=args.get("target_date", "today") or "today",
                            acting_member=actor)
                    else:
                        res = _atv2.add_dishes(args.get("description", "") or "",
                                               acting_member=actor)
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "refine_meal_dish":
                    from services import agent_tools_v2 as _atv2
                    res = _atv2.refine_meal_dish(args.get("dish_name", "") or "",
                                                 args.get("detail", "") or "")
                    if res.get("message"): agent_message = res["message"]
                elif func_name in ("mark_leftovers", "clear_leftovers"):
                    from services import agent_tools_v2 as _atv2
                    if func_name == "mark_leftovers":
                        res = _atv2.mark_leftovers(args.get("what", "") or "",
                                                   target_date=args.get("target_date", "today") or "today",
                                                   parts=args.get("parts", "") or "")
                    else:
                        res = _atv2.clear_leftovers(args.get("target_date", "today") or "today",
                                                    what=args.get("what", "") or "")
                    if res.get("message"): agent_message = res["message"]
                elif func_name in ("suggest_dinner", "add_meal_to_repertoire",
                                   "add_meal_ingredients_to_list", "mark_meal_served"):
                    from services import agent_tools_v2 as _atv2
                    actor = acting_member
                    if actor is None and driver:
                        from services import storage as _st
                        actor = _st.get_member_by_driver_id(driver_id)
                    if func_name == "suggest_dinner":
                        res = _atv2.suggest_dinner(args.get("target_date", "today") or "today",
                                                   acting_member=actor)
                    elif func_name == "add_meal_to_repertoire":
                        res = _atv2.add_meal_to_repertoire(args.get("name", "") or "",
                                                           acting_member=actor)
                    elif func_name == "add_meal_ingredients_to_list":
                        res = _atv2.add_meal_ingredients_to_list(
                            args.get("meal_name", "") or "",
                            list_name=args.get("list_name", "") or "", acting_member=actor)
                    else:
                        res = _atv2.mark_meal_served(args.get("meal_name", "") or "",
                                                     acting_member=actor)
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "get_eating_plan":
                    from services import agent_tools_v2 as _atv2
                    res = _atv2.get_eating_plan(args.get("target_date", "today") or "today")
                    if res.get("message"): agent_message = res["message"]
                elif func_name in ("add_shopping_items", "get_shopping_list_items",
                                   "check_off_shopping_item", "remove_shopping_item_by_name"):
                    from services import agent_tools_v2 as _atv2
                    # Same actor resolution as the kid-task tools, but nothing
                    # here is identity-GATED: anyone in the family may add to
                    # the list (the actor is recorded as attribution only).
                    actor = acting_member
                    if actor is None and driver:
                        from services import storage as _st
                        actor = _st.get_member_by_driver_id(driver_id)
                    if func_name == "add_shopping_items":
                        res = _atv2.add_shopping_items(args.get("items", "") or "",
                                                       list_name=args.get("list_name", "") or "",
                                                       acting_member=actor)
                    elif func_name == "get_shopping_list_items":
                        res = _atv2.get_shopping_list_items(args.get("list_name", "") or "",
                                                            acting_member=actor)
                    elif func_name == "check_off_shopping_item":
                        res = _atv2.check_off_shopping_item(args.get("item_name", "") or "",
                                                            list_name=args.get("list_name", "") or "",
                                                            acting_member=actor)
                    else:
                        res = _atv2.remove_shopping_item_by_name(args.get("item_name", "") or "",
                                                                 list_name=args.get("list_name", "") or "",
                                                                 acting_member=actor)
                    if res.get("message"): agent_message = res["message"]
                elif func_name == "propose_family_action":
                    # Post a confirmation card instead of mutating directly. The
                    # card rides Argyle's reply; the parent's Approve tap is what
                    # executes the action (scope enforced at approval time).
                    from services.agent_tools_v2 import propose_family_action
                    res = propose_family_action(
                        args.get("action_type"), args.get("summary"),
                        payload=args.get("payload") or {},
                        created_by_member_id=(acting_member or {}).get("id"))
                    if res.get("card"): card = res["card"]
                    if res.get("message"): agent_message = res["message"]
                elif func_name in BRIDGED_V1_TOOLS and bridge_ok:
                    # Full-parity bridge: scheduling-core, errand, memory,
                    # places and deep trip-planning tools delegate to v1's
                    # tested handlers. Admin context only — the `bridge_ok`
                    # guard mirrors the toolset gating so a hallucinated tool
                    # name can't execute in PWA driver mode or for a
                    # non-admin @argyle asker. Schedule-mutating
                    # tools flag schedule_dirty so the client re-solves, exactly
                    # like the override tools above.
                    from services import agent_tools
                    res = agent_tools.execute_tool(func_name, args)
                    if isinstance(res, dict) and res.get("status") == "success" \
                            and func_name in SCHEDULE_MUTATING_V1_TOOLS:
                        schedule_dirty = True
                    if isinstance(res, dict) and res.get("message"):
                        agent_message = res["message"]
            except Exception as e:
                res = {"error": str(e)}

            tool_status = res.get("status", "ok") if isinstance(res, dict) else "?"
            if isinstance(res, dict) and (res.get("error") or res.get("status") == "error"):
                logger.warning(f"[agent] tool {func_name} error: {res.get('message') or res.get('error')}")
            logger.info(f"[agent-timing] tool {func_name} took {_time.time() - tool_start:.1f}s (status={tool_status})")
            agent_scratchpad += f"\nTool Result: {json.dumps(res)}\n"
            executed_results[sig] = res
            if not _is_terminal_success(func_name, res):
                round_all_terminal = False

        if round_all_terminal:
            # Every tool call this round was a completed action with its own
            # spoken confirmation — the request is done. Query tools (e.g.
            # get_calendar_events) keep looping so the model can use the data.
            logger.info("[agent-timing] round contained only completed actions — skipping concluding LLM call")
            break

    logger.info(f"[agent-timing] process_agent_request total {_time.time() - request_start:.1f}s "
                f"({llm_calls} LLM call(s))")
    return {
        "status": "success",
        "message": agent_message,
        "target_element_id": target_id,
        "ui_action": ui_action,
        "target_driver_id": target_driver_id,
        "schedule_dirty": schedule_dirty,
        "card": card
    }
