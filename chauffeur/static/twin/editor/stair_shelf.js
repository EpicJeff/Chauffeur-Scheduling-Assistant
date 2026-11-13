// Same plain label/select fields as porch_foundation_shelf; shared by Add and selection.
export function stairShelf(host, stair, building, { canEdit, change, report }) {
  const section = document.createElement('section'); host.append(section);
  const from = building.levels.find(l => l.id === stair.level);
  const targets = building.levels.filter(l => l.elevation > from.elevation).sort((a, b) => a.elevation - b.elevation);
  const target = stair.to_level || targets.find(l => l.elevation === stair.rise_to)?.id || '';
  for (const [field, title, choices, value] of [
    ['width', 'Width (ft)', null, stair.width ?? 3],
    ['to_level', 'To level', [...(!target ? [['', `Height ${stair.rise_to} ft`]] : []), ...targets.map(l => [l.id, l.name || l.id])], target],
    ['style', 'Style', ['solid', 'open'], stair.style || 'solid'],
    ['rail', 'Rails', ['none', 'left', 'right', 'both'], stair.rail || 'none'],
  ]) {
    const label = document.createElement('label'); label.textContent = title;
    const input = document.createElement(choices ? 'select' : 'input');
    if (choices) for (const choice of choices) {
      const [value, text] = Array.isArray(choice) ? choice : [choice, choice[0].toUpperCase() + choice.slice(1)];
      const option = document.createElement('option'); option.value = value; option.textContent = text; input.append(option);
    } else { input.type = 'number'; input.min = '2'; input.max = '8'; input.step = 'any'; }
    input.value = String(value); input.setAttribute('aria-label', title); input.disabled = !canEdit(); label.append(input); section.append(label);
    input.addEventListener('change', () => {
      if (!canEdit()) return;
      const value = field === 'width' ? Number(input.value) : input.value;
      if (field === 'width' && (!input.value.trim() || !Number.isFinite(value) || value < 2 || value > 8)) {
        report(new Error('Choose a stair width from 2 to 8 ft.')); return;
      }
      if (field === 'to_level' && !value) return;
      Promise.resolve().then(() => canEdit() && change(field, value)).catch(report);
    });
  }
}
