"""Typed agent action-proposals for the family chat.

The agent proposes a schedule-changing action as an interactive card; a parent
taps Approve; approval executes the action through the same tested v1/v2 handlers
the agent would call directly. This is the "ask before acting" safety layer:
a proposal is a dismissible card, never a silent mutation, and the approval tap
is where the parent/admin gate is enforced.

Distinct from services/email_ingest event proposals (which create calendar
events from email) — these carry a typed *action* over the scheduler.
"""
import logging
import re
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# --- Implicit detection funnel (Layer 3) -------------------------------------
# Tier 1: a cheap, deterministic keyword pre-filter. High-precision phrases only
# — the cost of a miss (someone must @argyle explicitly) is far lower than the
# cost of the bot butting into ordinary chatter. Expand as measured precision
# from real @argyle usage justifies it.
SUGGESTION_PATTERNS = [
    r"can'?t drive", r"cannot drive", r"can'?t make it", r"won'?t make it",
    r"can'?t do the (pick|drop)", r"can someone (drive|take|pick|grab)",
    r"we'?re out of", r"we are out of", r"need to (buy|grab|pick up)",
    r"reschedul", r"swap (the )?(drive|pickup|dropoff)",
]
_SUGGESTION_RE = re.compile("|".join(SUGGESTION_PATTERNS), re.IGNORECASE)

# Tier 2 confidence needed before the agent is even run on an unsolicited line.
SUGGESTION_CONFIDENCE_THRESHOLD = 0.6


def suggests_action(body: str) -> bool:
    """Tier 1: does this line plausibly imply a schedulable action?"""
    return bool(body) and bool(_SUGGESTION_RE.search(body))


def classify_actionable(body: str) -> Dict[str, Any]:
    """Tier 2: one cheap single-shot LLM classification of whether a family-chat
    line implies a schedule action the agent should offer to handle. Fail-closed
    — any error or missing key returns actionable=False so the funnel never
    butts in on uncertainty. Mocked in tests."""
    from services.storage import get_settings
    settings = get_settings()
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return {"actionable": False, "confidence": 0.0}
    model = settings.get('agent_fallback_model') or 'gemma-4-31b-it'
    system = (
        "You are a strict classifier for a family logistics app. Decide whether the message "
        "implies an action the assistant should offer to handle: reassigning a driver, marking "
        "someone unavailable, changing/rescheduling a drive, or adding an errand/shopping item. "
        "Casual chatter, jokes, and general talk are NOT actionable. Respond ONLY as JSON: "
        '{\"actionable\": true|false, \"confidence\": 0.0-1.0}.'
    )
    try:
        from services.llm import _call_llm_json
        res = _call_llm_json('gemini', '', api_key, model, system, body, tools=None, timeout_s=20)
        return {"actionable": bool(res.get("actionable")),
                "confidence": float(res.get("confidence") or 0.0)}
    except Exception as e:
        logger.warning(f"classify_actionable failed (fail-closed): {e}")
        return {"actionable": False, "confidence": 0.0}

# Actions the agent may propose. Every one changes the schedule/calendar, so
# each requires an approving parent/adult and flags a re-solve on success.
ADMIN_ACTIONS = {
    "reassign_driver", "clear_assignment",
    "add_routing_rule", "delete_routing_rule",
    "add_priority_rule", "delete_priority_rule",
    "add_errand", "update_errand", "delete_errand", "add_errand_rule",
    "create_event",
}

# Human-friendly label shown as the card's action badge.
ACTION_LABELS = {
    "reassign_driver": "Reassign driver",
    "clear_assignment": "Clear assignment",
    "add_routing_rule": "Add rule",
    "delete_routing_rule": "Remove rule",
    "add_priority_rule": "Add priority",
    "delete_priority_rule": "Remove priority",
    "add_errand": "Add errand",
    "update_errand": "Update errand",
    "delete_errand": "Remove errand",
    "add_errand_rule": "Add errand rule",
    "create_event": "Add to calendar",
}


def _is_admin(member) -> bool:
    return bool(member) and member.get('role') in ('parent', 'adult')


def _create_event(payload: dict) -> dict:
    """Insert a calendar event from a proposed create_event action.

    The payload comes straight from the LLM, which reliably emits NAIVE ISO
    datetimes ("2026-08-05T16:00:00") — Google rejects any dateTime without a
    zone ("Missing time zone definition"), which surfaced to parents as a bare
    "the calendar rejected the event" after they'd already tapped Approve. So
    normalize here: naive datetimes get the server's local offset, all-day
    ends are made exclusive (Google's convention), and unparseable times get
    a specific message instead of the generic rejection."""
    from datetime import date, datetime, timedelta
    from services import storage
    from services import calendar as gcal
    title = (payload.get("title") or "").strip()
    start, end = payload.get("start"), payload.get("end")
    if not title or not start or not end:
        return {"status": "error", "message": "I need a title, start, and end time to create an event."}
    calendar_id = payload.get("calendar_id") or storage.get_settings().get("default_calendar_id")
    if not calendar_id:
        return {"status": "error", "message": "No default calendar is set — set one in settings first."}
    if payload.get("all_day"):
        try:
            s = date.fromisoformat(str(start)[:10])
            e = date.fromisoformat(str(end)[:10])
        except ValueError:
            return {"status": "error",
                    "message": f"I couldn't understand those dates ({start} – {end})."}
        if e <= s:
            e = s + timedelta(days=1)   # Google's all-day end date is exclusive
        body_start, body_end = {"date": s.isoformat()}, {"date": e.isoformat()}
    else:
        try:
            s_dt = datetime.fromisoformat(str(start))
            e_dt = datetime.fromisoformat(str(end))
        except ValueError:
            return {"status": "error",
                    "message": f"I couldn't understand those times ({start} – {end}). "
                               "Try again with a specific date and time."}
        if s_dt.tzinfo is None:
            s_dt = s_dt.astimezone()   # naive = server-local
        if e_dt.tzinfo is None:
            e_dt = e_dt.astimezone()
        if e_dt <= s_dt:
            return {"status": "error",
                    "message": f"The end time ({end}) isn't after the start time ({start})."}
        body_start, body_end = {"dateTime": s_dt.isoformat()}, {"dateTime": e_dt.isoformat()}
        # Name the calendar's real zone — an offset-only dateTime pins the
        # event to a fixed GMT offset in the Calendar edit UI.
        tz = gcal.get_calendar_timezone(calendar_id)
        if tz:
            body_start["timeZone"] = body_end["timeZone"] = tz
    body = {"summary": title, "start": body_start, "end": body_end}
    if payload.get("location"):
        body["location"] = payload["location"]
    if payload.get("description"):
        body["description"] = payload["description"]
    gid = gcal.insert_event(calendar_id, body)
    if not gid:
        return {"status": "error",
                "message": f"The calendar rejected the event — check that '{calendar_id}' "
                           "is writable (the server log has Google's exact error)."}
    return {"status": "success", "message": f"Added '{title}' to the calendar."}


def _execute(action_type: str, payload: dict) -> dict:
    """Run an approved action through the tested handlers."""
    from services import agent_tools
    if action_type == "reassign_driver":
        from services.agent_tools_v2 import assign_driver_to_event_fuzzy
        return assign_driver_to_event_fuzzy(payload.get("event_name"),
                                            payload.get("driver_name"),
                                            payload.get("target_date"))
    if action_type == "clear_assignment":
        from services.agent_tools_v2 import remove_override_for_event_fuzzy
        return remove_override_for_event_fuzzy(payload.get("event_name"),
                                               payload.get("target_date"))
    if action_type == "create_event":
        return _create_event(payload)
    if action_type in agent_tools.TOOL_HANDLERS:
        return agent_tools.execute_tool(action_type, payload)
    return {"status": "error", "message": f"Unknown action type '{action_type}'."}


def run_suggestion_funnel(channel: dict, sender: dict, body: str) -> Optional[dict]:
    """Implicit detection (Layer 3), opt-in per family. Tier 1 (keyword) is
    gated by the caller. Here: Tier 2 cheap classify, then run the agent and
    surface a dismissible proposal card ONLY if it produced one. Never mutates
    anything and never posts plain chatter — worst case is a suggestion a parent
    ignores. Suggestion, never action. Returns the posted message (or None)."""
    from services import storage
    from services.agent_router import process_agent_request
    from services.agent_tools_v2 import _post_chat_message
    verdict = classify_actionable(body)
    if not verdict.get("actionable") or verdict.get("confidence", 0) < SUGGESTION_CONFIDENCE_THRESHOLD:
        return None
    try:
        res = process_agent_request(body, source="family", acting_member=sender)
    except Exception as e:
        logger.error(f"Suggestion funnel agent run failed: {e}")
        return None
    card = (res or {}).get("card")
    if not card or not card.get("proposal_id"):
        return None  # agent produced no concrete action — stay silent
    storage.update_action_proposal(card["proposal_id"], {"channel_id": channel["id"]})
    lead = f"It sounds like this might need a change — {res.get('message') or 'want me to handle it?'}"
    try:
        return _post_chat_message(channel, storage.ensure_argyle_member(), lead, card=card)
    except Exception as e:
        logger.error(f"Suggestion post failed: {e}")
        return None


def build_card(proposal_id: str, action_type: str, summary: str, status: str) -> dict:
    """The interactive card payload carried on an Argyle chat message. When the
    proposal is still open it offers Approve/Dismiss; once resolved it renders as
    a static status chip (no live buttons)."""
    actions = []
    if status == "proposed":
        actions = [
            {"label": "Approve", "style": "primary", "proposal_id": proposal_id, "act": "approve"},
            {"label": "Dismiss", "style": "default", "proposal_id": proposal_id, "act": "dismiss"},
        ]
    return {
        "kind": "action_proposal",
        "proposal_id": proposal_id,
        "action_type": action_type,
        "action_label": ACTION_LABELS.get(action_type, action_type),
        "title": summary,
        "status": status,          # proposed | approved | dismissed
        "actions": actions,
    }


def create_action_proposal(action_type: str, summary: str, payload: dict,
                           created_by_member_id: str = None) -> Dict[str, Any]:
    """Store a proposed action; return {status, message, proposal_id, card}."""
    from services import storage
    if action_type not in ADMIN_ACTIONS:
        return {"status": "error", "message": f"'{action_type}' is not a proposable action."}
    summary = (summary or action_type).strip()
    pid = storage.add_action_proposal({
        "action_type": action_type,
        "summary": summary,
        "payload": payload or {},
        "created_by_member_id": created_by_member_id,
        "channel_id": None,
        "requires_admin": True,
    })
    return {"status": "success", "proposal_id": pid,
            "message": summary,
            "card": build_card(pid, action_type, summary, "proposed")}


def act_on_proposal(proposal_id: str, act: str, approver_member: Optional[dict]) -> Dict[str, Any]:
    """Approve or dismiss a proposal. Returns {status, message, card, schedule_dirty}."""
    from services import storage
    prop = storage.get_action_proposal(proposal_id)
    if not prop:
        return {"status": "error", "message": "That action is no longer available."}
    a_type, summary = prop.get("action_type"), prop.get("summary")
    if prop.get("status") != "proposed":
        return {"status": "error",
                "message": f"That action was already {prop.get('status')}.",
                "card": build_card(proposal_id, a_type, summary, prop.get("status"))}

    if act == "dismiss":
        storage.update_action_proposal(proposal_id, {"status": "dismissed"})
        return {"status": "success", "message": f"Dismissed: {summary}",
                "card": build_card(proposal_id, a_type, summary, "dismissed")}

    # approve — the tap is where admin scope is enforced
    if prop.get("requires_admin") and not _is_admin(approver_member):
        return {"status": "error", "message": "Only a parent can approve this.",
                "card": build_card(proposal_id, a_type, summary, "proposed")}
    res = _execute(a_type, prop.get("payload") or {})
    if res.get("status") == "error":
        return {"status": "error", "message": res.get("message") or "That action failed.",
                "card": build_card(proposal_id, a_type, summary, "proposed")}
    storage.update_action_proposal(proposal_id, {
        "status": "approved",
        "approved_by_member_id": (approver_member or {}).get("id"),
    })
    return {"status": "success",
            "message": res.get("message") or f"Done: {summary}",
            "card": build_card(proposal_id, a_type, summary, "approved"),
            "schedule_dirty": a_type in ADMIN_ACTIONS}
