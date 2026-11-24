export const SUPPORT_KINDS = ['walls', 'bracket', 'corbel', 'brace', 'cable', 'post'];

export function isSupported(section) {
  return !!section.support?.kind && section.support.kind !== 'walls';
}
