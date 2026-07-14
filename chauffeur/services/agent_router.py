import json
import logging
from typing import Dict, Any, Optional

from services.agent_tools_v2 import (
    get_available_tools,
    get_calendar_events,
    schedule_calendar_override,
    add_trip_poi,
    clear_trip_itinerary
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
    
    try:
        res = _call_llm_json(provider, url, api_key, primary_model, system_prompt, prompt, tools=None)
        if res.get("error") and "429" in str(res.get("error")):
            raise RateLimitException("429 Too Many Requests")
        return res
    except RateLimitException:
        logger.warning(f"{primary_model} rate limited, falling back to {fallback_model}...")
        return _call_llm_json(provider, url, api_key, fallback_model, system_prompt, prompt, tools=None)
    except Exception as e:
        logger.error(f"Error calling Gemma: {e}")
        return {"error": str(e)}

def process_agent_request(user_prompt: str, context: Optional[Dict] = None, history: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """
    Main entrypoint for the Agent Orchestrator.
    Decides whether to route to Gemma (tools) or Gemini (heavy lifting).
    """
    system_prompt = """You are Argyle, an intelligent family assistant.
You help manage schedules, trips, and errands. 
You MUST use your provided tools to fetch data or perform actions.
Respond with a concise, helpful message about what you did.
If you need to generate a massive 10-day trip, output {"delegate_to_gemini": true}.
"""
    
    if history:
        system_prompt += "\n\nCONVERSATION HISTORY:\n"
        # Take last 5 turns to keep context window small
        for msg in history[-5:]:
            system_prompt += f"{msg.get('role').upper()}: {msg.get('content')}\n"
            
    if context:
        system_prompt += f"\n\nUSER CONTEXT:\n{json.dumps(context)}\n"
        if "pathname" in context and "/trip/" in context["pathname"]:
            trip_id = context["pathname"].split("/trip/")[-1].split("/")[0]
            system_prompt += f"The current active trip_id is: {trip_id}\n"
        
    tools = get_available_tools()
    
    # 1. Call Gemma Router
    llm_response = call_gemma_with_fallback(user_prompt, tools, system_prompt)
    
    # 2. Check for Delegation to Gemini
    if llm_response.get("delegate_to_gemini"):
        # Hand off to Gemini for massive trip planning
        logger.info("Delegating massive task to Gemini 3.1 Flash Lite")
        return {"status": "delegated", "message": "I'm delegating this massive trip to my heavy lifter module. One moment!"}
        
    # 3. Process Tool Calls from Gemma
    tool_calls = llm_response.get("tool_calls", [])
    agent_message = llm_response.get("message", "I have processed your request.")
    target_id = None
    ui_action = None
    
    for tool_call in tool_calls:
        func_name = tool_call.get("name")
        args = tool_call.get("arguments", {})
        
        if func_name == "get_calendar_events":
            res = get_calendar_events(args.get("start_date"), args.get("end_date"))
            # In a real loop, we would pass this back to Gemma. For now, just return it.
            
        elif func_name == "schedule_calendar_override":
            res = schedule_calendar_override(args.get("event_id"), args.get("driver_id"), args.get("reason"))
            if res.get("target_element_id"):
                target_id = res["target_element_id"]
                
        elif func_name == "add_trip_poi":
            res = add_trip_poi(args.get("trip_id"), args.get("title"), args.get("start_time"), args.get("duration_mins"), args.get("location"))
            if res.get("target_element_id"):
                target_id = res["target_element_id"]
                
        elif func_name == "clear_trip_itinerary":
            res = clear_trip_itinerary(args.get("trip_id"))
            if res.get("target_element_id"):
                target_id = res["target_element_id"]
            if res.get("ui_action"):
                ui_action = res["ui_action"]
            if res.get("message"):
                agent_message = res["message"]
                
    return {
        "status": "success",
        "message": agent_message,
        "target_element_id": target_id,
        "ui_action": ui_action
    }
