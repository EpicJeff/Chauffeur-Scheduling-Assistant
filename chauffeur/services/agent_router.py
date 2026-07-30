import json
import logging
from typing import Dict, Any, Optional, List

from services.agent_tools_v2 import (
    get_available_tools,
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
    Implements the Dual-Gemma fallback. 
    Tries 31B first, falls back to 26B on HTTP 429 (Rate Limit).
    """
    primary_model = "gemma-4-31b-it"
    fallback_model = "gemma-4-26b-it"
    
    from services.storage import get_settings
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

    try:
        res = _call_llm_json(provider, url, api_key, primary_model, system_prompt, prompt, tools=None)
        if res.get("error") and "429" in str(res.get("error")):
            raise RateLimitException("429 Too Many Requests")
        return res
    except RateLimitException:
        logger.warning(f"{primary_model} rate limited, falling back to {fallback_model}...")
    except Exception as e:
        # 5xx = that model is overloaded/unavailable right now (the call layer
        # already retried with backoff) — the fallback model may still work.
        if not _is_transient(str(e)):
            logger.error(f"Error calling Gemma: {e}")
            return {"error": str(e)}
        logger.warning(f"{primary_model} unavailable ({e}), falling back to {fallback_model}...")

    try:
        return _call_llm_json(provider, url, api_key, fallback_model, system_prompt, prompt, tools=None)
    except Exception as e:
        logger.error(f"Error calling Gemma fallback model: {e}")
        return {"error": str(e), "transient": _is_transient(str(e))}

def process_agent_request(user_prompt: str, context: Optional[Dict] = None, history: Optional[List[Dict]] = None,
                          source: str = "admin", driver_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Main entrypoint for the Agent Orchestrator.
    Decides whether to route to Gemma (tools) or Gemini (heavy lifting).
    source/driver_id come from the chat payload: the PWA sends source='pwa'
    plus the logged-in driver's id, which switches on driver context.
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
    
    if driver:
        system_prompt += f"""
DRIVER MODE (PWA):
You are speaking directly to {driver.get('name')}, a family driver, on their phone while on the go.
Be brief, warm, and plain-spoken — no technical jargon, short sentences, mobile-friendly replies.
Their drives for TODAY are listed below; use get_my_route for other days.
When they say they are leaving or heading out, call start_route. When they say they picked up,
dropped off, arrived, or finished, call complete_route with the matching action.
Never ask them which driver they are — you already know.
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
                        
    tools = get_available_tools()
    if driver:
        from services.agent_tools_v2 import get_driver_tools
        tools = tools + get_driver_tools()

    import time as _time
    request_start = _time.time()
    llm_calls = 0

    # Tools that complete the user's request on their own and return a spoken
    # confirmation. When a round of tool calls consists only of these and they
    # all succeeded, the request is done: skip the concluding LLM round-trip.
    # Timing data showed each Gemma call costs 40-80s, and given the chance the
    # model re-issues the same action instead of concluding (observed writing a
    # duplicate override), so the extra round is both slow and harmful.
    TERMINAL_ACTION_TOOLS = {"assign_driver_to_event_fuzzy", "add_trip_poi",
                             "clear_trip_itinerary", "auto_schedule_trip_itinerary",
                             "manage_trip_rules", "manage_trip_flights",
                             "start_route", "complete_route"}

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
    agent_message = "I have processed your request."
    
    for iteration in range(max_iterations):
        current_system_prompt = system_prompt
        if agent_scratchpad:
            current_system_prompt += "\n\nTOOL EXECUTION SCRATCHPAD:\n" + agent_scratchpad
            
        call_start = _time.time()
        llm_response = call_gemma_with_fallback(user_prompt, tools, current_system_prompt)
        llm_calls += 1
        logger.info(f"[agent-timing] LLM call {llm_calls} took {_time.time() - call_start:.1f}s")

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

        # Check for Delegation to Gemini
        if llm_response.get("delegate_to_gemini"):
            logger.info("Delegating massive task to Gemini 3.1 Flash Lite")
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
            except Exception as e:
                res = {"error": str(e)}

            logger.info(f"[agent-timing] tool {func_name} took {_time.time() - tool_start:.1f}s")
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
        "schedule_dirty": schedule_dirty
    }
