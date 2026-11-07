// Slice 1 has a flat site. Keep the plan and coordinates at every call site
// so terraces can supply the ground height without moving building semantics.
export function groundAt(plan, x, y) {
  const terraces = plan.site?.terraces || [];
  void terraces; void x; void y;
  return 0;
}
