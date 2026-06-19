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

    system_prompt = f"""You are the backend AI assistant for 'Chauffeur', a family driving scheduler.
Your task is to translate a natural language 'Family Philosophy' and individual driver/passenger biographies into structured constraint rules, priority rules, and solver themes.

Available Drivers (use only these IDs for rules):
{chr(10).join(driver_context)}

Available Passengers (use only these passenger IDs for rules):
{chr(10).join(passenger_context)}
{feedback_context}

Rule Types available:
1. 'required': A driver MUST drive for events matching these filters.
2. 'preferred': A driver is preferred (weight bonus) for events matching these filters.
3. 'unavailable': A driver cannot drive for events matching these filters.
4. 'tolerance': Defines acceptable late arrival or early departure in minutes (tolerance_mins) and applies to ('arrival', 'departure', 'both').
5. 'duplicate': Action for duplicate events ('schedule_one' or 'schedule_all') in a grouping_period ('daily', 'weekly', 'monthly', 'all').
6. 'buffer': Extra prep time needed in minutes before (buffer_before_mins) or after (buffer_after_mins) events.

Priority Rule modifiers (weight_modifier values):
- 10000: Critical (must-attend events)
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

CRITICAL INSTRUCTIONS:
1. Every rule in the "rules" array MUST use the key "constraint_type" to specify the type (do NOT use "type" or "rule_type").
2. Every rule and priority rule MUST contain at least one non-empty filtering field (keywords, passenger_ids, days_of_week, time_start, time_end, location). Do NOT generate rules with empty filters.
3. The "passenger_ids" inside rules MUST match the Passenger IDs provided in the context above (not names or emails).
4. CONFLICT AVOIDANCE: Avoid generating redundant or conflicting rules.
5. THEMES: You MUST generate 3-5 custom "Solver Themes" that represent different strategic ways to fulfill the family philosophy.
   - The first theme should ALWAYS be the "Standard" or "Balanced" default theme with 1.0 multipliers for everything.
   - Additional themes should tweak the multipliers (e.g., 5.0 for a huge bonus/penalty, 0.2 for a reduction) to optimize for specific behaviors mentioned or implied in the philosophy/feedback (e.g., "Fewest Handoffs" by increasing stickiness, "Fastest Drives" by increasing travel time penalty).

You MUST respond with a single valid JSON object of the following exact structure:
{{
  "rules": [
    {{
      "driver_id": "string (e.g. 'mom')",
      "constraint_type": "string ('required' | 'preferred' | 'unavailable' | 'tolerance' | 'duplicate' | 'buffer' | 'attendance')",
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
            "Your task is to refine and rewrite a natural language 'Family Philosophy' "
            "to make it extremely clear, structured, and easy for an AI scheduling engine to understand.\n"
            "Keep the scheduling guidelines, names, days, times, and preferences accurate, "
            "but organize them into a clean, concise, and structured bulleted list.\n"
            "Do not add rules that are not in the original text, but make existing rules explicit.\n"
            "Respond ONLY with the refined text. No introductory remarks, explanations, or code blocks."
        )
    elif context_type == "driver_bio":
        system_prompt = (
            "You are an expert family scheduling assistant.\n"
            "Your task is to rewrite a driver's biography / context description to be clear, "
            "precise, and easy for an AI rules generator to parse.\n"
            "Make driver preferences, home location details, anxieties (e.g. driving after dark or in rain), "
            "and constraints explicit, while keeping the description concise (1-3 sentences).\n"
            "Respond ONLY with the refined text. No introductory remarks, explanations, or code blocks."
        )
    elif context_type == "passenger_bio":
        system_prompt = (
            "You are an expert family scheduling assistant.\n"
            "Your task is to rewrite a passenger's biography / context description to be clear, "
            "precise, and easy for an AI rules generator to parse.\n"
            "Make passenger preferences, specific routines, anxieties, and dropoff/pickup needs explicit, "
            "while keeping the description concise (1-3 sentences).\n"
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
