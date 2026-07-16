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

def process_agent_request(user_prompt: str, context: Optional[Dict] = None, history: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """
    Main entrypoint for the Agent Orchestrator.
    Decides whether to route to Gemma (tools) or Gemini (heavy lifting).
    """
    system_prompt = f"""You are Argyle, an intelligent family assistant.
You help manage schedules, trips, and errands. 
You MUST use your provided tools to fetch data or perform actions.
Respond with a concise, helpful message about what you did.

CRITICAL INSTRUCTIONS FOR TRIP PLANNING:
1. If the user asks you to *generate* or *plan* a massive 10-day trip (e.g. "plan my trip to France"), you must output `{{"delegate_to_gemini": true}}` so the heavy lifter can generate the initial ideas.
2. If the user asks you to "add my attractions to the itinerary" or "schedule the attractions", DO NOT delegate! This means they want you to take the ALREADY SAVED attractions (listed in your context) and place them onto the calendar itinerary. You MUST use the `auto_schedule_trip_itinerary` tool to instantly bulk-schedule all of them into the timeline based on their distances and opening hours.
"""
    
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
                        
    tools = get_available_tools()
    
    agent_scratchpad = ""
    max_iterations = 3
    
    target_id = None
    ui_action = None
    target_driver_id = None
    agent_message = "I have processed your request."
    
    for iteration in range(max_iterations):
        current_system_prompt = system_prompt
        if agent_scratchpad:
            current_system_prompt += "\n\nTOOL EXECUTION SCRATCHPAD:\n" + agent_scratchpad
            
        llm_response = call_gemma_with_fallback(user_prompt, tools, current_system_prompt)

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
                "target_driver_id": target_driver_id
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
            
        for tool_call in tool_calls:
            func_name = tool_call.get("name")
            args = tool_call.get("arguments", {})
            agent_scratchpad += f"\nTool Call: {func_name}({json.dumps(args)})"
            
            res = {"error": f"Unknown tool: {func_name}"}
            
            try:
                if func_name == "get_calendar_events":
                    res = get_calendar_events(args.get("start_date"), args.get("end_date"))
                elif func_name == "assign_driver_to_event_fuzzy":
                    from services.agent_tools_v2 import assign_driver_to_event_fuzzy
                    res = assign_driver_to_event_fuzzy(args.get("event_name"), args.get("driver_name"), args.get("target_date"))
                    if res.get("target_element_id"): target_id = res["target_element_id"]
                    if res.get("message"): agent_message = res["message"]
                    if res.get("ui_action"): ui_action = res["ui_action"]
                    if res.get("target_driver_id"): target_driver_id = res["target_driver_id"]
                elif func_name == "add_trip_poi":
                    res = add_trip_poi(args.get("trip_id"), args.get("title"), args.get("start_time"), args.get("duration_mins"), args.get("location"))
                    if res.get("target_element_id"): target_id = res["target_element_id"]
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
            except Exception as e:
                res = {"error": str(e)}
                
            agent_scratchpad += f"\nTool Result: {json.dumps(res)}\n"
            
    return {
        "status": "success",
        "message": agent_message,
        "target_element_id": target_id,
        "ui_action": ui_action,
        "target_driver_id": target_driver_id
    }
