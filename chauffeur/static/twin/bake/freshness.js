// One physical freshness contract for the editor, viewer and baker.
export function matchesEntry(expected, stored) {
  return !!expected && !!stored && expected.key === stored.key && expected.location === stored.location &&
    expected.channel === stored.channel && expected.scale === stored.scale &&
    JSON.stringify(expected.pages) === JSON.stringify(stored.pages);
}

export function pageDamage(manifest, page, digest, size) {
  const saved = manifest?.pageIntegrity?.[page];
  return saved && ((saved.digest && digest && saved.digest !== digest) ||
    (size != null && saved.size !== size)) ? `Lightmap page ${page}: damaged stored page` : null;
}
