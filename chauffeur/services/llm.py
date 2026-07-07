import json
import urllib.request
import urllib.error
from typing import List, Tuple, Dict
from models.schemas import Rule, PriorityRule

def test_llm_connection(provider: str, url: str = None, api_key: str = None, model: str = None) -> Tuple[bool, str]:
    """
    Tests the connection to Ollama or Gemini.
    Returns: (success_bool, message_str)
    """
    if provider == 'ollama':
        if not url:
            return False, "Ollama URL is required."
        try:
            req = urllib.request.Request(
                f"{url.rstrip('/')}/api/tags",
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                models = [m['name'] for m in data.get('models', [])]
                if model and model not in models and f"{model}:latest" not in models:
                    return True, f"Connected to Ollama, but model '{model}' was not found. Available models: {', '.join(models)}"
                return True, f"Successfully connected to Ollama! Found {len(models)} models."
        except urllib.error.URLError as e:
            return False, f"Connection to Ollama failed: {e.reason}"
        except Exception as e:
            return False, f"Unexpected error connecting to Ollama: {str(e)}"
            
    elif provider == 'gemini':
        if not api_key:
            return False, "Gemini API Key is required."
        try:
            # Simple test call
            gemini_model = model or 'gemini-3.5-flash'
            if gemini_model.startswith('models/'):
                gemini_model = gemini_model[7:]
            req_url = f"https://generativelanguage.googleapis.com/v1/models/{gemini_model}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": "Hello"}]}],
                "generationConfig": {"maxOutputTokens": 5}
            }
            req = urllib.request.Request(
                req_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    return True, "Successfully connected to Gemini API!"
                return False, f"Gemini API returned status code {resp.status}"
        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode('utf-8'))
                msg = err_data.get('error', {}).get('message', str(e))
                return False, f"Gemini API Error: {msg}"
            except:
                return False, f"Gemini API HTTP Error: {e.code} {e.reason}"
        except Exception as e:
            return False, f"Unexpected error connecting to Gemini: {str(e)}"
            
    return False, "Invalid provider selected."

def generate_rules_from_philosophy(
    provider: str,
    url: str,
    api_key: str,
    model: str,
    philosophy: str,
    drivers: List[dict],
    passengers: List[dict],
    feedback: List[str] = None
) -> Tuple[List[dict], List[dict], List[dict], str]:
    """
    Calls Ollama or Gemini to synthesize rules and solver themes from philosophy and bios.
    Returns: (list_of_rules, list_of_priority_rules, list_of_themes, raw_response_log)
    """
    
    # Build context about drivers and passengers
    driver_context = []
    for d in drivers:
        driver_context.append(
            f"- Driver ID: '{d['id']}', Name: '{d['name']}', Group: '{d['group']}', Priority Index: {d['priority_index']}, Bio/Context: \"{d.get('bio', '')}\""
        )
        
    passenger_context = []
    for p in passengers:
        # Match calendar IDs or names
        cal_ids = p.get('calendar_ids', [])
        p_id = cal_ids[0] if cal_ids else p['id']
        passenger_context.append(
            f"- Passenger ID: '{p_id}' (matches calendar ID), Name: '{p['name']}', Hashtags: {p.get('hashtags', [])}, Bio/Context: \"{p.get('bio', '')}\""
        )
        
    feedback_context = ""
    if feedback:
        feedback_context = "\nRecent user feedback to learn from:\n" + "\n".join([f"- {f}" for f in feedback]) + "\nAdjust your generated themes and rules to respect this past feedback."

    from services import storage
    settings = storage.get_settings()
    ai_memory = settings.get('ai_memory', '')
    memory_str = f"\n\nCUSTOM INSTRUCTIONS (Memory):\n{ai_memory}\n" if ai_memory else ""

    system_prompt = f"""You are the backend AI assistant for 'Chauffeur', a family driving scheduler.
Your task is to infer a set of useful and meaningful structured constraint rules, priority rules, and solver themes from a natural language 'Family Philosophy' and individual driver/passenger biographies to be used to generate a schedule that will be used to generate a schedule for the family's driving activities so the parents can focus on time with their children instead of on driving logistics.    {memory_str}

Available Drivers (use only these IDs for rules):
{chr(10).join(driver_context)}

Available Passengers (use only these passenger IDs for rules):
{chr(10).join(passenger_context)}
{feedback_context}

Rule Types available:
1. 'required': This specific driver MUST be assigned to drive for events matching these filters.
2. 'preferred': This specific driver is preferred (has higher weight) for events matching these filters.
3. 'unavailable': This specific driver cannot drive for events matching these filters.
4. 'tolerance': Defines acceptable late arrival or early departure in minutes (tolerance_mins) and applies to ('arrival', 'departure', 'both').
5. 'duplicate': Action for duplicate events for the same attendees ('schedule_one' or 'schedule_all') if they occur within the same grouping_period ('daily', 'weekly', 'monthly', 'all').
6. 'buffer': Extra prep time needed in minutes before (buffer_before_mins) or after (buffer_after_mins) events, e.g. to warm up for a game or change clothes after a swim meet.
7. 'group': Combines events matching the array of filters into a single logical trip.
8. 'attendance': tells the driver whether to stay at the event or just drop off and pick up (uses attendance_action).

Priority Rule modifiers (weight_modifier values):
- 10000: Critical Importance (must route a driver to this event at all costs)
- 1000: High priority
- -1000: Low priority
- -10000: Ignore (do not assign drivers)

Constraints & rules details:
- 'days_of_week' is a list of integers: 0 for Monday, 1 for Tuesday, 2 for Wednesday, 3 for Thursday, 4 for Friday, 5 for Saturday, 6 for Sunday.
- 'time_start' and 'time_end' are strings formatted as 'HH:MM' (24-hour time) or null.
- 'keywords' are substring matches (case-insensitive) for event titles or descriptions.
- 'passenger_ids' is a list of calendar IDs/passenger IDs.
- 'location' is a substring match for the event location field.
- All rules must include 'is_ai_generated': true.
- For 'group' rules, you must define multiple independent objects in the 'filter_sets' array to match the events to be grouped (e.g. one object for 'Soccer' and one for 'Basketball'). If you use 'filter_sets', leave the top-level 'keywords' and 'passenger_ids' empty.

CRITICAL INSTRUCTIONS:
1. Every rule in the "rules" array MUST use the key "constraint_type" to specify the type (do NOT use "type" or "rule_type").
2. Every rule and priority rule MUST contain at least one non-empty filtering field (keywords, passenger_ids, days_of_week, time_start, time_end, location, filter_sets). Do NOT generate rules with empty filters.
3. The "passenger_ids" inside rules MUST match the Passenger IDs provided in the context above (not names or emails).
4. CONFLICT AVOIDANCE: Avoid generating redundant or conflicting rules.
5. ATTENDANCE vs PRIORITY: If the user says a driver must "stay" or "attend" an event (instead of dropping off), generate an 'attendance' rule with attendance_action='stay'. Do NOT generate a priority rule unless the user is talking about how important the event is to be scheduled!
6. THEMES: You MUST generate 3-5 custom "Solver Themes" that represent different strategic ways to fulfill the family philosophy.
   - The first theme should ALWAYS be the "Standard" or "Balanced" default theme with 1.0 multipliers for everything.
   - Additional themes should tweak the multipliers to optimize for specific behaviors. CRITICAL: You must use multipliers scaled high enough to actually bridge the gap between the underlying engine's base weights!
     * The base weight for Primary Driver Bonus is 2000.
     * The base weight for Same Location Bonus is 5000.
     * The base weight for Unassigned Penalty is 100.
     * The base weight for Travel Time Penalty is 1 (per minute, usually ~30 penalty max).
     * The base weight for Stickiness Bonus is 5.
     If you want a theme to prioritize "Fastest Drives" (Travel Time), your travel_time_penalty_multiplier must be massive (e.g. 50 to 100) to compete with the 2000 primary driver bonus.
     If you want a theme to prioritize "Fewest Handoffs" (Stickiness), use a stickiness_bonus_multiplier of 200 to 500.
     If you want to ensure no events are dropped, use an unassigned_penalty_multiplier of 20 to 50.

You MUST respond with a single valid JSON object of the following exact structure:
{{
  "rules": [
    {{
      "driver_id": "string (e.g. 'mom')",
      "constraint_type": "string ('required' | 'preferred' | 'unavailable' | 'tolerance' | 'duplicate' | 'buffer' | 'attendance' | 'group')",
      "duplicate_action": "string or null ('schedule_one' | 'schedule_all')",
      "tolerance_mins": 0,
      "tolerance_type": "string ('arrival' | 'departure' | 'both')",
      "grouping_period": "string ('daily' | 'weekly' | 'monthly' | 'all')",
      "buffer_before_mins": 0,
      "buffer_after_mins": 0,
      "attendance_action": "string or null ('dropoff_pickup' | 'stay')",
      "keywords": ["list of strings"],
      "passenger_ids": ["list of Passenger IDs"],
      "days_of_week": [0, 1],
      "time_start": "string ('HH:MM' or null)",
      "time_end": "string ('HH:MM' or null)",
      "location": "string or null",
      "filter_sets": [
        {{ "keywords": ["string"], "passenger_ids": ["string"] }}
      ],
      "is_ai_generated": true
    }}
  ],
  "priority_rules": [
    {{
      "weight_modifier": 1000,
      "keywords": ["list of strings"],
      "passenger_ids": ["list of Passenger IDs"],
      "days_of_week": [0, 1],
      "time_start": "string ('HH:MM' or null)",
      "time_end": "string ('HH:MM' or null)",
      "location": "string or null",
      "is_ai_generated": true
    }}
  ],
  "themes": [
    {{
      "name": "string (e.g., 'Balanced Default')",
      "description": "string",
      "unassigned_penalty_multiplier": 1.0,
      "stickiness_bonus_multiplier": 1.0,
      "travel_time_penalty_multiplier": 1.0,
      "primary_driver_bonus_multiplier": 1.0,
      "same_location_bonus_multiplier": 1.0
    }}
  ]
}}
Do NOT wrap the output in markdown code blocks like ```json ... ```. Just return raw JSON."""

    prompt = f"Family Philosophy:\n{philosophy}\n\nSynthesize the rules now."
    
    raw_response = ""
    
    if provider == 'ollama':
        try:
            req_url = f"{url.rstrip('/')}/api/chat"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1}
            }
            req = urllib.request.Request(
                req_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw_response = data.get('message', {}).get('content', '')
        except Exception as e:
            raise RuntimeError(f"Ollama request failed: {str(e)}")
            
    elif provider == 'gemini':
        try:
            gemini_model = model or 'gemini-3.5-flash'
            if gemini_model.startswith('models/'):
                gemini_model = gemini_model[7:]
            req_url = f"https://generativelanguage.googleapis.com/v1/models/{gemini_model}:generateContent?key={api_key}"
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": f"{system_prompt}\n\nUser Request: {prompt}"}]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1
                }
            }
            req = urllib.request.Request(
                req_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw_response = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            raise RuntimeError(f"Gemini API request failed: {str(e)}\nDetails: {error_body}")
        except Exception as e:
            raise RuntimeError(f"Gemini API request failed: {str(e)}")
    else:
        raise ValueError("Invalid LLM provider configured.")
        
    # Clean output in case LLM wrapped it in markdown code blocks despite instructions
    cleaned_json_str = raw_response.strip()
    if cleaned_json_str.startswith("```"):
        # Remove first line if it's ```json or ```
        lines = cleaned_json_str.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned_json_str = "\n".join(lines).strip()
        
    try:
        parsed = json.loads(cleaned_json_str)
        rules_out = parsed.get('rules', [])
        priority_rules_out = parsed.get('priority_rules', [])
        themes_out = parsed.get('themes', [])
        
        # Ensure is_ai_generated flag is set to True
        for r in rules_out:
            r['is_ai_generated'] = True
        for pr in priority_rules_out:
            pr['is_ai_generated'] = True
        for t in themes_out:
            t['is_ai_generated'] = True
            
        return rules_out, priority_rules_out, themes_out, raw_response
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON. Error: {str(e)}. Raw output was:\n{raw_response}")

def refine_scheduling_text(
    provider: str,
    url: str,
    api_key: str,
    model: str,
    text: str,
    context_type: str
) -> str:
    """
    Calls Ollama or Gemini to improve and clarify a natural language philosophy or bio text
    so that it is optimized for the AI rules generator and solver.
    """
    if not text or not text.strip():
        return ""

    if context_type == "philosophy":
        system_prompt = (
            "You are an expert family scheduling assistant.\n"
            "Your task is to expand and improve a natural language 'Family Philosophy for kids activities' "
            "to help the AI scheduling engine understand the goals for the family and turn those into a set of structured constraint rules, priority rules, and solver themes.\n"
            "Keep the scheduling guidelines, names, days, times, and preferences accurate, "
            "but add potentially useful prompts with placeholders like 'We are an [INSERT ADJECTIVE HERE] family so [INSERT ACTIVITY TYPE HERE] is something we prioritize not missing' that will help the user build a rich and detailed family philosophy.\n"
            "Respond ONLY with the refined text. No introductory remarks, explanations, or code blocks."
        )
    elif context_type == "driver_bio":
        system_prompt = (
            "You are an expert family scheduling assistant.\n"
            "Your task is to expand and improve a natural language driver's biography / context description "
            "to help the AI scheduling engine understand the strengths and preferences of the driver and turn those into a set of structured constraint rules, priority rules, and solver themes.\n"
            "Make driver preferences, home location details, anxieties (e.g. driving after dark or in rain), "
            "and constraints explicit, add potentially useful prompts with placeholders like 'I work during the day so I prefer to drive to events after [INSERT TIME HERE]' that will help the user build a rich and detailed bio while keeping the description concise (1-3 sentences).\n"
            "Respond ONLY with the refined text. No introductory remarks, explanations, or code blocks."
        )
    elif context_type == "passenger_bio":
        system_prompt = (
            "You are an expert family scheduling assistant.\n"
            "Your task is to expand and improve a natural language passenger's biography / context description "
            "to help the AI scheduling engine understand the needs and preferences of the passenger and turn those into a set of structured constraint rules, priority rules, and solver themes.\n"
            "Make passenger preferences, specific routines, anxieties, and dropoff/pickup needs explicit, "
            "add potentially useful prompts with placeholders like 'I like [INSERT DRIVER HERE] to take me to [INSERT ACTIVITY HERE]' that will help the user build a rich and detailed bio while keeping the description concise (1-3 sentences).\n"
            "Respond ONLY with the refined text. No introductory remarks, explanations, or code blocks."
        )
    else:
        raise ValueError(f"Invalid context_type '{context_type}' for text refinement.")

    user_prompt = f"Original text to refine:\n{text}\n\nRefined version:"

    raw_response = ""

    if provider == 'ollama':
        try:
            req_url = f"{url.rstrip('/')}/api/chat"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "stream": False,
                "options": {"temperature": 0.2}
            }
            req = urllib.request.Request(
                req_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw_response = data.get('message', {}).get('content', '')
        except Exception as e:
            raise RuntimeError(f"Ollama request failed: {str(e)}")

    elif provider == 'gemini':
        try:
            gemini_model = model or 'gemini-3.5-flash'
            if gemini_model.startswith('models/'):
                gemini_model = gemini_model[7:]
            req_url = f"https://generativelanguage.googleapis.com/v1/models/{gemini_model}:generateContent?key={api_key}"
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": f"{system_prompt}\n\nUser Request: {user_prompt}"}]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2
                }
            }
            req = urllib.request.Request(
                req_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw_response = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            raise RuntimeError(f"Gemini API request failed: {str(e)}\nDetails: {error_body}")
        except Exception as e:
            raise RuntimeError(f"Gemini API request failed: {str(e)}")
    else:
        raise ValueError("Invalid LLM provider configured.")

    # Simple cleaning if LLM returned wrapped code blocks or markdown
    refined_str = raw_response.strip()
    if refined_str.startswith("```"):
        lines = refined_str.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        refined_str = "\n".join(lines).strip()

    return refined_str

def evaluate_schedule_options(
    provider: str,
    url: str,
    api_key: str,
    model: str,
    philosophy: str,
    drivers: List[dict],
    options: List[dict],
    feedback: List[str] = None
) -> Tuple[int, str]:
    """
    Evaluates generated schedule options and returns the selected index and reasoning.
    options: List of dicts, each containing 'theme_name', 'assignments_summary', 'unassigned_summary'.
    """
    if not options:
        return 0, "No options to evaluate."

    driver_context = []
    for d in drivers:
        driver_context.append(f"- {d['name']} (ID: {d['id']}, Group: {d['group']}, Bio: {d.get('bio', '')})")

    feedback_context = ""
    if feedback:
        feedback_context = "\nRecent user feedback to learn from:\n" + "\n".join([f"- {f}" for f in feedback]) + "\nAdjust your choice to respect this past feedback."

    options_text = ""
    for idx, opt in enumerate(options):
        options_text += f"Option {idx}:\nTheme: {opt.get('theme_name', 'Unknown')}\n"
        options_text += f"Assignments: {opt.get('assignments_summary', 'None')}\n"
        options_text += f"Unassigned Events: {opt.get('unassigned_summary', 'None')}\n\n"

    system_prompt = f"""You are an expert family scheduling assistant.
Your task is to review multiple schedule options generated by a mathematical solver, and pick the ONE that best fits the family's philosophy and recent feedback.

Family Philosophy:
{philosophy}

Drivers:
{chr(10).join(driver_context)}
{feedback_context}

Available Options:
{options_text}

You MUST respond with a single valid JSON object of the following exact structure:
{{
  "selected_index": 0,
  "reasoning": "A 1-3 sentence explanation of why this option is the best fit."
}}
Do NOT wrap the output in markdown code blocks like ```json ... ```. Just return raw JSON."""

    prompt = "Evaluate the options and return the best one in JSON format."

    raw_response = ""

    if provider == 'ollama':
        try:
            req_url = f"{url.rstrip('/')}/api/chat"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1}
            }
            req = urllib.request.Request(req_url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw_response = data.get('message', {}).get('content', '')
        except Exception as e:
            return 0, f"Ollama request failed: {str(e)}"

    elif provider == 'gemini':
        try:
            gemini_model = model or 'gemini-3.5-flash'
            if gemini_model.startswith('models/'):
                gemini_model = gemini_model[7:]
            req_url = f"https://generativelanguage.googleapis.com/v1/models/{gemini_model}:generateContent?key={api_key}"
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": f"{system_prompt}\n\nUser Request: {prompt}"}]
                    }
                ],
                "generationConfig": {"temperature": 0.1}
            }
            req = urllib.request.Request(req_url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw_response = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
        except Exception as e:
            return 0, f"Gemini request failed: {str(e)}"
    else:
        return 0, "Invalid LLM provider."

    cleaned_json_str = raw_response.strip()
    if cleaned_json_str.startswith("```"):
        lines = cleaned_json_str.splitlines()
        if lines[0].startswith("```"): lines = lines[1:]
        if lines and lines[-1].startswith("```"): lines = lines[:-1]
        cleaned_json_str = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned_json_str)
        sel_idx = parsed.get('selected_index', 0)
        reasoning = parsed.get('reasoning', "I chose this option based on the family philosophy.")
        if not isinstance(sel_idx, int) or sel_idx < 0 or sel_idx >= len(options):
            sel_idx = 0
        return sel_idx, reasoning
    except json.JSONDecodeError:
        return 0, "Failed to parse LLM evaluation."


def _call_llm_json(provider: str, url: str, api_key: str, model: str, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> dict:
    import json
    import urllib.request
    
    raw_response = ""
    if provider == 'ollama':
        try:
            req_url = f"{url.rstrip('/')}/api/chat"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": temperature}
            }
            req = urllib.request.Request(
                req_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw_response = data.get('message', {}).get('content', '')
        except Exception as e:
            raise RuntimeError(f"Ollama request failed: {str(e)}")
            
    elif provider == 'gemini':
        try:
            gemini_model = model or 'gemini-3.5-flash'
            if gemini_model.startswith('models/'):
                gemini_model = gemini_model[7:]
            req_url = f"https://generativelanguage.googleapis.com/v1/models/{gemini_model}:generateContent?key={api_key}"
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": f"{system_prompt}\n\nUser Request: {user_prompt}"}]
                    }
                ],
                "generationConfig": {
                    "temperature": temperature
                }
            }
            req = urllib.request.Request(
                req_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                try:
                    raw_response = data['candidates'][0]['content']['parts'][0]['text']
                except (KeyError, IndexError):
                    raise RuntimeError("Unexpected response format from Gemini API")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            raise RuntimeError(f"Gemini API request failed: {str(e)}\nDetails: {error_body}")
        except Exception as e:
            raise RuntimeError(f"Gemini request failed: {str(e)}")
    else:
        raise ValueError(f"Unknown provider: {provider}")
        
    try:
        if raw_response.startswith('```json'):
            raw_response = raw_response.split('```json')[1]
            if raw_response.endswith('```'):
                raw_response = raw_response[:-3]
        return json.loads(raw_response.strip())
    except json.JSONDecodeError as e:
        import traceback
        raise RuntimeError(f"Failed to parse LLM JSON: {str(e)}\nRaw: {raw_response}")

def identify_override_patterns(provider: str, url: str, api_key: str, model: str, overrides: list) -> list:
    system_prompt = """You are the backend AI assistant for 'Chauffeur', a family driving scheduler.
Your task is to review a list of manual drag-and-drop schedule overrides made by a user and group them into logical 'Pattern Clusters'.
A Pattern Cluster is a recurring behavior. For example, if you see the user moved 'Lily Swim Practice' to driver 'mom' on 5 different dates, that is a cluster.

You MUST respond with a single valid JSON object of the following structure:
{
  "clusters": [
    {
      "description": "Brief description of the pattern (e.g. 'Moved Lily Swim to Mom')",
      "dates": ["2026-06-12", "2026-06-14", "2026-06-19"],
      "original_driver_id": "dad",
      "new_driver_id": "mom"
    }
  ]
}
Do NOT wrap the output in markdown code blocks like ```json ... ```. Just return raw JSON.
"""
    
    overrides_text = "List of Overrides:\n"
    for o in overrides:
        event_str = f"Event '{o.get('event_title')}'" if o.get('event_title') else f"Event ID: {o.get('event_id')}"
        overrides_text += f"Date: {o.get('date_str')}, {event_str}, Reassigned to Driver: {o.get('driver_id')}\n"
        
    res = _call_llm_json(provider, url, api_key, model, system_prompt, overrides_text)
    return res.get('clusters', [])

def deduce_rules_from_context(provider: str, url: str, api_key: str, model: str, cluster: dict, original_schedules_context: str, modified_schedules_context: str, passengers: list) -> dict:
    passenger_context = []
    for p in passengers:
        cal_ids = p.get('calendar_ids', [])
        p_id = cal_ids[0] if cal_ids else p['id']
        passenger_context.append(
            f"- Passenger ID: '{p_id}' (matches calendar ID), Name: '{p['name']}', Hashtags: {p.get('hashtags', [])}"
        )
        
    from services import storage
    settings = storage.get_settings()
    ai_memory = settings.get('ai_memory', '')
    memory_str = f"\n\nCUSTOM INSTRUCTIONS (Memory):\n{ai_memory}\n" if ai_memory else ""

    system_prompt = f"""You are the backend AI assistant for 'Chauffeur', a family driving scheduler.{memory_str}
You identified a Pattern Cluster: {cluster.get('description')} where the user repeatedly reassigned an event to driver '{cluster.get('new_driver_id')}'.
I will provide you with the full daily schedules for the dates this occurred, BOTH before the user's manual changes (Original) and after their changes (Modified).
Your goal is to deduce the LOGICAL REASON (the "Why") behind this pattern by looking at what changed and the surrounding context.

CRITICAL INSTRUCTION: Do NOT just blindly output 'required' or 'preferred' driver rules. You MUST analyze the surrounding schedule to find the true root cause:
- Did the user move this event so it could be driven together with another event at the same time/location? -> Generate a 'group' rule to combine them!
- Did the original driver not have enough travel time between events? -> Generate a 'buffer' rule to ensure they have enough time!
- Does the new driver have an overlapping event, but the user assigned it anyway? -> Generate a 'tolerance' rule to explicitly allow the overlap!
- Does the event overlap with something that shouldn't be attended? -> Generate an 'attendance' rule!

Think deeply about the relationships between the events. The driver reassignment is just the symptom; the rule you generate should fix the root cause.

Based on your deduction, you MUST generate structured JSON rules that codify this behavior.

Original Schedules (Before changes):
{original_schedules_context}

Modified Schedules (After manual user overrides):
{modified_schedules_context}

Available Passengers (use only these passenger IDs for rules):
{chr(10).join(passenger_context)}

Rule Types available:
1. 'required': This specific driver MUST be assigned to drive for events matching these filters.
2. 'preferred': This specific driver is preferred (has higher weight) for events matching these filters.
3. 'unavailable': This specific driver cannot drive for events matching these filters.
4. 'duplicate': tells the solver to ('schedule_one' or 'schedule_all') for duplicate events for the same attendees if they occur within the same grouping_period.
5. 'tolerance': Defines acceptable late arrival or early departure for events (uses tolerance_mins and tolerance_type).
6. 'group': Combines events matching the array of filters into a single logical trip.
7. 'buffer': tells the solver to add buffer_before_mins and/or buffer_after_mins around matched events.
8. 'attendance': tells the driver whether to stay at the event or just drop off and pick up (uses attendance_action).

Constraints & rules details:
- 'days_of_week' is a list of integers: 0 for Monday, 1 for Tuesday, 2 for Wednesday, 3 for Thursday, 4 for Friday, 5 for Saturday, 6 for Sunday.
- 'time_start' and 'time_end' are strings formatted as 'HH:MM' (24-hour time) or null.
- 'keywords' are substring matches (case-insensitive) for event titles or descriptions.
- 'passenger_ids' is a list of calendar IDs/Passenger IDs.
- 'location' is a substring match for the event location field.
- For 'tolerance' rules, you must set 'tolerance_mins' (integer) and 'tolerance_type' ('arrival', 'departure', or 'both').
- For 'buffer' rules, you must set 'buffer_before_mins' and/or 'buffer_after_mins' (integers).
- For 'duplicate' rules, you must set 'duplicate_action' ('schedule_one' or 'schedule_all').
- For 'attendance' rules, you must set 'attendance_action' (e.g. 'ignore', 'require').
- All rules must include 'is_ai_generated': true.
- For 'group' rules, you must define multiple independent objects in the 'filter_sets' array to match the events to be grouped (e.g. one object for 'Soccer' and one for 'Basketball'). If you use 'filter_sets', leave the top-level 'keywords' and 'passenger_ids' empty.

You MUST respond with a single valid JSON object of the following exact structure:
{{
  "rules": [
    {{
      "driver_id": "{cluster.get('new_driver_id')}",
      "constraint_type": "string ('required' | 'preferred' | 'unavailable' | 'duplicate' | 'tolerance' | 'group' | 'buffer' | 'attendance')",
      "keywords": ["list of strings"],
      "passenger_ids": ["list of Passenger IDs"],
      "days_of_week": [],
      "time_start": null,
      "time_end": null,
      "location": null,
      "filter_sets": [
        {{ "keywords": ["Soccer"], "passenger_ids": [] }}
      ],
      "tolerance_mins": 0,
      "tolerance_type": "both",
      "buffer_before_mins": 0,
      "buffer_after_mins": 0,
      "duplicate_action": null,
      "attendance_action": null,
      "is_ai_generated": true
    }}
  ],
  "priority_rules": []
}}
Do NOT wrap the output in markdown code blocks like ```json ... ```. Just return raw JSON.
"""
    
    res = _call_llm_json(provider, url, api_key, model, system_prompt, "Please analyze the original vs modified schedules and generate the rules.")
    return res

def agentic_chat_loop(user_msg: str, source: str = "admin", driver_id: str = None, context: dict = None, conversation_id: str = None) -> str:
    import json
    import time
    import urllib.request
    from services import storage
    from services import agent_tools
    
    settings = storage.get_settings()
    
    import os
    if os.path.exists('/data/options.json'):
        DATA_DIR = '/data'
    else:
        DATA_DIR = '.'
        
    page_context_str = ""
    if context:
        path = context.get('pathname', '')
        search = context.get('search', '')
        page_context_str = f"\n\nCURRENT PAGE CONTEXT:\nThe user is currently viewing the page: {path}{search}\n"
        
        try:
            if 'trip' in path and 'event_id=' in search:
                from urllib.parse import parse_qs
                qs = parse_qs(search.lstrip('?'))
                event_id = qs.get('event_id', [''])[0]
                if event_id:
                    from main import get_trip_api
                    trip_resp = get_trip_api(event_id)
                    if trip_resp and "error" not in trip_resp:
                        page_context_str += f"Current Trip Details: {json.dumps(trip_resp)}\n"
            elif 'trips' in path:
                from main import get_all_trips_api
                trips_resp = get_all_trips_api()
                page_context_str += f"All Current Trips: {json.dumps(trips_resp)}\n"
            elif 'errand' in path:
                errands = storage.get_all_errands()
                page_context_str += f"All Current Errands: {json.dumps(errands)}\n"
            elif 'schedule' in path or 'dashboard_v2' in path or path == '/' or path == '/chauffeur/':
                page_context_str += "They are looking at the schedule/calendar.\n"
            elif 'config' in path:
                page_context_str += f"Current System Settings: {json.dumps(settings)}\n"
        except Exception as e:
            page_context_str += f"(Failed to load extended page context: {str(e)})\n"
            
    provider = settings.get('llm_provider', 'gemini')
    if context and context.get('model_override'):
        provider = context.get('model_override')
    
    if not conversation_id:
        convs = storage.get_all_conversations()
        general_convs = [c for c in convs if c.get('type') == 'general']
        if general_convs:
            conversation_id = general_convs[0]['id']
        else:
            import uuid
            conversation_id = storage.create_conversation({
                'id': uuid.uuid4().hex,
                'type': 'general', 
                'mode': 'standard', 
                'title': 'General Chat', 
                'messages': [],
                'created_at': time.time(),
                'updated_at': time.time()
            })
            
    storage.add_message_to_conversation(conversation_id, {'role': 'user', 'content': user_msg, 'timestamp': time.time()})
    
    conv = storage.get_conversation(conversation_id)
    
    mode = context.get('mode') if context and context.get('mode') else (conv.get('mode', 'standard') if conv else 'standard')
    if mode == 'planner':
        path = context.get('pathname', '') if context else ''
        search = context.get('search', '') if context else ''
        duration_days = context.get('duration_days') if context else None
        
        event_id = None
        if 'trip' in path and 'event_id=' in search:
            from urllib.parse import parse_qs
            qs = parse_qs(search.lstrip('?'))
            event_id = qs.get('event_id', [''])[0]
            
        if not event_id:
            err = "⚠️ Smart Planner mode is only available on a specific Trip page."
            storage.add_message_to_conversation(conversation_id, {'role': 'assistant', 'content': err, 'timestamp': time.time()})
            return err
            
        meta = storage.get_trip_metadata(event_id)
        if not meta:
            err = "⚠️ Trip not found."
            storage.add_message_to_conversation(conversation_id, {'role': 'assistant', 'content': err, 'timestamp': time.time()})
            return err
            
        from models.schemas import TripMetadata
        trip_obj = TripMetadata(**meta)
        
        if duration_days is None:
            duration_days = meta.get('draft_duration_days')
        if duration_days is None:
            start_ts = meta.get('mock_start_date')
            end_ts = meta.get('mock_end_date')
            if start_ts and end_ts:
                duration_days = max(1, int((end_ts - start_ts) / 86400) + 1)
            else:
                duration_days = 3
        
        # Determine intent (POIs vs Accommodations vs Entire Trip)
        system_prompt = "You are a classifier. The user is asking to add things to their trip itinerary. Decide if they are asking for 'accommodations' (hotels, airbnbs, lodging, places to stay, house), 'pois' (activities, restaurants, sights, points of interest, etc), or an 'entire_trip' (they want you to plan a full trip, an entire itinerary, or both accommodations and pois at the same time). Respond with a JSON object exactly like this: {\"intent\": \"accommodations\"}, {\"intent\": \"pois\"}, or {\"intent\": \"entire_trip\"}."
        
        url = settings.get('llm_ollama_url', 'http://localhost:11434')
        api_key = settings.get('llm_gemini_api_key', '')
        model = settings.get('llm_gemini_model', 'gemini-3.5-flash') if provider == 'gemini' else settings.get('llm_ollama_model', 'qwen2.5:7b')
        
        try:
            res = _call_llm_json(provider, url, api_key, model, system_prompt, user_msg)
            intent = res.get('intent', 'pois').lower()
        except Exception as e:
            print(f"Failed to classify intent: {e}")
            intent = 'pois'
            
        if intent == 'accommodations':
            from services.trip_planner import generate_trip_accommodations
            accs = generate_trip_accommodations(trip_obj, user_msg)
            
            if 'accommodations' not in meta:
                meta['accommodations'] = []
            for acc in accs:
                meta['accommodations'].append(acc.model_dump() if hasattr(acc, 'model_dump') else acc.dict())
                
            reply = f"✨ I've generated and added {len(accs)} new accommodations to your trip based on your request!"
        elif intent == 'entire_trip':
            from services.trip_planner import generate_trip_plan
            pois, accs, flights = generate_trip_plan(trip_obj, user_msg, duration_days)
            
            if 'accommodations' not in meta:
                meta['accommodations'] = []
            for acc in accs:
                meta['accommodations'].append(acc.model_dump() if hasattr(acc, 'model_dump') else acc.dict())
                
            if 'pois' not in meta:
                meta['pois'] = []
            for poi in pois:
                meta['pois'].append(poi.model_dump() if hasattr(poi, 'model_dump') else poi.dict())
                
            if 'flights' not in meta:
                meta['flights'] = []
            for flight in flights:
                meta['flights'].append(flight.model_dump() if hasattr(flight, 'model_dump') else flight.dict())
                
            reply = f"✨ I've generated and added {len(pois)} new Points of Interest, {len(accs)} accommodations, and {len(flights)} flights to your trip based on your request!"
        else:
            from services.trip_planner import generate_trip_pois
            pois = generate_trip_pois(trip_obj, user_msg, duration_days)
            
            if 'pois' not in meta:
                meta['pois'] = []
            for poi in pois:
                meta['pois'].append(poi.model_dump() if hasattr(poi, 'model_dump') else poi.dict())
                
            reply = f"✨ I've generated and added {len(pois)} new Points of Interest to your trip based on your request!"
            
        storage.set_trip_metadata(event_id, meta)
        storage.add_message_to_conversation(conversation_id, {'role': 'assistant', 'content': reply, 'timestamp': time.time()})
        return reply

    raw_history = conv.get('messages', [])[-20:] if conv else []
    
    ai_memory = settings.get('ai_memory', '')
    memory_str = f"\n\nCUSTOM INSTRUCTIONS (Memory):\n{ai_memory}\n" if ai_memory else ""
    
    import datetime
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    
    capabilities_str = ""
    try:
        capabilities_path = os.path.join(DATA_DIR, 'system_capabilities.md')
        if os.path.exists(capabilities_path):
            with open(capabilities_path, "r", encoding="utf-8") as f:
                capabilities_str = f"\n\nSYSTEM CAPABILITIES AND CONSTRAINTS:\n{f.read()}\n"
    except Exception:
        pass

    SYSTEM_PROMPT = f"""You are Argyle, the AI Assistant for 'Chauffeur'. Today is {today_str}.{memory_str}{capabilities_str}{page_context_str}
Your job is to help the user manage their family's calendar, routing, and driving schedule.
Use the tools provided to fetch the current state, add rules, add overrides, manage errands, search places (POIs), update your memory, and run the solver.
Always call run_solver after adding or deleting rules to ensure the schedule resolves successfully.
If the user asks for a one-off change to a specific event, DO NOT create a rule. Instead, use get_current_state with the specific date to get the schedule, find the event_id, and then use add_override to directly assign the driver.
If the user wants a persistent pattern, use add_routing_rule.
If the user asks to add an errand near a person's route, FIRST use get_current_state to identify a location on their route, SECOND use search_places with that proximity to find a real address, and THIRD use add_errand with the specific found location.
If the user asks to add a Point of Interest (POI) to a trip, FIRST use get_current_state to identify the trip event, SECOND use search_places to find the exact address, and THIRD use add_trip_poi.
If the user specifies WHO should run the errand (e.g., "Lorena needs to get gas"), you MUST use the required_drivers parameter directly on add_errand (or update_errand) instead of creating an errand rule. You can also set time constraints (time_window_start/end), buffers, tolerances, and group_ids directly on the errand.
If the user specifies urgency or a tight deadline (e.g. "this afternoon", "today", "tomorrow"), you MUST pass window_days: 1 to the errand to restrict the solver to that specific day.
If the solver returns an error, explain the conflict to the user and ask how they want to resolve it.
Once you have run the solver successfully or finished your task, you MUST reply to the user with a final text summary.
Do NOT guess driver IDs, rule IDs, or event IDs. Always use get_current_state to see the IDs first if you don't know them.
You can use update_memory to save persistent rules, preferences, or global instructions for yourself across sessions."""

    if source == "pwa":
        SYSTEM_PROMPT += "\n\nCRITICAL PWA DRIVER INSTRUCTIONS:\nYou are speaking directly to a driver via the mobile app on the go. Be extremely polite, concise, and friendly. Focus purely on the driver's immediate needs (routing, overrides, active errands, and live state tracking). DO NOT use technical jargon (e.g. 'heuristic solver', 'JSON payloads'). If the driver asks to change something, ALWAYS prefer using one-off overrides (`AddOverrideTool`) rather than global routing rules. Do NOT create global rules (`AddRoutingRuleTool`) unless the driver explicitly uses the word 'permanently'."

    if provider == 'ollama':
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in raw_history:
            # We don't save tool outputs to DB across sessions right now, so we only see user and assistant
            messages.append({"role": msg['role'], "content": msg['content']})
            
        url = settings.get('llm_ollama_url', 'http://localhost:11434')
        model = settings.get('llm_ollama_model', 'qwen2.5:7b')
        tools = agent_tools.get_openai_tools()
        
        for _ in range(10):
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "tools": tools,
                "options": {
                    "num_ctx": 16384
                }
            }
            req = urllib.request.Request(
                f"{url.rstrip('/')}/api/chat",
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    msg_resp = data.get('message', {})
            except Exception as e:
                err = f"Ollama request failed: {str(e)}"
                storage.add_message_to_conversation(conversation_id, {'role': 'assistant', 'content': err, 'timestamp': time.time()})
                return err
                
            messages.append(msg_resp)
            
            if msg_resp.get("tool_calls"):
                for tc in msg_resp["tool_calls"]:
                    func = tc["function"]
                    name = func["name"]
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        try: args = json.loads(args)
                        except: args = {}
                    
                    res = agent_tools.execute_tool(name, args)
                    
                    if provider == 'ollama':
                        # Inject explicit instructions into the tool result for local models 
                        # to guide them out of the tool loop and back to conversational replies.
                        res["_system_instruction"] = "Tool execution complete. Reply to the user acknowledging completion and summarizing what you just did based on this output."

                    tool_msg = {
                        "role": "tool",
                        "content": json.dumps(res)
                    }
                    # Include tool_call_id and name for strict model parsing
                    if "id" in tc:
                        tool_msg["tool_call_id"] = tc["id"]
                    tool_msg["name"] = name
                    messages.append(tool_msg)
            else:
                final_text = msg_resp.get("content", "")
                storage.add_message_to_conversation(conversation_id, {'role': 'assistant', 'content': final_text, 'timestamp': time.time()})
                return final_text
                
    elif provider == 'gemini':
        api_key = settings.get('llm_gemini_api_key', '')
        if not api_key:
            err = "Error: Gemini API Key is missing. Please configure it in the settings."
            storage.add_message_to_conversation(conversation_id, {'role': 'assistant', 'content': err, 'timestamp': time.time()})
            return err
            
        gemini_model = settings.get('llm_gemini_model', 'gemini-3.5-flash')
        if gemini_model.startswith('models/'): gemini_model = gemini_model[7:]
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
        
        gemini_tools = [{"functionDeclarations": []}]
        for t in agent_tools.get_openai_tools():
            gemini_tools[0]["functionDeclarations"].append(t["function"])
            
        gemini_msgs = []
        for msg in raw_history:
            role = "user" if msg["role"] in ["user", "tool"] else "model"
            gemini_msgs.append({"role": role, "parts": [{"text": msg["content"]}]})
            
        system_instruction = {"parts": [{"text": SYSTEM_PROMPT}]}
        
        for _ in range(10):
            payload = {
                "systemInstruction": system_instruction,
                "contents": gemini_msgs,
                "tools": gemini_tools,
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
            except Exception as e:
                err = f"Gemini request failed: {str(e)}"
                try:
                    if hasattr(e, 'read'):
                        err += f" {e.read().decode('utf-8')}"
                except: pass
                storage.add_message_to_conversation(conversation_id, {'role': 'assistant', 'content': err, 'timestamp': time.time()})
                return err
                
            if "candidates" not in data or not data["candidates"]:
                err = "Gemini returned empty response."
                storage.add_message_to_conversation(conversation_id, {'role': 'assistant', 'content': err, 'timestamp': time.time()})
                return err
                
            candidate = data["candidates"][0]
            parts = candidate.get("content", {}).get("parts", [])
            
            gemini_msgs.append(candidate.get("content", {"role": "model", "parts": parts}))
            
            has_tool_call = False
            function_response_parts = []
            for part in parts:
                if "functionCall" in part:
                    has_tool_call = True
                    fc = part["functionCall"]
                    name = fc["name"]
                    args = fc.get("args", {})
                    res = agent_tools.execute_tool(name, args)
                    
                    function_response_parts.append({
                        "functionResponse": {
                            "name": name,
                            "response": res
                        }
                    })
            
            if has_tool_call:
                gemini_msgs.append({
                    "role": "function",
                    "parts": function_response_parts
                })
            else:
                final_text = "".join([p.get("text", "") for p in parts if "text" in p])
                storage.add_message_to_conversation(conversation_id, {'role': 'assistant', 'content': final_text, 'timestamp': time.time()})
                return final_text

    return "Error: Max loops reached or unknown provider."

def auto_name_conversation(conversation_id: str, first_message: str):
    from services import storage
    import json
    import urllib.request
    try:
        settings = storage.get_settings()
        provider = settings.get('llm_provider', 'gemini')
        prompt = f"Summarize this message into a short 3-5 word conversation title. DO NOT use quotes. Message: \n{first_message}"
        
        title = ""
        if provider == 'ollama':
            url = settings.get('llm_ollama_url', 'http://localhost:11434')
            model = settings.get('llm_ollama_model', 'qwen2.5:7b')
            req_url = f"{url.rstrip('/')}/api/chat"
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.3}
            }
            req = urllib.request.Request(req_url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                title = data.get('message', {}).get('content', '')
        elif provider == 'gemini':
            api_key = settings.get('llm_gemini_api_key', '')
            gemini_model = settings.get('llm_gemini_model', 'gemini-3.5-flash')
            if api_key:
                req_url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
                payload = {
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.3}
                }
                req = urllib.request.Request(req_url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    title = data['candidates'][0]['content']['parts'][0]['text']

        title = title.strip().replace('"', '')
        if title:
            storage.update_conversation_title(conversation_id, title)
    except Exception as e:
        print(f"Error auto-naming conversation: {e}")
