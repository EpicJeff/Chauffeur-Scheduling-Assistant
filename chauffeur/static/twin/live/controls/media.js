import { controls, title } from './shared.js';

export function mediaControls(options) {
  const c = controls(options), a = c.attrs;
  const service = s => s?.state === 'playing' ? 'media_pause' : c.has(16384) ? 'media_play' : 'media_play_pause';
  const nowPlaying = s => [s?.attributes?.media_title, s?.attributes?.media_artist].filter(Boolean).join(' · ');
  if (c.ring) {
    if (c.has(4)) c.slider('volume', 'Volume', 0, 100, 1, s => Math.round((s?.attributes?.volume_level || 0) * 100),
      'volume_set', v => ({volume_level: v / 100}), false, '%');
    // HA's media controls: previous, play/pause, next across the middle of the dial.
    const row = c.place('row'); row.classList.add('twin-dial-row-media');
    if (c.has(16)) c.button('previous', 'Previous', 'media_previous_track', {}, row, 'previous');
    if (c.has(1) || c.has(16384)) {
      const play = c.button('play', 'Play', service, {}, row, 'play');
      play.classList.add('twin-ring-primary');
      c.watch(s => {
        const playing = s?.state === 'playing';
        play.setAttribute('aria-label', playing ? 'Pause' : 'Play');
        play.querySelector('path')?.setAttribute('d', playing ? 'M8 5v14M16 5v14' : 'M8 5v14l11-7z');
      });
    }
    if (c.has(32)) c.button('next', 'Next', 'media_next_track', {}, row, 'next');
    // What is playing, as text under the controls (no artwork: it needs HA's authentication).
    c.text('now-playing', s => nowPlaying(s) || title(s?.state || 'unavailable'), 'below');
  } else {
    c.text('state', s => s?.state || 'unavailable', c.root);
    if (c.has(1) || c.has(16384)) c.button('play', 'Play / pause', service, {}, c.root);
    if (c.has(16)) c.button('previous', 'Previous', 'media_previous_track', {}, c.root);
    if (c.has(32)) c.button('next', 'Next', 'media_next_track', {}, c.root);
    if (c.has(4)) c.slider('volume', 'Volume', 0, 100, 1, s => Math.round((s?.attributes?.volume_level || 0) * 100),
      'volume_set', v => ({volume_level: v / 100}), false, '%');
  }
  if (c.has(8)) c.toggle('mute', 'Mute', s => s?.attributes?.is_volume_muted, 'volume_mute',
    s => ({is_volume_muted: !s?.attributes?.is_volume_muted}));
  if (c.has(2048)) c.chips('sources', 'Source', a.source_list, s => s?.attributes?.source, 'select_source', 'source');
  if (!c.ring) c.text('now-playing', s => nowPlaying(s) || s?.state || 'unavailable', c.root);
  return c.finish();
}
