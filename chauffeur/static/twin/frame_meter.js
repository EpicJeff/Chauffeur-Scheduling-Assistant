// Frame meter (?perf=1): what a frame costs on this screen, and a render-scale switch that
// tells a slow fill rate (speeds up at 50%) from a slow scene (does not).
const SCALES = [1, .75, .5];
const SOFTWARE = /swiftshader|llvmpipe|softpipe|software/i;

export function mountFrameMeter(el, { renderer3, gpu, tier, pixelRatio, stats }) {
  const box = document.createElement('div'), text = document.createElement('div'), button = document.createElement('button');
  box.className = 'twin-frame-meter';
  box.style.cssText = 'position:fixed;left:8px;top:8px;z-index:9999;font:12px/1.4 ui-monospace,Consolas,monospace;' +
    'color:#fff;background:rgba(0,0,0,.78);padding:8px 10px;border-radius:8px;white-space:pre;max-width:92vw;overflow:hidden';
  button.type = 'button';
  button.style.cssText = 'margin-top:6px;padding:6px 10px;border-radius:6px;border:1px solid #fff;background:transparent;color:#fff;font:inherit';
  box.append(text, button); el.appendChild(box);
  // A tap on the meter is not a tap on the house.
  for (const name of ['pointerdown', 'pointerup', 'click']) box.addEventListener(name, event => event.stopPropagation());
  let scale = 0, frames = 0, since = performance.now(), last = since, worst = 0, script = 0;
  const label = () => { button.textContent = `Render scale ${Math.round(SCALES[scale] * 100)}% (tap to change)`; };
  button.addEventListener('click', () => {
    scale = (scale + 1) % SCALES.length;
    renderer3.setPixelRatio(pixelRatio * SCALES[scale]); label();
  });
  label();
  const write = (now) => {
    const span = now - since, s = stats(), canvas = renderer3.domElement;
    text.textContent = [
      `${(frames * 1000 / span).toFixed(1)} fps   ${(span / frames).toFixed(1)} ms a frame (worst ${worst.toFixed(0)})`,
      `script ${(script / frames).toFixed(1)} ms a frame`,
      `${s.drawCalls} draws   ${s.triangles} triangles`,
      `${canvas.width} x ${canvas.height} px   tier ${tier}`,
      gpu || 'GPU unknown',
      ...(SOFTWARE.test(gpu || '') ? ['SOFTWARE RENDERING: the graphics chip is not in use'] : []),
    ].join('\n');
  };
  return {
    // now: the frame's clock; scriptMs: time this frame spent in the page's own draw call.
    frame(now, scriptMs) {
      worst = Math.max(worst, now - last); last = now; ++frames; script += scriptMs;
      if (now - since < 500) return;
      write(now); frames = 0; since = now; worst = 0; script = 0;
    },
    stop() { box.remove(); renderer3.setPixelRatio(pixelRatio); },
  };
}
