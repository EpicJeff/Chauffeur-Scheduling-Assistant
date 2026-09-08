"""The Home ROOM — the dollhouse the panel lives in.

Spec: docs/superpowers/specs/2026-09-08-house-design.md. The kitchen room
scaled to the whole house. H1: the house's one feed IS the kitchen's feed
(eight sections, unchanged); the garage, curb, mudroom and living sections
join here in H2/H3. All kitchen laws inherited and pinned by
tests/test_house_state.py: reads only, per-section calm, family-safe by
construction.
"""
from services import kitchen_room


def state(since_ts: float = 0, now=None) -> dict:
    return kitchen_room.state(since_ts=since_ts, now=now)
