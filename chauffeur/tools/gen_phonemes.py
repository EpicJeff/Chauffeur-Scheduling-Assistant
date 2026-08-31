"""Render the closed set of English letter sounds through the house's own voice.

WHY THIS IS A TOOL AND NOT A RUNTIME PATH
-----------------------------------------
A general text-to-speech engine handed the letter `c` says "see". A
reading lesson needs /k/. There is no reliable way to make a TTS voice
say a phoneme rather than a letter NAME across engines, voices and
languages, and a letter sound said wrong in an authoritative voice is
worse than silence -- a five-year-old will believe it.

So the set is closed and rendered once: the ~44 English phonemes plus the
26 letter names, written to `static/phonics/` as ordinary files, with a
manifest naming exactly which keys actually have audio behind them.
`services/program_lessons.py` validates a card's `phoneme` against that
manifest, so a key with no file is dropped at the door and the player
draws no speaker tap for it. Missing audio is silence, never a guess.

RUNNING IT (a hand step, on purpose)
------------------------------------
This needs the live Home Assistant add-on environment, where the
household's own Piper voice is reachable -- it is not CI-runnable and it
is not run on boot. From the add-on shell:

    python tools/gen_phonemes.py

It writes `static/phonics/<key>.wav` for every phrase Piper renders and
rewrites `static/phonics/manifest.json` to list exactly those. Re-running
it is safe: it overwrites, and a key whose render fails is left out of
the manifest rather than left pointing at a broken file.

Until it is run the manifest is empty, which is the correct empty state:
cards still speak through `speak`/`speak_lang` in the browser's own
voice (ordinary words, which general TTS says correctly), and only the
per-phoneme taps are absent.
"""
import datetime
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

OUT_DIR = os.path.join(HERE, 'static', 'phonics')
MANIFEST = os.path.join(OUT_DIR, 'manifest.json')

# The closed set, key -> what to have the voice say. Keys are what a
# lesson script writes in a card's `phoneme` field; the SPOKEN half is a
# word or nonsense syllable chosen because a voice says it correctly,
# which is the whole trick -- Piper is never asked to pronounce a symbol.
#
# Consonants first, then short and long vowels, then the digraphs and
# controlled vowels a phonics scheme actually teaches, then letter names.
PHONEMES = {
    'b': 'buh', 'd': 'duh', 'f': 'ff', 'g': 'guh', 'h': 'huh',
    'j': 'juh', 'k': 'kuh', 'l': 'll', 'm': 'mm', 'n': 'nn',
    'p': 'puh', 'r': 'rr', 's': 'ss', 't': 'tuh', 'v': 'vv',
    'w': 'wuh', 'y': 'yuh', 'z': 'zz',
    'ch': 'ch as in chair', 'sh': 'sh as in ship', 'th': 'th as in thin',
    'th_voiced': 'th as in this', 'ng': 'ng as in ring',
    'zh': 'zh as in measure', 'qu': 'kw',
    'a_short': 'a as in cat', 'e_short': 'e as in bed',
    'i_short': 'i as in sit', 'o_short': 'o as in hot',
    'u_short': 'u as in cup',
    'a_long': 'a as in cake', 'e_long': 'e as in feet',
    'i_long': 'i as in kite', 'o_long': 'o as in boat',
    'u_long': 'u as in cube',
    'oo_short': 'oo as in book', 'oo_long': 'oo as in moon',
    'ar': 'ar as in car', 'or': 'or as in fork', 'er': 'er as in her',
    'ow': 'ow as in cow', 'oy': 'oy as in boy', 'air': 'air as in hair',
    'ear': 'ear as in dear', 'schwa': 'a as in about',
}

# Letter NAMES, which are a different thing from letter sounds and are
# routinely wanted on the same card ("this letter is called ess and it
# says /s/"). Prefixed so the two can never collide as keys.
LETTER_NAMES = {f'name_{c}': c for c in 'abcdefghijklmnopqrstuvwxyz'}

ALL = dict(PHONEMES, **LETTER_NAMES)


def _render(key: str, phrase: str) -> bool:
    """One phrase through the household's own Piper voice.

    Returns whether a real file landed. Anything that fails -- no HA, no
    TTS engine configured, a voice that refuses the phrase -- returns
    False and the key stays OUT of the manifest, which is exactly the
    behaviour the no-guessing rule needs.
    """
    from services import announce, ha_api
    tts, language, voice = announce._tts_config()
    if not tts:
        print(f"  no TTS engine configured in Home Assistant; nothing to render")
        return False
    data = {'entity_id': tts, 'message': phrase, 'cache': True}
    if language:
        data['language'] = language
    if voice:
        data['options'] = {'voice': voice}
    # `tts.get_url` hands back a URL to the rendered clip rather than
    # playing it, which is the half of the TTS integration this needs --
    # the announce path plays into a room, and this wants a file.
    # `return_response` comes back inside HA's own wrapper, the same
    # shape ha_api.get_weather_forecast already unwraps.
    res = ha_api.call_service('tts', 'get_url', data, return_response=True)
    sr = (res or {}).get('service_response') or res or {}
    url = sr.get('url') if isinstance(sr, dict) else None
    if not url:
        print(f"  {key}: no url came back")
        return False
    import requests
    base, token = ha_api._base_and_token()
    # HA hands back an absolute URL on some setups and a path on others.
    full = url if url.startswith('http') else base.rstrip('/') + url
    r = requests.get(full, headers={'Authorization': f'Bearer {token}'},
                     timeout=30)
    if not r.ok or not r.content:
        print(f"  {key}: the url would not load ({r.status_code})")
        return False
    with open(os.path.join(OUT_DIR, f'{key}.wav'), 'wb') as f:
        f.write(r.content)
    return True


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    from services import announce
    _, _, voice = announce._tts_config()
    written = {}
    for key, phrase in ALL.items():
        try:
            if _render(key, phrase):
                written[key] = {'say': phrase, 'file': f'{key}.wav'}
                print(f"  {key}: ok")
        except Exception as e:
            print(f"  {key}: {e}")
    manifest = {
        'version': 1,
        'voice': voice or '',
        'generated': datetime.datetime.now().isoformat(timespec='seconds'),
        'note': ('Generated by tools/gen_phonemes.py. Only keys with a real '
                 'file are listed; program_lessons validates against this, so '
                 'a missing sound is silence rather than a guess.'),
        'phonemes': written,
    }
    with io.open(MANIFEST, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    print(f"{len(written)}/{len(ALL)} rendered into {OUT_DIR}")


if __name__ == '__main__':
    main()
