import json
import urllib.request
import urllib.error
from typing import List, Tuple, Dict
from models.schemas import Rule, PriorityRule
from services import llm_budget

ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'
ANTHROPIC_MODELS_URL = 'https://api.anthropic.com/v1/models'
OPENAI_URL = 'https://api.openai.com/v1/responses'
OPENAI_MODELS_URL = 'https://api.openai.com/v1/models'
DEFAULT_MAX_OUTPUT = 8192
_EFFORT = {'low': 'low', 'medium': 'medium', 'high': 'high'}


def effort_for(bare_model: str, thinking_level, is_pro: bool) -> str:
    if thinking_level in _EFFORT:
        return _EFFORT[thinking_level]
    return 'medium' if is_pro else 'low'


def _is_pro(bare_model: str) -> bool:
    from services import model_pools
    return any(bare_model in pools['pro'] for pools in model_pools.PROVIDER_POOLS.values())


def _send_with_retries(req, timeout_s, transient_retries, model, label, metrics):
    """Paid-provider transport with the same retry/error contract as Gemini."""
    try:
        for attempt in range(transient_retries + 1):
            try:
                with llm_budget.urlopen(req, timeout=timeout_s) as resp:
                    return json.loads(resp.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                if e.code in (500, 502, 503, 504) and attempt < transient_retries:
                    import time
                    wait_s = 2 * (attempt + 1)
                    print(f"{label} API returned {e.code} for {model} "
                          f"(attempt {attempt + 1}/{transient_retries + 1}), retrying in {wait_s}s...")
                    time.sleep(wait_s)
                    continue
                raise
    except llm_budget.Deferred:
        raise
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        if metrics is not None:
            metrics['http_status'] = e.code
        if e.code == 429:
            return {'error': f"429 Too Many Requests: {error_body}"}
        raise RuntimeError(f"{label} API request failed: {str(e)}\nDetails: {error_body}")
    except Exception as e:
        raise RuntimeError(f"{label} API request failed: {str(e)}")


def test_llm_connection(provider: str, url: str = None, api_key: str = None, model: str = None) -> Tuple[bool, str]:
    """
    Tests the connection to the selected model provider.
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
            with llm_budget.urlopen(req, timeout=5) as resp:
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
            gemini_model = model or 'gemini-3.5-flash-lite'
            if gemini_model.startswith('models/'):
                gemini_model = gemini_model[7:]
            req_url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
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
            with llm_budget.urlopen(req, timeout=8) as resp:
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
            
    elif provider in ('anthropic', 'openai'):
        label = 'Claude' if provider == 'anthropic' else 'OpenAI'
        if not api_key:
            return False, f"{label} API key is required."
        url = ANTHROPIC_MODELS_URL if provider == 'anthropic' else OPENAI_MODELS_URL
        headers = ({'x-api-key': api_key, 'anthropic-version': '2023-06-01'} if provider == 'anthropic'
                   else {'Authorization': f'Bearer {api_key}'})
        try:
            with llm_budget.urlopen(urllib.request.Request(url, headers=headers, method='GET'), timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            ids = [m.get('id') for m in data.get('data', [])]
            from services import model_pools
            table = sorted({m for pool in model_pools.PROVIDER_POOLS[provider].values() for m in pool})
            missing = [m for m in table if m not in ids] + ([model] if model and model not in ids and model not in table else [])
            n = f"{len(ids)} model" + ('' if len(ids) == 1 else 's')
            if missing:
                return True, f"Connected to {label} ({n} listed), but this key does not list: {', '.join(missing)}. Pick another model in the pool settings."
            return True, f"Successfully connected to {label}! {n} listed."
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode('utf-8')).get('error', {}).get('message', str(e))
            except Exception:
                msg = f"{e.code} {e.reason}"
            return False, f"{label} API Error: {msg}"
        except Exception as e:
            return False, f"Unexpected error connecting to {label}: {str(e)}"

    return False, "Invalid provider selected."

def call_model(model_id: str, api_key: str, system_prompt: str, user_prompt: str, text: bool = False, **kw) -> dict:
    """Dispatch by the id's provider prefix (model_pools.split_model): the
    bare id goes on the wire. `text=True` asks for prose back ({'text': ...})
    instead of parsed JSON."""
    from services import model_pools
    prov, bare = model_pools.split_model(model_id)
    return _call_llm_json(prov, '', api_key, bare, system_prompt, user_prompt, text=text, **kw)


def _call_llm_json(provider: str, url: str, api_key: str, model: str, system_prompt: str, user_prompt: str, temperature: float = 0.1, tools: list = None, timeout_s: int = 180, images: list = None, metrics: dict = None, max_output_tokens: int = None, transient_retries: int = 2, thinking_level: str = None, strict_json: bool = False, response_schema: dict = None, use_system_instruction: bool = False, text: bool = False) -> dict:
    from services.app_voice import current as phone_voice, MODEL_ATTEMPT_TIMEOUT
    phone_turn = phone_voice.get()
    if phone_turn is not None:
        from services import model_pools
        from services.storage import get_settings
        full = model if provider == 'gemini' else f'{provider}:{model}'
        if provider == 'ollama' or not model_pools.is_lite(full, get_settings()):
            return {'error': 'That work needs the text/background path; voice uses the interactive lite tier.'}
        timeout_s = min(timeout_s, phone_turn.remaining(), MODEL_ATTEMPT_TIMEOUT)
        transient_retries = 0
    # images: [{'mime': 'image/jpeg', 'b64': '<base64>'}]; Ollama ignores them.
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
            if tools:
                payload["tools"] = [{"type": "function", "function": t} for t in tools]
            req = urllib.request.Request(
                req_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with llm_budget.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode('utf-8'))

                # Check if it returned a tool call
                message = data.get('message', {})
                if 'tool_calls' in message:
                    tool_calls = []
                    for tc in message['tool_calls']:
                        if 'function' in tc:
                            tool_calls.append({
                                'name': tc['function']['name'],
                                'arguments': tc['function']['arguments']
                            })
                    return {"tool_calls": tool_calls, "message": ""}
                
                raw_response = message.get('content', '')
                if text:
                    return {'text': raw_response.strip()}
        except Exception as e:
            raise RuntimeError(f"Ollama request failed: {str(e)}")
            
    elif provider == 'gemini':
        try:
            gemini_model = model or 'gemini-3.5-flash-lite'
            if gemini_model.startswith('models/'):
                gemini_model = gemini_model[7:]
            req_url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
            separate_system = use_system_instruction and not gemini_model.startswith('gemma')
            user_parts = [{"text": user_prompt if separate_system
                           else f"{system_prompt}\n\nUser Request: {user_prompt}"}]
            for img in (images or []):
                user_parts.append({"inline_data": {
                    "mime_type": img.get('mime') or 'image/jpeg',
                    "data": img['b64'],
                }})
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": user_parts
                    }
                ],
                "generationConfig": {
                    "temperature": temperature
                }
            }
            
            if tools:
                payload["tools"] = [{"functionDeclarations": tools}]
            if separate_system:
                payload['systemInstruction'] = {'parts': [{'text': system_prompt}]}
            if max_output_tokens is not None:
                payload['generationConfig']['maxOutputTokens'] = max_output_tokens
            if thinking_level is not None:
                payload['generationConfig']['thinkingConfig'] = (
                    {'thinkingBudget': {'low': 1024, 'medium': 4096, 'high': 8192}.get(thinking_level, 1024)}
                    if gemini_model.startswith('gemini-2.5-') else {'thinkingLevel': thinking_level})
            if response_schema is not None:
                payload['generationConfig']['responseJsonSchema'] = response_schema
            if strict_json or response_schema is not None:
                payload['generationConfig']['responseMimeType'] = 'application/json'
                
            req = urllib.request.Request(
                req_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            # Transient 5xx (e.g. 503 "model experiencing high demand") gets a
            # short backoff and retry before we give up on this model.
            data = None
            for attempt in range(transient_retries + 1):
                try:
                    with llm_budget.urlopen(req, timeout=timeout_s) as resp:
                        data = json.loads(resp.read().decode('utf-8'))
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (500, 502, 503, 504) and attempt < transient_retries:
                        import time
                        wait_s = 2 * (attempt + 1)
                        print(f"Gemini API returned {e.code} for {gemini_model} "
                              f"(attempt {attempt + 1}/3), retrying in {wait_s}s...")
                        time.sleep(wait_s)
                        continue
                    raise
            if metrics is not None:
                metrics.update(data.get('usageMetadata') or {})
                metrics['modelVersion'] = data.get('modelVersion', gemini_model)
                metrics['finish_reason'] = (data.get('candidates') or [{}])[0].get('finishReason')
            if strict_json and (data.get('candidates') or [{}])[0].get('finishReason') != 'STOP':
                finish = (data.get('candidates') or [{}])[0].get('finishReason') or 'NO_CANDIDATE'
                usage = data.get('usageMetadata') or {}
                raise RuntimeError(f"Incomplete Gemini JSON response (finish={finish}; output_tokens={usage.get('candidatesTokenCount', 0)}; thinking_tokens={usage.get('thoughtsTokenCount', 0)}; limit={max_output_tokens})")
            try:
                parts = data['candidates'][0]['content']['parts']

                # Check for tool call
                tool_calls = []
                text_resp = ""
                for part in parts:
                    if 'functionCall' in part:
                        fc = part['functionCall']
                        tool_calls.append({
                            'name': fc['name'],
                            'arguments': fc['args']
                        })
                    if 'text' in part:
                        text_resp += part['text']

                if tool_calls:
                    return {"tool_calls": tool_calls, "message": text_resp}

                raw_response = text_resp
                if text:
                    return {'text': raw_response.strip()}
            except (KeyError, IndexError, TypeError):
                raise RuntimeError("Unexpected response format from Gemini API")
        except llm_budget.Deferred:
            raise
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            if metrics is not None:
                metrics['http_status'] = e.code
            if e.code == 429:
                return {"error": f"429 Too Many Requests: {error_body}"}
            raise RuntimeError(f"Gemini API request failed: {str(e)}\nDetails: {error_body}")
        except Exception as e:
            raise RuntimeError(f"Gemini request failed: {str(e)}")
    elif provider == 'anthropic':
        content = [{'type': 'text', 'text': user_prompt}]
        for img in (images or []):
            content.append({'type': 'image', 'source': {
                'type': 'base64', 'media_type': img.get('mime') or 'image/jpeg', 'data': img['b64']}})
        payload = {
            'model': model, 'max_tokens': max_output_tokens or DEFAULT_MAX_OUTPUT,
            'system': system_prompt,
            'messages': [{'role': 'user', 'content': content}],
            'output_config': {'effort': effort_for(model, thinking_level, _is_pro(model))},
        }
        if response_schema is not None:
            payload['output_config']['format'] = {'type': 'json_schema', 'schema': response_schema}
        req = urllib.request.Request(
            ANTHROPIC_URL, data=json.dumps(payload).encode('utf-8'), method='POST',
            headers={'Content-Type': 'application/json', 'x-api-key': api_key, 'anthropic-version': '2023-06-01'})
        data = _send_with_retries(req, timeout_s, transient_retries, model, 'Claude', metrics)
        if isinstance(data, dict) and data.get('error'):
            return data
        if metrics is not None:
            usage = data.get('usage') or {}
            metrics.update({'promptTokenCount': usage.get('input_tokens', 0),
                            'candidatesTokenCount': usage.get('output_tokens', 0),
                            'modelVersion': model, 'finish_reason': data.get('stop_reason')})
        if data.get('stop_reason') == 'refusal':
            cat = (data.get('stop_details') or {}).get('category') or 'unspecified'
            return {'error': f'refused: {cat}'}
        if strict_json and data.get('stop_reason') != 'end_turn':
            usage = data.get('usage') or {}
            raise RuntimeError(f"Incomplete Claude JSON response (finish={data.get('stop_reason')}; output_tokens={usage.get('output_tokens', 0)}; limit={max_output_tokens})")
        raw_response = ''.join(b.get('text', '') for b in (data.get('content') or []) if b.get('type') == 'text')
        if text:
            return {'text': raw_response.strip()}
    elif provider == 'openai':
        content = [{'type': 'input_text', 'text': user_prompt}]
        for img in (images or []):
            content.append({'type': 'input_image',
                            'image_url': f"data:{img.get('mime') or 'image/jpeg'};base64,{img['b64']}",
                            'detail': 'auto'})
        payload = {
            'model': model, 'instructions': system_prompt,
            'input': [{'role': 'user', 'content': content}],
            'max_output_tokens': max_output_tokens or DEFAULT_MAX_OUTPUT,
            'reasoning': {'effort': effort_for(model, thinking_level, _is_pro(model))},
        }
        if response_schema is not None:
            payload['text'] = {'format': {'type': 'json_schema', 'name': 'result', 'schema': response_schema, 'strict': False}}
        elif strict_json:
            payload['text'] = {'format': {'type': 'json_object'}}
        req = urllib.request.Request(
            OPENAI_URL, data=json.dumps(payload).encode('utf-8'), method='POST',
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'})
        data = _send_with_retries(req, timeout_s, transient_retries, model, 'OpenAI', metrics)
        if isinstance(data, dict) and data.get('error'):
            return data
        if metrics is not None:
            usage = data.get('usage') or {}
            metrics.update({'promptTokenCount': usage.get('input_tokens', 0),
                            'candidatesTokenCount': usage.get('output_tokens', 0),
                            'modelVersion': model, 'finish_reason': data.get('status')})
        if strict_json and data.get('status') != 'completed':
            raise RuntimeError(f"Incomplete OpenAI JSON response (status={data.get('status')}; reason={(data.get('incomplete_details') or {}).get('reason')}; limit={max_output_tokens})")
        raw_response = ''.join(c.get('text', '') for item in (data.get('output') or []) if item.get('type') == 'message'
                               for c in (item.get('content') or []) if c.get('type') == 'output_text')
        if text:
            return {'text': raw_response.strip()}
    else:
        raise ValueError(f"Unknown provider: {provider}")
        
    try:
        if strict_json:
            return json.loads(raw_response.strip())
        import re
        match = re.search(r'```+(?:json)?\s*\n?([\s\S]*?)\n?\s*```+', raw_response)
        if match:
            return json.loads(match.group(1).strip())
            
        decoder = json.JSONDecoder()
        valid_objs = []
        i = 0
        while i < len(raw_response):
            if raw_response[i] in ('{', '['):
                try:
                    obj, length = decoder.raw_decode(raw_response[i:])
                    valid_objs.append(obj)
                    i += length
                    continue
                except json.JSONDecodeError:
                    pass
            i += 1
                    
        if valid_objs:
            return valid_objs[-1]
            
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
        
    from services import model_pools
    res = model_pools.pooled_or_direct(provider, url, api_key, model, 'heavy', system_prompt, overrides_text)
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
- For 'buffer' rules, you must set 'buffer_before_mins' and/or 'buffer_after_mins' (integers). Set 'buffer_reason' to WHY they need to be there early in the family's own words ('Warm-up', 'Check-in', 'Sound check') when they said it, or null. It is shown to them, so never invent a reason they did not give.
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
      "buffer_reason": null,
      "duplicate_action": null,
      "attendance_action": null,
      "is_ai_generated": true
    }}
  ],
  "priority_rules": []
}}
Do NOT wrap the output in markdown code blocks like ```json ... ```. Just return raw JSON.
"""
    
    from services import model_pools
    res = model_pools.pooled_or_direct(provider, url, api_key, model, 'heavy', system_prompt, "Please analyze the original vs modified schedules and generate the rules.")
    return res

def auto_name_conversation(conversation_id: str, first_message: str):
    from services import storage
    import json
    import urllib.request
    try:
        settings = storage.get_settings()
        provider = (settings.get('llm_provider') or 'gemini')
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
            with llm_budget.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                title = data.get('message', {}).get('content', '')
        else:
            # One tiny call per new conversation: the interactive tier's first
            # model on whichever provider is selected, prose back, never JSON.
            from services import model_pools
            model_id, api_key = model_pools.credentials('interactive', settings)
            if api_key:
                res = call_model(model_id, api_key, 'You name conversations.', prompt, text=True, timeout_s=30, temperature=0.3)
                title = res.get('text', '') if isinstance(res, dict) else ''

        title = title.strip().replace('"', '')
        if title:
            storage.update_conversation_title(conversation_id, title)
    except Exception as e:
        print(f"Error auto-naming conversation: {e}")
