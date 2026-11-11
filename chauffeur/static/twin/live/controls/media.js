import { controls } from './shared.js';

export function mediaControls(options) {
  const c = controls(options), a = c.attrs;
  c.text('state', s => s?.state || 'unavailable', true);
  if (c.has(1) || c.has(16384)) c.button('play', 'Play / pause', s => s?.state === 'playing' ? 'media_pause' : 'media_play');
  if (c.has(16)) c.button('previous', 'Previous', 'media_previous_track');
  if (c.has(32)) c.button('next', 'Next', 'media_next_track');
  if (c.has(4)) c.slider('volume', 'Volume', 0, 100, 1, s => Math.round((s?.attributes?.volume_level || 0) * 100),
    'volume_set', v => ({volume_level: v / 100}), false, '%');
  if (c.has(8)) c.toggle('mute', 'Mute', s => s?.attributes?.is_volume_muted, 'volume_mute',
    s => ({is_volume_muted: !s?.attributes?.is_volume_muted}));
  if (c.has(2048)) c.chips('sources', 'Source', a.source_list, s => s?.attributes?.source, 'select_source', 'source');
  c.text('now-playing', s => [s?.attributes?.media_title, s?.attributes?.media_artist].filter(Boolean).join(' · ') || s?.state || 'unavailable');
  return c.finish();
}
