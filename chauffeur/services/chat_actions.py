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
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Actions the agent may propose. Every one mutates global scheduling, so each
# requires an approving parent/adult and flags a re-solve on success.
ADMIN_ACTIONS = {
    "add_routing_rule", "delete_routing_rule",
    "add_priority_rule", "delete_priority_rule",
    "add_errand", "reassign_driver",
}


def _is_admin(member) -> bool:
    return bool(member) and member.get('role') in ('parent', 'adult')


def _execute(action_type: str, payload: dict) -> dict:
    """Run an approved action through the tested handlers."""
    from services import agent_tools
    if action_type == "reassign_driver":
        from services.agent_tools_v2 import assign_driver_to_event_fuzzy
        return assign_driver_to_event_fuzzy(payload.get("event_name"),
                                            payload.get("driver_name"),
                                            payload.get("target_date"))
    if action_type in agent_tools.TOOL_HANDLERS:
        return agent_tools.execute_tool(action_type, payload)
    return {"status": "error", "message": f"Unknown action type '{action_type}'."}


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
