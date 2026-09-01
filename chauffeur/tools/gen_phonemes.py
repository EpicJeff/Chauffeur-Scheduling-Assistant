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

It writes `static/phonics/<key>.<ext>` for every phrase the voice renders
-- the extension comes from what HA's tts_proxy actually served, never
assumed -- and rewrites `static/phonics/manifest.json` to list exactly
those, filename included. Re-running it is safe: it overwrites, and a key
whose render fails is dropped from the manifest rather than left pointing
at a broken file.

WHY AN ISOLATED SOUND IS HARD, AND WHAT ACTUALLY WORKS
------------------------------------------------------
A text-to-speech engine phonemizes GRAPHEMES AS WORDS. `k` is the word
"kay"; so is the `k` at the front of "k as in kite". No choice of
spelling fixes that, because the spelling is the thing being read. Three
routes exist and only an ear can rank them:

  1. SSML. An Azure/Edge neural voice -- and this house's own is
     `AndrewNeural`, not Piper, whatever the rest of the docs assume --
     honours `<phoneme alphabet="ipa" ph="k">`, the tag built for exactly
     this. The sound rides an ATTRIBUTE, so there is no spelling left for
     the engine to read as a word. The open question is only whether
     Home Assistant's `tts.speak` hands the markup through or escapes it.
     `--mode ssml` renders the whole set this way once an ear confirms it.
  2. eSpeak's bracket escape, `[[k]]`, for a house running Piper: eSpeak
     reads double square brackets as phonemes rather than letters.
  3. A recording. Forty-five sounds in a parent's own voice is the
     highest-quality answer available and the one a five-year-old would
     rather hear anyway. `overrides.json` takes `{"k": {"file":
     "my_k.wav"}}` and this tool then leaves that key alone entirely.

`IPA` below carries the whole set in IPA, which is the payload for route
1 and the script somebody would read from for route 3.

TUNING IT BY EAR, which is the only way
---------------------------------------
Nothing here can hear its own output. The loop is: render, listen, fix
the one that came out wrong, render that one again.

    python tools/gen_phonemes.py --list          what it will say, no HA needed
    python tools/gen_phonemes.py --probe k       every candidate for /k/, side by side
    python tools/gen_phonemes.py --mode ssml     render the set as IPA phoneme tags
    python tools/gen_phonemes.py --only l,j      re-render just those

Corrections go in `static/phonics/overrides.json`, either as
`{"key": "what to say"}` or `{"key": {"file": "your-recording.wav"}}`.
That file is READ and never written, so a full regeneration cannot
quietly undo a fix somebody made by ear -- and an ear is the only
authority there is about how a letter sounds.

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

# The IPA table below is the whole point of this tool and every character
# in it is outside cp1252, which is what a Windows console still defaults
# to -- printing one crashes the run rather than mis-rendering a glyph.
# `errors='replace'` because a console that cannot draw ʃ should show a
# box, not take the render down.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

OUT_DIR = os.path.join(HERE, 'static', 'phonics')
MANIFEST = os.path.join(OUT_DIR, 'manifest.json')

# The closed set, key -> what to have the voice say.
#
# EVERY ENTRY IS AN EXEMPLAR, and that is a correction rather than a
# style choice. The first cut asked the voice for bare syllables -- `l`
# was "ll", `j` was "juh" -- on the theory that a nonsense spelling would
# come out as the sound. It does not: Piper read "ll" as "ello" and "juh"
# as "jew", which is precisely the failure this whole closed set exists
# to prevent, produced by the set itself. Meanwhile the entries already
# written as "ch as in chair" came out right, because they are made of
# real words and a text-to-speech engine is good at real words and bad at
# everything else.
#
# So the rule, learned by listening: never ask the voice for a sound.
# Ask it for a WORD that contains the sound, in the phrasing a phonics
# lesson uses out loud anyway. It is also what a teacher says.
#
# A voice that happens to nail a bare form is welcome to -- put it in
# `overrides.json` beside this file (see `_phrases()`), which this tool
# reads and never rewrites.
PHONEMES = {
    'b': 'b as in ball', 'd': 'd as in dog', 'f': 'f as in fish',
    'g': 'g as in goat', 'h': 'h as in hat', 'j': 'j as in jam',
    'k': 'k as in kite', 'l': 'l as in leaf', 'm': 'm as in moon',
    'n': 'n as in net', 'p': 'p as in pig', 'r': 'r as in rain',
    's': 's as in sun', 't': 't as in top', 'v': 'v as in van',
    'w': 'w as in wind', 'y': 'y as in yes', 'z': 'z as in zip',
    'ch': 'ch as in chair', 'sh': 'sh as in ship', 'th': 'th as in thin',
    'th_voiced': 'th as in this', 'ng': 'ng as in ring',
    'zh': 'zh as in measure', 'qu': 'qu as in queen',
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

OVERRIDES = os.path.join(OUT_DIR, 'overrides.json')

# eSpeak-NG phoneme mnemonics, for the ONE route that can make a
# text-to-speech engine produce an isolated sound rather than a word.
#
# Piper phonemizes with eSpeak-NG, and eSpeak reads anything inside
# double square brackets as PHONEMES instead of letters: `[[k]]` is the
# /k/ sound, where plain `k` is the letter name "kay". Whether that
# survives the trip through Wyoming and Home Assistant is a question
# nobody can answer by reading -- hence `--probe`, which renders the
# candidates side by side so an ear can decide.
#
# Consonants only. The vowel mnemonics are long and engine-version
# sensitive, and a vowel exemplar ("a as in cat") already carries its
# sound in a real word; the leading letter name is the only wart, and it
# is a smaller one there.
# IPA for the whole set. This is the payload for the SSML route -- an
# Azure/Edge neural voice (this house's own is `AndrewNeural`) honours
# `<phoneme alphabet="ipa" ph="k">`, which is the tag purpose-built for
# exactly this problem and is a completely different mechanism from
# eSpeak's bracket escape below.
#
# It is worth having written down whichever route wins: it is also the
# script a person would read from while recording these by hand.
IPA = {
    'b': 'b', 'd': 'd', 'f': 'f', 'g': 'ɡ', 'h': 'h', 'j': 'dʒ',
    'k': 'k', 'l': 'l', 'm': 'm', 'n': 'n', 'p': 'p', 'r': 'ɹ',
    's': 's', 't': 't', 'v': 'v', 'w': 'w', 'y': 'j', 'z': 'z',
    'ch': 'tʃ', 'sh': 'ʃ', 'th': 'θ', 'th_voiced': 'ð', 'ng': 'ŋ',
    'zh': 'ʒ', 'qu': 'kw',
    'a_short': 'æ', 'e_short': 'ɛ', 'i_short': 'ɪ', 'o_short': 'ɒ',
    'u_short': 'ʌ',
    'a_long': 'eɪ', 'e_long': 'i', 'i_long': 'aɪ', 'o_long': 'oʊ',
    'u_long': 'ju',
    'oo_short': 'ʊ', 'oo_long': 'u',
    'ar': 'ɑɹ', 'or': 'ɔɹ', 'er': 'ɝ', 'ow': 'aʊ', 'oy': 'ɔɪ',
    'air': 'ɛɹ', 'ear': 'ɪɹ', 'schwa': 'ə',
}

ESPEAK = {
    'b': 'b', 'd': 'd', 'f': 'f', 'g': 'g', 'h': 'h', 'j': 'dZ',
    'k': 'k', 'l': 'l', 'm': 'm', 'n': 'n', 'p': 'p', 'r': 'r',
    's': 's', 't': 't', 'v': 'v', 'w': 'w', 'y': 'j', 'z': 'z',
    'ch': 'tS', 'sh': 'S', 'th': 'T', 'th_voiced': 'D', 'ng': 'N',
    'zh': 'Z', 'qu': 'kw',
}


def _phrases():
    """What to say for each key, with the household's own corrections on
    top.

    This tool cannot hear its own output, and neither can whoever asked
    for it until it has run — so the loop that matters is: render, listen,
    fix the one that came out wrong, re-render only that one. A plain
    `{key: "what to say"}` file at `static/phonics/overrides.json` is that
    fix. It is READ here and never written, so a regeneration can never
    quietly undo a correction somebody made by ear, which is the only kind
    of authority there is about how a letter sounds.
    """
    out = dict(ALL)
    for key, val in _overrides().items():
        if key in out and isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out


def _overrides() -> dict:
    """The raw overrides file. A value may be a STRING (say this instead)
    or `{"file": "something.wav"}` (play this instead, rendered by
    nobody).

    The file form is the escape hatch that always works. No engine can be
    made to say an isolated consonant on demand -- see ESPEAK above for
    the one route that might -- and a parent recording forty-four sounds
    in their own voice is both the highest-quality answer available and
    the one a five-year-old would rather hear anyway. Dropping the file
    beside the manifest and naming it here is all that takes.
    """
    try:
        with io.open(OVERRIDES, encoding='utf-8') as f:
            return json.load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[overrides] ignored ({e})")
        return {}


def _probe_texts(key: str, phrase: str) -> list:
    """Every plausible way to ask for one sound, so an ear can pick.

    The problem this exists for: a text-to-speech engine phonemizes
    GRAPHEMES AS WORDS, so `k` is "kay" and `k as in kite` is "kay as in
    kite". Nothing about that is fixable by choosing better words -- it
    needs either an escape out of the text layer entirely (the `[[...]]`
    eSpeak form) or a recording. Which of these a given Piper build
    actually honours is not knowable from here.
    """
    # A letter NAME is the one thing every engine already gets right --
    # "kay" is a word to a phonemizer, which is exactly why the sound is
    # hard and the name is not. Nothing to audition.
    if key.startswith('name_'):
        return [phrase]
    letter = key.split('_')[0]
    out = []
    ipa = IPA.get(key)
    if ipa:
        # SSML, the route built for this. An Azure/Edge neural voice --
        # which is what this house actually runs, `AndrewNeural` --
        # honours `<phoneme alphabet="ipa">`; whether Home Assistant's
        # tts.speak hands the markup through untouched or escapes it is
        # the open question, and is exactly what listening answers.
        # Wrapped and bare, because integrations differ on whether they
        # add the <speak> envelope themselves.
        out.append('<speak version="1.0" '
                   'xmlns="http://www.w3.org/2001/10/synthesis" '
                   f'xml:lang="en-US"><phoneme alphabet="ipa" ph="{ipa}">'
                   f'{letter}</phoneme></speak>')
        out.append(f'<phoneme alphabet="ipa" ph="{ipa}">{letter}</phoneme>')
    if key in ESPEAK:
        # eSpeak's own escape, for a house running Piper instead.
        out.append(f"[[{ESPEAK[key]}]]")
    out.append(phrase)                       # what ships today
    out.append(letter + 'uh')                # the syllable guess
    out.append(letter)                       # the letter name, as a control
    exemplar = phrase.split(' as in ')
    if len(exemplar) == 2:
        out.append(exemplar[1])              # the bare word
    seen, uniq = set(), []
    for t in out:
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


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


def _ssml(key: str, letter: str) -> str:
    """One key as an SSML phoneme tag. The whole point of the SSML route:
    the sound is carried by an IPA attribute rather than by a spelling,
    so there is nothing left for the engine to read as a word."""
    return ('<speak version="1.0" '
            'xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xml:lang="en-US"><phoneme alphabet="ipa" ph="{IPA[key]}">'
            f'{letter}</phoneme></speak>')


def main():
    phrases = _phrases()
    argv = sys.argv[1:]

    # --mode ssml switches every key that HAS an IPA form over to the
    # phoneme tag, in one pass, for the house whose engine honours it.
    # Letter names stay plain text: a name is a word, and the tag would be
    # solving a problem they do not have. Overrides still win over both --
    # a correction made by ear outranks any mechanism.
    if '--mode' in argv:
        i = argv.index('--mode')
        mode = argv[i + 1] if i + 1 < len(argv) else ''
        if mode not in ('text', 'ssml'):
            print("--mode takes 'text' (default) or 'ssml'.")
            return 1
        if mode == 'ssml':
            pinned = set(_overrides())
            for key in list(phrases):
                if key in IPA and key not in pinned:
                    phrases[key] = _ssml(key, key.split('_')[0])

    # --list spends nothing and needs no connection: it is how you read
    # what the voice is about to be asked for, which is the half of this
    # you can check without listening to seventy-one files.
    if '--list' in argv:
        for key in sorted(phrases):
            print(f"  {key:12} {phrases[key]}")
        print(f"\n{len(phrases)} keys. Override any of them in {OVERRIDES} "
              f"as {{\"key\": \"what to say\"}} and re-run with "
              f"--only <keys>.")
        return 0

    # --only re-renders a subset, because the real loop here is listen,
    # fix the one that came out wrong, render that one again. Making that
    # cost a full pass over every key is how a person stops bothering.
    only = []
    if '--only' in argv:
        i = argv.index('--only')
        if i + 1 < len(argv):
            only = [k.strip() for k in argv[i + 1].split(',') if k.strip()]
        unknown = [k for k in only if k not in phrases]
        if unknown:
            print(f"Not keys: {', '.join(unknown)}. Try --list.")
            return 1

    # --probe renders every plausible way of asking for one sound, side by
    # side, so the choice is made by listening instead of by me guessing a
    # third time. Nothing here can hear its own output; this is the whole
    # answer to that.
    probe = ''
    if '--probe' in argv:
        i = argv.index('--probe')
        if i + 1 < len(argv):
            probe = argv[i + 1].strip()
        if probe not in phrases:
            print(f"Not a key: {probe!r}. Try --list.")
            return 1

    ready = preflight()
    if not ready:
        return 1
    engine, language, voice = ready
    os.makedirs(OUT_DIR, exist_ok=True)

    if probe:
        print(f"\nProbing {probe!r} — listen to each and put the winner in\n"
              f"{OVERRIDES} as {{\"{probe}\": \"<the text that worked>\"}}.\n")
        for n, text in enumerate(_probe_texts(probe, phrases[probe]), 1):
            name = _render(f'probe_{probe}_{n}', text, engine, language, voice)
            print(f"  {n}. {'ok ' if name else 'FAILED'} {name or '':22} "
                  f"said: {text!r}")
        print("\nThese probe_* files are scratch — delete them once you have "
              "picked.\nIf none of them is the real sound, that is the honest "
              "answer for this\nvoice: record it instead and name the file in "
              "overrides.json as\n{\"" + probe + "\": {\"file\": \"my_" + probe
              + ".wav\"}}.")
        return 0

    # A partial run must not delete the rest of the manifest, so it starts
    # from what is already there and replaces only what it re-rendered.
    written = {}
    if only:
        try:
            with io.open(MANIFEST, encoding='utf-8') as f:
                written = (json.load(f) or {}).get('phonemes') or {}
        except Exception:
            written = {}

    raw = _overrides()
    todo = {k: phrases[k] for k in (only or sorted(phrases))}
    for key, phrase in todo.items():
        # A key whose override names a FILE is not rendered at all: it is
        # somebody's own recording, which outranks anything an engine can
        # be talked into. Checked for existence, because a manifest entry
        # pointing at a file nobody put there is the exact broken-tap
        # state the closed set exists to prevent.
        pinned = raw.get(key)
        if isinstance(pinned, dict) and pinned.get('file'):
            fname = str(pinned['file'])
            if os.path.exists(os.path.join(OUT_DIR, fname)):
                written[key] = {'say': '(recorded)', 'file': fname}
                print(f"  {key:12} kept — your own recording, {fname}")
            else:
                written.pop(key, None)
                print(f"  {key:12} SKIPPED — {fname} is not in {OUT_DIR}")
            continue
        try:
            name = _render(key, phrase, engine, language, voice)
            if name:
                written[key] = {'say': phrase, 'file': name}
                print(f"  {key:12} ok  — said: {phrase!r}")
            else:
                written.pop(key, None)
        except Exception as e:
            print(f"  {key}: {e}")
            written.pop(key, None)
    manifest = {
        'version': 1,
        # sorted so a re-render produces a reviewable diff rather than a
        # reshuffled file.
        'keys': len(written),
        'voice': voice or '',
        'generated': datetime.datetime.now().isoformat(timespec='seconds'),
        'note': ('Generated by tools/gen_phonemes.py. Only keys with a real '
                 'file are listed; program_lessons validates against this, so '
                 'a missing sound is silence rather than a guess.'),
        'phonemes': written,
    }
    with io.open(MANIFEST, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    print(f"{len(written)}/{len(phrases)} keys have audio in {OUT_DIR}")
    if written:
        print("Commit static/phonics/ and rebuild the add-on -- these are "
              "repo assets, not runtime state.")
    return 0 if written else 1


if __name__ == '__main__':
    sys.exit(main())
