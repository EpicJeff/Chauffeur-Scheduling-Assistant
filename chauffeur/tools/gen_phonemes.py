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

RUNNING IT (a hand step, on purpose — and NOT on the add-on)
------------------------------------------------------------
Run it from a DEV CHECKOUT pointed at the house's Home Assistant, not
from inside the add-on container. `static/` is baked into the add-on
image, so anything this wrote in there would vanish on the next rebuild —
these files are an ASSET that belongs in the repo, committed and shipped,
exactly like the vendored fonts and the pet artwork beside them.

PowerShell (this repo's usual shell — note that PowerShell has NO inline
`VAR=value command` prefix, so the bash form below silently sets nothing
there and the run fails with no connection at all):

    cd chauffeur
    $env:HA_BASE_URL = 'http://homeassistant.local:8123'
    $env:HA_TOKEN    = '<long-lived token>'
    python tools/gen_phonemes.py

bash:

    cd chauffeur
    HA_BASE_URL=http://homeassistant.local:8123 HA_TOKEN=<long-lived token> \
        python tools/gen_phonemes.py

The token is a long-lived access token from your Home Assistant profile
page (Security → Long-lived access tokens). `ha_api._base_and_token`
takes those two env vars as its dev fallback, which is the whole reason
that fallback exists; `ha_base_url`/`ha_token` in settings work too if
this checkout shares the household's database. `preflight()` below names
which of the three ways this can fail actually happened, once, before
spending anything. Then commit what it wrote and rebuild the add-on.

It is not CI-runnable and never runs on boot.

It writes `static/phonics/<key>.<ext>` for every phrase Piper renders --
the extension comes from what HA's tts_proxy actually served, never
assumed -- and rewrites `static/phonics/manifest.json` to list exactly
those, filename included. Re-running
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


def preflight():
    """What is actually wrong, worked out ONCE and said in words.

    The first cut asked `_tts_config()` inside the render loop, so a
    checkout with no Home Assistant connection at all printed "no TTS
    engine configured in Home Assistant" seventy-one times -- a sentence
    that names the last thing checked rather than the thing that failed,
    repeated once per phoneme. Three states look identical from inside
    that loop and want three different answers: nothing configured, a
    connection that will not answer, and a real HA with no text-to-speech
    integration in it.

    Returns (engine, language, voice), or None having already explained.
    """
    from services import announce, ha_api
    base, token = ha_api._base_and_token()
    if not base or not token:
        # Name what THIS PROCESS can see, not what a person believes they
        # set. `$env:` in PowerShell lives in one window; a variable set
        # in that window and a python started in another (or in Git Bash,
        # which has its own environment entirely) are two different
        # answers to "is it set", and only one of them is this one.
        seen = {k: ('set' if os.environ.get(k) else 'not set')
                for k in ('HA_BASE_URL', 'HA_TOKEN', 'SUPERVISOR_TOKEN')}
        print("This process sees: "
              + ', '.join(f"{k}={v}" for k, v in seen.items()))
        print("No Home Assistant connection configured for this checkout.\n"
              "This tool talks to the house's real HA to borrow its voice, so\n"
              "it needs a base URL and a long-lived access token:\n"
              "\n"
              "  PowerShell:\n"
              "    $env:HA_BASE_URL = 'http://homeassistant.local:8123'\n"
              "    $env:HA_TOKEN    = '<long-lived token>'\n"
              "    python tools/gen_phonemes.py\n"
              "\n"
              "  bash:\n"
              "    HA_BASE_URL=http://homeassistant.local:8123 \\\n"
              "        HA_TOKEN=<long-lived token> python tools/gen_phonemes.py\n"
              "\n"
              "(Create the token in Home Assistant under your profile ->\n"
              "Security -> Long-lived access tokens. PowerShell has no inline\n"
              "VAR=value command prefix, so the bash form silently sets\n"
              "nothing there.)")
        return None
    print(f"Home Assistant: {base}")
    if not ha_api.is_available():
        print("  ...but it did not answer. The line above this one is the\n"
              "  real error: a 401 means the token is wrong, a timeout or a\n"
              "  connection error means the URL is.")
        return None
    engine, language, voice = announce._tts_config()
    if not engine:
        print("  Reached Home Assistant, and it has no tts.* entity at all.\n"
              "  Add a text-to-speech integration first -- Piper is the one\n"
              "  this house is built around (Settings -> Devices & services\n"
              "  -> Add integration -> Piper), and any HA TTS engine works.")
        return None
    print(f"  voice: {engine}"
          + (f" / {voice}" if voice else '')
          + (f" [{language}]" if language else ''))
    return engine, language, voice


def _render(key: str, phrase: str, engine: str, language: str, voice: str):
    """One phrase through the household's own Piper voice.

    Returns the written filename, or None. A phrase the voice refuses
    leaves its key OUT of the manifest, which is exactly the behaviour the
    no-guessing rule needs -- a card whose sound never rendered draws no
    speaker tap rather than a silent one.

    Rendering without playing is an HTTP endpoint, `POST /api/tts_get_url`,
    and NOT a service call: `tts.speak` sends audio at a media player,
    which is what the announce path wants and the opposite of what this
    does. The endpoint hands back `{url, path}` for the clip sitting in
    HA's own tts_proxy cache; `path` is HA-relative, which is the half
    `ha_api.fetch_binary` already knows how to fetch with the token
    attached.

    The extension comes from the RESPONSE, never assumed: HA's tts_proxy
    serves mp3 for most engines and wav for some, and a file named .wav
    holding mp3 bytes plays on nothing.
    """
    from services import ha_api
    body = {'engine_id': engine, 'message': phrase}
    if language:
        body['language'] = language
    if voice:
        body['options'] = {'voice': voice}
    res = ha_api._request('POST', '/tts_get_url', json_body=body)
    path = (res or {}).get('path') or (res or {}).get('url') or ''
    if not path:
        print(f"  {key}: no url came back ({res})")
        return None
    got = ha_api.fetch_binary(path)
    if not got or not got[0]:
        print(f"  {key}: the url would not load")
        return None
    audio, _ = got
    ext = os.path.splitext(path.split('?')[0])[1] or '.mp3'
    name = f'{key}{ext}'
    with open(os.path.join(OUT_DIR, name), 'wb') as f:
        f.write(audio)
    return name


def main():
    ready = preflight()
    if not ready:
        return 1
    engine, language, voice = ready
    os.makedirs(OUT_DIR, exist_ok=True)
    written = {}
    for key, phrase in ALL.items():
        try:
            name = _render(key, phrase, engine, language, voice)
            if name:
                written[key] = {'say': phrase, 'file': name}
                print(f"  {key}: ok ({name})")
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
    if written:
        print("Commit static/phonics/ and rebuild the add-on -- these are "
              "repo assets, not runtime state.")
    return 0 if written else 1


if __name__ == '__main__':
    sys.exit(main())
