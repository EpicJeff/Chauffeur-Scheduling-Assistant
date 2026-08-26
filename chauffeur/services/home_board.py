"""What the wall panel shows when nobody has asked it for anything.

Every other Chauffeur surface answers a question you arrived with: which
chores are unclaimed, what are we eating, where is everyone. A panel screwed
to the kitchen wall is looked at by somebody walking past with their hands
full, who asked nothing. So the board is built around one claim — **the hero
says the next thing that is actually about to happen**, and the tiles below it
are glances, not pages.

Three rules the tiles follow, because a wall display fails differently from a
web page:

1. **Hide what is not SET UP; never hide what is merely quiet.**

   The first version of this rule was "a tile with nothing to say renders
   nothing", and it was wrong in practice — the panel kept dropping to four
   tiles and the family could not tell whether the map was empty or broken.
   The mistake was conflating two different silences. A household that has
   never made a shopping list wants no Lists tile; a household with a list
   that happens to be empty tonight wants to SEE that it is empty. Same for
   the map (where everyone is has no empty day), the calendar, and chores and
   routines once any are configured.

   So a builder returns `None` only when the feature is unconfigured, and
   otherwise returns a payload — possibly `{'empty': "…"}`, which renders as
   an honest sentence. The original instinct still holds where it belongs: a
   grid of boxes explaining that they are empty is the characteristic failure
   of every wall dashboard, and `{'empty': …}` is a real answer rather than a
   placeholder. What it is NOT is a reason to make a configured feature vanish.
2. **One request, one cache.** The tiles are assembled server-side and served
   as ONE payload, so a six-tile board costs one HTTP request per tick instead
   of six. `TTL_SECONDS` then protects the DB and Home Assistant when a second
   panel (or an HA dashboard card) polls on its own offset.
3. **Nothing here computes, proposes, or writes.** The meals tile reads the
   PINNED plate and shows nothing when none is pinned — it deliberately does
   not call `get_or_compose_plate`, which would compose a proposal (and
   persist one) every 60 seconds forever. A display that changes what it is
   displaying is not a display.
"""

def _member_image(m):
    """The chip image for a member dict: their photo, or their character
    (avatar arc A2). One decision, made in avatar_render, not per tile."""
    from services import avatar_render
    return avatar_render.effective_image(m)


import datetime
import json
import os
import re
import time
from typing import Callable, List, Optional

from services import leave_by, scope, storage

# ── The option vocabulary.
#
# Every tile type declares what it can be asked, and the editor renders those
# declarations rather than carrying a hand-built form per type. The point is
# that a tile's options live NEXT TO the builder that reads them: the pair that
# drifts apart in a system like this is "what the editor offers" and "what the
# code honours", and one list is the only real defence.
#
#   text    a free string
#   int     a number, clamped to min/max here and again in the builder
#   bool    a switch
#   choice  one of `choices`, which are fixed and known at import
#   select  one or many of a live list — `source` names it, and the catalog
#           ships the current contents, because members, drivers, lists and
#           trips are household data and cannot be enumerated here
#
# An option's DEFAULT is what the tile does when nobody has said otherwise, and
# it is a LITERAL. `days` on the calendar used to start from a board-wide
# `panel_agenda_days` setting instead, which made sense while a board had one
# calendar and stopped making sense the moment tiles became instances: two
# calendars on one board, one showing three days and one showing a fortnight,
# is the whole point of instances, and a board-wide number is a second place to
# set a thing each card already owns. Removed in v2.229.2.
# How far a calendar tile looks ahead when nobody has said. Five days is a
# working week seen from a Monday; the calendar page's agenda offers 1–14 and
# this is the middle of that. Declared HERE rather than beside the other
# drawing constants because it is an option's default, and the option
# vocabulary is built at import — a constant defined below it is a NameError,
# which is exactly how this landed the first time.
AGENDA_DAYS = 5


def _opt(key, label, type_, default=None, **extra):
    o = {'key': key, 'label': label, 'type': type_, 'default': default}
    o.update(extra)
    return o


# Offered on every tile, appended in `catalog()` rather than repeated fifteen
# times. Two calendar tiles need different NAMES more than they need anything
# else — "What's coming" twice is a board that cannot be read.
TITLE_OPTION = _opt('title', 'Title', 'text', '',
                    help="What this tile is called on the board. "
                         "Blank uses the standard name.")

# The other half of the heading, and offered for the same reason. Every entry
# in the catalog ships an emoji that says what KIND of thing it is — 🚗 for the
# driving schedule, ⭐ for chores — and for most of them that is the right
# answer forever. It stops being one the moment a tile is generic: Custom,
# Card, Entities, Camera and Web page are 🧩 🃏 🏠 📷 🌐 whatever they were
# pointed at, so a board with the back-door camera, the front-door camera and
# the radar on it is three tiles wearing the same 📷. The type cannot know; the
# household does. Appended here rather than declared five times, because it
# means exactly one thing everywhere and a tile that already has a good default
# loses nothing by being able to override it.
ICON_OPTION = _opt('icon', 'Icon', 'emoji', '',
                   help="The emoji beside the title. Blank uses the standard "
                        "one for this kind of tile.")


def _cfg_int(config, key, default, lo, hi):
    try:
        return max(lo, min(hi, int((config or {}).get(key, default))))
    except (TypeError, ValueError):
        return default


def _cfg_bool(config, key, default):
    v = (config or {}).get(key)
    return default if v is None else bool(v)


def _cfg_str(config, key, default=''):
    v = (config or {}).get(key)
    return default if v is None else str(v).strip()


def _cfg_choice(config, key, allowed, default):
    """A `choice` option's value, refused rather than trusted.

    Stored config is data a household typed into `?widgets=` or an older build
    wrote — the screensaver's `folder` is the standing lesson, where one side
    stored a word the other had never heard of and the feature silently fell
    back forever. A value outside the vocabulary is the default, and the
    vocabulary lives beside the option that declares it."""
    v = _cfg_str(config, key)
    return v if v in allowed else default


def _cfg_ids(config, key):
    """A multi-select's value. EMPTY MEANS EVERYONE, always, on every tile that
    takes one — the alternative is a tile that shows nothing until you have
    ticked somebody, which reads as broken rather than as unconfigured."""
    v = (config or {}).get(key)
    if not isinstance(v, list):
        return []
    return [str(x) for x in v if str(x).strip()]


# The catalog.
#
# `label` is the tile's NAME — and it is the name of the page it summarises,
# deliberately. It used to be the sentence the tile prints on the wall ("The
# rest of the day", "Where everyone is"), which read beautifully on a board and
# was useless in a picker: a household choosing from nineteen of them is asking
# "which of these is the map", and a list of small poems does not answer that.
#
# `heading` is that sentence, kept, because it was doing a second job well. So
# the picker says Map and the wall says "Where everyone is", and an instance's
# own `title` still beats both. A tile with no `heading` falls back to `label`,
# which is right for the ones whose page name is already the best thing to
# print (Lists).
#
# `blurb` is what it is FOR, which is what somebody choosing actually reads.
# `options` is what one instance can be asked; a type with none is a tile that
# only knows one thing to say.
WIDGETS = [
    # ── This list is the CARD catalog.
    #
    # Every entry below draws a piece of content and nothing else — no heading,
    # no icon, no link out. That chrome belongs to the tile the card sits in,
    # which is what makes a card usable anywhere: a chores card is the same
    # drawing whether it is the whole of a built-in Chores tile or one of five
    # things in a tile somebody assembled.
    #
    # A TILE is one of two things, and both are containers:
    #   * a BUILT-IN tile — this list's own entries, offered by name in the
    #     picker, each one a locked container holding exactly one card of that
    #     type. Nothing about them changed when cards arrived, which is the
    #     point: the surface a household already knows still works.
    #   * a CUSTOM tile — the entry immediately below. Starts empty, takes any
    #     number of cards, and lays them out on its own grid.
    #
    # Because a built-in tile's stored shape is still `{id, type, config}` with
    # the type naming its one card, no board anywhere needed migrating.
    {'key': 'custom', 'icon': '🧩', 'label': 'Custom',
     'heading': '',
     'container': True,
     'blurb': "An empty tile you fill with cards and lay out yourself.",
     'options': [
         # Two panels around one card is the clutter this answers: a card
         # already draws its own surface, so a tile drawing another behind it
         # is a box inside a box. Bare, the cards float on the board.
         _opt('bare', 'No panel behind the cards', 'bool', False,
              help='The cards keep their own surfaces; the tile stops drawing '
                   'one behind them.'),
     ]},
    # ── The board's own chrome, as tiles. Until v2.209 the clock strip and
    # the hero band were hardcoded template markup above the grid, drawn on
    # every board unconditionally — which made every "new" board a copy of
    # the home page and put the strip beyond the reach of every layout tool.
    # As tiles they are addable, movable, resizable and deletable like
    # everything else, and a new board is genuinely blank. Boards stored
    # before the change are migrated in _page_from, so no wall changes.
    {'key': 'clock', 'icon': '🕰️', 'label': 'Clock & weather',
     'heading': '',
     'blurb': "Time, date and weather — the strip the home board leads with.",
     'options': [
         _opt('days', 'Forecast days', 'int', 4, min=0, max=7,
              help='0 hides the forecast.'),
     ]},
    {'key': 'hero', 'icon': '🚦', 'label': "What's next",
     'heading': '',
     'blurb': "The next drive — or the honest empty state — leading the board.",
     'options': []},
    {'key': 'heading', 'icon': '🔤', 'label': 'Heading',
     'heading': '',
     'blurb': "Big text that names a board, the way a page names itself.",
     'options': [
         _opt('size', 'Size', 'choice', 'xl', choices=[
             {'value': 'xl', 'label': 'Page title'},
             {'value': 'lg', 'label': 'Section'}]),
     ]},
    {'key': 'drives', 'icon': '🚗', 'label': 'Driving schedule',
     'heading': 'The rest of the day',
     'blurb': "Every drive still ahead today, and who has it.",
     'options': [
         # The timeline is the Drives page's own renderer, and it draws one
         # section PER DAY in its range — the same multi-day view the Schedule
         # page shows in kiosk mode. So `days` applies to both shapes, and the
         # choice between them is about WIDTH, not about span: an hour rail
         # needs room, and a tile too narrow for one can still say the same
         # thing as a list.
         _opt('view', 'View', 'choice', 'timeline', choices=[
             {'value': 'timeline', 'label': 'Timeline'},
             {'value': 'list', 'label': 'Compact list'}]),
         # ON by default, the same call the calendar card made and for the
         # same reason: this card IS the Drives page's drawing, and the page's
         # one irreplaceable tap is opening a drive to see where it goes, who
         # has it and when to leave. Overlay in place — the SHARED details
         # dialog the calendar opens, so a wall has one answer to "what is
         # this event" rather than two. Off, the tile goes back to being a
         # door onto the Drives page.
         _opt('interactive', 'Interactive', 'bool', True,
              help='Tapping a drive opens its details. Off, the timeline is '
                   'a display and the tile opens the Drives page.'),
         _opt('days', 'Days', 'int', 1, min=1, max=14,
              help='One timeline per day, as the Schedule page shows them.'),
         _opt('drivers', 'Drivers', 'select', [], source='drivers', multi=True,
              help='Leave empty for everyone.'),
         _opt('errands', 'Show errands', 'bool', True),
     ]},
    {'key': 'kids', 'icon': '🎒', 'label': 'Kids',
     'heading': 'Each kid',
     'blurb': "The same calm look at the day each child gets in their digest.",
     'options': [
         _opt('members', 'Children', 'select', [], source='members', multi=True,
              help='Leave empty for every child.'),
         _opt('lines', 'Lines each', 'int', 4, min=1, max=8),
         # The conversion paradigm, which this card predates by a year. The
         # day caption in particular: it is the one thing in the drawing that
         # is not about a specific child, and the first household to put this
         # card on a board went looking for the setting that removed it.
         _opt('show_figure', 'The standing character', 'bool', True),
         _opt('figure_compact', 'Compact avatar (small face)', 'bool', False,
              help='On, the block shows the small face instead of the full '
                   'figure - for pages that already show the figure nearby.'),
         _opt('show_day', 'Which day this is', 'bool', True,
              help='The strip flips between today and tomorrow at the '
                   'evening cutover, and says which.'),
         _opt('show_header', 'Name & avatar', 'bool', True),
         _opt('show_streak', 'The streak count', 'bool', True),
         _opt('show_tasks', 'School tasks', 'bool', True),
         _opt('show_routines', 'How many routine things', 'bool', True),
     ]},
    {'key': 'meals', 'icon': '🍽️', 'label': 'Meals',
     'heading': "Tonight's plate",
     'blurb': "What is planned to eat, once a plate is pinned for the day.",
     'options': [
         # Nights, not days: a plate is pinned per date, and 1 is tonight.
         # More than one turns the tile from "what is on the table" into "what
         # is planned", which is a different question and a different shape.
         _opt('nights', 'Nights', 'int', 1, min=1, max=7,
              help='1 is tonight. More shows the plan ahead.'),
         _opt('offset', 'Starting', 'int', 0, min=0, max=7,
              help='0 is today, 1 is tomorrow.'),
     ]},
    {'key': 'lists', 'icon': '🛒', 'label': 'Lists',
     'heading': 'Lists',
     'blurb': "How much is open on each shopping list.",
     'options': [
         _opt('list', 'List', 'select', '', source='lists',
              help='One list, or leave empty for all of them.'),
         # 12 because that is what the tile already showed — the server
         # sends twelve names and the panel rendered all of them. A new
         # default here would have been a silent redesign of every board.
         _opt('items', 'Items shown', 'int', 12, min=0, max=20,
              help='0 shows the counts only.'),
     ]},
    # ── The shopping page, as cards (kiosk-boards arc). `shopping` above is
    # the GLANCE — how much is open on each list. These three are the page's
    # own drawings (components/shopping_lists.html): the week's dinners, the
    # "we've run out of this" chips, and the list itself with its tick.
    {'key': 'meals_week', 'icon': '📆', 'label': 'The nights ahead',
     'heading': '',
     'blurb': "A block per night with what is planned, how much work it is, "
              "and whether the evening is tight.",
     'options': [
         # Nights from TODAY, straight through the shop boundary. The span
         # split is real and it stays on the page, where it decides which run
         # an ingredient goes on; it means nothing to somebody walking past
         # the kitchen wanting to know what is for dinner.
         _opt('nights', 'Nights', 'int', 7, min=1, max=7),
         _opt('show_image', 'Pictures', 'bool', True),
         _opt('show_sides', 'The rest of the plate', 'bool', True),
         _opt('show_effort', 'How long it takes', 'bool', True),
         _opt('show_squeeze', 'Warn when the evening is tight', 'bool', True),
     ]},
    {'key': 'shopping_staples', 'icon': '🧺', 'label': 'Drop in the cart',
     'heading': '',
     'blurb': "A chip per thing the household keeps on hand. Tap one to say "
              "you have run out and it goes on the list.",
     'options': [
         # ON by default, and safe there: tapping a chip puts a LINE on the
         # list for this shop and changes nothing about whether the household
         # treats the thing as a staple. Tap again to undo.
         _opt('interactive', 'Interactive', 'bool', True,
              help='Tap to add, tap again to undo. Off, the chips only show '
                   'what is already on the list.'),
         # No `empty` of "All" here, and this is the one shopping option
         # where blank cannot mean it: a tap puts a LINE somewhere, and
         # "somewhere" has to be one list.
         _opt('list', 'List', 'select', '', source='lists',
              empty='The default list',
              help='Which list a tap adds to. Empty uses the default.'),
         _opt('show_hint', 'The line explaining the tap', 'bool', True),
     ]},
    {'key': 'shopping_list', 'icon': '📝', 'label': 'The shopping list',
     'heading': '',
     'blurb': "Every line still to buy, split by shop run, with a tick for "
              "what is in the cart.",
     'options': [
         _opt('interactive', 'Interactive', 'bool', True,
              help='Ticking a line moves it to the cart. Off, the list is a '
                   'display.'),
         # Blank means EVERY list, and it now does. It used to mean "the
         # household default", which on every real install is the grocery
         # list — so a picker reading All showed the groceries and nothing
         # else, and a second list somebody made was unreachable from a
         # board. The card draws one section per list instead.
         _opt('list', 'List', 'select', '', source='lists',
              help='One list, or leave empty for every list in the scope '
                   'below.'),
         # WHY a scope and not just the picker above: a shipped board cannot
         # name a household's list. "The grocery list" is a different id in
         # every install, and the two boards this app ships need exactly that
         # distinction — Meals & Groceries owns the main list, Shopping &
         # Lists is every OTHER one. `is_default` is the app's own word for
         # "the list every capture path falls back to", which on every real
         # install is the groceries, so it is the one household-independent
         # way to say which.
         _opt('scope', 'Which lists', 'choice', 'all', choices=[
             {'value': 'all', 'label': 'Every list'},
             {'value': 'default', 'label': 'The main list only'},
             {'value': 'others', 'label': 'Everything except the main list'}],
              help='The main list is the household default — the grocery list '
                   'the Meals & Groceries page owns. Ignored when a single '
                   'list is pinned above.'),
         # A list is NARROW and a wall is wide, so several of them stacked
         # down a landscape tile is a column of text with a field of empty
         # panel beside it. This is how many go across before the next one
         # wraps to a new line. `auto` is the default and the honest one: a
         # board's tiles are all different widths and this one is on a
         # kitchen wall AND a phone, so "as many as fit" is a better answer
         # than a number somebody has to re-guess per screen — the same
         # bargain Fill makes against a typed height. A stated number still
         # collapses on a tile too narrow to honour it; nothing here can push
         # a list below being readable.
         _opt('columns', 'Lists per row', 'choice', 'auto', choices=[
             {'value': 'auto', 'label': 'As many as fit'},
             {'value': '1', 'label': 'One'},
             {'value': '2', 'label': 'Two'},
             {'value': '3', 'label': 'Three'},
             {'value': '4', 'label': 'Four'}],
              help='Ignored when the card is pinned to a single list.'),
         _opt('show_runs', 'Split by shop run', 'bool', True),
         _opt('show_cart', 'What is already in the cart', 'bool', True),
         _opt('show_note', 'Notes on a line', 'bool', True),
         _opt('show_byline', 'Who added it', 'bool', True),
     ]},
    {'key': 'chores', 'icon': '⭐', 'label': 'Chores',
     'heading': 'Chore points',
     'blurb': "The points leaderboard, exactly as the chores kiosk shows it.",
     'options': [
         _opt('members', 'People', 'select', [], source='members', multi=True,
              help='Leave empty for everyone with points.'),
         _opt('count', 'Rows', 'int', 6, min=1, max=12),
     ]},
    # ── The chores kiosk, as cards (board-cards arc): the leaderboard is the
    # `chores` tile above; these two are the kiosk's other drawings, rendered
    # from the SAME macros the kiosk page renders
    # (components/chores_lanes.html), so the wall can never drift from it.
    {'key': 'chores_lanes', 'icon': '🧒', 'label': 'Chore lanes',
     'heading': '',
     'blurb': "The kiosk's per-child lanes: chores, rewards and goals, one column per kid.",
     'options': [
         # ON by default (user decision 2026-08-13): an inert lanes card is
         # the leaderboard with extra steps — the card's whole purpose is
         # the tap. Off remains for walls that really are just displays.
         _opt('interactive', 'Interactive', 'bool', True,
              help='Claim, Done and Redeem buttons on the card. Off, the '
                   'lanes are a display.'),
         _opt('members', 'Children', 'select', [], source='members', multi=True,
              help='Leave empty for everyone.'),
         # THE CONVERSION PARADIGM: every part of the page's drawing is a
         # toggle on the card, all on by default — so a card can be exactly
         # the slice of the kiosk a board wants ("Emma's chores": one
         # member, header off, title typed).
         _opt('show_figure', 'The standing character', 'bool', True),
         _opt('show_header', 'Name & points', 'bool', True),
         _opt('show_goals', 'Family goals', 'bool', True),
         _opt('show_rewards', 'Rewards', 'bool', True),
         _opt('show_mine', 'Claimed chores', 'bool', True),
         _opt('show_available', 'Available chores', 'bool', True),
     ]},
    {'key': 'chores_rewards', 'icon': '🎯', 'label': 'Family goals',
     'heading': '',
     'blurb': "The pooled-reward thermometers, one per shared goal.",
     'options': []},
    {'key': 'packing', 'icon': '🗓️', 'label': 'Family day',
     'heading': "The family's day",
     'blurb': "Everything happening today and what has to be ready for it "
              "— trips, home, and who is driving.",
     'options': [
         # ON by default, the same reasoning the lanes card settled: a packing
         # list nobody can tick is a poster. Off remains for a wall that really
         # is only a display.
         _opt('interactive', 'Interactive', 'bool', True,
              help='Tick things off on the wall. Off, the card is a display.'),
         _opt('members', 'People', 'select', [], source='members', multi=True,
              help='Leave empty for the whole household.'),
         # The agenda this card replaces shows a week, and prep for tomorrow
         # morning has to be visible tonight — a one-day card cannot show
         # work that belongs to the evening before.
         _opt('days', 'Days', 'int', 1, min=1, max=7,
              help='How many days ahead to show. One day is just today.'),
     ]},
    {'key': 'routines', 'icon': '🔁', 'label': 'Routines',
     'heading': 'Streaks',
     'blurb': "Who has kept their routine going, and for how long.",
     'options': [
         _opt('members', 'People', 'select', [], source='members', multi=True,
              help='Leave empty for everyone with a routine.'),
         _opt('count', 'Rows', 'int', 6, min=1, max=12),
     ]},
    # ── The routines kiosk, as a card. `routines` above is the GLANCE — who
    # has kept theirs going and for how long. This is the kiosk's own lanes:
    # today's checklist per child, with the tap that ticks one off.
    {'key': 'avatar_editor', 'icon': '🪞', 'label': 'Avatar editor',
     'heading': '',
     'blurb': "Tap a face, build your look. The dressing-up box as a card, "
              "for anyone who wants to give it a wall of its own.",
     'options': [
         _opt('members', 'People', 'select', [], source='members', multi=True,
              help='Leave empty for everyone.'),
         _opt('figures', 'Standing characters', 'bool', True,
              help='Off, the card is a compact row of faces.'),
     ]},
    {'key': 'pets', 'icon': '🐾', 'label': 'Pets',
     'heading': '',
     'blurb': "Everyone's critter, and a way in to build one. Tap a pet to "
              "open the editor; an empty slot is the invitation to hatch.",
     'options': [
         _opt('members', 'People', 'select', [], source='members', multi=True,
              help='Leave empty for everyone.'),
         _opt('show_unhatched', 'Empty slots', 'bool', True,
              help='Off, the card shows only creatures that exist.'),
         _opt('show_level', 'Level and element', 'bool', True),
         _opt('show_owner', 'Whose pet it is', 'bool', True),
         _opt('interactive', 'Tap to edit', 'bool', True,
              help='Off, the card is a display shelf.'),
     ]},
    {'key': 'routines_lanes', 'icon': '✅', 'label': 'Routine lanes',
     'heading': '',
     'blurb': "Today's routine for each child, with a tap to tick one off. "
              "The routines kiosk's own lanes.",
     'options': [
         _opt('interactive', 'Interactive', 'bool', True,
              help='Tapping a line ticks it off for that child. Off, the '
                   'lanes are a display.'),
         _opt('members', 'People', 'select', [], source='members', multi=True,
              help='Leave empty for everyone with a routine.'),
         _opt('show_figure', 'The standing character', 'bool', True),
         _opt('show_header', 'Name & avatar', 'bool', True),
         _opt('show_status', 'The earned status', 'bool', True),
         _opt('show_streak', 'The streak count', 'bool', True),
         _opt('show_progress', "Today's progress bar", 'bool', True),
         _opt('show_items', "Today's checklist", 'bool', True),
     ]},
    {'key': 'occasions', 'icon': '🎁', 'label': 'Occasions',
     'heading': 'Coming up',
     'blurb': "The next occasion and how many days are left to get ready.",
     'options': [
         _opt('count', 'Rows', 'int', 3, min=1, max=10),
         _opt('within_days', 'Within', 'int', None, min=1, max=365,
              help='Days ahead. Blank shows everything that is coming.'),
     ]},
    {'key': 'weather', 'icon': '🌤️', 'label': 'Weather',
     'heading': 'The week',
     'blurb': "A forecast chip per day. Needs a Home Assistant weather entity.",
     'options': [
         _opt('days', 'Days', 'int', 5, min=1, max=7),
     ]},
    {'key': 'moments', 'icon': '📸', 'label': 'Moments',
     'heading': 'Latest moments',
     'blurb': "Recent photos from the family's events.",
     'options': [
         # ON by default: a mosaic of thumbnails whose only affordance is
         # "leave for the gallery" is a worse version of tapping the picture
         # you were already looking at. It opens the SAME full-screen overlay
         # a brand-new moment pops on the wall by itself — one drawing, so a
         # tapped photo and an announced one cannot look like different apps.
         _opt('interactive', 'Interactive', 'bool', True,
              help='Tapping a photo opens it full screen. Off, the tile is a '
                   'display and opens the Moments page.'),
         _opt('count', 'Photos', 'int', 6, min=1, max=12),
         _opt('within_days', 'Going back', 'int', 30, min=1, max=365,
              help='Days. A wall of last summer is a screensaver, not a board.'),
     ]},
    # ── The moments PAGE, as a card (kiosk-boards arc). `moments` above is the
    # GLANCE — the last few photos as a mosaic, right on a home board beside
    # eight other tiles. This is the page's own two-level gallery, and its
    # absence is what made the Moments BOARD wrong: `?panel=true` on /moments
    # drew the mosaic, so a family walking up to the Moments screen got "here
    # are six recent pictures" where the page says "here is every activity you
    # have ever shared, pick one". Reported exactly that way.
    #
    # Self-fetching (rule 4) and necessarily so: it is the whole history, two
    # levels deep, paged on scroll. Nothing about that can ride in a board
    # payload that five other cards are waiting on — which is also why this
    # builder ships CONFIG and one fact the client cannot know for itself.
    {'key': 'moments_gallery', 'icon': '🖼️', 'label': 'The moments gallery',
     'heading': '',
     'blurb': "Every activity with moments, a block each. Tapping one opens "
              "its photos, with a way back. The Moments page's own gallery.",
     'options': [
         # ON by default: an inert gallery is the mosaic with extra steps, and
         # drilling into an event is the entire point of the top level. Off,
         # the blocks are a display and nothing opens.
         _opt('interactive', 'Interactive', 'bool', True,
              help='Tapping an activity opens its moments, with a button back '
                   'to the list. Off, the blocks are a display.'),
         _opt('lightbox', 'Photos open full screen', 'bool', True,
              help='Inside an activity, tapping a photo opens it big.'),
         # A wall is read from across a room; a browser is not. The page picks
         # this from `?kiosk=true` and a card cannot, so it is asked.
         _opt('tile_width', 'Block width', 'int', 260, min=140, max=600,
              help='Pixels, minimum. The grid fits as many as the tile is '
                   'wide — bigger blocks, fewer of them.'),
         # THE CONVERSION PARADIGM: every part of the page's drawing is a
         # toggle, all on by default, so zero-config equals the page.
         _opt('show_count', 'How many moments', 'bool', True),
         _opt('show_who', 'Who shared them', 'bool', True),
         _opt('show_when', 'When', 'bool', True),
         _opt('show_body', 'What they said', 'bool', True),
         _opt('show_reactions', 'Reactions', 'bool', True),
     ]},
    {'key': 'calendar', 'icon': '📅', 'label': 'Calendar',
     'heading': "What's coming",
     'blurb': "The next few days on the family calendar, drives or not.",
     'options': [
         # The four the calendar page offers, plus the board's own two. Month,
         # week and day are the PAGE's grid, mounted here from the shared
         # component; agenda and list are drawn from this payload and need no
         # library at all, which is why an agenda card on a wall panel
         # downloads nothing.
         _opt('view', 'View', 'choice', 'agenda', choices=[
             {'value': 'agenda', 'label': 'A card per day'},
             {'value': 'list', 'label': 'One list, next first'},
             {'value': 'month', 'label': 'Month grid'},
             {'value': 'week', 'label': 'Week grid'},
             {'value': 'day', 'label': 'One day, by the hour'}]),
         _opt('view_selector', 'Show the view buttons', 'bool', False,
              help='Lets somebody change the view on the wall. Off pins the '
                   'card to the view above.'),
         # ON by default (the conversion paradigm) and freshly earned: this
         # card IS the calendar page's content now, and the page's one
         # irreplaceable tap is opening an event. Overlay in place, never a
         # navigation — doors are wrong for taps inside a drawing.
         _opt('interactive', 'Interactive', 'bool', True,
              help='Tapping an event opens its details. Off, the calendar '
                   'is a display.'),
         _opt('show_legend', 'The people legend', 'bool', True,
              help='The per-person chips under the calendar; tapping one '
                   'hides that person on this card.'),
         _opt('days', 'Days', 'int', AGENDA_DAYS, min=1, max=14,
              help='How far ahead this calendar looks.'),
         _opt('members', 'People', 'select', [], source='members', multi=True,
              help="Matches each person's own calendars. Empty shows everyone."),
         _opt('all_day', 'Include all-day events', 'bool', True),
     ]},
    {'key': 'errands', 'icon': '📋', 'label': 'Errands',
     'heading': 'Errands waiting',
     'blurb': "What still needs doing, past-due first.",
     'options': [
         _opt('count', 'Rows', 'int', 5, min=1, max=12),
         _opt('past_due_only', 'Past due only', 'bool', False),
     ]},
    {'key': 'tasks', 'icon': '📝', 'label': 'Household tasks',
     'heading': 'The household owes',
     'blurb': "Work with a deadline and nowhere to drive — past due first, "
              "and what nobody has taken.",
     'options': [
         _opt('count', 'Rows', 'int', 6, min=1, max=12),
         _opt('members', 'Owner', 'select', [], source='members', multi=True,
              help='Leave empty for the whole household.'),
         _opt('unclaimed_only', 'Only what nobody has taken', 'bool', False),
     ]},
    # ── The errands page, as cards (kiosk-boards arc). The two above are
    # GLANCES — four rows on a home board saying what is waiting. These two
    # are the page's actual lists, drawn from the SAME macros the errands page
    # renders (components/errand_lists.html), with the taps that finish
    # something and none of the editors: a natural-language errand parser on a
    # screen with no keyboard is furniture.
    {'key': 'task_list', 'icon': '🧾', 'label': 'The household list',
     'heading': '',
     'blurb': "Every household task, with a tick to finish one. The errands "
              "page's own list.",
     'options': [
         # ON by default: an inert list is the glance tile with extra steps,
         # and the tick is the whole reason a wall panel has this on it.
         _opt('interactive', 'Interactive', 'bool', True,
              help='A tick-box that finishes a task. Off, the list is a '
                   'display.'),
         _opt('count', 'Rows', 'int', 12, min=1, max=40),
         _opt('members', 'Owner', 'select', [], source='members', multi=True,
              help='Leave empty for the whole household.'),
         _opt('unclaimed_only', 'Only what nobody has taken', 'bool', False),
         # THE CONVERSION PARADIGM: every part of the page's drawing is a
         # toggle, all on by default, so zero-config equals the page.
         _opt('show_load', 'The load sentence', 'bool', True),
         _opt('show_due', 'Due dates', 'bool', True),
         _opt('show_owner', "Who's doing it", 'bool', True),
         _opt('show_recurrence', 'Repeats', 'bool', True),
     ]},
    {'key': 'errand_list', 'icon': '🧭', 'label': 'The errand list',
     'heading': '',
     'blurb': "Every errand waiting, past due first, with a tick to finish "
              "one. The errands page's own list.",
     'options': [
         _opt('interactive', 'Interactive', 'bool', True,
              help='A tick-box that finishes an errand, and Reschedule on '
                   'anything past due. Off, the list is a display.'),
         _opt('count', 'Rows per section', 'int', 12, min=1, max=40),
         _opt('past_due_only', 'Past due only', 'bool', False),
         _opt('show_past_due', 'The past-due band', 'bool', True),
         _opt('show_open', 'What is still waiting', 'bool', True),
         _opt('show_completed', 'What is done', 'bool', True),
         _opt('show_location', 'Where it is', 'bool', True),
         _opt('show_when', 'Start and scheduled times', 'bool', True),
     ]},
    {'key': 'trips', 'icon': '🧭', 'label': 'Trips',
     'heading': 'Next trip',
     'blurb': "The next trip and how long until it starts.",
     'options': [
         _opt('trip', 'Trip', 'select', '', source='trips',
              empty='Whatever is next',
              help='One trip, or leave empty for whatever is next.'),
         _opt('count', 'Trips shown', 'int', 4, min=1, max=8,
              help='Ignored when a single trip is pinned.'),
     ]},
    # ── The trips PAGE, as a card (kiosk-boards arc). `trips` above is the
    # GLANCE — the next trip and how long until it starts, as a small collage.
    # This is the page's own gallery: a big photograph per trip carrying its
    # status, dates, where it is and how many stops are planned, and each one
    # opens the trip. Its absence made the Trips BOARD the same mistake the
    # Moments board was: `?panel=true` on /trips drew the collage, so walking
    # up to the Trips screen got you one trip block with no way into any of
    # them, where the page is a gallery you browse.
    {'key': 'trips_gallery', 'icon': '🖼️', 'label': 'The trips gallery',
     'heading': '',
     'blurb': "A photograph per trip — status, dates, where and how many "
              "stops — and tapping one opens it. The Trips page's own gallery.",
     'options': [
         # ON by default: a gallery of trips you cannot open is a slideshow.
         # Opening a trip IS a navigation here (the trip viewer is its own
         # page), unlike the calendar's dialog or the moments overlay — so
         # this card stays a door, it just points each card at its own trip
         # instead of all of them at the trips list.
         _opt('interactive', 'Interactive', 'bool', True,
              help='Tapping a trip opens it. Off, the gallery is a display '
                   'and the tile opens the Trips page.'),
         _opt('count', 'Trips shown', 'int', 0, min=0, max=40,
              help='0 shows every one.'),
         # The page shows recent trips with a "Past" badge, so the card does
         # too — zero-config equals the page. A wall that only wants what is
         # ahead turns it off.
         _opt('show_past', 'Trips already over', 'bool', True,
              help='Badged as past, sorted below what is still coming.'),
         _opt('tile_width', 'Block width', 'int', 320, min=180, max=700,
              help='Pixels, minimum. The grid fits as many as the tile is wide.'),
         # THE CONVERSION PARADIGM: every part of the page's drawing is a
         # toggle, all on by default.
         _opt('show_status', 'The status badge', 'bool', True),
         _opt('show_dates', 'Dates', 'bool', True),
         _opt('show_location', 'Where it is', 'bool', True),
         _opt('show_pois', 'How many stops', 'bool', True),
     ]},
    {'key': 'map', 'icon': '🗺️', 'label': 'Map',
     'heading': 'Where everyone is',
     'blurb': "Who is home, out, or driving. Needs Home Assistant.",
     'options': [
         # OFF by default, and the ONE interactive option in this catalog that
         # breaks the paradigm's "on where there are taps" — deliberately.
         # Panning is the only interaction a map has, and it is the only one
         # that PERSISTS: a chore ticked off stays ticked because that is the
         # point, but a map dragged half a county sideways by somebody
         # squeezing past the panel stays there until a human fixes it. The
         # tile is also the board's door onto the Map page, and a Leaflet map
         # swallows that tap. So it is a picture of the map unless a household
         # says otherwise — and when they do, the tile grows a ⌖ that puts the
         # view back, so nobody can strand it.
         _opt('interactive', 'Interactive', 'bool', False,
              help='Pan, zoom and tap a pin for who it is, with a ⌖ to frame '
                   'everyone again. Off, the map is a picture and tapping '
                   'the tile opens the Map page.'),
         # The three things on this map are switched independently, because a
         # household asked for a card that shows the CARS and nothing else —
         # and the members filter could not express it. "Everyone" and
         # "nobody" are different answers and an empty multi-select already
         # means the first one, so the second needs its own switch.
         # THREE SOURCES, each with the same pair of controls: a switch and a
         # picker. Asked for in exactly those words — "choose which vehicles
         # and buses show the same way you can choose which people show" —
         # after a map that guessed put a school bus on a grandmother.
         # Empty picker means all of that kind; it never means none, which is
         # what the switch beside it is for.
         _opt('people', 'Show people', 'bool', True,
              help='Off, the map shows only the vehicles below — a fleet '
                   'board rather than a family one.'),
         _opt('members', 'Which people', 'select', [], source='members', multi=True,
              help='Leave empty for everyone. Ignored when people are off.'),
         _opt('cars', 'Show cars', 'bool', True),
         _opt('car_ids', 'Which cars', 'select', [], source='cars', multi=True,
              help='Leave empty for every car that has a tracker.'),
         # OFF by default, unlike cars: a bus is only real for the twenty
         # minutes it is running, and a household with no bus kids would get
         # a permanently absent row it never asked about.
         _opt('buses', 'Show school buses', 'bool', False,
              help='The bus each child rides, with the stop it is heading '
                   'for. Needs a tracker entity on the child in '
                   'Config → People.'),
         _opt('bus_ids', 'Whose buses', 'select', [], source='bus_riders',
              multi=True,
              help='Leave empty for every child who has a bus tracker.'),
     ]},
    # ── Music.
    #
    # This card exists because of a change in what the app IS. For a year
    # Chauffeur was reached THROUGH Home Assistant, so Music Assistant was
    # always one tab away and a music surface here would have been a second
    # drawing of something already at hand. It is the other way round now: the
    # family reaches the house through Chauffeur — wall panels, the PWA, the
    # kiosk boards — and on a panel there is no MA within reach at all.
    #
    # It is the PWA's music widget's twin, not its port. Shared logic
    # (static/music_logic.js: players, transport, search, favourites, and the
    # artwork proxying that is genuinely hard-won), separate drawing — because
    # the widget is a phone control in fixed dark colours, and this is read
    # and pressed from across a kitchen in whatever theme the wall is wearing.
    {'key': 'music', 'icon': '🎵', 'label': 'Music',
     'heading': '',
     'blurb': "Play, pause and search Music Assistant on a room's speaker. "
              "Needs Home Assistant.",
     'options': [
         # A wall card whose buttons do nothing is a poster of a stereo. ON,
         # per the conversion paradigm — but a household putting one on a
         # bedroom panel a toddler can reach has the switch.
         _opt('interactive', 'Interactive', 'bool', True,
              help='Play, pause, skip, volume and search all work. Off, the '
                   'card shows what is playing and nothing responds.'),
         # The room, not the speaker: the same words the family already says
         # to Argyle, resolved through the same pins.
         _opt('room', 'Room', 'text', '',
              help='A Home Assistant area — the card starts on that room\'s '
                   'speaker, using the same pin room announcements use. '
                   'Empty means whatever is already playing.'),
         _opt('player', 'Speaker', 'entity', '', source='ha_players',
              help='Pins this card to one speaker, ignoring the room.'),
         # A kitchen tablet HAS speakers. A music screen that can only send
         # music to other rooms is a remote control, so this screen offers
         # itself as a player like the phone app does — same Sendspin client,
         # different identity (a phone is a person, a panel is a place).
         _opt('local_player', 'This screen can play', 'bool', True,
              help='Adds this screen to the speaker list as a real Music '
                   'Assistant player, so music comes out of the panel itself.'),
         _opt('screen_name', 'What to call this screen', 'text', '',
              help='How it appears in Music Assistant — not on this card, '
                   'which just says "This Panel". Empty uses the room, then '
                   'the name this device was paired under, then a short code '
                   'unique to it, so two panels never arrive as duplicates.'),
         # THE CONVERSION PARADIGM: every part of the drawing is a toggle, all
         # on by default, so a card nobody configured equals the full surface.
         _opt('show_art', 'Album art', 'bool', True),
         _opt('show_picker', 'The speaker picker', 'bool', True,
              help='Lets anybody move the music to another room from the '
                   'card. Off, it stays on the one it was given.'),
         _opt('show_volume', 'Volume', 'bool', True),
         _opt('show_search', 'Search', 'bool', True),
         _opt('show_favorites', 'Favourites', 'bool', True),
         _opt('show_members', 'Who is listening', 'bool', True,
              help='A row of faces on the card. Picking one swaps the '
                   'favourites shelf to that person\'s own, and it falls '
                   'back to the house shelf after a few quiet minutes.'),
         _opt('show_shelves', 'Music Assistant shelves', 'bool', True,
              help='Recently played and MA\'s recommendations, on the house '
                   'view. Typing is the worst part of a wall music card — '
                   'these are the taps that replace it. Needs the Music '
                   'Assistant token; hidden without it.'),
     ]},
    # ── Home Assistant.
    #
    # Deliberately NOT in DEFAULT_WIDGETS: a household without HA should never
    # be shown a tile about it, and one with HA has to choose which entities
    # matter — there is no sensible default set of somebody else's sensors.
    #
    # Neither of these vanishes when HA is missing, unlike the weather tile.
    # Weather is a tile the board offers you; these are tiles you went and
    # added, and a thing you deliberately put on the wall disappearing without
    # explanation is the failure this board's "a quiet feature says so" rule
    # exists to prevent. They say "Needs Home Assistant" instead.
    {'key': 'ha', 'icon': '🏠', 'label': 'Entities',
     'heading': 'Home Assistant',
     'blurb': "Any Home Assistant entities you choose, as a list of readings.",
     'options': [
         _opt('entities', 'Entities', 'entity', [], source='ha_entities',
              multi=True, help='Type to search. Empty shows nothing.'),
         _opt('show_state_only', 'Values only', 'bool', False,
              help='Hide the names and show a wall of readings.'),
         # OFF by default, and that is board rule 3 rather than timidity: a
         # display does not change what it is displaying. A household that
         # wants light switches on the wall can say so; nobody gets them by
         # accident from adding a tile to read a temperature.
         _opt('interactive', 'Allow tapping to toggle', 'bool', False,
              help='Lights, switches, fans and helpers only.'),
     ]},
    {'key': 'ha_image', 'icon': '📷', 'label': 'Camera or image',
     'heading': 'Camera or radar',
     'blurb': "A picture from a Home Assistant camera or image entity.",
     'options': [
         _opt('entity', 'Entity', 'entity', '', source='ha_cameras'),
         _opt('refresh_seconds', 'Refresh every', 'int', 60, min=0, max=3600,
              help='Seconds. 0 fetches once and leaves it.'),
     ]},
    # ── A real Home Assistant dashboard, in a frame.
    #
    # This is the honest answer to "can you render HA cards". You cannot run a
    # Lovelace card here — they are custom elements that want a live `hass`
    # object and an authenticated websocket, and there is no supported way to
    # host one outside HA's own frontend. What you CAN do is let HA render it,
    # which is what a household means when they say they want their card: make
    # a dashboard with one card on it and point a tile at that view.
    #
    # It is a frame, so it comes with a frame's rules, and they are worth
    # knowing before you configure one:
    #   - It is HOME ASSISTANT'S look, not the panel's. It will not take the
    #     panel theme, and that is not a bug to be fixed here.
    #   - It only works where the browser is already signed in to HA. Under
    #     ingress that is automatic — the panel IS on HA's origin. Standalone
    #     on port 8000 it is a different origin, and HA sends
    #     `X-Frame-Options: SAMEORIGIN`, so the frame will very likely be
    #     refused however well the URL is spelled.
    {'key': 'ha_dashboard', 'icon': '🧩', 'label': 'Dashboard',
     'heading': 'A Home Assistant dashboard',
     'blurb': "A dashboard view, framed. Put ONE card on a view and point a "
              "tile at it. Reliable under ingress; a standalone panel is a "
              "different origin and Home Assistant usually refuses to be framed.",
     'options': [
         _opt('path', 'Dashboard view', 'text', '',
              help='e.g. lovelace/0 or my-panel/cameras. Add ?kiosk if you '
                   'have the kiosk-mode integration installed.'),
         # Hiding HA's own header and sidebar is the difference between "a
         # card on the wall" and "a browser window on the wall", so it is the
         # default. It works by reaching INTO the frame, which is only
         # possible same-origin — see the note in home.html for why that is
         # both fine and fragile.
         _opt('chrome', "Home Assistant's own chrome", 'choice', 'hide', choices=[
             {'value': 'hide', 'label': 'Hide the header and sidebar'},
             {'value': 'as_is', 'label': 'Leave the dashboard as it is'}],
              help='Hiding only works when the panel is opened through Home '
                   'Assistant. Cross-origin, nothing here can touch the frame.'),
         _opt('refresh_seconds', 'Reload every', 'int', 0, min=0, max=86400,
              help='Seconds. 0 leaves it alone — a live dashboard updates '
                   'itself and reloading only costs a flash.'),
     ]},
    # ── A custom Home Assistant card, actually running.
    #
    # The tile above frames HA's page because a Lovelace card "cannot run
    # outside HA's frontend". That was half true, and this is the other half:
    # a custom card is a plain custom element, and what it needs — a `hass`
    # object, a setConfig call, an element library, a set of CSS variables —
    # can be supplied. services/ha_cards.py holds the reasoning and the limits;
    # the one worth knowing here is that BUILT-IN card types (gauge, entities,
    # tile) live inside HA's own bundle and are not loadable, so this tile is
    # for `type: custom:…` only and says so when handed anything else.
    {'key': 'ha_card', 'icon': '🃏', 'label': 'Card',
     'heading': 'A Home Assistant card',
     'blurb': "Paste any card's YAML. Custom cards run for real; the common "
              "built-in ones are drawn in the panel's own colours.",
     'options': [
         _opt('config', 'Card YAML', 'yaml', '',
              help='The same text Home Assistant shows you under "Show code '
                   'editor". A type: custom:… card is run as itself; '
                   'entities, glance, tile, gauge, markdown, picture-entity, '
                   'button and the stacks are drawn natively.'),
         _opt('resource', 'Card file', 'text', '',
              help='Usually found on its own. Fill this in only if the card '
                   'lives somewhere unusual, e.g. /local/my-card.js'),
         # Same default and the same reason as the entity tile's: a display
         # does not change what it is displaying, and a card that can call
         # services is a control surface somebody added by accident.
         _opt('interactive', 'Let the card control things', 'bool', False,
              help='Lights, switches, fans and helpers only, whatever the '
                   'card tries to call.'),
     ]},
    # ── Any web page, in a frame.
    #
    # The most generic tile there is, and that is the argument for it: the
    # dashboard tile already proved a frame is useful, and there is nothing
    # about a Home Assistant dashboard that makes it the only page worth
    # putting on a wall. A bus timetable, a school's lunch menu, a webcam a
    # neighbour runs — none of those will ever have a tile of their own.
    #
    # It comes with a frame's rules, and they are in the blurb rather than
    # only in the code: plenty of sites refuse to be framed at all
    # (X-Frame-Options / frame-ancestors), and nothing here can change that.
    {'key': 'web', 'icon': '🌐', 'label': 'Web page',
     'heading': 'A web page',
     'blurb': "Any address, in a frame. Sites that refuse to be embedded will "
              "stay blank — that is their choice and nothing here can change it.",
     'options': [
         _opt('url', 'Address', 'text', '',
              help='https://… — must be https if the panel is, or the browser '
                   'will block it as mixed content.'),
         _opt('refresh_seconds', 'Reload every', 'int', 0, min=0, max=86400,
              help='Seconds. 0 leaves it alone, which is right for anything '
                   'that updates itself.'),
         _opt('scroll', 'Let it scroll', 'bool', False,
              help='Off makes it a picture rather than a page — which is what '
                   'a wall usually wants.'),
         _opt('zoom', 'Zoom', 'int', 100, min=25, max=400,
              help='Per cent. A page built for a laptop is often unreadable at '
                   'tile size until it is scaled down.'),
     ]},
    {'key': 'intake', 'icon': '📬', 'label': 'Intake',
     'heading': 'Waiting to approve',
     'blurb': "How many intake proposals need a parent. A COUNT only — the "
              "mail itself stays off shared screens."},
]
WIDGET_KEYS = [w['key'] for w in WIDGETS]

# Tiles that draw no panel of their own: the board's chrome. The clock strip
# floats on the wall, the hero band draws its own rounded card, a heading is
# ink. Everything else keeps the tile as its surface.
BARE_TILES = ('clock', 'hero', 'heading')

# Everything the household has actually set up, in a sensible reading order.
# The earlier six-tile default was chosen when any quiet tile vanished, which
# made "show them all" look like a wall of empty boxes; under rule 1 the board
# prunes itself to what this family uses, so the honest default is everything.
# `intake` is the one exclusion — it is an admin surface and stays opt-in.
DEFAULT_WIDGETS = ['drives', 'calendar', 'kids', 'meals', 'map', 'chores',
                   'routines', 'lists', 'errands', 'occasions', 'trips',
                   'weather', 'moments']

# Long enough to collapse several panels onto one build, short enough that
# checking a chore off in the kitchen and glancing at the wall agrees.
TTL_SECONDS = 20
# Keyed by board, not one entry, since v2.188: a household with a kitchen panel
# and a hallway panel polls two different boards on their own offsets, and a
# single slot would have had them evicting each other every few seconds — each
# poll a full rebuild, the cache doing worse than nothing. Bounded because the
# key includes tile config, so a card cycling `?widgets=` could otherwise grow
# this without limit.
_CACHE: dict = {}
_CACHE_MAX = 8


# --- small shared helpers -------------------------------------------------

def _local_naive(dt: datetime.datetime) -> datetime.datetime:
    """Everything on this board gets compared against `now`, and the schedule
    cache mixes aware and naive stamps depending on which calendar an event
    came from. Comparing those raises, so they are flattened to local wall
    time once, here, rather than defensively at every call site."""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _parse(val) -> Optional[datetime.datetime]:
    try:
        return _local_naive(datetime.datetime.fromisoformat(str(val)))
    except (TypeError, ValueError):
        return None


def _leg_event_id(leg_id: str) -> str:
    """init_{ev} / route_{ev}_1..3 / final_{ev} -> {ev}. Mirrors
    main._leg_event_id; duplicated rather than imported because importing main
    from a service is a cycle."""
    s = re.sub(r'^(init_|route_|final_)', '', str(leg_id))
    return re.sub(r'_[123]$', '', s)


def _clock(dt: datetime.datetime) -> str:
    return dt.strftime('%I:%M %p').lstrip('0')


def day_word(d: datetime.date, today: datetime.date) -> str:
    """'Today' / 'Tomorrow' / 'Wed'. Same convention as family_digest's
    day_label, shortened — a tile has room for three letters, not a date."""
    if d == today:
        return 'Today'
    if d == today + datetime.timedelta(days=1):
        return 'Tomorrow'
    return d.strftime('%a')


def _driver_index() -> dict:
    """driver_id -> {name, color, avatar, image}. Built once per board rather
    than looked up per drive: family_digest._driver_name scans every driver on
    every call, which is fine for a digest of six lines and not for a board
    rebuilt on a timer."""
    idx = {}
    for d in storage.get_all_drivers():
        idx[d.get('id')] = {'name': d.get('name') or 'Driver',
                            'color': d.get('color_code') or '#3b82f6',
                            'avatar': None, 'image': None}
    for m in storage.get_all_members(include_archived=True):
        d_id = m.get('driver_id')
        if not d_id:
            continue
        idx[d_id] = {'name': m.get('name') or idx.get(d_id, {}).get('name') or 'Driver',
                     'color': m.get('color_code') or '#3b82f6',
                     'avatar': m.get('avatar'), 'image': _member_image(m)}
    return idx


def day_schedule(day: datetime.date, sched: dict = None) -> dict:
    """The cached schedule, with ONE day taken from the freshest source there is.

    Reported from the wall: an event changed, the schedule re-solved, and the
    board said there was nothing left to drive today — while the Drives page,
    two taps away, listed the drives. It came back on its own several minutes
    later.

    The two surfaces were reading different caches. `/api/schedule?start&end`
    (the page) assembles its answer from the PER-DAY rows, which the solver
    rewrites the moment it finishes a day. `storage.get_cached_schedule()` (the
    board, and this module's only source until now) returns the combined
    global cache — and that is written **only by a refresh with no date range**
    (`main.refresh_schedule_logic`: `if not start_date_str and not
    end_date_str`). A single day re-solving never touches it. It is repaired by
    the five-minute poller, which is precisely the "wait a few minutes and it
    fixes itself" the family saw.

    So the board reads the day's own row first. This cannot go the other way:
    the global cache is COMPILED FROM these rows, so a daily row is never the
    staler of the two. The global cache still supplies everything that is not
    per-day — calendar colours, the driver roster, the home location.
    """
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    try:
        daily = (storage.get_cached_daily_schedule(day.isoformat()) or {}).get('schedule')
    except Exception as e:
        print(f"[home_board] daily schedule read failed: {e}")
        daily = None
    if not daily:
        return sched

    day_ids = {e.get('id') for e in (daily.get('events') or [])}
    if not day_ids:
        return sched

    # Authoritative for the whole DAY, not only for the ids it happens to list.
    # An event the re-solve dropped is gone from the daily row, so keying the
    # merge on that row's ids alone would leave its assignment behind — a
    # driver's name on the wall for a drive nobody is doing.
    drop = set(day_ids)
    for e in (sched.get('events') or []):
        start = _parse(e.get('start'))
        if start and start.date() == day:
            drop.add(e.get('id'))

    merged = dict(sched)

    # The day's own events replace the global copies of themselves — same ids,
    # possibly new times, which is the whole reason the day was re-solved. It is
    # a UNION rather than a replacement because a daily row holds the events the
    # solver was given, which is not the whole day: an appointment nobody drives
    # to is on the calendar tile and never in there.
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    for e in (daily.get('events') or []):
        events[e.get('id')] = e
    merged['events'] = list(events.values())

    def rekey(key):
        """Drop the global cache's entries for this day, then lay the day's own
        over the top. Merging without the drop would keep an assignment the
        re-solve has since taken away, which is a driver's name on the wall for
        a drive they are no longer doing."""
        out = {k: v for k, v in (sched.get(key) or {}).items() if k not in drop}
        out.update(daily.get(key) or {})
        return out

    merged['assignments'] = rekey('assignments')
    merged['ghost_assignments'] = rekey('ghost_assignments')
    merged['car_assignments'] = rekey('car_assignments')

    for key in ('unassigned', 'no_location'):
        rest = [e for e in (sched.get(key) or []) if e not in drop]
        merged[key] = rest + list(daily.get(key) or [])

    # The timeline slice reads these; `edges[driver][event]` is keyed by event
    # underneath, so the same drop-then-overlay applies one level down.
    for key in ('route_edges', 'initial_edges', 'final_edges'):
        out = {}
        for d_id, by_event in (sched.get(key) or {}).items():
            rows = {k: v for k, v in (by_event or {}).items() if k not in drop}
            if rows:
                out[d_id] = rows
        for d_id, by_event in (daily.get(key) or {}).items():
            out.setdefault(d_id, {}).update(by_event or {})
        merged[key] = out

    errands = [er for er in (sched.get('scheduled_errands') or [])
               if str(_parse(er.get('start_time')) or '')[:10] != day.isoformat()]
    merged['scheduled_errands'] = errands + list(daily.get('scheduled_errands') or [])
    return merged


def _errand_leave(start: datetime.datetime, er: dict) -> dict:
    """An errand's own travel time, as the same `leave_at` an event gets from
    the solver's edges. Nothing when it is unknown or zero — see
    services/leave_by on why a guessed departure is worse than none."""
    try:
        mins = int(round(float(er.get('travel_to_mins') or 0)))
    except (TypeError, ValueError):
        return {}
    if mins <= 0:
        return {}
    when = start - datetime.timedelta(minutes=mins)
    return {'leave_at': when.isoformat(), 'leave_label': _clock(when),
            'travel_mins': mins, 'from_home': False}


def todays_runs(target: datetime.date = None, sched: dict = None,
                now: datetime.datetime = None) -> List[dict]:
    """Every assigned drive and scheduled errand on one day, sorted by time,
    each tagged done / live / **over**.

    `over` is the one that matters, and it is computed HERE rather than by each
    consumer, because the hero and the drives tile both need it and the wall
    must not contradict itself. A drive is behind us if somebody marked it
    complete OR its end time has simply passed — and nobody marks drives
    complete. Reading only the manual flag put "Nothing left to drive today"
    directly above a tile headed "the rest of the day" listing a 5pm drive at
    6:34pm, which is the exact failure this shared builder existed to prevent.
    A drive under way is never over, whatever the clock says.
    """
    now = now or datetime.datetime.now()
    target = target or now.date()
    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    events = {e.get('id'): e for e in (sched.get('events') or [])}
    drivers = _driver_index()

    try:
        done_events = {_leg_event_id(l) for l in storage.get_completed_drives()}
        live_events = {_leg_event_id(l) for l in storage.get_in_progress_drives()}
    except Exception:
        done_events, live_events = set(), set()

    runs = []
    for ev_id, d_id in (sched.get('assignments') or {}).items():
        # Ghost drivers are the solver's "nobody real can do this" placeholder;
        # naming one on the wall would be inventing a person.
        if not d_id or str(d_id).startswith('ghost_'):
            continue
        ev = events.get(ev_id)
        start = _parse((ev or {}).get('start'))
        if not ev or not start or start.date() != target:
            continue
        d = drivers.get(d_id) or {'name': 'Driver', 'color': '#3b82f6'}
        end = _parse(ev.get('end')) or start
        live = ev_id in live_events
        done = ev_id in done_events
        runs.append({
            'id': ev_id, 'kind': 'event', 'title': ev.get('title') or 'Event',
            'location': ev.get('location') or None,
            'start': start.isoformat(), 'at': _clock(start),
            'end': end.isoformat(),
            'driver_id': d_id, 'driver': d['name'], 'color': d['color'],
            'avatar': d.get('avatar'), 'image': d.get('image'),
            'done': done, 'live': live,
            # WHEN TO LEAVE, which is the number a family actually plans
            # around — the start time is when somebody else expects you.
            # Absent when the schedule cannot support the claim; a guessed
            # departure gets a household burned once and then the board is
            # never believed again. Shared with the kid digest's "Leave by"
            # (services/leave_by), so the kitchen and the phone cannot differ.
            # live=True lays TODAY's traffic over the static plan (the day-of
            # cache maps' sweep maintains) — the board is a surface people
            # act on, and a free-flow 17 on a 28-minute rush-hour drive makes
            # someone late. Errands below stay static: the solver records
            # only their detour cost, not a route to read traffic against.
            **(leave_by.for_run(sched, d_id, ev_id, start, live=True, now=now) or {}),
            # BE THERE BY — the destination-side twin of leave-by, stamped on
            # the event by the solve (services/arrive_by). Carried verbatim:
            # the label is built once server-side so the wall and the phone
            # cannot describe the same game differently. Never replaces
            # `at`/`start` — a board that shows only the arrival makes 10:05
            # feel like missing a game that has not started.
            'arrive_by': ev.get('arrive_by'),
            'depart_after': ev.get('depart_after'),
            # UNDER WAY, read off the clock. `live` is the manual flag from
            # somebody tapping a leg as started, and the same thing that makes
            # `over` clock-based makes this one: nobody taps. A drive between
            # its start and its end is happening, whatever anybody remembered
            # to press, and a board that calls it "next up" is arguing with the
            # clock two feet above it.
            # Optional events (v2.153.0): the hero and the tiles must SAY an
            # event is the soft kind — "next up" asserting attendance for a
            # drop-in gym is the exact false-urgency the flag exists to end.
            # A skip-decided event never gets here (excluded from the solve,
            # so never assigned); 'attend' renders as a confirmed "✓ going".
            'optional': bool((ev.get('app_config') or {}).get('is_optional')),
            'optional_decision': ev.get('optional_decision'),
            'underway': bool(start <= now <= end),
            # The EVENT's end is the end. The live flag is a claim about a
            # DRIVE, and it must never extend the event's life on the board:
            # an away game an hour from home would otherwise read "happening
            # now" for the whole drive back. Whether people are home yet is
            # presence's business (the map, the hearth) — this tile's subject
            # is the event, and past its end time the event is over, whatever
            # any leg's flag still says. (First shipped as a 20-minute grace;
            # the family challenged the grace too, and they were right.)
            'over': bool(done or end < now),
        })

    for er in (sched.get('scheduled_errands') or []):
        d_id = (er.get('driver') or {}).get('id')
        start = _parse(er.get('start_time'))
        if not d_id or not start or start.date() != target:
            continue
        d = drivers.get(d_id) or {'name': 'Driver', 'color': '#3b82f6'}
        end = _parse(er.get('end_time')) or start
        runs.append({
            'id': er.get('id') or er.get('title'), 'kind': 'errand',
            'title': er.get('title') or 'Errand',
            'location': er.get('location') or None,
            'start': start.isoformat(), 'at': _clock(start),
            'end': end.isoformat(),
            'driver_id': d_id, 'driver': d['name'], 'color': d['color'],
            'avatar': d.get('avatar'), 'image': d.get('image'),
            'done': False, 'live': False,
            # An errand carries its own travel time rather than an edge: the
            # solver inserts it into a driver's chain and records what the
            # detour costs.
            **_errand_leave(start, er),
            'underway': bool(start <= now <= end),
            'over': bool(end < now),
        })

    # Outside hands (load arc A1, reaching the wall at last). A covered event
    # leaves the SOLVE — outside help removes load, and that is the point —
    # but it must not leave the WALL: Emma's mom pulling up to a house where
    # nobody knew the game was coming is not "load removed". The kid digest
    # learnt this in A1 ("a carpool-covered ride had no driver, so the digest
    # simply said nothing"); the hero had the same blindness for a year
    # because this builder reads assignments, and a covered event has none.
    # No leave-by on these rows — nobody in this house drives — but there IS
    # a "be ready at": the pickup happens at our door, and the road from here
    # to there is the same road whoever is at the wheel. See
    # `leave_by.ready_for_covered`; cache-only, and silent when it cannot be
    # supported, exactly like a departure of our own.
    assist_map = dict(sched.get('assist_assignments') or {})
    if assist_map:
        try:
            contacts = {c['id']: c for c in
                        (sched.get('assist_contacts')
                         or storage.get_assist_contacts(include_inactive=True))}
        except Exception:
            contacts = {}
        assigned = sched.get('assignments') or {}
        for ev_id, cid in assist_map.items():
            ev = events.get(ev_id)
            start = _parse((ev or {}).get('start'))
            if not ev or not start or start.date() != target:
                continue
            # Belt and braces: if a solve somehow also assigned it, the
            # household's own assignment is the row that already exists.
            if assigned.get(ev_id):
                continue
            c = contacts.get(cid) or {}
            # The label the family says out loud — a child knows "Emma's
            # mom" and may not know her name. Same rule as the digest.
            who = c.get('relation_label') or c.get('name') or 'Outside help'
            end = _parse(ev.get('end')) or start
            runs.append({
                'id': ev_id, 'kind': 'event',
                'title': ev.get('title') or 'Event',
                'location': ev.get('location') or None,
                'start': start.isoformat(), 'at': _clock(start),
                'end': end.isoformat(),
                'driver_id': None, 'driver': who, 'color': '#a78bfa',
                'avatar': None, 'image': None,
                'assist': True,
                **(leave_by.ready_for_covered(ev, start, live=True, now=now) or {}),
                'arrive_by': ev.get('arrive_by'),
                'depart_after': ev.get('depart_after'),
                'done': False, 'live': False,
                'optional': bool((ev.get('app_config') or {}).get('is_optional')),
                'optional_decision': ev.get('optional_decision'),
                'underway': bool(start <= now <= end),
                'over': bool(end < now),
            })

    # The order a family ACTS in, not the order hosts expect them: sorted by
    # the departure when the schedule knows it (start as the fallback),
    # because two events starting together are not the same urgency when one
    # is a seventeen-minute drive away — "next up" is the one you leave for
    # first. The id tail makes the order TOTAL: ties used to fall through to
    # the assignments dict's order from the last solve, and the hero flipped
    # between two same-time events on every refetch.
    # `ready_at` counts as a departure for ordering: on a covered event the
    # thing this house DOES is be ready, and "next up is the one you act on
    # first" is the rule the sort exists to express.
    runs.sort(key=lambda r: (r.get('leave_at') or r.get('ready_at') or r['start'],
                             r['start'], str(r['id'])))
    return runs


# --- the hero -------------------------------------------------------------

def _hero(now: datetime.datetime, runs: List[dict], sched: dict = None) -> dict:
    """The one thing that matters right now.

    A wall board that only tiles six lists is a worse phone — the app already
    KNOWS what is next, so the panel should lead with it. `next` is the first
    run not yet done; `minutes_until` is what makes it a countdown rather than
    a timetable.

    What it is NOT is a countdown to something that has already begun.
    Photographed from the wall at 1:53: **"NEXT UP · 53 min ago — Pre
    Jazz/Ballet"**, for a class that started at one o'clock and still had ten
    minutes to run. Both halves were computed correctly and the sentence they
    made together was nonsense. A thing that has started is not next; it is on.
    So a run between its start and its end is the hero and says so, and the
    board goes back to counting down only once that run is behind us.
    """
    upcoming = [r for r in runs if not r['over']]
    # Under way outranks not-yet-started. The manual flag and the clock are the
    # same claim, and the clock is the one that is always kept up to date.
    now_on = next((r for r in upcoming if r['live'] or r.get('underway')), None)
    nxt = now_on or (upcoming[0] if upcoming else None)

    hero = {'next': None, 'remaining': len(upcoming), 'later': [], 'all_done': False,
            'unbuilt': False, 'kids': []}
    if nxt:
        start = _parse(nxt['start']) or now
        end = _parse(nxt['end']) or start
        leave = _parse(nxt.get('leave_at'))
        hero['next'] = {**nxt,
                        'minutes_until': int(round((start - now).total_seconds() / 60)),
                        # The one somebody sets an alarm by. Absent when the
                        # schedule has no travel time for the drive.
                        'minutes_to_leave': (int(round((leave - now).total_seconds() / 60))
                                             if leave else None),
                        # How long it has LEFT, which is the useful number once
                        # it has started — "53 min ago" answers a question
                        # nobody standing in the kitchen is asking.
                        'minutes_left': int(round((end - now).total_seconds() / 60))}
        hero['later'] = [r for r in upcoming if r['id'] != nxt['id']][:3]
        _hero_outing(hero['next'], sched, now)
    elif runs:
        # There WERE drives and they are all behind us. Saying so is a real
        # answer; a blank hero reads as a broken panel.
        hero['all_done'] = True
    return hero


def _hero_outing(nxt: dict, sched: dict, now: datetime.datetime) -> None:
    """The trip AROUND the next drive, on the hero itself.

    The hero is the household's 3-metre surface, and it had two blindnesses
    the tiles were already cured of: "leave at 4:34" said nothing about the
    bags (and departure is exactly when unpacked matters), and a drive that
    chains into a second stop read as a 6:30 return from a trip the car is
    actually out on until 8:22.

    `outing` — stops, the events after this one, when the car is back
    (the outing's own end, drive home included) — only when the drive
    chains; a single-stop trip has nothing to add. `pack` — the outing's
    needed/packed, resolved by the same code the packing card uses
    (family_day.pack_status_for), so wall and card cannot disagree.
    Both best-effort: a hero that cannot answer says nothing."""
    if not sched or not nxt:
        return
    try:
        from services import outings as _o, family_day as _fd
        start = _parse(nxt.get('start'))
        if not start:
            return
        rows = _o.outings_for(start.date(), sched, now)
        mine = next((r for r in rows if nxt.get('id') in r['event_ids']), None)
        if not mine:
            return
        ids = mine['event_ids']
        if len(ids) > 1:
            events = {e.get('id'): e for e in (sched.get('events') or [])}
            after = ids[ids.index(nxt['id']) + 1:] if nxt['id'] in ids else []
            then = []
            for eid in after:
                ev = events.get(eid) or {}
                t = _parse(ev.get('start'))
                then.append({'title': ev.get('title') or 'Event',
                             'at': _clock(t) if t else None})
            end = _parse(mine.get('end'))
            nxt['outing'] = {'stops': len(ids), 'then': then,
                             'back_at': _clock(end) if end else None}
        pack = _fd.pack_status_for(mine['key'], ids, sched, start.date())
        if pack:
            nxt['pack'] = pack
    except Exception:
        return


def _hero_unbuilt(sched: dict) -> bool:
    """No schedule in the cache at all — a fresh install, a cleared cache, or
    the window before the first refresh finishes. "No drives today" is a
    confident claim about a day; this is the absence of any claim, and the two
    must not read the same on a wall."""
    return not (sched or {}).get('events')


# --- tile builders --------------------------------------------------------
# Each returns the tile's payload, or None when it has nothing to say.

def _schedule_slice(day: datetime.date, sched: dict, drivers=None,
                    days: int = 1) -> dict:
    """A RANGE of the cached schedule, in the shape `renderSchedule` reads.

    `days` is how many days from `day` inclusive. It is not a summary of
    several days — `renderSchedule` loops `sortedDates.forEach` and draws one
    complete timeline section PER DAY into its container, which is exactly how
    the Schedule page shows a week in kiosk mode. The tile hands over the
    range and the component does the rest; the only thing the caller must do
    is set `currentStartDate`/`currentEndDate` and NOT pass `dateFilter`,
    which is the option that narrows the loop back down to one.

    The drives tile draws the REAL Drives timeline — the same function, from
    `components/schedule_timeline.html` — and that function wants a schedule
    payload, not a summary. What it must not be given is `GET /api/schedule`:
    that endpoint SAVES a combined custom-range cache and kicks a background
    refresh every five minutes, so a wall panel polling it would keep the
    solver warm forever for a display nobody is looking at. Rule 3 of this
    module, exactly.

    So the slice is assembled here, from the cache the board already holds,
    and it is a slice rather than the whole thing because the panel does not
    need three weeks of events to draw this afternoon. The edge maps are
    `edges[driver_id][event_id]`, so they prune against the same day's ids.

    `drivers` is the tile's own filter, a set of driver ids or None. It prunes
    the LANES only — the timeline draws a column per driver — and deliberately
    not the events, because an event nobody in the filter is driving still has
    to leave a gap where it is: a timeline with the day's other drives silently
    removed reads as a free afternoon.
    """
    last = day + datetime.timedelta(days=max(1, days) - 1)

    def in_range(value) -> bool:
        d = (_parse(value) or datetime.datetime.min).date()
        return day <= d <= last

    events = [e for e in (sched.get('events') or []) if in_range(e.get('start'))]
    keep = {e.get('id') for e in events}

    def prune(edges):
        out = {}
        for d_id, by_event in (edges or {}).items():
            rows = {k: v for k, v in (by_event or {}).items() if k in keep}
            if rows:
                out[d_id] = rows
        return out

    errands = [er for er in (sched.get('scheduled_errands') or [])
               if in_range(er.get('start_time'))]

    try:
        completed = storage.get_completed_drives()
        in_progress = storage.get_in_progress_drives()
    except Exception:
        completed, in_progress = [], []

    return {
        'events': events,
        'scheduled_errands': errands,
        'assignments': {k: v for k, v in (sched.get('assignments') or {}).items()
                        if k in keep},
        'ghost_assignments': {k: v for k, v in (sched.get('ghost_assignments') or {}).items()
                              if k in keep},
        'ghost_drivers': sched.get('ghost_drivers') or [],
        'car_assignments': {k: v for k, v in (sched.get('car_assignments') or {}).items()
                            if k in keep},
        'unassigned': [e for e in (sched.get('unassigned') or []) if e in keep],
        'no_location': [e for e in (sched.get('no_location') or []) if e in keep],
        'overridden_events': [e for e in (sched.get('overridden_events') or []) if e in keep],
        'lateness_warnings': [w for w in (sched.get('lateness_warnings') or [])
                              if (w.get('event_id') if isinstance(w, dict) else w) in keep],
        'route_edges': prune(sched.get('route_edges')),
        'initial_edges': prune(sched.get('initial_edges')),
        'final_edges': prune(sched.get('final_edges')),
        'driver_events': {d: [e for e in evs if e in keep]
                          for d, evs in (sched.get('driver_events') or {}).items()},
        'calendar_metadata': sched.get('calendar_metadata') or {},
        'home_location': sched.get('home_location') or '',
        'drivers': [d for d in (storage.get_all_drivers() or [])
                    if not d.get('is_disabled')
                    and (drivers is None or d.get('id') in drivers)],
        'cars': [c for c in (storage.get_all_cars() or []) if not c.get('is_disabled')],
        'completed_drives': completed,
        'in_progress_drives': in_progress,
        # Deliberately absent: `ai_metadata`, `duplicate_groups`,
        # `solving_dates`. Every one of them renders a BUTTON — approve this
        # suggestion, create this rule — and a wall board is a display. The
        # renderer treats them as optional, so leaving them out leaves the
        # timeline and drops the controls.
        'date': day.isoformat(),
    }


def _tile_drives(now, runs, sched=None, config=None, **_):
    """The rest of the day, drawn by the DRIVES PAGE'S OWN TIMELINE.

    The first version of this tile drew a timeline of its own — lanes, blocks,
    an hour rail — and the family's report was the obvious one: it did not look
    like the page it was summarising. Two drawings of the same thing is exactly
    what a shelf of surfaces must not be, and the answer was never to copy the
    chips more carefully. `renderSchedule` moved to a shared component and the
    tile calls it; what arrives here is the data that function reads.

    The tile still decides WHAT to show — the same `over` rule as the hero, so
    the two halves of the board cannot disagree about what is behind us — and
    the page decides how it looks.
    """
    view = _cfg_str(config, 'view', 'timeline') or 'timeline'
    show_errands = _cfg_bool(config, 'errands', True)
    # Rides at the TOP of both payload shapes, like the calendar's: the board's
    # door logic reads the tile, and a card whose drives open a dialog cannot
    # also be an <a> to the Drives page or every tap would navigate mid-overlay.
    interactive = _cfg_bool(config, 'interactive', True)
    only = set(_cfg_ids(config, 'drivers'))
    span = _cfg_int(config, 'days', 1, 1, 14)

    # Applied to the RUNS as well as to the timeline, so the count, the "next"
    # scroll target and the drawing all agree about whose day this tile is.
    if only:
        runs = [r for r in runs if r.get('driver_id') in only]
    if not show_errands:
        runs = [r for r in runs if r.get('kind') != 'errand']

    # `over`, not `done` — a drive whose end time has passed is not upcoming
    # whether or not anybody remembered to tap it complete. Reading `done` here
    # while the hero read the clock is what let the wall contradict itself.
    rest = [r for r in runs if not r['over']]

    # The COMPACT shape, for a tile too narrow to read a timeline in. Not the
    # multi-day answer — the timeline does several days natively, one section
    # per day, which is what the Schedule page shows in kiosk mode — just a
    # different way of saying the same thing where an hour rail will not fit.
    if view == 'list':
        rows, seen_days = [], set()
        for i in range(span):
            day = now.date() + datetime.timedelta(days=i)
            day_runs = runs if i == 0 else todays_runs(day, sched=sched, now=now)
            if only:
                day_runs = [r for r in day_runs if r.get('driver_id') in only]
            if not show_errands:
                day_runs = [r for r in day_runs if r.get('kind') != 'errand']
            for r in day_runs:
                if i == 0 and r.get('over'):
                    continue          # today is the rest of the day, as ever
                rows.append({**r, 'day': day_word(day, now.date()),
                             'first_of_day': day not in seen_days})
                seen_days.add(day)
        if not rows:
            return {'empty': "No drives on the schedule."}
        return {'view': 'list', 'rows': rows[:14], 'count': len(rows),
                'interactive': interactive,
                'more': max(0, len(rows) - 14)}

    # `runs` is TODAY's. A tile showing a week has plenty to draw on a day when
    # today happens to be clear, so the nothing-to-say test only applies to a
    # single-day tile — otherwise a quiet Sunday would blank a whole week.
    if not runs and span == 1:
        if not storage.get_all_drivers():
            return None                      # no drivers: the feature is unused
        # NOTHING IN THE CACHE AT ALL is not the same claim as a day with no
        # drives on it, and saying the confident version of a sentence you
        # cannot support is how this board loses the family's trust. An empty
        # cache happens on a fresh install, after the caches are cleared, and
        # in the window before the first refresh finishes.
        if not (sched or {}).get('events'):
            return {'empty': "Waiting for the schedule to be built."}
        return {'empty': "No drives on the schedule today."}
    if not storage.get_all_drivers():
        return None

    sched = sched if sched is not None else (storage.get_cached_schedule() or {})
    first = now.date()
    return {
        'view': 'timeline',
        'count': len(rest),
        'interactive': interactive,
        # Read by the client, which hands it to `renderSchedule` — the page's
        # own errand switch, driven per tile.
        'show_errands': show_errands,
        # The RANGE, which is what makes a multi-day timeline tile possible at
        # all: `renderSchedule` draws one complete timeline section per day in
        # its date range, exactly as the Schedule page does in kiosk mode. The
        # client sets the range from these two and withholds `dateFilter`,
        # which is the option that narrows that loop back down to one day.
        'days': span,
        'start_date': first.isoformat(),
        'end_date': (first + datetime.timedelta(days=span - 1)).isoformat(),
        'schedule': _schedule_slice(first, sched, drivers=only or None,
                                    days=span),
        # Where to scroll the timeline so the tile opens on the part of the day
        # that has not happened. The whole day is drawn — a wall panel showing
        # a drive that finished an hour ago at the top of the tile is showing
        # the past. After the LAST drive this is None and the tile rests at the
        # bottom of the day: swapping the timeline for "nothing left to drive"
        # prose repeated the hero's sentence across a quarter of the board.
        'next_event_id': rest[0]['id'] if rest else None,
    }


def _tile_kids(now, kid_digest_fn=None, config=None, **_):
    """The kid digest, which main.py owns (it is the same builder the evening
    DMs use). Passed in rather than imported, because reaching into main from a
    service is the cycle this module is avoiding."""
    if not kid_digest_fn:
        return None
    try:
        digest = kid_digest_fn() or {}
    except Exception as e:
        print(f"[home_board] kid digests failed: {e}")
        return None
    wanted = set(_cfg_ids(config, 'members'))
    lines = _cfg_int(config, 'lines', 4, 1, 8)
    # The digest is keyed by member id and its ENTRIES do not repeat it, so
    # the id is folded in here — the filter below compared against a field
    # that did not exist and silently emptied every filtered tile, and the
    # shared lane drawing keys its rows by it.
    kids = [dict(k, id=mid, member_id=mid)
            for mid, k in (digest.get('kids') or {}).items()
            if k.get('lines') or k.get('tasks') or k.get('routine_count')]
    if wanted:
        # A kid the household filtered to but who has no digest entry simply
        # is not here, which is the same as any other quiet day.
        kids = [k for k in kids if k['member_id'] in wanted]
    # The page's own order, so the tile and the strip agree lane for lane.
    kids.sort(key=lambda k: (k.get('name') or ''))
    for k in kids:
        k['lines'] = (k.get('lines') or [])[:lines]
    if not kids:
        # No children in the household is unconfigured; children with a quiet
        # day is a thing worth saying out loud.
        if not any(m.get('role') == 'child' for m in storage.get_all_members()):
            return None
        return {'empty': "Nothing on for the kids today."}
    # No weather: there is a weather CARD, and a payload that quietly carries
    # another card's content is how a board says the same thing twice.
    return {'label': digest.get('label'), 'kids': kids, 'lines': lines,
            'parts': {**{p: _cfg_bool(config, f'show_{p}', True)
                         for p in ('day', 'header', 'streak', 'tasks', 'routines', 'figure')},
                      'figure_compact': _cfg_bool(config, 'figure_compact', False)}}


def _tile_meals(now, config=None, **_):
    """The PINNED plates only. Composing one here would make the wall panel a
    writer of meal plans, on a timer, forever.

    One night is "what is on the table" and reads as a picture of dinner;
    several is "what is planned" and reads as a list with a day on each row.
    Same data either way — the only difference is how many dates were asked
    for, so it is one number rather than a view switch.
    """
    try:
        nights = _cfg_int(config, 'nights', 1, 1, 7)
        offset = _cfg_int(config, 'offset', 0, 0, 7)
        tonight = nights == 1 and offset == 0
        items, dates, edited = [], [], False
        for i in range(nights):
            d = now.date() + datetime.timedelta(days=offset + i)
            plate = storage.get_plate(d.isoformat()) or {}
            edited = edited or bool(plate.get('edited'))
            for it in (plate.get('items') or []):
                items.append(it)
                dates.append(d)
        if not items:
            # A household with no dishes has never used meals at all; one with
            # dishes and no plate tonight has simply not decided yet.
            if not storage.get_dishes():
                return None
            return {'empty': "Nothing pinned for tonight yet." if tonight
                             else "Nothing pinned for those nights yet."}
        dishes = storage.get_dishes_by_ids([i['dish_id'] for i in items])
        by_id = {d['id']: d for d in dishes}
        rows = [{'name': by_id[i['dish_id']].get('short_name')
                         or by_id[i['dish_id']].get('name'),
                 'image': by_id[i['dish_id']].get('image_url'),
                 # Only when there is more than one night to tell apart. A day
                 # label over tonight's dinner answers a question nobody
                 # standing in the kitchen is asking.
                 'day': None if tonight else day_word(dates[n], now.date())}
                for n, i in enumerate(items) if i['dish_id'] in by_id]
        return {'dishes': rows, 'edited': edited, 'nights': nights} if rows \
            else {'empty': "Nothing pinned for tonight yet."}
    except Exception as e:
        print(f"[home_board] plate failed: {e}")
        return None


def _tile_meals_week(now, config=None, **_):
    """The nights ahead as a card. Self-fetching (`GET api/meals/week`, which
    composes in memory and persists nothing), so this is only the mount config.

    Composed rather than pinned, unlike the plate tile above, and that is not a
    contradiction of board rule 3: composing is what the endpoint does for
    every reader, and it writes nothing. What the rule forbids is the wall
    CAUSING a plan to exist — `get_or_compose_plate` persists, `compose_week`
    does not.
    """
    try:
        if not storage.get_dishes():
            return None                       # meals never used at all
        return {'nights': _cfg_int(config, 'nights', 7, 1, 7),
                'parts': {p: _cfg_bool(config, f'show_{p}', True)
                          for p in ('image', 'sides', 'effort', 'squeeze')}}
    except Exception as e:
        print(f"[home_board] meal week failed: {e}")
        return None


def _tile_shopping_staples(now, config=None, **_):
    """The drop-in-the-cart chips. Self-fetching, because a chip is ticked when
    the thing is already on the list and that is the whole difference between
    "tap to add" and "tap to undo"."""
    try:
        if not storage.get_shopping_lists():
            return None                       # never made a list
        return {'interactive': _cfg_bool(config, 'interactive', True),
                'list': _cfg_str(config, 'list'),
                'parts': {'hint': _cfg_bool(config, 'show_hint', True)}}
    except Exception as e:
        print(f"[home_board] staples failed: {e}")
        return None


def _tile_shopping_list(now, config=None, **_):
    """The list itself. Self-fetching for the same reason every interactive
    card is: a twenty-second payload cache is twenty seconds of a line coming
    back out of the cart."""
    try:
        if not storage.get_shopping_lists():
            return None
        return {'interactive': _cfg_bool(config, 'interactive', True),
                'list': _cfg_str(config, 'list'),
                'scope': _cfg_choice(config, 'scope',
                                     ('all', 'default', 'others'), 'all'),
                'columns': _cfg_str(config, 'columns', 'auto') or 'auto',
                'parts': {p: _cfg_bool(config, f'show_{p}', True)
                          for p in ('runs', 'cart', 'note', 'byline')}}
    except Exception as e:
        print(f"[home_board] shopping list failed: {e}")
        return None


def _tile_shopping(now, config=None, **_):
    try:
        all_lists = storage.get_shopping_lists()
        if not all_lists:
            return None                       # never made a list: feature unused
        only = _cfg_str(config, 'list')
        if only:
            picked = [l for l in all_lists if l.get('id') == only]
            # A list somebody deleted since configuring the tile. Saying so is
            # the only useful thing here: silently falling back to all lists
            # would look like the setting doing nothing, and hiding the tile
            # would look like the board being broken.
            if not picked:
                return {'empty': "That list is gone."}
            all_lists = picked
        show_items = _cfg_int(config, 'items', 12, 0, 20)
        lists = []
        for l in all_lists:
            items = storage.get_shopping_items(l['id'])
            open_items = [i for i in items if not i.get('is_checked')]
            if open_items:
                lists.append({
                    'id': l.get('id'),
                    'name': l.get('name') or 'List',
                    'store': l.get('store'),
                    'open': len(open_items),
                    # The THINGS, not the count. "Groceries — 12" tells you
                    # nothing you can act on walking past; "milk, eggs, bread…"
                    # is the entire reason a list is on the wall.
                    'items': [i.get('name') or '' for i in open_items[:12]],
                })
        if not lists:
            return {'empty': "Nothing on the lists."}
        lists.sort(key=lambda x: -x['open'])
        # A tile pinned to ONE list is showing that list, so it shows all of
        # it that fits rather than the top three of one.
        keep = 1 if only else 3
        return {'lists': lists[:keep], 'total': sum(l['open'] for l in lists),
                'show_items': show_items}
    except Exception as e:
        print(f"[home_board] shopping failed: {e}")
        return None


def _tile_chores(now, config=None, **_):
    try:
        from services import status_tiers
        wanted = set(_cfg_ids(config, 'members'))
        count = _cfg_int(config, 'count', 6, 1, 12)
        rows = storage.get_all_point_balances() or []
        rows = [r for r in rows if r.get('member_id')]
        if wanted:
            rows = [r for r in rows if r['member_id'] in wanted]
        if not rows:
            # Configured means the household set up the economy at all —
            # chores, or rewards to spend points on. Zeroes across the board
            # are a real answer ("nobody has earned anything yet"), not a
            # reason for the tile to disappear.
            if not (storage.get_all_chores() or storage.get_rewards()):
                return None
            return {'empty': "No points earned yet."}
        for r in rows:
            try:
                r['status'] = status_tiers.compute_member_status(r['member_id'], 'chore')
            except Exception:
                r['status'] = None
        rows.sort(key=lambda r: -(r.get('balance') or 0))
        return {'balances': rows[:count]}
    except Exception as e:
        print(f"[home_board] chores failed: {e}")
        return None


def _tile_chores_lanes(now, config=None, **_):
    """The kiosk lanes as a card. Interactive depth, so the card fetches its
    own four arrays (rule 2 — a payload that rebuilds under the finger typing
    a chip-in amount cannot carry them); this is only the mount config."""
    try:
        # Same configured-at-all test as the leaderboard: no chores and no
        # rewards means the household has not set the economy up.
        if not (storage.get_all_chores() or storage.get_rewards()):
            return None
        return {'interactive': _cfg_bool(config, 'interactive', True),
                'members': _cfg_ids(config, 'members'),
                'parts': {p: _cfg_bool(config, f'show_{p}', True)
                          for p in ('figure', 'header', 'goals', 'rewards',
                                    'mine', 'available')}}
    except Exception as e:
        print(f"[home_board] chore lanes failed: {e}")
        return None


def _tile_chores_goals(now, config=None, **_):
    """The family-goals strip. Display, so it RIDES the board payload (rule
    2), in the same reward shape the lanes fetch live — which is what lets
    one macro draw both."""
    try:
        goals = []
        for r in storage.get_rewards():
            if not r.get('pooled'):
                continue
            goals.append({'id': r.get('id'), 'title': r.get('title'),
                          'cost': r.get('cost'), 'pooled': True,
                          'pool': storage.get_pool_status(r)})
        # No pooled rewards = the feature is not set up; the card vanishes
        # like any unconfigured feature's tile does.
        return {'goals': goals} if goals else None
    except Exception as e:
        print(f"[home_board] family goals failed: {e}")
        return None


def _tile_packing(now, config=None, **_):
    """The wall's day surface: every block today (or tomorrow, once the last
    one is home) and what has to be ready for it. Interactive depth, so the
    card fetches its own list (rule 2) — this is only the mount config.

    Rule 1's None-for-unconfigured half (family_day_plan task 3 flip,
    docs/family_day_design.md "What changes underneath") no longer applies
    here: that half hides FEATURES a household never set up (no prep kits,
    no shopping list). The day itself is not a feature — the calendar
    underneath it is core — so this always returns mount config, whether or
    not any prep kits exist and whether or not today has any blocks. The
    old `get_prep_kits()` gate is gone.
    """
    try:
        return {'interactive': _cfg_bool(config, 'interactive', True),
                'members': _cfg_ids(config, 'members'),
                'days': _cfg_int(config, 'days', 1, 1, 7)}
    except Exception as e:
        print(f"[home_board] packing card failed: {e}")
        return None


def _tile_routines(now, config=None, **_):
    try:
        wanted = set(_cfg_ids(config, 'members'))
        count = _cfg_int(config, 'count', 6, 1, 12)
        member_ids = {r['member_id'] for r in storage.get_routines()}
        if not member_ids:
            return None
        rows = []
        for m in storage.get_all_members():
            if m['id'] not in member_ids:
                continue
            if wanted and m['id'] not in wanted:
                continue
            rows.append({'name': m.get('name'), 'color_code': m.get('color_code'),
                         'avatar': m.get('avatar'), 'image': _member_image(m),
                         'streak': storage.compute_streak(m['id'])})
        rows = [r for r in rows if r.get('streak')]
        if not rows:
            return {'empty': "No streaks going yet."}
        rows.sort(key=lambda r: (-(r['streak'].get('current') or 0), r['name'] or ''))
        return {'streaks': rows[:count]}
    except Exception as e:
        print(f"[home_board] routines failed: {e}")
        return None


def _tile_avatar_editor(now, config=None, **_):
    """The dressing-up box as a card: a row of faces, each one a door.

    The card is a launcher -- tapping a face runs the same PIN handshake and
    opens the same overlay as the pencil on a lane. No avatar art built means
    no card, honestly, rather than a grid of doors that open onto nothing."""
    try:
        from services import avatar_render
        if not avatar_render.available():
            return None
        wanted = _cfg_ids(config, 'members')
        rows = []
        for m in storage.get_all_members():
            if wanted and m['id'] not in wanted:
                continue
            rows.append({'member_id': m['id'], 'name': m.get('name'),
                         'color_code': m.get('color_code'),
                         'avatar': m.get('avatar'),
                         'image': _member_image(m),
                         'figure': avatar_render.effective_figure(m),
                         'has_pin': bool(m.get('pin_hash'))})
        # figures=True is the mantelpiece form: the family standing in a row.
        return {'members': rows, 'interactive': True,
                'figures': _cfg_bool(config, 'figures', True)} if rows else None
    except Exception as e:
        print(f"[home_board] avatar editor tile failed: {e}")
        return None


def _tile_pets(now, config=None, **_):
    """The family's critters, each one a door into the pet editor.

    A member with no pet still gets a tile -- an empty slot that says "hatch
    one" is the invitation, and hiding it would mean the only way to find the
    feature is to already know about it. Turn it off for a wall that should
    show only the creatures that exist."""
    try:
        from services import pet_render
        from services import pet_catalog
        if not pet_render.available():
            return None                  # no art: no doors onto nothing
        wanted = _cfg_ids(config, 'members')
        show_empty = _cfg_bool(config, 'show_unhatched', True)
        rows = []
        for m in storage.get_all_members():
            if wanted and m['id'] not in wanted:
                continue
            if m.get('status') in ('archived',):
                continue
            # ONE ROW PER CRITTER, because a member may own more than one
            # once they have bought a slot (P5). An empty slot is still a row:
            # it is the invitation, and hiding it means the only way to find
            # the feature is to already know about it.
            pets = storage.get_pets(m['id'])
            if not pets and not show_empty:
                continue
            prog = storage.pet_level_progress(m['id'])
            spend = storage.pet_spend_hint(m['id'])
            base = {'member_id': m['id'], 'name': m.get('name'),
                    'color_code': m.get('color_code'),
                    'has_pin': bool(m.get('pin_hash')),
                    # Shown only when it can actually buy something -- a badge
                    # that is always lit stops meaning anything.
                    'xp': spend['balance'], 'hint': spend['hint']}
            for pet in pets:
                cfg = dict(pet.get('species') or {})
                cfg.update(pet.get('look') or {})
                t = pet_catalog.get(pet.get('type')) or {}
                rows.append(dict(base, kind='pet', pet={
                    'id': pet['id'], 'name': pet.get('name'),
                    'level': prog['level'], 'progress': prog,
                    'type': pet.get('type'), 'type_label': t.get('label'),
                    'type_glyph': t.get('glyph'), 'type_color': t.get('color'),
                    # the pet id is the id namespace, so a board may draw a
                    # dozen critters without their clips colliding
                    'svg': pet_render.render_svg(cfg, crop='chip',
                                                 nonce=pet['id'][:12])}))
            if not show_empty:
                continue
            if len(pets) < storage.pet_slots(m['id']):
                rows.append(dict(base, kind='empty', pet=None))
            elif storage.get_pet_xp_balance(m['id']) >= storage.PET_SLOT_COST:
                # Affordable but not yet bought, so offer it. A carrot nobody
                # can see is not a carrot.
                rows.append(dict(base, kind='buy', pet=None,
                                 cost=storage.PET_SLOT_COST))
        if not rows:
            return None
        return {'members': rows, 'interactive': _cfg_bool(config, 'interactive', True),
                'show_level': _cfg_bool(config, 'show_level', True),
                'show_owner': _cfg_bool(config, 'show_owner', True)}
    except Exception as e:
        print(f"[home_board] pets tile failed: {e}")
        return None


def _tile_routines_lanes(now, config=None, **_):
    """The routines kiosk lanes as a card. Interactive depth, so the card
    fetches its own streaks and per-child checklists (rule 2); this is only the
    mount config."""
    try:
        if not storage.get_routines():
            return None                       # never made one: feature unused
        return {'interactive': _cfg_bool(config, 'interactive', True),
                'members': _cfg_ids(config, 'members'),
                'parts': {p: _cfg_bool(config, f'show_{p}', True)
                          for p in ('figure', 'header', 'status', 'streak',
                                    'progress', 'items')}}
    except Exception as e:
        print(f"[home_board] routine lanes failed: {e}")
        return None


def _tile_occasions(now, config=None, viewer=None, **_):
    try:
        today = now.date()
        count = _cfg_int(config, 'count', 3, 1, 10)
        within = _cfg_int(config, 'within_days', None, 1, 365) \
            if (config or {}).get('within_days') is not None else None
        rows, hidden = [], 0
        for o in storage.get_occasions(include_done=False) or []:
            # Family-network S4: a party being planned is a surprise until
            # somebody marks it for the wall — same closed default as trips,
            # applied where the rows are assembled.
            if not scope.audience_allows(o, 'occasion', viewer):
                hidden += 1
                continue
            anchor = o.get('anchor_date') or o.get('window_start')
            try:
                d = datetime.date.fromisoformat(str(anchor)[:10])
            except (TypeError, ValueError):
                continue
            if d < today:
                continue
            if within is not None and (d - today).days > within:
                continue
            rows.append({'title': o.get('title') or 'Occasion', 'date': d.isoformat(),
                         'kind': o.get('kind'), 'days': (d - today).days})
        can_know = viewer is not None \
            and scope.reach(viewer, 'occasions') != 'none'
        if not rows:
            # Nothing upcoming, but the household clearly uses occasions if any
            # exist at all (including ones already done).
            if hidden and can_know:
                return {'occasions': [], 'hidden': hidden}
            if not storage.get_occasions(include_done=True):
                return None
            return {'empty': "Nothing coming up."}
        rows.sort(key=lambda r: r['days'])
        out = {'occasions': rows[:count]}
        if hidden and can_know:
            out['hidden'] = hidden
        return out
    except Exception as e:
        print(f"[home_board] occasions failed: {e}")
        return None


def _tile_weather(now, config=None, **_):
    """Needs Home Assistant. The panel is pitched as standalone, so this tile
    disappearing when HA is absent is the designed behaviour, not a gap."""
    try:
        from services import ha_api
        from services import family_digest
        settings = storage.get_settings() or {}
        forecast = ha_api.get_weather_forecast(settings.get('weather_entity') or None)
        days = []
        for f in (forecast or [])[:_cfg_int(config, 'days', 5, 1, 7)]:
            d = str(f.get('datetime') or '')[:10]
            if not d:
                continue
            try:
                dd = datetime.date.fromisoformat(d)
            except ValueError:
                continue
            hi, lo = f.get('temperature'), f.get('templow')
            days.append({
                'day': 'Today' if dd == now.date() else dd.strftime('%a'),
                'emoji': family_digest._WEATHER_EMOJI.get(str(f.get('condition') or ''), '🌤️'),
                'hi': round(hi) if hi is not None else None,
                'lo': round(lo) if lo is not None else None,
                'rain': round(f.get('precipitation_probability') or 0) or None,
            })
        return {'days': days} if days else None
    except Exception as e:
        print(f"[home_board] weather failed: {e}")
        return None


def _tile_clock(now, config=None, **_):
    """The clock strip. Time and date are drawn client-side (they tick), so
    the payload only carries the forecast. ALWAYS truthy — a clock has
    something to say by existing, and must never vanish the way a quiet data
    tile does."""
    days = _cfg_int(config, 'days', 4, 0, 7)
    data = (_tile_weather(now, config={'days': days}) or {}) if days else {}
    return {'days': data.get('days') or []}


def _tile_hero(now, config=None, **_):
    """The hero band rides the board payload's own top-level `hero` — built
    once per board for whoever asks — so this tile is a PLACEMENT, not a
    second computation. Truthy for the same reason the clock is."""
    return {'ok': True}


def _tile_heading(now, config=None, **_):
    """Big text. The text itself is the instance's `title`, which _build_card
    already resolves into `label`; the payload carries only the scale."""
    return {'size': _cfg_str(config, 'size') or 'xl'}


def _tile_moments(now, config=None, **_):
    try:
        from services import presence
        count = _cfg_int(config, 'count', 6, 1, 12)
        within = _cfg_int(config, 'within_days', 30, 1, 365)
        # A generous window rather than 48h: on a wall, last week's photo from
        # the game beats an empty frame, and the hearth overlay is what handles
        # "brand new" anyway.
        rows = presence.recent_moments(hours=24 * within, limit=count) or []
        rows = [m for m in rows if m.get('media_url') or m.get('poster_url')
                or (m.get('attachment') or {}).get('url')]
        if not rows:
            return None
        return {'moments': rows[:count],
                'interactive': _cfg_bool(config, 'interactive', True)}
    except Exception as e:
        print(f"[home_board] moments failed: {e}")
        return None


def _tile_moments_gallery(now, config=None, **_):
    """The Moments page's own gallery, as a card.

    Config only, plus the one fact the client genuinely cannot answer for
    itself: whether this household has ANY moments. Rule 1 hides a feature
    nobody has set up, and the component cannot make that call — by the time
    it has fetched enough to know, it has already drawn an empty grid where a
    tile should not have been. One index read here settles it.
    """
    try:
        from services import presence
        # `limit=1` — the count is what matters and the page is thrown away.
        total = (presence.moment_events(offset=0, limit=1) or {}).get('total', 0)
    except Exception as e:
        print(f"[home_board] moments gallery failed: {e}")
        return None
    if not total:
        # Not an error and not empty-state prose: a household that has never
        # shared a moment has no gallery, and the Moments BOARD says so for
        # itself through `require` (REQUIRED_EMPTY).
        return None
    return {
        'events': total,
        'interactive': _cfg_bool(config, 'interactive', True),
        'lightbox': _cfg_bool(config, 'lightbox', True),
        'tile_width': _cfg_int(config, 'tile_width', 260, 140, 600),
        'show': {
            'count': _cfg_bool(config, 'show_count', True),
            'who': _cfg_bool(config, 'show_who', True),
            'when': _cfg_bool(config, 'show_when', True),
            'body': _cfg_bool(config, 'show_body', True),
            'reactions': _cfg_bool(config, 'show_reactions', True),
        },
    }


# Per day, before the card says "+3 more". A day card taller than the tile is
# the tile scrolling for one busy Saturday.


def _member_calendar_ids(member_ids: List[str]) -> set:
    """The Google calendars belonging to these people.

    `FamilyMember.calendar_ids` is the single place a person's calendars are
    set (Config → People → Identity); Driver and Passenger records carry
    derived mirrors. Filtering by member therefore means filtering by their
    calendars, which is also the honest answer to "show me Emma's week": an
    event is hers if it is on a calendar of hers.

    A member with NO calendars matches nothing, and that is correct rather than
    a bug to paper over — the alternative, treating "no calendars" as "all
    calendars", would silently turn a filter into no filter.
    """
    wanted = set(member_ids or [])
    ids = set()
    for m in (storage.get_all_members() or []):
        if m.get('id') in wanted:
            ids.update(m.get('calendar_ids') or [])
    return ids


# The calendar page's URL vocabulary, which is also the card's. Kept as one
# table so "month" means the same thing in a query string and in a card config.
# `agenda` is here too since v2.207: the component owns the agenda now, so the
# card mounts it like any other view and the last server-side drawing of an
# agenda is gone. Only `list` is still built into the board payload — it is
# genuinely a different thing (one line per event for a narrow tile), not a
# second drawing of the same one.
_CAL_GRID_VIEWS = {'month': 'dayGridMonth', 'week': 'timeGridWeek',
                   'day': 'timeGridDay', 'agenda': 'agenda'}


def _tile_calendar(now, sched=None, settings=None, config=None, **_):
    """The drives tile answers "who is taking whom"; this answers "what is on",
    which on most days is a different list — a dentist appointment nobody
    drives to still belongs on the wall.

    Four of the five views — agenda, month, week, day — are the calendar
    page's own, mounted from components/family_calendar.html; this builder
    only resolves their config (which view, whose events, how many days) and
    the component fetches for itself. The one view still BUILT here is
    `list`: one line per event for a tile too narrow to hold day cards, which
    is genuinely a different drawing and not a copy of the page's.

    Today's finished events stay, flagged `past` and greyed. Dropping them
    made a busy morning invisible: a list showing two things at four in the
    afternoon reads as a quiet day rather than as a day nearly done.
    """
    try:
        sched = sched if sched is not None else (storage.get_cached_schedule() or {})
        assignments = sched.get('assignments') or {}
        unassigned = set(sched.get('unassigned') or [])
        drivers = _driver_index()
        today = now.date()
        span = _cfg_int(config, 'days', AGENDA_DAYS, 1, 14)
        view = _cfg_str(config, 'view', 'agenda') or 'agenda'
        # The three GRID views are the calendar page's own, mounted from the
        # shared component. There is nothing for this builder to compute: the
        # grid fetches the schedule itself, because a month of events is not
        # something to ship inside a board payload that five other cards are
        # waiting on. What it does need is the filter, resolved from member ids
        # to the NAMES the pipeline matches on.
        if view in _CAL_GRID_VIEWS:
            names = []
            wanted = _cfg_ids(config, 'members')
            if wanted:
                try:
                    names = [m.get('name') for m in (storage.get_all_members() or [])
                             if str(m.get('id')) in wanted and m.get('name')]
                except Exception as e:
                    print(f"[home_board] calendar card members failed: {e}")
            # `interactive` rides at the TOP of the payload as well as inside
            # the mount config: the board's door logic reads the tile, not the
            # mount — a tile whose events open a dialog cannot also be an <a>
            # to the calendar page, or every tap would navigate mid-overlay.
            interactive = _cfg_bool(config, 'interactive', True)
            return {'interactive': interactive,
                    'grid': {'view': _CAL_GRID_VIEWS[view],
                             'toolbar': _cfg_bool(config, 'view_selector', False),
                             'days': _cfg_int(config, 'days',
                                              AGENDA_DAYS, 1, 14),
                             'only': names,
                             # The page's own two affordances, previously
                             # hardcoded off in syncCalendars: the details
                             # dialog behind every event tap, and the
                             # per-person legend chips.
                             'details': interactive,
                             'legend': _cfg_bool(config, 'show_legend', True)}}
        show_all_day = _cfg_bool(config, 'all_day', True)
        member_ids = _cfg_ids(config, 'members')
        # Resolved ONCE, not per event: this reads every member record, and a
        # busy fortnight is a few hundred events. Empty set = no filter.
        wanted_cals = _member_calendar_ids(member_ids) if member_ids else set()

        def mine(ev) -> bool:
            if not member_ids:
                return True
            return bool(wanted_cals.intersection(ev.get('calendar_ids') or []))

        days = {}
        order = []
        for i in range(span):
            d = today + datetime.timedelta(days=i)
            days[d] = []
            order.append(d)

        def place(d, row):
            if d in days:
                days[d].append(row)

        for ev in (sched.get('events') or []):
            # The trip's own span event covers every day of the trip and would
            # print on all five cards. The trips tile is where a trip belongs.
            if ev.get('event_type') == 'background_trip':
                continue
            if ev.get('all_day') and not show_all_day:
                continue
            if not mine(ev):
                continue
            start = _parse(ev.get('start'))
            if not start:
                continue
            end = _parse(ev.get('end')) or start
            d_id = assignments.get(ev.get('id'))
            d = drivers.get(d_id) if d_id and not str(d_id).startswith('ghost_') else None
            place(start.date(), {
                'title': ev.get('title') or 'Event',
                'at': '' if ev.get('all_day') else _clock(start),
                'end_at': '' if ev.get('all_day') else _clock(end),
                'all_day': bool(ev.get('all_day')),
                'start': start.isoformat(),
                'driver': (d or {}).get('name'),
                # An unassigned event is the one thing on this tile somebody has
                # to DO something about, so it is coloured for it rather than
                # left in the same grey as everything else.
                'needs_driver': ev.get('id') in unassigned,
                'color': ('#ef4444' if ev.get('id') in unassigned
                          else (d or {}).get('color') or '#64748b'),
                'kind': 'event',
                # Behind us, on the same reading of the clock the drives side
                # uses for `over`. An all-day event is never past — it is the
                # whole day, and half of it is still ahead.
                'past': bool(not ev.get('all_day') and end < now),
            })

        # An errand is household work with a driver, not something on a
        # person's calendar — so a tile filtered to particular people drops
        # them rather than guessing that the driver's errands are "theirs".
        # "Emma's week" containing the household's trip to the tip is worse
        # than it missing it.
        for er in ([] if member_ids else (sched.get('scheduled_errands') or [])):
            start = _parse(er.get('start_time'))
            if not start:
                continue
            end = _parse(er.get('end_time')) or start
            d_id = (er.get('driver') or {}).get('id')
            d = drivers.get(d_id) if d_id else None
            place(start.date(), {
                'title': er.get('title') or 'Errand',
                'at': _clock(start), 'end_at': _clock(end), 'all_day': False,
                'start': start.isoformat(),
                'driver': (d or {}).get('name'),
                'needs_driver': False,
                'color': (d or {}).get('color') or '#f59e0b',
                'kind': 'errand',
                'past': bool(end < now),
            })

        total = sum(len(v) for v in days.values())
        # Never hidden. A family calendar with a quiet stretch is information;
        # a calendar tile that vanishes just looks broken. A FILTERED tile says
        # whose calendar is quiet, because "nothing on the calendar" under a
        # tile headed "Emma's week" reads as the tile being broken.
        if not total:
            who = ''
            if member_ids:
                names = [m.get('name') for m in (storage.get_all_members() or [])
                         if m.get('id') in set(member_ids) and m.get('name')]
                who = f" for {', '.join(names)}" if names else ''
            return {'empty': f"Nothing on the calendar{who} "
                             f"for the next {span} day{'s' if span != 1 else ''}."}

        # Anything else stored in `view` is a config written by an older
        # version or by hand; the list is the only payload drawing left.
        rows = sorted((r for v in days.values() for r in v),
                      key=lambda r: (r['start'], not r['all_day']))
        for r in rows:
            d = datetime.date.fromisoformat(r['start'][:10])
            r['day'] = day_word(d, today)
        return {'view': 'list', 'rows': rows[:12], 'total': total,
                'more': max(0, len(rows) - 12)}
    except Exception as e:
        print(f"[home_board] calendar failed: {e}")
        return None


def _tile_tasks(now, config=None, **_):
    """Household work with a deadline and no destination (load arc A2).

    Past due first, then unclaimed, then the rest. The unclaimed band is the
    one that earns the tile: "nobody has this and it is due Thursday" is
    invisible everywhere else, and a wall is where a household actually
    notices it.
    """
    try:
        count = _cfg_int(config, 'count', 6, 1, 12)
        wanted = set(_cfg_ids(config, 'members'))
        unclaimed_only = _cfg_bool(config, 'unclaimed_only', False)
        rows = storage.get_household_tasks()
        if not rows and not storage.get_household_tasks(include_done=True):
            return None                       # never made one: feature unused
        if not rows:
            return {'empty': "Nothing owed right now."}
        today = now.date().isoformat()
        names = {m['id']: m.get('name') for m in storage.get_all_members(include_archived=True)}
        out = []
        for t in rows:
            # `unclaimed_only` and an owner filter are opposite questions, so
            # a tile asked both shows what it was asked LAST: an unclaimed task
            # has no owner and can never match an owner filter, and a tile that
            # silently returned nothing would look broken rather than
            # contradictory.
            if unclaimed_only and t.get('assigned_to'):
                continue
            if wanted and not unclaimed_only and t.get('assigned_to') not in wanted:
                continue
            due = t.get('due_date')
            out.append({
                'title': t.get('title') or 'Task',
                'due': due,
                'past_due': bool(due and due < today),
                'unclaimed': not t.get('assigned_to'),
                'who': names.get(t.get('assigned_to') or ''),
            })
        out.sort(key=lambda r: (not r['past_due'], not r['unclaimed'],
                                r['due'] or '9999-99-99'))
        return {'tasks': out[:count], 'total': len(out),
                'unclaimed': sum(1 for r in out if r['unclaimed'])}
    except Exception as e:
        print(f"[home_board] tasks failed: {e}")
        return None


def _tile_errands(now, config=None, **_):
    try:
        count = _cfg_int(config, 'count', 5, 1, 12)
        past_due_only = _cfg_bool(config, 'past_due_only', False)
        every = storage.get_all_errands() or []
        if not every:
            return None                       # never made one: feature unused
        rows = []
        for er in every:
            if er.get('is_completed') or er.get('status') == 'completed':
                continue
            if past_due_only and er.get('status') != 'past_due':
                continue
            rows.append({'title': er.get('title') or 'Errand',
                         'location': er.get('location') or None,
                         'past_due': er.get('status') == 'past_due',
                         'priority': er.get('priority') or 2})
        if not rows:
            return {'empty': ("Nothing past due." if past_due_only
                              else "Nothing waiting.")}
        # Past-due first, then by priority: a wall panel shows the thing that
        # has already slipped before the thing that has not.
        rows.sort(key=lambda r: (not r['past_due'], r['priority']))
        return {'errands': rows[:count], 'total': len(rows)}
    except Exception as e:
        print(f"[home_board] errands failed: {e}")
        return None


def _tile_task_list(now, config=None, **_):
    """The household list as a card. Interactive depth, so the card fetches its
    own rows (rule 2 — twenty seconds of cached payload is twenty seconds of a
    ticked box coming back unticked); this is only the mount config.

    It still answers the unconfigured question here, because that is the one
    thing the client cannot: a household that has never made a task wants no
    tile, and a household whose list is empty tonight wants to see that it is.
    """
    try:
        if not storage.get_household_tasks() and \
                not storage.get_household_tasks(include_done=True):
            return None                       # never made one: feature unused
        return {'interactive': _cfg_bool(config, 'interactive', True),
                'count': _cfg_int(config, 'count', 12, 1, 40),
                'members': _cfg_ids(config, 'members'),
                'unclaimed_only': _cfg_bool(config, 'unclaimed_only', False),
                'parts': {p: _cfg_bool(config, f'show_{p}', True)
                          for p in ('load', 'due', 'owner', 'recurrence')}}
    except Exception as e:
        print(f"[home_board] task list failed: {e}")
        return None


def _tile_errand_list(now, config=None, **_):
    """The errand list as a card. Same shape and the same reasoning as the
    household list above."""
    try:
        if not (storage.get_all_errands() or []):
            return None                       # never made one: feature unused
        return {'interactive': _cfg_bool(config, 'interactive', True),
                'count': _cfg_int(config, 'count', 12, 1, 40),
                'past_due_only': _cfg_bool(config, 'past_due_only', False),
                'parts': {p: _cfg_bool(config, f'show_{p}', True)
                          for p in ('past_due', 'open', 'completed',
                                    'location', 'when')}}
    except Exception as e:
        print(f"[home_board] errand list failed: {e}")
        return None


def _trip_rows(now, back_days: int = 0, viewer: Optional[dict] = None):
    """Trips this install can know about WITHOUT calling Google, newest-first.

    Three sources, because no single one is complete:

    1. The `/api/trips` snapshot — the only place a real trip's dates and title
       exist, since both live on its Google calendar event. Written whenever
       somebody loads the trips page.
    2. Draft trips from `trip_metadata`, which carry their own mock dates and
       never touch Google at all.
    3. Spans derived from the cached schedule by grouping scheduled activities
       on `trip_id`. This is the safety net for the case that actually bit: a
       trip whose snapshot is stale or was never taken still shows up, because
       its POIs are sitting in the schedule cache with real dates on them.
    """
    seen, rows = set(), []
    hidden = [0]   # trips withheld from THIS viewer (family-network S4)
    # How far back a caller wants to look. The glance tile wants 0 — "the next
    # trip" is not a trip you got home from last week. The GALLERY wants a
    # window, because the trips page has always shown recent trips with a
    # "Past" badge on them, and a card that is the page must be the page.
    floor = now.date() - datetime.timedelta(days=max(0, back_days))

    def add(tid, title, start, end, location=None, image=None, draft=False):
        if not start or (tid and tid in seen):
            return
        if tid:
            seen.add(tid)
        # Family-network S4: audience, checked where the data is ASSEMBLED so
        # every tile inherits it. A trip WITH a metadata record and no
        # declared audience is closed ('parents' default — a plan is a
        # surprise until somebody says otherwise); a trip with NO record at
        # all is 'household', since it exists only as calendar events the
        # family already sees. The panel is the one surface a child meets a
        # trip on, and it calls this with viewer=None — a place, not a
        # person — so a closed trip never reaches the kitchen wall.
        meta = (storage.get_trip_metadata(tid) or None) if tid else None
        if not scope.audience_allows(meta if meta is not None
                                     else {'audience': 'household'},
                                     'trip', viewer):
            hidden[0] += 1
            return
        end = end or start
        # background_url is not always a URL — older trips stored a search
        # phrase ("disney world") in it, which as an <img src> is a broken
        # image on the kitchen wall.
        raw = str(image or '')
        img = raw if raw.startswith(('http://', 'https://', '/', 'data:')) else None
        # …but a phrase is not nothing, and the trips PAGE has always turned
        # one into a picture through the same Unsplash endpoint that backs
        # trip artwork. So does this now: a trip with no photograph gets one
        # found for it from the phrase, then its title, then where it is —
        # which is exactly the ladder the page walks. Without it the gallery
        # card drew grey boxes where the page drew photographs.
        art = img or _as_background(
            raw or (str(title or '').split(':')[0].split(' - ')[0].strip())
            or location or 'travel')
        rows.append({
            'id': tid, 'title': title or 'Trip', 'location': location or None,
            'image': img, 'art': art, 'draft': bool(draft),
            'poi_count': len((meta or {}).get('pois') or []),
            'start': start.isoformat(), 'end': end.isoformat(),
            'past': bool(end < now.date()),
            # NEGATIVE days would mean "already started", so an in-progress
            # trip reports 0 and says so. The first version filtered anything
            # starting before today, which is precisely how a trip the family
            # was ON showed as "No trips planned".
            'days': max(0, (start - now.date()).days),
            'live': start <= now.date() <= end,
        })

    def as_date(val):
        if val in (None, ''):
            return None
        try:
            return datetime.datetime.fromisoformat(str(val).replace('Z', '+00:00')).date()
        except (TypeError, ValueError):
            pass
        try:
            return datetime.datetime.fromtimestamp(float(val)).date()
        except (TypeError, ValueError, OSError):
            return None

    for t in (storage.get_cached_trips() or {}).get('trips') or []:
        s, e = as_date(t.get('start')), as_date(t.get('end'))
        if s and e and e >= floor:
            add(t.get('id'), t.get('title'), s, e, t.get('location'),
                t.get('background_url'), t.get('is_draft'))

    for t in storage.get_all_trip_metadata() or []:
        if not t.get('is_draft'):
            continue
        s, e = as_date(t.get('mock_start_date')), as_date(t.get('mock_end_date'))
        if s and (e or s) >= floor:
            add(t.get('event_id'), t.get('title') or 'Draft trip', s, e,
                t.get('location'), t.get('background_url'), True)

    spans = {}
    for ev in (storage.get_cached_schedule() or {}).get('events') or []:
        tid = ev.get('trip_id')
        s, e = _parse(ev.get('start')), _parse(ev.get('end'))
        if not tid or not s:
            continue
        lo, hi = spans.get(tid, (s, e or s))
        spans[tid] = (min(lo, s), max(hi, e or s))
    for tid, (lo, hi) in spans.items():
        if hi.date() < floor:
            continue
        meta = storage.get_trip_metadata(tid) or {}
        add(tid, meta.get('title'), lo.date(), hi.date(),
            meta.get('location'), meta.get('background_url'), meta.get('is_draft'))

    # Under way first, then what is coming, then what is behind us. The past
    # tail only exists when a caller asked for a window back, and it belongs
    # at the bottom rather than interleaved by date — a trip you got home from
    # is a memory, not a plan, whatever its start date says.
    rows.sort(key=lambda r: (r['past'], not r['live'], r['start']))
    return rows, hidden[0]


def _trips_payload(rows, hidden, viewer):
    """Attach the never-silent counter — to exactly whoever may know (§7).

    A viewer whose scope permits trips sees "N trips not shown here"; anyone
    else (a viewerless panel above all) gets NO trace, not even a count. The
    absence is legible to whoever may know and invisible to everyone else."""
    out = {'trips': rows}
    if hidden and viewer is not None \
            and scope.reach(viewer, 'trips.gallery') != 'none':
        out['hidden'] = hidden
    return out


def _tile_trips(now, config=None, viewer=None, **_):
    try:
        if not (storage.get_all_trip_metadata() or storage.get_cached_trips()):
            return None                       # no trips ever: feature unused
        pinned = _cfg_str(config, 'trip')
        count = _cfg_int(config, 'count', 4, 1, 8)
        rows, hidden = _trip_rows(now, viewer=viewer)
        if pinned:
            # A trip somebody pinned and has since finished or deleted. Saying
            # so beats silently showing a different trip under a tile the
            # household set to one — the same rule the pinned shopping list
            # follows.
            rows = [r for r in rows if r.get('id') == pinned]
            if not rows:
                return {'empty': "That trip is over."}
            return {'trips': rows[:1], 'pinned': True}
        if not rows:
            payload = _trips_payload([], hidden, viewer)
            return payload if payload.get('hidden') \
                else {'empty': "No trips planned."}
        payload = _trips_payload(rows[:count], hidden, viewer)
        return payload
    except Exception as e:
        print(f"[home_board] trips failed: {e}")
        return None


# How far back "trips" reaches, for EVERYBODY: `/api/trips` uses it as its
# Google `timeMin`, and the gallery card uses it as its look-back. One number,
# because the two must agree — a card looking back further than the fetch
# looks back is a card that can never find what it is asking for.
#
# It was 30 days, and that was the whole of "past trips are not showing even
# when the setting is on". A month is the wrong unit for this: the trips page
# calls itself "your upcoming and past adventures", and a family's adventures
# are months and seasons back, not weeks. Nothing older than a month could be
# known by ANY surface — the page included — because a real trip's dates live
# on its Google event and nothing outside that window was ever fetched.
#
# A year costs the same number of requests (one search per calendar per
# hashtag); only the window widens.
TRIPS_BACK_DAYS = 365


def _tile_trips_gallery(now, config=None, viewer=None, **_):
    """The trips page's own gallery, as a card.

    Rides the PAYLOAD rather than self-fetching, and that is a rule rather
    than a preference: the page's own `/api/trips` calls Google Calendar and
    WRITES a snapshot on the way past. A wall panel polling it every minute
    would keep the calendar warm and rewrite a cache for a display nobody is
    looking at — rule 3, exactly. `_trip_rows` answers from what this install
    already has (the snapshot, draft metadata, the schedule cache), which is
    what the glance tile has always used.
    """
    try:
        if not (storage.get_all_trip_metadata() or storage.get_cached_trips()):
            return None                       # no trips ever: feature unused
        show_past = _cfg_bool(config, 'show_past', True)
        count = _cfg_int(config, 'count', 0, 0, 40)
        rows, hidden = _trip_rows(now, back_days=TRIPS_BACK_DAYS if show_past else 0,
                                  viewer=viewer)
        if not show_past:
            rows = [r for r in rows if not r['past']]
        if not rows:
            payload = _trips_payload([], hidden, viewer)
            return payload if payload.get('hidden') \
                else {'empty': "No trips planned."}
        return {
            **_trips_payload(rows[:count] if count else rows, hidden, viewer),
            'interactive': _cfg_bool(config, 'interactive', True),
            'tile_width': _cfg_int(config, 'tile_width', 320, 180, 700),
            'show': {
                'status': _cfg_bool(config, 'show_status', True),
                'dates': _cfg_bool(config, 'show_dates', True),
                'location': _cfg_bool(config, 'show_location', True),
                'pois': _cfg_bool(config, 'show_pois', True),
            },
        }
    except Exception as e:
        print(f"[home_board] trips gallery failed: {e}")
        return None


# Where a map with nothing on it should look, and for how long that answer is
# reusable. A house does not move, so this is memoised for an hour rather than
# re-derived on every board build: the geocode fallback re-asks the network
# whenever the cached entry is a FAILURE, and a home address that will never
# geocode would otherwise buy a lookup a minute forever.
_HOME_CENTER = {'at': 0.0, 'coords': None}
_HOME_CENTER_TTL = 3600.0


def _home_center():
    """The household's home as (lat, lon), or None if nobody has said where.

    `zone.home` first: Home Assistant already knows the house exactly, it costs
    one state read, and it is the same circle every `state: home` on this map
    is measured against — so the fallback view and the pins agree about where
    home is. Without HA (or without that zone) the household's own home
    address, geocoded through the cache that already backs every drive.
    """
    now = time.time()
    if _HOME_CENTER['coords'] is not None and now - _HOME_CENTER['at'] < _HOME_CENTER_TTL:
        return _HOME_CENTER['coords']
    coords = None
    try:
        from services import ha_api
        attrs = (ha_api.get_state('zone.home') or {}).get('attributes') or {}
        if attrs.get('latitude') is not None and attrs.get('longitude') is not None:
            coords = (float(attrs['latitude']), float(attrs['longitude']))
    except Exception:
        coords = None
    if coords is None:
        try:
            from services import bus as bus_svc
            coords = bus_svc._home_coords()
        except Exception:
            coords = None
    # A miss is cached too — for the same TTL and for the same reason. An
    # install with no home address set is the case that would otherwise pay
    # for the lookup on every single build.
    _HOME_CENTER.update(at=now, coords=coords)
    return coords


def _tile_map(now, runs=None, config=None, **_):
    """Where everyone is — as a MAP, with the list as the fallback.

    Six names beside six zone words was a table of contents for a map. "Kit:
    not_home" is true and tells you nothing; a pin two streets away tells you
    they are walking back. So the rows carry `latitude`/`longitude` and the
    panel draws the same markers /map draws, from the same component.

    The coordinates are FREE: this builder was already reading each member's
    Home Assistant state and throwing everything but the zone word away. Cars
    cost one state read each and are here for the same reason they are on /map
    — "where is the car" is half of "can we leave yet".

    The payload deliberately speaks `/api/family/locations`'s vocabulary
    (`member_id`, `latitude`, `driving: {leg_title}`) so the shared renderer
    takes either one without a translation layer in the middle.

    Needs Home Assistant for the zone and the pin; the driving half comes from
    in-progress legs and works without it, which is why a member with no person
    entity still appears when they are behind the wheel.
    """
    try:
        from services import ha_api
        driving = {r['driver_id']: r['title'] for r in (runs or []) if r.get('live')}
        wanted = set(_cfg_ids(config, 'members'))
        show_cars = _cfg_bool(config, 'cars', True)
        show_people = _cfg_bool(config, 'people', True)
        rows = []
        from services import stages
        for m in (storage.get_all_members() if show_people else []):
            if m.get('role') == 'helper' or m.get('system'):
                continue
            if wanted and m.get('id') not in wanted:
                continue
            # Stage privacy (load arc A4): the wall panel is the kiosk, and a
            # Navigator's whereabouts belong to the family, not the kitchen
            # wall. The row stays (a 🔒 chip, not a silent absence); driving
            # stays too, because that is the schedule speaking.
            private = (m.get('role') == 'child'
                       and stages.can(m, 'private_location'))
            state = lat = lon = None
            ent = None if private else m.get('ha_person_entity')
            if ent:
                try:
                    s = ha_api.get_state(ent) or {}
                    attrs = s.get('attributes') or {}
                    state = s.get('state')
                    lat, lon = attrs.get('latitude'), attrs.get('longitude')
                except Exception:
                    state = lat = lon = None
            leg = driving.get(m.get('driver_id'))
            # Everyone appears, tracked or not. "Where is everyone" has no
            # empty day, and a person silently missing from the list is worse
            # than a person shown as unknown — you cannot tell the difference
            # between "not tracked" and "not home".
            rows.append({'member_id': m.get('id'), 'name': m.get('name'),
                         'color_code': m.get('color_code'),
                         'avatar': m.get('avatar'), 'image': _member_image(m),
                         'state': state or None,
                         'latitude': lat, 'longitude': lon, 'is_car': False,
                         'private': private or None,
                         'driving': {'leg_title': leg} if leg else None})
        # Anyone out ranks anyone home: "everybody is home" is the boring case.
        # (The has-anything check waits until the vehicles are in — a card
        # configured to show only the cars has no people by design, and
        # bailing here would delete the very board somebody built.)
        rows.sort(key=lambda r: (not r['driving'], (r['state'] or '') == 'home',
                                 r['name'] or ''))
        # Cars ride along the bottom of the list and on the map as squares. A
        # car with no tracker is not a person with no phone — it simply is not
        # on the map — so unlike the family it is left out rather than shown
        # as unknown.
        try:
            from services import cars as cars_svc
            wanted_cars = set(_cfg_ids(config, 'car_ids'))
            for c in (storage.get_all_cars() if show_cars else []):
                if c.get('is_disabled') or not c.get('ha_device_tracker'):
                    continue
                if wanted_cars and str(c.get('id')) not in wanted_cars:
                    continue
                loc = cars_svc.car_location(c) or {}
                levels = cars_svc.car_levels(c) or {}
                rows.append({'member_id': f"car:{c.get('id')}", 'name': c.get('name'),
                             'color_code': c.get('color_code'),
                             'avatar': c.get('icon') or '🚗', 'image': c.get('image'),
                             'state': loc.get('state'), 'is_car': True,
                             'latitude': loc.get('latitude'),
                             'longitude': loc.get('longitude'),
                             'battery_pct': levels.get('battery_pct'),
                             'fuel_pct': levels.get('fuel_pct'),
                             'range': levels.get('range'),
                             'driving': None})
        except Exception as e:
            print(f"[home_board] map cars failed: {e}")
        # Buses. This USED to draw only while an in-service sensor said the
        # bus was running — sound reasoning (a stale pin at 3pm is a claim
        # about a bus that is not there) that in practice drew nothing at
        # all, because the sensor it depended on is HCTB-shaped and most
        # households do not have one. Reported from a wall with a correct
        # tracker and a correct stop and no pin, twice. The rule is now the
        # household's: if there is an entity to draw, draw it — the same
        # answer Home Assistant's own map gives, which is what anybody
        # comparing the two screens expects. The stop rides along as its own
        # pin, because "how far is it from the stop" is the actual question.
        try:
            from services import bus as bus_svc
            # Grouped by VEHICLE, not by child. Siblings on one bus each have
            # their own tracker entity reporting the same vehicle, so drawn
            # per child the wall would stack two identical pins and label them
            # separately — "Addison's bus" hiding "Cole's bus" underneath.
            buses, stops = {}, {}
            wanted_buses = set(_cfg_ids(config, 'bus_ids'))
            for m in (storage.get_all_members() if _cfg_bool(config, 'buses', False) else []):
                # A bus belongs to a CHILD's morning. Dropping this check is
                # how a grandmother got a school bus, and no amount of
                # cleverness downstream recovers from asking the wrong
                # question here.
                if m.get('role') != 'child':
                    continue
                if wanted_buses and m.get('id') not in wanted_buses:
                    continue
                # THE ONE GATE: is there an entity to draw? A morning stop
                # time is a scheduling fact that said nothing about a live
                # vehicle and made every PM-only rider invisible; an
                # in-service sensor from an integration this house does not
                # run answered False forever. `bus_map_position` reads either
                # of the two entity boxes.
                pos = bus_svc.bus_map_position(m)
                first = ((m.get('name') or '').split() or [''])[0]
                if pos:
                    # Keyed on the position ACTUALLY DRAWN. `bus_key` resolves
                    # the tracker its own way, so when the two disagreed — a
                    # tracker typed into the other box — siblings on one bus
                    # stopped merging and the pins were labelled by whichever
                    # child the key happened to land on.
                    key = bus_svc.bus_key(m, pos=pos)
                    entry = buses.setdefault(key, {'pos': pos, 'names': [],
                                                   'where': bus_svc.bus_where(m)})
                    if first and first not in entry['names']:
                        entry['names'].append(first)
                # The stop is drawn whether or not the bus is. It used to hang
                # off the vehicle — no live position, `continue`, no stop —
                # so the one pin that is ALWAYS true (a zone a parent drew on
                # a map; it does not move and it does not need an integration)
                # was missing exactly when it was the only thing left to say.
                # Where the bus stops is most of what a family walking past
                # the panel wants from this card at 7am.
                stop = bus_svc.stop_position(m)
                if stop:
                    # Stops group on POSITION: one bus can serve two stops
                    # (different schools, same vehicle), and two children at
                    # one stop is still one place to stand.
                    skey = (round(stop[0], 5), round(stop[1], 5))
                    sentry = stops.setdefault(skey, {'pos': stop, 'names': []})
                    if first and first not in sentry['names']:
                        sentry['names'].append(first)
            for key, b in buses.items():
                who = bus_svc._and_list(b['names'])
                rows.append({'member_id': f"bus:{key}",
                             'name': f"{who}'s bus" if who else 'School bus',
                             'avatar': '🚌', 'is_car': True,
                             'state': b['where'] or 'on the way',
                             'latitude': b['pos'][0], 'longitude': b['pos'][1],
                             'driving': None})
            for skey, st in stops.items():
                who = bus_svc._and_list(st['names'])
                rows.append({'member_id': f"stop:{skey[0]},{skey[1]}",
                             'name': f"{who}'s stop" if who else 'Bus stop',
                             'avatar': '🚏', 'is_car': True, 'state': None,
                             'latitude': st['pos'][0], 'longitude': st['pos'][1],
                             'driving': None})
        except Exception as e:
            print(f"[home_board] map buses failed: {e}")
        show_buses = _cfg_bool(config, 'buses', False)
        # A card configured to show NOTHING draws nothing — that is still
        # rule 1. But a card configured to show the cars draws even when no
        # car is reporting, because it vanishing as you tick the box is the
        # editor telling you the setting broke something. The people half
        # already worked this way (an untracked member is a row without a
        # pin, so the card stayed and the overlay explained), and the
        # asymmetry was the bug: same emptiness, two different behaviours.
        if not (show_people or show_cars or show_buses):
            return None
        # A blank install still draws nothing: people are ON by default and
        # every member produces a row (tracked or not), so no rows here means
        # no family yet rather than a quiet afternoon. That is the original
        # "no family members at all" case and it must survive — a fresh board
        # should not offer a map of nobody.
        if not rows and show_people:
            return None
        # Nothing to plot is not nothing to SHOW. A card whose pins have all
        # gone quiet used to draw a grey rectangle with a sentence on it,
        # which is the one thing this board is built to avoid — and it is
        # indistinguishable from a map that failed to load. Home is a real
        # place the family recognises at a glance, so the map draws itself
        # there and the sentence shrinks to a note in the corner. Absent when
        # nobody has told us where home is; then the old overlay is still the
        # honest answer.
        home = _home_center()
        return {'people': rows,
                # Read by the markup (whether the canvas takes pointer events),
                # by the renderer (Leaflet's own handlers and the marker
                # popups) and by the door logic — a map you can drag cannot
                # also be a link, or the first pan navigates away.
                'interactive': _cfg_bool(config, 'interactive', False),
                # What to say when there is nothing to draw. Server-side
                # because only this end knows WHICH of the three sources the
                # household asked for — "nobody is sharing a location" over a
                # card set to show only the cars is an answer to a question
                # nobody asked.
                'empty_text': ("Nobody is sharing a location yet." if show_people
                               else "No vehicle is sharing a location yet."),
                'mapped': sum(1 for r in rows if r.get('latitude') is not None
                              and r.get('longitude') is not None),
                # The view of last resort, never a marker: a house pin nobody
                # asked for would be a new thing on a map whose every other
                # symbol is somebody's location.
                'center': ({'latitude': home[0], 'longitude': home[1]}
                           if home else None)}
    except Exception as e:
        print(f"[home_board] map failed: {e}")
        return None


# Domains a tap may act on. An allowlist rather than "anything with a toggle
# service": a wall panel in a kitchen is reachable by everybody in the house
# including the people who cannot read yet, and `lock`, `cover` and `alarm_*`
# are not things a mis-tap should operate.
HA_TOGGLE_DOMAINS = ('light', 'switch', 'fan', 'input_boolean')

# What a household can ADD to that, deliberately and in one place.
#
# These were refused outright, on the reasoning that a wall panel in a kitchen
# is reachable by everybody in the house including the people who cannot read
# yet — which is a good reason to make it a decision rather than a default, and
# not a good enough reason to make it impossible. A household that wants to
# unlock the pool house from the panel it walks past knows more about its own
# doors than this file does.
#
# `alarm_control_panel` is NOT here and is not a toggle away. Disarming an
# alarm is the one control on this list whose failure mode is not "somebody
# opened a door they could have opened anyway".
HA_UNSAFE_DOMAINS = ('lock', 'cover', 'garage', 'valve')


def toggle_domains(settings: dict = None) -> tuple:
    """Which domains a tap may operate, for THIS household.

    A function rather than a constant because the answer is now a setting, and
    every caller — the tile, the board endpoint, the hosted-card service
    endpoint — has to get the same answer or the lock works from one surface
    and not another.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    if settings.get('panel_allow_unsafe_controls'):
        return HA_TOGGLE_DOMAINS + HA_UNSAFE_DOMAINS
    return HA_TOGGLE_DOMAINS

def _tile_music(now, config=None, **_):
    """Music Assistant, as a card on the wall.

    The payload is CONFIG plus one resolved speaker, and carries no transport
    state at all — deliberately, and this is the interesting decision in the
    tile. Board payloads are cached (`TTL_SECONDS`) and the panel polls them a
    minute apart, which is fine for what is for dinner and wrong for a play
    button: a pause/play glyph twenty seconds stale is a control that lies
    about what it will do, and the first thing anybody does with a wall music
    card is press it. So the card fetches its own state on the widget's ten
    second beat and this builder answers the two questions the browser cannot:
    is there a Home Assistant here, and which speaker does this ROOM mean.

    Room binding reuses `announce_targets` through `announce.pick_music_player`
    rather than inventing a second one — a house that has already said "the
    kitchen means the kitchen display" should not have to say it again because
    this surface plays instead of talks.
    """
    if not ha_configured():
        return None                       # see _tile_ha: unused, not quiet
    if not ha_available():
        return {'empty': "Needs Home Assistant."}
    room = _cfg_str(config, 'room')
    player = _cfg_str(config, 'player')
    room_label = ''
    try:
        from services import announce as announce_svc
        if not player and room:
            area = announce_svc.match_area(room)
            if area:
                room_label = area.get('name') or room
                player = announce_svc.pick_music_player(area) or ''
            else:
                # NAMED, not silently ignored: a room that was renamed in HA
                # would otherwise look like a card that simply forgot its
                # speaker, and nothing on the wall would ever lead anybody to
                # the setting that is now wrong.
                return {'empty': f"No room called “{room}” in Home Assistant."}
        if not player:
            player = announce_svc.pick_music_player() or ''
    except Exception as e:
        print(f"[home_board] music tile failed: {e}")
        return {'empty': "Could not reach Home Assistant."}
    # What Music Assistant will call this screen — the SHARED half of it.
    # Resolved server-side so the name is the same on every reload and every
    # browser pointed at this board, and because the name is also how the HA
    # entity is found again.
    #
    # And ONLY the shared half. The old fallback was the literal "Chauffeur
    # screen", which a house with two unnamed panels registered twice: two
    # Music Assistant players wearing one name, indistinguishable in the
    # picker, and — since HA deduplicates the entity_id and not the friendly
    # name — able to bind to each OTHER's entity. Empty now means "this board
    # has no name to give you", and the browser answers with one unique to the
    # device (`screenPlayerName` in home.html). It could not be minted here in
    # any case: this payload is CACHED across panels, so the second panel would
    # be served the first one's name.
    screen = (_cfg_str(config, 'screen_name')
              or (f"{room_label} screen" if room_label else ''))
    # The member row, for the per-person shelf. A wall panel is the one
    # surface that does not know who is standing at it — these chips are how
    # it asks. Kept to what the chips draw.
    members = []
    if _cfg_bool(config, 'show_members', True):
        try:
            members = [{'id': m['id'], 'name': m.get('name'),
                        'color_code': m.get('color_code'),
                        'avatar': m.get('avatar'), 'image': _member_image(m)}
                       for m in storage.get_all_members()]
        except Exception:
            members = []
    return {
        # May be '' — a house with HA and no speakers is a real state, and the
        # card says so rather than drawing dead transport buttons.
        'player': player,
        'room': room_label,
        'local_player': _cfg_bool(config, 'local_player', True),
        'screen_name': screen,
        'interactive': _cfg_bool(config, 'interactive', True),
        'members': members,
        'show': {
            'art': _cfg_bool(config, 'show_art', True),
            'picker': _cfg_bool(config, 'show_picker', True),
            'volume': _cfg_bool(config, 'show_volume', True),
            'search': _cfg_bool(config, 'show_search', True),
            'favorites': _cfg_bool(config, 'show_favorites', True),
            'members': _cfg_bool(config, 'show_members', True),
            'shelves': _cfg_bool(config, 'show_shelves', True),
        },
    }


# HA ships mdi icon names, and this app has no mdi font — an `mdi:thermometer`
# rendered literally is worse than no icon. A glyph per domain is the honest
# amount of decoration a board can promise for an arbitrary entity.
_HA_DOMAIN_GLYPH = {
    'light': '💡', 'switch': '🔌', 'fan': '🌀', 'lock': '🔒', 'cover': '🪟',
    'climate': '🌡️', 'sensor': '📈', 'binary_sensor': '⚫', 'person': '🧍',
    'device_tracker': '📍', 'media_player': '🎵', 'camera': '📷',
    'input_boolean': '🎚️', 'vacuum': '🧹', 'water_heater': '🚿',
    'weather': '🌤️', 'sun': '☀️', 'update': '⬆️', 'battery': '🔋',
}


def ha_configured() -> bool:
    """Is there a Home Assistant in this household's life at all?

    Configuration only, no request, instant. Separate from `ha_available()`
    because the two answer different questions and the board treats them
    completely differently: NOT CONFIGURED means the feature is unused and the
    tile should not exist (property 1, the same rule that hides the shopping
    tile from a household that never made a list), while CONFIGURED BUT
    UNREACHABLE means a set-up feature is quiet and has to say so.
    """
    try:
        from services import ha_api
        return ha_api.mode() != 'unconfigured'
    except Exception:
        return False


def ha_available() -> bool:
    """Configured AND answering.

    Cheap first, then real: `mode()` answers instantly, `is_available()` makes
    a request. Asking the expensive question when the cheap one already said
    there is no Home Assistant is how a household without one ends up waiting
    on a timeout to draw a board that has nothing to do with Home Assistant.
    """
    if not ha_configured():
        return False
    try:
        from services import ha_api
        return bool(ha_api.is_available())
    except Exception:
        return False


def ha_options() -> dict:
    """What the board editor's entity pickers offer.

    NOT part of `option_sources()` and not in the catalog, deliberately: an
    ordinary Home Assistant has hundreds to thousands of entities, and putting
    them in the payload every browser loads to edit a board would make the
    catalog the biggest thing on the page. The editor fetches this once, when
    somebody actually opens an entity picker.

    `available` is the whole graceful-degradation contract for the editor: a
    picker that knows HA is absent says so, rather than showing an empty list
    that is indistinguishable from "no matches".
    """
    if not ha_available():
        return {'available': False, 'entities': [], 'cameras': [], 'players': []}
    try:
        from services import ha_api
        entities, cameras = [], []
        for s in (ha_api.get_states(ttl=30) or []):
            eid = s.get('entity_id') or ''
            if not eid:
                continue
            name = (s.get('attributes') or {}).get('friendly_name') or eid
            row = {'value': eid, 'label': f'{name} — {eid}'}
            entities.append(row)
            if eid.split('.', 1)[0] in ('camera', 'image'):
                cameras.append(row)
        entities.sort(key=lambda r: r['label'].lower())
        cameras.sort(key=lambda r: r['label'].lower())
        return {'available': True, 'entities': entities, 'cameras': cameras,
                'players': _player_options()}
    except Exception as e:
        print(f"[home_board] ha options failed: {e}")
        return {'available': False, 'entities': [], 'cameras': [], 'players': []}


def _player_options() -> List[dict]:
    """Speakers the music card can be pinned to.

    Music Assistant's own players when there are any, the full media_player
    list when there are not — the same rule `/api/ha/media_players` applies,
    for the same reason: an HA instance accumulates dozens of TVs and cast
    targets MA cannot play to, and offering them is offering a choice that
    fails later.
    """
    try:
        from services import ha_api
        rows, ma = [], []
        for s in (ha_api.get_states(ttl=30) or []):
            eid = s.get('entity_id') or ''
            if not eid.startswith('media_player.'):
                continue
            attrs = s.get('attributes') or {}
            row = {'value': eid,
                   'label': f"{attrs.get('friendly_name') or eid} — {eid}"}
            rows.append(row)
            if 'mass_player_type' in attrs:
                ma.append(row)
        out = ma or rows
        out.sort(key=lambda r: r['label'].lower())
        return out
    except Exception as e:
        print(f"[home_board] player options failed: {e}")
        return []


def _tile_ha(now, config=None, settings=None, **_):
    """Any Home Assistant entities the household picked, as readings.

    Not a Lovelace card and not pretending to be one: HA's cards are custom
    elements that need a live `hass` object and an authenticated websocket, and
    there is no supported way to run one here. What IS portable is the DATA —
    entity, state, unit — and rendering that in the panel's own vocabulary
    reads better on this wall than an embedded rectangle of somebody else's
    theme would.
    """
    # No Home Assistant in this household AT ALL: the feature is unused and the
    # tile does not exist, which is property 1 and the same rule that hides the
    # shopping tile from a household that never made a list. The palette is
    # where a household without HA finds out — it marks these two unavailable
    # rather than letting somebody add a tile that could never appear.
    if not ha_configured():
        return None
    wanted = _cfg_ids(config, 'entities')
    interactive = _cfg_bool(config, 'interactive', False)
    if not wanted:
        # Added but never configured. "Pick some entities" is a thing to do;
        # an empty card is a puzzle.
        return {'empty': "Pick some entities in board setup."}
    # Set up, but not answering right now — restarting, rebooted, off the
    # network. A configured feature that is quiet says so.
    if not ha_available():
        return {'empty': "Needs Home Assistant."}
    try:
        from services import ha_api
        by_id = {s.get('entity_id'): s for s in (ha_api.get_states(ttl=30) or [])}
        rows = []
        for eid in wanted:
            s = by_id.get(eid)
            domain = eid.split('.', 1)[0]
            attrs = (s or {}).get('attributes') or {}
            state = (s or {}).get('state')
            rows.append({
                'entity_id': eid,
                'name': attrs.get('friendly_name') or eid,
                'glyph': _HA_DOMAIN_GLYPH.get(domain, '•'),
                'state': state,
                'unit': attrs.get('unit_of_measurement') or '',
                # An entity that has been renamed or removed in HA. NAMED
                # rather than dropped: a row silently disappearing from a wall
                # is how a household stops trusting the wall, and "this one is
                # gone" is the only thing that leads anybody to fix it.
                'missing': s is None,
                'on': state in ('on', 'home', 'open', 'unlocked', 'playing'),
                'toggleable': bool(interactive and domain in toggle_domains(settings)
                                   and s is not None),
            })
        return {'rows': rows,
                'state_only': _cfg_bool(config, 'show_state_only', False),
                'interactive': interactive}
    except Exception as e:
        print(f"[home_board] ha tile failed: {e}")
        return {'empty': "Could not reach Home Assistant."}


def _tile_ha_image(now, config=None, **_):
    """A camera or image entity, drawn as the tile.

    The picture itself is fetched by the BROWSER, through the app's existing
    `/api/ha/image` proxy — the board's payload carries a URL, not bytes. A
    board that inlined camera frames would put a JPEG into every poll of a
    payload the panel refetches every sixty seconds, and the whole point of
    `entity_picture` is that it is already a cacheable URL.
    """
    if not ha_configured():
        return None                       # see _tile_ha: unused, not quiet
    entity = _cfg_str(config, 'entity')
    if not entity:
        return {'empty': "Pick a camera in board setup."}
    if not ha_available():
        return {'empty': "Needs Home Assistant."}
    try:
        from services import ha_api
        st = ha_api.get_state(entity) or {}
        if not st:
            return {'empty': "That entity is not in Home Assistant."}
        domain = entity.split('.', 1)[0]
        picture = (st.get('attributes') or {}).get('entity_picture')
        if domain == 'camera':
            # The camera proxy DIRECTLY, not `entity_picture`. A camera's
            # entity_picture carries `?token=`, which Home Assistant rotates
            # every few minutes — and this board's payload is cached, then
            # cached again by the browser, so the URL a panel is holding can
            # easily outlive the token in it. `/api/camera_proxy/<entity_id>`
            # is the authenticated endpoint and needs no token at all, because
            # the proxy hop already carries our bearer.
            picture = f'/api/camera_proxy/{entity}'
        if not picture:
            # A real entity that offers no picture: an `image` entity that has
            # never been populated, or something that is not a picture at all.
            return {'empty': "That entity has no picture."}
        import base64
        token = base64.urlsafe_b64encode(picture.encode('utf-8')).decode().rstrip('=')
        return {
            'name': (st.get('attributes') or {}).get('friendly_name') or entity,
            # image64, not `?path=`: an encoded-slash query reads like a
            # traversal probe and gets dropped by some proxies. Same reason
            # that endpoint exists at all.
            'url': f'api/ha/image64/{token}',
            'refresh_seconds': _cfg_int(config, 'refresh_seconds', 60, 0, 3600),
        }
    except Exception as e:
        print(f"[home_board] ha image failed: {e}")
        return {'empty': "Could not reach Home Assistant."}


def ha_browser_base(settings: dict = None) -> str:
    """Where a BROWSER reaches Home Assistant — which is not where the server
    reaches it.

    `ha_base_url` is the server's route, and under the Supervisor it is
    `http://supervisor/core`: correct for us, meaningless in a browser. The
    frame needs the address a person would type.

    Empty is the right default and the useful one: under ingress the panel is
    already ON Home Assistant's origin, so a root-relative `/lovelace/0`
    resolves to HA and is same-origin, which is also the only arrangement in
    which HA will agree to be framed at all.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    return str(settings.get('ha_browser_url') or '').rstrip('/')


def _tile_ha_dashboard(now, config=None, settings=None, **_):
    """A dashboard view of theirs, framed.

    The board sends a URL and nothing else. It deliberately does NOT try to
    verify the view exists: that would mean fetching HA's frontend from the
    server, which proves nothing about whether the BROWSER can load it — the
    frame's two real failure modes are "not signed in" and "refused to be
    framed", and both are the browser's business, not ours.
    """
    if not ha_configured():
        return None                       # see _tile_ha: unused, not quiet
    path = _cfg_str(config, 'path')
    if not path:
        return {'empty': "Pick a dashboard view in board setup."}
    base = ha_browser_base(settings)
    if path.startswith(('http://', 'https://')):
        url = path
    else:
        url = f"{base}/{path.lstrip('/')}"
    return {
        'url': url,
        # Read off the RESOLVED url, not off whether a base is configured — a
        # `path` typed as a full https:// address is cross-origin however empty
        # the setting is. Only a root-relative url is same-origin, and
        # same-origin is the only arrangement in which Home Assistant reliably
        # agrees to be framed at all.
        'same_origin': not url.startswith(('http://', 'https://')),
        'chrome': _cfg_str(config, 'chrome', 'hide') or 'hide',
        'refresh_seconds': _cfg_int(config, 'refresh_seconds', 0, 0, 86400),
    }


def _tile_ha_card(now, config=None, **_):
    """A custom Home Assistant card, prepared server-side.

    Everything the browser needs travels in the board payload — the card's
    config, the states it references, where its file lives — because the board
    is one request per tick by design and a card's four sensors are just more
    board data. The browser's only extra fetch is the card's own JavaScript,
    once per page.

    Every failure here comes back as `empty`, which the panel renders as a
    sentence. That is the whole difference between this and an iframe: a frame
    that will not load is a grey rectangle, and a card that will not load can
    at least say whether the YAML was wrong, the file was missing, or the card
    itself refused the config.
    """
    if not ha_configured():
        return None                       # see _tile_ha: unused, not quiet
    raw = _cfg_str(config, 'config')
    if not raw:
        return {'empty': "Paste a card's YAML in board setup."}
    try:
        from services import ha_cards
        prepared = ha_cards.prepare(raw, _cfg_str(config, 'resource'))
    except Exception as e:
        print(f"[home_board] ha_card prepare failed: {e}")
        return {'empty': "That card could not be read."}
    if prepared.get('error'):
        return {'empty': prepared['error']}
    # Read by the host when the card calls a service. Server-side it is
    # enforced again by the endpoint's domain allowlist — the tile decides
    # what to offer, the server decides what may be operated.
    prepared['interactive'] = _cfg_bool(config, 'interactive', False)
    return prepared


def _tile_web(now, config=None, **_):
    """Any web page, framed.

    No Home Assistant anywhere in it, which is why it sits apart from the three
    HA tiles: a household with no HA still has a bus timetable.

    The URL is checked for a SCHEME and nothing else. This is a frame in the
    household's own browser, going wherever they typed — there is no server
    fetch to protect and no token to leak, so a validator here would only be
    inventing rules about which of their own pages they may look at. `http:` is
    allowed and left to the browser to complain about, since a panel served
    over https will block it as mixed content and say so in a way no message
    here could improve on.
    """
    url = _cfg_str(config, 'url')
    if not url:
        return {'empty': "Put an address in board setup."}
    if not url.startswith(('http://', 'https://')):
        return {'empty': "That needs to start with https:// (or http://)."}
    return {
        'url': url,
        'refresh_seconds': _cfg_int(config, 'refresh_seconds', 0, 0, 86400),
        'scroll': _cfg_bool(config, 'scroll', False),
        'zoom': _cfg_int(config, 'zoom', 100, 25, 400),
    }


def _tile_intake(now, **_):
    """A COUNT and nothing else. Intake is mail approvals and IMAP settings —
    an admin surface the kiosk rule keeps off shared screens — but "three
    things are waiting for a parent" is not confidential, and it is the only
    part of intake anybody needs from across a kitchen. The proposals
    themselves stay on /intake."""
    try:
        # Unconfigured means intake is switched off entirely; switched on with
        # an empty queue is "you are caught up", which is worth saying.
        if not (storage.get_settings() or {}).get('ingest_email_enabled'):
            return None
        # 'proposed' is the waiting-for-a-parent status — NOT 'pending', which
        # matches nothing and would have made this tile permanently silent.
        waiting = storage.get_proposals('proposed') or []
        return {'pending': len(waiting)} if waiting else {'empty': "Nothing waiting."}
    except Exception as e:
        print(f"[home_board] intake failed: {e}")
        return None


# --- tiles and cards ------------------------------------------------------
#
# A CARD draws content. A TILE is a container that holds cards, gives them a
# grid, and optionally puts a heading over them. Every tile on every board is
# one of these two shapes:
#
#   * BUILT-IN — `{id, type: 'chores', config}`, exactly what boards have always
#     stored. It is a LOCKED container holding one card of that type, and the
#     heading and the link out belong to the tile. Nothing about it changed
#     when cards arrived, so nothing needed migrating.
#   * CUSTOM — `{id, type: 'custom', config: {title, cards: [...]}}`. Starts
#     empty, takes any number of cards, lays them out on its own twelve
#     columns.
#
# The reason to split them at all is that the content was previously welded to
# the chrome around it: there was no way to put a chores list anywhere except
# inside the tile called Chores. Now the drawing is the same drawing wherever
# it goes, which is the only version of this that does not end in two
# renderers per type quietly disagreeing with each other.

CUSTOM_TILE = 'custom'

# What a REQUIRED tile says when its builder had nothing. Each one is the same
# sentence its own page shows on an empty day, because that is the honest
# answer and because a household reading both should not have to work out
# whether they are looking at the same state twice.
REQUIRED_EMPTY = {
    'task_list': "Nothing owed right now.",
    'errand_list': "No errands yet — add one on the Errands page.",
    'shopping_list': "Nothing on this list.",
    'shopping_staples': "Nothing the household keeps on hand yet.",
    'meals_week': "No dinners planned yet.",
    'chores_lanes': "No chores set up yet.",
    'chores_rewards': "No family goals yet.",
    'packing': "Nothing on the calendar today.",
    'routines_lanes': "No routines set up yet.",
    'kids': "Nothing on for the kids today.",
    'occasions': "Nothing coming up.",
    'trips': "No trips planned.",
    'trips_gallery': "No trips yet. Plan one on the Trips page and it will "
                     "show up here.",
    'calendar': "Nothing on the calendar.",
    'drives': "No drives today.",
    'map': "Nobody is sharing a location yet.",
    'moments': "No moments yet.",
    # Deliberately the fuller sentence rather than "No moments yet." — this is
    # the whole of the Moments board, so an empty one is the only thing on the
    # screen and had better say what the feature IS.
    'moments_gallery': "No moments yet. When somebody is at a game or a "
                       "recital, Chauffeur asks them to share one.",
    # Reached only when there is no Home Assistant AT ALL (`_tile_music`
    # returns None there; a configured-but-quiet HA answers with its own
    # sentence). Same shape as the map board's: the Music board explains
    # itself rather than vanishing off the shelf, because a board that
    # disappears is indistinguishable from one that broke.
    'music': "Needs Home Assistant — Chauffeur plays through Music Assistant.",
}


def container_types() -> set:
    """Tile types that hold cards the household chooses, rather than one the
    type chose. Declared in the catalog so the picker and the server agree
    without a second list."""
    return {w['key'] for w in WIDGETS if w.get('container')}


def normalize_cards(raw) -> List[dict]:
    """The cards inside one tile, as instances — the same `{id, type, config}`
    a tile is, because a card and a tile's content are the same thing.

    A container cannot hold a container. Not because it could not be made to
    work, but because a wall panel is read at a glance from across a room, a
    layout nested three deep is not read at all, and the markup that draws a
    card is the markup that draws a tile and cannot include itself.

    There is no limit on HOW MANY cards a tile holds. There was one — twelve,
    enforced by a silent `break` right here, so a board pasted in with a
    thirteenth card quietly lost it. It arrived with the first version of this
    function and was never argued for anywhere, and the asymmetry gave it away:
    a board takes any number of TILES, so twenty tiles of one card each cost
    exactly what one tile of twenty cards costs, and only the second was
    refused. A household that wants a dense tile can have one.
    """
    known = {w['key'] for w in WIDGETS} - container_types()
    out, taken = [], set()
    for item in raw or []:
        if isinstance(item, str):
            item = {'type': item}
        if not isinstance(item, dict):
            continue
        type_ = str(item.get('type') or '').strip().lower()
        if type_ not in known:
            continue
        wanted = str(item.get('id') or '').strip()
        iid = wanted if wanted and wanted not in taken else _instance_id(type_, taken)
        taken.add(iid)
        config = item.get('config')
        out.append({'id': iid, 'type': type_,
                    'config': dict(config) if isinstance(config, dict) else {}})
    return out


def _icon_of(config, meta) -> str:
    """The emoji drawn beside the heading: the household's if they typed one,
    otherwise the type's. Capped, because this is a glyph slot rather than a
    second title and a tile whose "icon" is a sentence pushes the name it
    belongs to off the row. The cap is 8 rather than 1: a single emoji is
    routinely several code points (a flag is two, 👨‍👩‍👧 is five with the
    joiners), and slicing one of those in half renders as rubble."""
    return (_cfg_str(config, 'icon') or '')[:8] or meta['icon']


def _build_card(card, now, **kw):
    """One card, drawn. Returns None when it has nothing to say — rule 1, which
    holds for a card in a tile exactly as it held for a tile on a board."""
    builder = _BUILDERS.get(card['type'])
    if not builder:
        return None
    config = card['config']
    # `editing` is for the ASSEMBLY around the builders, not for the builders
    # themselves — a card's content does not change because somebody is
    # arranging the board. Stripped here rather than trusted to every
    # builder's `**_`: one signature without it would raise, and this
    # function turns an exception into a silently missing card.
    kw = {k: v for k, v in kw.items() if k != 'editing'}
    try:
        payload = builder(now, config=config, **kw)
    except Exception as e:
        print(f"[home_board] card '{card['id']}' ({card['type']}) failed: {e}")
        return None
    if not payload:
        return None
    meta = next(w for w in WIDGETS if w['key'] == card['type'])
    return {
        'id': card['id'], 'type': card['type'], 'icon': _icon_of(config, meta),
        # The card-level twin of the custom tile's own `bare`: the cell keeps
        # its place on the tile's grid and stops drawing a surface, so a
        # household can compose a custom tile out of existing cards without
        # every one of them arriving in its own box. Read for cards in CUSTOM
        # tiles only — a built-in tile's card has no surface of its own to
        # drop (the tile is its surface, and the tile's `bare` is the switch).
        'bare': _cfg_bool(config, 'bare', False),
        # Two different questions. `label` is what the EDITOR calls this card
        # in a list of them, so it always has an answer. `title` is what gets
        # DRAWN over it, and blank means draw nothing and take no room — a
        # heading reading "A Home Assistant card" over a card that says what it
        # is, is the second label in a box that already had one.
        'label': (_cfg_str(config, 'title')
                  or meta.get('heading') or meta['label']),
        'title': _cfg_str(config, 'title'),
        # Twelfths of the TILE, which is the grid this card is laid out on —
        # the same unit a card inside a Home Assistant stack uses, so the
        # number means one thing everywhere on the page.
        'cols': _cfg_int(config, 'cols', 12, 1, 12),
        'rows': _cfg_int(config, 'rows', 0, 0, 1000),
        'config': config, 'data': payload}


def _build_tile(inst, now, **kw):
    meta = next((w for w in WIDGETS if w['key'] == inst['type']), None)
    if not meta:
        return None
    config = inst.get('config') or {}

    if inst.get('hidden'):
        # A STUB: no builder runs, so a parked tile costs the wall nothing —
        # no query, no cache read, and no way for a tile somebody shelved to
        # break the payload five other cards are waiting on. It still ships,
        # because the editor has to be able to draw it ghosted and give it
        # back. The client is what refuses to draw it outside arrange mode.
        return {'id': inst['id'], 'type': inst['type'], 'hidden': True,
                'icon': _icon_of(config, meta),
                'label': (_cfg_str(config, 'title')
                          or meta.get('heading') or meta['label']),
                'locked': True, 'config': config,
                'bare': inst['type'] in BARE_TILES, 'cards': [],
                'data': {'empty': 'Hidden — showing only while you arrange.'}}

    if inst['type'] in container_types():
        cards = []
        for card in normalize_cards(config.get('cards')):
            # Namespaced by the tile. A card draws the tile body element ids
            # and all, so a `calendar` card would otherwise answer to the same
            # id as the `calendar` tile beside it — one map rendered into the
            # other's canvas.
            cid = f"{inst['id']}-{card['id']}"
            built = _build_card(dict(card, id=cid), now, **kw)
            if not built and kw.get('editing'):
                # Same reasoning as the built-in tile below: a card inside a
                # custom tile that draws nothing is a card nobody can select
                # to fix.
                cmeta = next((w for w in WIDGETS if w['key'] == card['type']), None)
                if cmeta:
                    built = {'id': cid, 'type': card['type'],
                             'icon': _icon_of(card['config'], cmeta),
                             'label': (_cfg_str(card['config'], 'title')
                                       or cmeta.get('heading') or cmeta['label']),
                             'title': _cfg_str(card['config'], 'title'),
                             'cols': _cfg_int(card['config'], 'cols', 12, 1, 12),
                             'rows': _cfg_int(card['config'], 'rows', 0, 0, 1000),
                             'bare': _cfg_bool(card['config'], 'bare', False),
                             'config': card['config'],
                             'data': {'empty': REQUIRED_EMPTY.get(
                                 card['type'], "Nothing to show yet.")}}
            if built:
                cards.append(built)
        tile = {'id': inst['id'], 'type': inst['type'],
                'icon': _icon_of(config, meta),
                # A heading only if one was typed. An untitled custom tile is
                # a plain panel, which is what somebody wanting one surface
                # under three cards is asking for.
                'label': _cfg_str(config, 'title'),
                'bare': _cfg_bool(config, 'bare', False),
                'locked': False, 'cards': cards, 'config': config}
        if not cards:
            # A container somebody added on purpose and has not filled is not
            # an unconfigured feature; a tile that vanished could not be told
            # from one that had broken.
            tile['data'] = {'empty': "No cards in this tile yet."}
        return tile

    # A built-in tile: one card, and the chrome is the tile's.
    built = _build_card({'id': inst['id'], 'type': inst['type'],
                         'config': config}, now, **kw)
    if not built and kw.get('editing'):
        # WHILE EDITING, everything the board holds draws — reported from a
        # wall, and it is the sharper half of rule 1's cost: a card that
        # hides itself when it has nothing to say also hides itself from the
        # person trying to configure it, so a setting that emptied a card
        # could not be undone from the board it emptied. Rule 1 is about the
        # WALL, where reserved blank space is the thing being avoided; in the
        # editor a hole you cannot click is worse than a box that says it is
        # empty.
        built = {'id': inst['id'], 'type': inst['type'],
                 'icon': _icon_of(config, meta),
                 'label': (_cfg_str(config, 'title')
                           or meta.get('heading') or meta['label']),
                 'title': _cfg_str(config, 'title'),
                 'cols': 12, 'rows': 0, 'config': config,
                 'data': {'empty': REQUIRED_EMPTY.get(inst['type'],
                                                      "Nothing to show yet.")}}
    if not built and inst.get('require'):
        # The board is ABOUT this. Rule 1's "hide what is not set up" is right
        # on a mixed board and wrong here — an Errands board with no errands
        # card reads as broken rather than as empty, which is exactly how it
        # reached a wall. Say the true thing instead of leaving a hole.
        built = {'id': inst['id'], 'type': inst['type'],
                 'icon': _icon_of(config, meta),
                 'label': (_cfg_str(config, 'title')
                           or meta.get('heading') or meta['label']),
                 'title': _cfg_str(config, 'title'),
                 'cols': 12, 'rows': 0, 'config': config,
                 'data': {'empty': REQUIRED_EMPTY.get(inst['type'],
                                                      "Nothing here yet.")}}
    if not built:
        return None
    return {
        'id': inst['id'], 'type': inst['type'], 'icon': _icon_of(config, meta),
        # What the WALL says is the typed title and NOTHING else — blank
        # means blank, the same rule cards adopted in v2.204.1. The type's
        # wall sentence ("The rest of the day") stopped being a fallback in
        # v2.210: it is backfilled into v<3 boards' title fields by
        # _page_from instead, so old walls keep their words while the field
        # finally tells the truth about what is drawn — and clearing it
        # finally works.
        'label': built['title'], 'locked': True, 'config': config,
        # Chrome draws no panel: the payload says so rather than the client
        # keeping a second list of which types are chrome.
        'bare': inst['type'] in BARE_TILES,
        # Its one card fills the tile: full width, no height of its own, and
        # no surface of its own either — the tile IS its surface.
        'cards': [dict(built, cols=12, rows=0)],
        # The tile's data is its card's data. Kept because a built-in tile
        # having exactly one card is not an implementation detail, it is what
        # a built-in tile IS, and everything that reasoned about `tile.data`
        # before cards existed is still reasoning correctly.
        'data': built['data']}


_BUILDERS: dict = {
    'clock': _tile_clock, 'hero': _tile_hero, 'heading': _tile_heading,
    'drives': _tile_drives, 'kids': _tile_kids, 'meals': _tile_meals,
    'lists': _tile_shopping, 'chores': _tile_chores,
    'meals_week': _tile_meals_week, 'shopping_staples': _tile_shopping_staples,
    'shopping_list': _tile_shopping_list,
    'chores_lanes': _tile_chores_lanes, 'chores_rewards': _tile_chores_goals,
    'packing': _tile_packing,
    'routines': _tile_routines, 'routines_lanes': _tile_routines_lanes,
    'avatar_editor': _tile_avatar_editor, 'pets': _tile_pets,
    'occasions': _tile_occasions, 'weather': _tile_weather, 'moments': _tile_moments,
    'moments_gallery': _tile_moments_gallery,
    'calendar': _tile_calendar, 'errands': _tile_errands, 'tasks': _tile_tasks,
    'task_list': _tile_task_list, 'errand_list': _tile_errand_list,
    'trips': _tile_trips, 'trips_gallery': _tile_trips_gallery,
    'map': _tile_map, 'intake': _tile_intake, 'music': _tile_music,
    'ha': _tile_ha, 'ha_image': _tile_ha_image,
    'ha_dashboard': _tile_ha_dashboard, 'ha_card': _tile_ha_card,
    'web': _tile_web,
}


# --- assembly -------------------------------------------------------------

def _as_background(raw: Optional[str]) -> Optional[str]:
    """A URL is used as-is; anything else is treated as a search phrase and
    handed to the Unsplash endpoint that already backs trip artwork (which
    redirects, caches for a day, and falls back on its own). So "mountains at
    dusk" is a valid value, which is the point — nobody wants to go and find an
    image URL to hang a picture on their kitchen wall, and a household that has
    to find eleven of them will set none."""
    raw = str(raw or '').strip()
    if not raw:
        return None
    if raw.startswith(('http://', 'https://', '/', 'data:')):
        return raw
    import urllib.parse
    return f"api/unsplash/background?query={urllib.parse.quote(raw)}"


def _background_url(settings: dict) -> Optional[str]:
    return _as_background((settings or {}).get('panel_background'))


# --- Screensaver (idle photo slideshow) --------------------------------------

# The HA media share the add-on maps (config.yaml `map: media:rw`). A module
# constant so tests can point it at a temp directory.
MEDIA_SHARE_ROOT = '/media'
_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')


# Words for the same source. The canonical value is on the LEFT of the arrow
# nowhere — these are the ones a stored setting might hold that this module
# would otherwise not recognise. Coercing an unknown value to `photos` is the
# right default and was also what hid this: a setting that silently means
# something else can only be found by someone watching the wall.
SCREENSAVER_SOURCE_ALIASES = {
    'folder': 'media',
    'media_folder': 'media',
    'wallpaper': 'background',
}


def screensaver_config(settings: dict = None) -> dict:
    """The screensaver's knobs, resolved with the same absent-means-default
    discipline as idle_seconds: stored settings dicts predate this arc, so
    absent must mean the default, while an explicit 0 stays off."""
    settings = settings if settings is not None else (storage.get_settings() or {})

    def _int(key, default, lo=0, hi=24 * 3600):
        raw = settings.get(key)
        try:
            v = default if raw is None else int(raw)
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    source = str(settings.get('panel_screensaver_source') or 'photos').lower()
    # The editor says "a folder" because that is what a person calls it; this
    # module says `media` because that is the HA media share it reads. Those
    # two words were never introduced to each other, so picking "a folder"
    # stored `folder`, failed the membership test below, and fell back to
    # `photos` — a screensaver that could ONLY ever show the family's moments,
    # however it was set. Aliased rather than renamed on one side, so a
    # household that already chose it starts working without re-picking.
    source = SCREENSAVER_SOURCE_ALIASES.get(source, source)
    if source not in ('photos', 'media', 'background'):
        source = 'photos'
    # The master switch folds into idle_seconds: 0 already means "never
    # starts" everywhere downstream, so disabled needs no second flag on the
    # wire. Absent means enabled — the settings dict predates the switch.
    enabled = settings.get('panel_screensaver_enabled')
    enabled = True if enabled is None else bool(enabled)
    return {
        'idle_seconds': _int('panel_screensaver_idle_seconds', 600) if enabled else 0,
        'dwell_seconds': _int('panel_screensaver_dwell_seconds', 20, lo=5, hi=600),
        'source': source,
    }


def _media_share_images(subpath: str) -> List[str]:
    """Relative paths of image files under MEDIA_SHARE_ROOT/subpath, newest
    first, capped. The subpath comes from settings (admin-controlled), but the
    realpath containment check makes traversal a non-question rather than a
    judgment call."""
    import os
    root = os.path.realpath(MEDIA_SHARE_ROOT)
    raw = (subpath or '').strip()
    # ABSOLUTE paths are taken at their word, relative ones hang off the share
    # root. Both, because the field's own placeholder taught people to type
    # `/media/photos` while the code read the value as a SUBPATH of /media —
    # so the one path the UI suggested resolved to /media/media/photos, found
    # nothing, and fell back to the wallpaper. Containment below is what makes
    # accepting an absolute path safe rather than a decision.
    base = os.path.realpath(raw if raw.startswith('/')
                            else os.path.join(root, raw.strip('/\\')))
    if not (base == root or base.startswith(root + os.sep)):
        return []
    if not os.path.isdir(base):
        return []
    found = []
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            if f.lower().endswith(_IMAGE_EXTS) and not f.startswith('.'):
                full = os.path.join(dirpath, f)
                try:
                    found.append((os.path.getmtime(full), os.path.relpath(full, root)))
                except OSError:
                    continue
        if len(found) >= 500:
            break
    found.sort(reverse=True)
    return [rel.replace(os.sep, '/') for _mt, rel in found[:300]]


def screensaver_playlist(settings: dict = None) -> dict:
    """Fresh picture URLs for one screensaver activation. Fetched at
    activation time rather than shipped in the profile: a panel is loaded
    once and left up for weeks, and the photos should not be frozen at
    whatever existed on page load.

    Fallback chain: an empty source falls back to the wallpaper, and an empty
    wallpaper to [] — the client then shows its gradient + clock, which is
    still a better idle face than a burned-in schedule."""
    settings = settings if settings is not None else (storage.get_settings() or {})
    cfg = screensaver_config(settings)
    urls: List[str] = []
    if cfg['source'] == 'photos':
        # Moments photos (and video posters — a still is a still). since_ts=0:
        # moments are exempt from chat retention, so the whole archive is the
        # playlist, newest first. EVERY item of an album, not just its cover:
        # this is a slideshow of the family's photographs and more of them is
        # strictly better.
        _URL_CAP = 240
        for m in storage.get_recent_event_moments(0, limit=120):
            for att in storage.attachment_items(m.get('attachment')):
                url = att.get('url') or ''
                if not url.startswith('/api/media/'):
                    continue  # legacy inline data_url photos: too heavy for a playlist
                if (att.get('kind') or 'photo') == 'photo':
                    urls.append(url.lstrip('/'))
                else:
                    # Poster convention from the chat renderer: media id + .jpg
                    media_id = url.rsplit('/', 1)[-1].split('.')[0]
                    if storage.media_file_path(f'{media_id}.jpg'):
                        urls.append(f'api/media/{media_id}.jpg')
            # A handful of ten-photo albums must not crowd the rest of the
            # archive out of the playlist entirely.
            if len(urls) >= _URL_CAP:
                break
        del urls[_URL_CAP:]
    elif cfg['source'] == 'media':
        urls = ['api/panel/media-image/' + rel
                for rel in _media_share_images(settings.get('panel_screensaver_media_path') or '')]
    if not urls:
        bg = _background_url(settings)
        if bg:
            return {'source': 'background', 'urls': [bg]}
        return {'source': 'none', 'urls': []}
    return {'source': cfg['source'], 'urls': urls}


def backgrounds(settings: dict = None) -> dict:
    """`{'default': url|None, '<slug>': url}` — every board's picture,
    resolved. The whole map travels in the panel profile so a page change does
    not cost a round trip: the panel already has the answer before you tap.

    Built from THE BOARDS, which is the fix for two halves of one bug.

    It used to be built straight from a `panel_page_backgrounds` map — a
    second, separately-edited setting — and filtered to `NAV_SLUGS`, and a
    board's own `background` never entered into it. So:
      * a BUILT-IN board's picture could only be set from the shelf editor's
        second field, and the field on the board itself did nothing — reported
        exactly that way;
      * a CUSTOM board's picture was not in this map at all (its slug is not a
        nav slug), so a wall panel showing one fell back to the household
        default and the board's own field did nothing THERE either. The field
        appeared to work only in a browser, where home.html applies the board
        payload's answer directly.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    out = {'default': _background_url(settings)}
    pages = {p['slug']: p for p in normalize_pages(settings)}
    # The shipped boards too: a destination nobody has edited is still a board
    # a wall can be standing on, and it can still carry a legacy picture.
    for slug in BUILTIN_PAGES:
        if slug not in pages:
            page = builtin_page(slug, settings)
            if page:
                pages[slug] = page
    for slug, page in pages.items():
        url = _as_background(page.get('background'))
        if url:
            out[slug] = url
    return out


def _instance_id(type_: str, taken: set) -> str:
    """`calendar`, then `calendar-2`, `calendar-3`. Readable on purpose.

    The FIRST instance of a type gets the bare type as its id, which is what
    makes the upgrade free: every board that exists today stores a list of type
    names, and `panel_tile_spans` is keyed by those same names. Migrated
    instances therefore already have the right id and their sizes already line
    up. A uuid here would have needed a real data migration to avoid resetting
    everybody's tile sizes on upgrade.
    """
    if type_ not in taken:
        return type_
    n = 2
    while f'{type_}-{n}' in taken:
        n += 1
    return f'{type_}-{n}'


# A tile type this app used to answer to. Same bargain as `SLUG_ALIASES`, and
# the same reason: the vocabulary changed, the households' stored boards did
# not, and the failure mode of a word one side never heard of is silence.
TILE_ALIASES = {'shopping': 'lists'}


def normalize_instances(raw, settings: dict = None) -> List[dict]:
    """A board is a list of INSTANCES, and this is the only place that decides
    what one is.

    Until v2.180 a tile's type WAS its identity: `panel_widgets` was a list of
    type names, spans were keyed by type name, the payload carried one `key`,
    and `resolve_widgets` deduped — so a second calendar was silently dropped.
    That made "two calendars, configured differently" impossible by
    construction rather than by omission.

    An instance is `{id, type, config}`. `id` is what the board, the grid and
    the editor address; `type` is what it draws. Both shapes are accepted here
    because the stored setting is upgraded lazily — nothing rewrites anybody's
    settings behind their back, the editor simply saves the new shape the next
    time somebody touches the board.
    """
    known = {w['key'] for w in WIDGETS}
    spans = (settings or {}).get('panel_tile_spans') or {}
    out, taken = [], set()
    for item in raw or []:
        if isinstance(item, str):
            item = {'type': item}
        if not isinstance(item, dict):
            continue
        type_ = str(item.get('type') or item.get('key') or '').strip().lower()
        # The Lists glance was keyed `shopping` until v2.351.0, when the page
        # it opens stopped being called that. ALIASED here rather than migrated
        # in the database, because this is the one function that decides what a
        # stored tile IS — an unknown type is DROPPED two lines down, so a
        # household's board would simply lose the tile, on the next boot, with
        # nothing anywhere saying why.
        type_ = TILE_ALIASES.get(type_, type_)
        if type_ not in known:
            continue
        wanted = str(item.get('id') or '').strip()
        iid = wanted if wanted and wanted not in taken else _instance_id(type_, taken)
        taken.add(iid)
        config = item.get('config')
        inst = {'id': iid, 'type': type_,
                'config': dict(config) if isinstance(config, dict) else {}}
        # A tile the board is ABOUT. Only the shipped boards set it (a
        # household's own board is a mix, where rule 1's hiding is right), and
        # it survives normalisation so `_build_tile` can honour it.
        if item.get('require'):
            inst['require'] = True
        # PARKED BY HAND, and not the same thing as rule 1 at all. Rule 1 is
        # the system hiding a feature nobody has set up; this is a person
        # keeping a tile they are not ready to delete. One is invisible and
        # automatic, the other is a decision — so it has to be visible in the
        # editor and undoable, which is why it rides on the instance rather
        # than being expressed by removing the tile.
        if item.get('hidden'):
            inst['hidden'] = True
        # Size lives in `panel_tile_spans` keyed by instance id, which for a
        # migrated board is the same string it was always keyed by.
        span = item.get('span') if isinstance(item.get('span'), dict) else spans.get(iid)
        if isinstance(span, dict):
            inst['span'] = span
        out.append(inst)
    return out


# --- pages ------------------------------------------------------------------
#
# A board stopped being THE board here.
#
# Everything above this line was written for one wall panel showing one set of
# tiles, and the settings say so: `panel_widgets`, `panel_tile_spans`,
# `panel_grid_columns`, `panel_grid_row_height` are single household-wide keys.
# That held exactly as long as a tile was a summary of a Chauffeur page. It
# stopped holding the moment tiles became INSTANCES with their own config and
# could point at a specific Home Assistant entity: a driveway camera belongs on
# the hallway panel and nowhere else, and "what is on the board" became a
# question with more than one right answer per household.
#
# So a page is the unit now, and the old keys are what the FIRST page is built
# from when a household has never made one. That migration is lazy, like
# `normalize_instances` before it — nothing rewrites anybody's settings behind
# their back, and a household that never opens the editor keeps the board it
# has, byte for byte, forever.
#
# The rule that makes the rest of this simple: **`panel_pages` wins entirely
# once it exists.** A half-migrated state where the home page reads its columns
# from a page and its row height from a legacy key is the kind of split brain
# that produces a board nobody can explain, so there is no such state.

PAGE_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,30}$')

# The grid's limits, and there is no technical one.
#
# `grid-auto-rows` takes any length; `repeat(N, …)` takes any count. The cost
# of a wide grid is O(N) track sizing per layout pass, which at any number a
# household would type is unmeasurable next to drawing the tiles themselves —
# the work in a board is proportional to the number of TILES, and that does not
# change when the grid under them gets finer. A short row is the same story: it
# creates more implicit rows, and an implicit row with nothing in it costs
# nothing to lay out.
#
# So these are not a judgement about what is sensible any more. They are a
# guard against a value that would hang the panel it was typed into — a
# mis-keyed 100000 columns is a hundred thousand grid tracks on a Raspberry Pi,
# and the wall goes white. Anything a person would actually choose is far
# inside them.
#
# Raising COLUMN_MAX is safe for existing boards: stored spans are counts of
# columns and the board's own column count is a separate setting, so nothing
# rescales until somebody changes it. (Which they should know before they do —
# going from 12 to 48 makes every tile a quarter as wide. The editor says so.)
ROW_MIN, ROW_MAX = 1, 10000
COLUMN_MAX = 1000

# The first page is the wall's own board — the one `/home` shows, the one a
# panel returns to when it goes idle, the one the shelf's Home button means.
# It is reserved rather than merely conventional: a household that renamed it
# to `kitchen` would have a panel whose idle return goes nowhere.
HOME_SLUG = 'home'

# The shelf draws the app's own destinations as stroked 24×24 icons
# (nav.html's NAV_ITEMS) and drew boards as whatever emoji the household
# typed — two optical languages on one row, and the emoji always read as the
# odd one out. These are shelf-matched stroked paths a board can wear
# instead: the page's icon field stores `icon:<key>`, and every surface that
# draws an icon resolves the key to paths — any other value still renders as
# emoji text, so nobody's 🗂️ changes out from under them.
#
# It shipped as eighteen, which is a sample rather than a set: a household
# naming a board "Homework" or "Grandma's" or "Saturday" found nothing that
# fit and fell back to an emoji — the exact ragged row the stroked set exists
# to prevent. Sixty-three now, all Heroicons-v1 outline like NAV_ITEMS, so the
# two languages on the shelf stay one.
#
# GROUPED, and the grouping is the whole reason a bigger set is an improvement
# rather than a longer scroll: sixty stroked glyphs in one undifferentiated
# wrap is a worse picker than eighteen were. The groups are for the PICKER
# alone — resolution reads the flat `BOARD_ICONS` derived below, so no stored
# `icon:<key>` value depends on which group its icon sits in and icons can be
# regrouped freely.
BOARD_ICON_GROUPS = [
    ('Places', [
        ('home', ['M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6']),
        ('building', ['M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4']),
        ('briefcase', ['M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z']),
        ('map', ['M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7']),
        ('pin', [
            'M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z',
            'M15 11a3 3 0 11-6 0 3 3 0 016 0z',
        ]),
        ('globe', ['M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z']),
        ('truck', [
            'M9 17a2 2 0 11-4 0 2 2 0 014 0zM19 17a2 2 0 11-4 0 2 2 0 014 0z',
            'M13 16V6a1 1 0 00-1-1H4a1 1 0 00-1 1v10a1 1 0 001 1h1m8-1a1 1 0 01-1 1H9m4-1V8a1 1 0 011-1h2.586a1 1 0 01.707.293l3.414 3.414a1 1 0 01.293.707V16a1 1 0 01-1 1h-1m-6-1a1 1 0 001 1h1',
        ]),
        ('plane', ['M12 19l9 2-9-18-9 18 9-2zm0 0v-8']),
    ]),
    ('Time', [
        ('calendar', ['M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z']),
        ('clock', ['M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z']),
        ('refresh', ['M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15']),
        ('sun', ['M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z']),
        ('moon', ['M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z']),
    ]),
    ('People', [
        ('user', ['M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z']),
        ('users', ['M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z']),
        ('smile', ['M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z']),
        ('school', ['M12 14l9-5-9-5-9 5 9 5zm0 0l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14zm-4 6v-7.5l4-2.222']),
        ('chat', ['M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z']),
        ('heart', ['M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z']),
    ]),
    ('Home', [
        ('cart', ['M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z']),
        ('bag', ['M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z']),
        ('checklist', ['M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4']),
        ('cash', ['M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z']),
        ('gift', ['M12 8v13m0-13V6a2 2 0 112 2h-2zm0 0V5.5A2.5 2.5 0 109.5 8H12zm-7 4h14M5 12a2 2 0 110-4h14a2 2 0 110 4M5 12v7a2 2 0 002 2h10a2 2 0 002-2v-7']),
        ('cake', ['M21 15.546c-.523 0-1.046.151-1.5.454a2.704 2.704 0 01-3 0 2.704 2.704 0 00-3 0 2.704 2.704 0 01-3 0 2.704 2.704 0 00-3 0 2.704 2.704 0 01-3 0 2.701 2.701 0 00-1.5-.454M9 6v2m3-2v2m3-2v2M9 3h.01M12 3h.01M15 3h.01M21 21v-7a2 2 0 00-2-2H5a2 2 0 00-2 2v7h18zm-3-9v-2a2 2 0 00-2-2H8a2 2 0 00-2 2v2h12z']),
        ('key', ['M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z']),
        ('lock', ['M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z']),
        ('cog', [
            'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z',
            'M15 12a3 3 0 11-6 0 3 3 0 016 0z',
        ]),
        ('wifi', ['M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.141 0M1.394 9.393c5.857-5.857 15.355-5.857 21.213 0']),
        ('phone', ['M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z']),
    ]),
    ('Media', [
        ('photo', ['M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z']),
        ('camera', [
            'M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z',
            'M15 13a3 3 0 11-6 0 3 3 0 016 0z',
        ]),
        ('film', ['M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z']),
        ('tv', ['M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z']),
        ('music', ['M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3']),
        ('speaker', ['M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z']),
        ('mic', ['M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z']),
        ('book', ['M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253']),
    ]),
    ('Signals', [
        ('bell', ['M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9']),
        ('star', ['M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z']),
        ('sparkles', ['M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z']),
        ('fire', [
            'M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z',
            'M9.879 16.121A3 3 0 1012.015 11L11 14H9c0 .768.293 1.536.879 2.121z',
        ]),
        ('bolt', ['M13 10V3L4 14h7v7l9-11h-7z']),
        ('flag', ['M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9']),
        ('check', ['M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z']),
        ('alert', ['M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z']),
        ('question', ['M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z']),
        ('bulb', ['M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z']),
        ('bookmark', ['M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z']),
        ('ticket', ['M15 5v2m0 4v2m0 4v2M5 5a2 2 0 00-2 2v3a2 2 0 110 4v3a2 2 0 002 2h14a2 2 0 002-2v-3a2 2 0 110-4V7a2 2 0 00-2-2H5z']),
        ('cloud', ['M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.002 4.002 0 003 15z']),
    ]),
    ('Work', [
        ('document', ['M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z']),
        ('folder', ['M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z']),
        ('stack', ['M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10']),
        ('inbox', ['M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4']),
        ('mail', ['M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z']),
        ('chart', ['M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z']),
        ('beaker', ['M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z']),
        ('pencil', ['M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z']),
        ('palette', ['M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01']),
        ('shield', ['M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z']),
        ('puzzle', ['M11 4a2 2 0 114 0v1a1 1 0 001 1h3a1 1 0 011 1v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H7a1 1 0 01-1-1v-3a1 1 0 00-1-1H4a2 2 0 110-4h1a1 1 0 001-1V7a1 1 0 011-1h3a1 1 0 001-1V4z']),
        ('grid', ['M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z']),
    ]),
]

# Flat lookup, derived so the groups above stay the single source of truth.
# Everything that RESOLVES an icon reads this; only the picker needs the
# grouping.
BOARD_ICONS = {k: paths for _, items in BOARD_ICON_GROUPS for k, paths in items}


def icon_paths(icon) -> Optional[List[str]]:
    """The stroked paths behind an `icon:<key>` value, or None for emoji."""
    if isinstance(icon, str) and icon.startswith('icon:'):
        return BOARD_ICONS.get(icon[5:])
    return None


def _norm_icon(raw) -> str:
    """A page's icon field: a known `icon:<key>` survives whole, anything
    else is emoji text and keeps the old four-character clamp."""
    icon = str(raw or '🗂️').strip()
    if icon.startswith('icon:') and icon[5:] in BOARD_ICONS:
        return icon
    return icon[:4] or '🗂️'


def _slugify(name: str, taken: set) -> str:
    """A page's address, from its name. `Kitchen Wall` -> `kitchen-wall`."""
    base = re.sub(r'[^a-z0-9]+', '-', str(name or '').strip().lower()).strip('-')
    base = base[:31] or 'page'
    if not PAGE_SLUG_RE.match(base):
        base = 'page'
    slug, n = base, 2
    while slug in taken:
        slug = f'{base}-{n}'
        n += 1
    return slug


def _page_from(item: dict, settings: dict, taken: set) -> dict:
    """One stored page, normalised. Every field has a fallback to the household
    setting it replaced, so a page saved by an older editor — or hand-written
    into settings — is a complete page rather than a board with no columns."""
    name = str(item.get('name') or '').strip() or 'Board'
    slug = str(item.get('slug') or '').strip().lower()
    if not PAGE_SLUG_RE.match(slug) or slug in taken:
        slug = _slugify(item.get('slug') or name, taken)
    spans = item.get('spans')
    # A COPY, not the stored dict: the chrome migration below adds spans for
    # the tiles it injects, and adding them to the household's own dict would
    # be the read-time rewrite this whole layer promises never to do.
    spans = dict(spans) if isinstance(spans, dict) else {}
    # The tiles, through the same normaliser every board has always used —
    # so a page accepts the old list-of-type-names shape too, and pasting
    # one board's widgets into another page just works.
    widgets = normalize_instances(item.get('widgets'),
                                  {'panel_tile_spans': spans})
    columns = _cfg_int(item, 'columns', grid_columns(settings), 1, COLUMN_MAX)
    # Page schema version. A v1 board was drawn under hardcoded chrome — the
    # clock strip and the hero band lived in the template, above the grid, on
    # every board unconditionally. v2 made them tiles, so a v1 board gets
    # them PREPENDED here, full width: the wall keeps looking like itself,
    # and the household can now move, resize or delete what it previously
    # could only have. Lazy like everything else in this layer — the stored
    # setting is rewritten only when somebody saves, and the editor saves v2.
    try:
        version = int(item.get('v') or 1)
    except (TypeError, ValueError):
        version = 1
    if version < 2:
        have = {w['type'] for w in widgets} | {w['id'] for w in widgets}
        # Injected in chrome order — clock above hero, both above the rest —
        # and AFTER any chrome the board somehow already holds, so a partial
        # list never ends up interleaved backwards.
        at = 0
        while at < len(widgets) and widgets[at]['type'] in ('clock', 'hero'):
            at += 1
        for wtype in ('clock', 'hero'):
            if wtype in have:
                continue
            spans.setdefault(wtype, {'cols': columns, 'rows': 1})
            widgets.insert(at, {'id': wtype, 'type': wtype, 'config': {},
                                'span': spans[wtype]})
            at += 1
    if version < 3:
        # v3: blank means blank. Until v2.210 an untitled built-in tile fell
        # back to its type's wall sentence, so a heading could never be
        # REMOVED. The fallback is gone; what a v<3 board was showing gets
        # written into each tile's title field instead — the wall keeps its
        # words, the field finally matches the wall, and clearing it works.
        # Chrome and containers never had the fallback, so they stay blank.
        for w in widgets:
            meta = next((m for m in WIDGETS if m['key'] == w['type']), None)
            if not meta or meta.get('container') or w['type'] in BARE_TILES:
                continue
            cfg = w.setdefault('config', {})
            if not str(cfg.get('title') or '').strip():
                cfg['title'] = meta.get('heading') or meta['label']
    # The gutter between tiles, the third number a grid is (was a hardcoded
    # Tailwind gap-4). 0 is legal and means seamless.
    gap = _cfg_int(item, 'gap', 16, 0, 100)
    row_height = _cfg_int(item, 'row_height', grid_row_height(settings),
                          ROW_MIN, ROW_MAX)
    if version == 4:
        # v4 (one release, v2.214.0) padded every stored row height by one
        # gap for the painted-inset model, whose box was R*row_height - gap.
        # v5's box is R*row_height EXACTLY — a tile is the same size at any
        # gutter — so the padding comes back off. Boards that skipped v4
        # (v<4 stored) were never padded and keep their numbers: their
        # single-row tiles keep their exact height, and a multi-row tile
        # gives up the (R-1) gutters its spans used to swallow, which is
        # the point of the whole change.
        row_height = max(ROW_MIN, row_height - gap)
    return {
        'slug': slug,
        'name': name,
        'icon': _norm_icon(item.get('icon')),
        'v': 5,
        'widgets': widgets,
        'spans': spans,
        'columns': columns,
        'row_height': row_height,
        'gap': gap,
        # Blank means the household's own background. Two levels of "not set"
        # rather than three: a page either has a picture of its own or takes
        # the household's.
        #
        # ONE place, since v2.227.0. Per-page pictures used to live in a
        # `panel_page_backgrounds` map edited from a second field on the shelf
        # row, and that map was what the wall actually applied — so a board's
        # own field did nothing and the household had two settings for one
        # thing, the wrong one of which looked authoritative. The map is gone,
        # not deprecated: there is one install of this app, it had nothing
        # stored under that key, and a compatibility path nobody needs is a
        # second way for this to be wrong again.
        'background': str(item.get('background') or '').strip(),
    }


def _legacy_page(settings: dict) -> dict:
    """The board this household already has, as a page.

    Built from the pre-pages settings keys and given the reserved home slug, so
    upgrading changes nothing anybody can see: same tiles, same sizes, same
    grid, same picture. A household that never opens the editor never learns
    that pages happened.

    A household with NOTHING is a different question, and it used to get the
    same answer: `DEFAULT_WIDGETS` — thirteen tiles, unsized, on a 12-column
    grid of 240px rows. Every board this app ships is 64 columns of 10px rows
    with spans somebody chose, so the one board a family met first was the only
    one nobody had laid out. It gets `HOME_SEED` now.

    The test is `panel_widgets`, not "are there pages": a stored board means a
    household who arranged one before pages existed, and their board wins over
    anything we ship. The seed is for the empty install and nowhere else.
    """
    settings = settings or {}
    if not settings.get('panel_widgets') and HOME_SEED:
        item = json.loads(json.dumps(HOME_SEED))
        item['slug'] = HOME_SLUG
        return _page_from(item, settings, set())
    return _page_from({
        'slug': HOME_SLUG,
        'name': 'Home',
        'icon': '🏠',
        'widgets': settings.get('panel_widgets') or list(DEFAULT_WIDGETS),
        'spans': settings.get('panel_tile_spans') or {},
        'columns': grid_columns(settings),
        'row_height': grid_row_height(settings),
        # No picture of its own: this is the PRE-pages board, and there was
        # nowhere to have set one per page. It takes the household's.
        'background': '',
    }, settings, set())


def normalize_pages(settings: dict = None) -> List[dict]:
    """Every board this household has, and NEVER an empty list.

    A blank result would be a wall with nothing on it, which is the failure
    this whole module is built to avoid — so an install with no pages gets the
    legacy board, and an install whose pages all failed validation gets it too.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    raw = settings.get('panel_pages')
    pages, taken = [], set()
    for item in (raw if isinstance(raw, list) else []):
        if not isinstance(item, dict):
            continue
        # A stored page under a SHIPPED board's slug is a fork from the old
        # model, and it does not win any more (v2.229.0). The shipped boards
        # are authored data; a household changes one by duplicating it into a
        # board of their own. Dropped on READ rather than migrated, like every
        # other change in this layer — nothing rewrites anybody's settings
        # behind their back, and the stored copy simply stops being consulted.
        if str(item.get('slug') or '').strip().lower() in BUILTIN_PAGES:
            continue
        page = _page_from(item, settings, taken)
        taken.add(page['slug'])
        pages.append(page)
    if not pages:
        return [_legacy_page(settings)]
    # SOMETHING has to be the wall's own board. If nothing claims the reserved
    # slug — a hand-edited setting, or a household that deleted the home page
    # from a future editor — the first page becomes it rather than the panel
    # having nowhere to return to.
    if not any(p['slug'] == HOME_SLUG for p in pages):
        pages[0]['slug'] = HOME_SLUG
    return pages


# ── The app's own destinations, as boards.
#
# What the panel shelf did until now: every button on it opened the ADMIN page.
# The Errands button opened a page whose top half is two editors and a
# natural-language input; the Routines button opened per-member editing forms.
# On a screen nobody can type on, mounted where everybody in the house can
# reach it, that is the wrong half of the page — a wall wants the LISTS, with
# the taps that finish something, and nothing else.
#
# So each destination has a board here. `?panel=true` on that destination draws
# it instead of the page, and everything a board can do — resize, reorder,
# retitle, filter to one child, drop a card, add one from anywhere else in the
# app — applies to it, because it is not a special screen. It is a board.
#
# These are AUTHORED, and they are the product. They are not defaults a
# household edits into their own copy — that model is gone (v2.229.0). It read
# as generous and behaved as a trap: editing one forked it into `panel_pages`,
# their fork won forever, and no improvement we ever shipped reached them
# again. By the time it was noticed all ten had forked on this very install and
# none of them tracked anything. A household may HIDE one of these from the
# shelf; to change one, they Duplicate it into a board of their own.
#
# Which makes this file the way we author them: set a board up on a real
# instance against real chores and real photos, export it, and write it here.
# See `docs/boards_editor_design.md`.
#
# `columns`, `row_height` and `gap` are stated rather than inherited: a span
# here is a count of columns, so a household that put their home board on a
# 24-column grid would otherwise get every one of these at half width.
#
# Heights are `auto` almost everywhere, and that is not laziness. A list's
# height is not a number anybody can type: four children with eleven routine
# items each is a different height every morning, so one guess is either short
# (the wall cuts the last child off — which is exactly how these shipped) or
# tall (a band of empty panel under the last row). `auto` means the tile is as
# tall as whatever it is showing, measured client-side (home.html's `autoPx`).
# Only tiles whose content is laid out INTO them — a map, a timeline, a
# mosaic — keep a stated `rows`, because there the height decides the content
# rather than the other way round.
#
# `require` marks a tile the board is ABOUT. Rule 1 hides a feature nobody has
# set up, which is right on a mixed board and wrong here: an Errands board with
# no errands card reads as broken rather than as empty, and that is exactly how
# it reached a wall. A required tile says so instead of vanishing.
# The per-board reasoning that used to live in comments between these entries,
# kept here because it is the kind of decision that gets undone by accident:
#   - errands states `show_completed: False` — the one place the conversion
#     paradigm's "every section defaults on" is overridden, and deliberately in
#     the instance rather than in the option's default, so the toggle keeps
#     meaning "the page shows this". A wall is about what is left.
#   - map and chores_lanes state `interactive: True`. That option defaults OFF
#     because a tile on a mixed board is a door and a dragged view stays
#     dragged; these boards ARE that page, so there is no door to protect, and
#     a map you cannot pan is a screenshot.
#   - the galleries and lists FILL. How many trips a family has, or errands, is
#     not a number anybody can type, and a stated height is either short (the
#     wall cuts the last one off) or a band of empty panel.
#   - no board carries a leaderboard or a streak strip: the lanes already carry
#     rank and the streak in their own headers, and both kiosks decided against
#     showing it twice.
# Beside this module rather than in a `data/` directory, deliberately:
# `chauffeur/data/` is git-ignored as a secrets folder, so a boards file in
# there is one that never reaches the repo and never ships — the add-on would
# build with no shipped boards at all and say nothing about it.
_BUILTIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'builtin_boards.json')


def _load_builtin_pages() -> dict:
    """The shipped boards, off disk.

    Data rather than a Python literal because this file is WRITTEN — a board is
    authored by setting it up on a real instance and exporting it, and a dict
    full of prose is not something a machine can rewrite without destroying the
    prose. Hence the comment block above rather than notes in the JSON.

    A missing or unreadable file leaves the app with no shipped boards rather
    than no app: every destination is still reachable as its admin page, and
    the shelf reads `NAV_SLUGS` rather than this. Loud on stdout, because the
    only way it happens is a build that dropped its package data.
    """
    try:
        with open(_BUILTIN_PATH, encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[home_board] shipped boards unavailable ({_BUILTIN_PATH}): {e}")
        return {}


# The wall's own board, as a STARTING POINT — and deliberately not one of the
# shipped boards above.
#
# The difference is the whole design. A shipped board is authored data that
# WINS: `normalize_pages` drops any stored page under a shipped slug, so a
# household changes one by duplicating it. Apply that to `home` and every
# household's customised home board is silently discarded on the next read —
# which is precisely the failure v2.288.0 exists to prevent, delivered by a
# different door.
#
# So it is popped out of `BUILTIN_PAGES` before that dict is ever consulted.
# `home` is not a shipped slug, the drop rule never sees it, `own_boards` and
# the shelf are unchanged, and this is read in exactly one place: the fresh
# install that has no board of any kind.
_ALL_BUILTIN = _load_builtin_pages()
HOME_SEED = _ALL_BUILTIN.pop(HOME_SLUG, None)
BUILTIN_PAGES = _ALL_BUILTIN


def builtin_page(slug: Optional[str] = None, settings: dict = None):
    """The board this app ships for one of its own destinations, or None.

    A fresh copy every call — the spec above is module state, and `_page_from`
    hands its spans dict out to callers who are entitled to edit what they were
    given.

    THE PICTURE. A household picture for this board wins over the authored one.
    That is a per-slug map feeding a background in `builtin_page`, which is the
    shape of the v2.227.0 bug, and it is worth being precise about why it is
    not that bug. Then: two HOUSEHOLD settings for one thing — a board's own
    editable `background` field and a separate map — and the map won, so the
    field that looked authoritative did nothing. Now: a shipped board has no
    household-editable field at all, because the board is authored data. This
    map IS the household's field for these boards, and it is the only one, so
    there is nothing for it to silently overrule. A board the household OWNS
    still keeps its own field and never appears in this map.

    Precedence, and it is the only one: household picture, then the authored
    one, then (via `_as_background` returning nothing) the panel background.
    """
    wanted = str(slug or '').strip().lower()
    spec = BUILTIN_PAGES.get(wanted)
    if not spec:
        return None
    settings = settings if settings is not None else (storage.get_settings() or {})
    item = json.loads(json.dumps(spec))
    item['slug'] = wanted
    mine = (settings.get('panel_shipped_backgrounds') or {})
    if isinstance(mine, dict):
        # Blank means "no answer", not "no picture" — same two-levels-of-unset
        # discipline every other background field has, so clearing the box
        # falls back to the authored picture rather than to the gradient.
        picked = str(mine.get(wanted) or '').strip()
        if picked:
            item['background'] = picked
    return _page_from(item, settings, set())


def own_boards(settings: dict = None) -> List[dict]:
    """The household's OWN boards — every page that is neither the wall's home
    board nor one of the app's own destinations.

    A stored page whose slug IS a destination is that destination's board: the
    shelf already has a button for it, and offering it a second time as "a
    board" would put two Errands side by side on a wall and make the editor
    ask which one you meant.
    """
    return [p for p in normalize_pages(settings)
            if p['slug'] != HOME_SLUG and p['slug'] not in BUILTIN_PAGES]


def home_slug(settings: dict = None) -> str:
    """WHICH board is home. `home` unless the household said otherwise.

    Hiding the Home board from the shelf was the ask; this is the primitive
    that actually delivers it. `/home` is the landing route, the idle-return
    target and what the shelf's Home button means, so hiding that board
    without moving those left the wall snapping back every three minutes to a
    board somebody had deliberately taken off the shelf.

    With a designation, "build my own home board" is a first-class act and
    hiding becomes an ordinary toggle with no special case. Falls back when it
    names a board that is gone — a dangling pointer here is a wall with
    nowhere to return to.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    wanted = str(settings.get('panel_home_board') or '').strip().lower()
    if wanted and any(p['slug'] == wanted for p in normalize_pages(settings)):
        return wanted
    return HOME_SLUG


def find_page(slug: Optional[str] = None, settings: dict = None) -> dict:
    """The page a URL asked for, or the home board.

    Stored first, then the shipped board for that destination, then home. An
    unknown slug falls back rather than 404ing, because the address that
    produces it is a wall panel's bookmark and a deleted page must not leave a
    screen showing an error. The board it lands on is a real board.
    """
    pages = normalize_pages(settings)
    wanted = str(slug or '').strip().lower()
    if wanted:
        for p in pages:
            if p['slug'] == wanted:
                return p
        built = builtin_page(wanted, settings)
        if built:
            return built
    # No slug means HOME, and home is wherever the household put it. `/home`
    # is the one address that means "the home board" rather than a particular
    # board, so a designation here is all the idle timer and the shelf's Home
    # button need — both already point at `/home`.
    at_home = home_slug(settings)
    return next((p for p in pages if p['slug'] == at_home),
                next((p for p in pages if p['slug'] == HOME_SLUG), pages[0]))


def resolve_instances(requested: Optional[str] = None,
                      settings: dict = None,
                      page: dict = None) -> List[dict]:
    """URL wins, then the stored panel profile, then the default set.

    The URL has to win because an HA dashboard card is a second panel with
    different needs, and its config channel is its own address. The stored
    profile exists so the display bolted to a wall needs no address at all —
    the case that a URL-only design serves worst.

    Two URL grammars, because those are two different jobs. `?widgets=drives,
    calendar` is the one people type and the one every existing card uses: a
    list of types, default config, unchanged. A JSON array is the one a card
    generates when it wants a configured board — now that a tile has options,
    a comma-separated list of names can no longer express what a card might
    want, and inventing a mini-language in a query string would be worse than
    admitting it is JSON.

    An empty result always falls back to the defaults. "Show nothing" is never
    what someone meant by a blank setting, and a blank screen on a wall is
    indistinguishable from a crash.

    `page` is the board being drawn. It beats the household-wide setting and
    loses to the URL, which keeps the precedence people already know: the
    address a card was given is still the most specific thing in the system.
    """
    if requested is not None:
        raw = requested.strip()
        if raw.startswith('['):
            try:
                picked = normalize_instances(json.loads(raw), settings)
            except (ValueError, TypeError):
                picked = []
        else:
            picked = normalize_instances(
                [s.strip().lower() for s in raw.split(',')], settings)
        if picked:
            return picked
    if page is not None:
        # A page's tiles are already normalised; an EMPTY page is a real state
        # (somebody just made it) and must not silently fill with the defaults,
        # or a new board would arrive with thirteen tiles nobody asked for.
        return list(page.get('widgets') or [])
    picked = normalize_instances((settings or {}).get('panel_widgets'), settings)
    return picked or normalize_instances(list(DEFAULT_WIDGETS), settings)


def resolve_widgets(requested: Optional[str] = None, settings: dict = None) -> List[str]:
    """The instance TYPES, in order. Kept for callers that only need to know
    which kinds of tile a board contains — it can no longer identify one."""
    return [i['type'] for i in resolve_instances(requested, settings)]


# The shelf's vocabulary — the same slugs `?tabs=` already speaks, plus the
# home board itself. Kept here rather than in the template because the panel
# profile endpoint has to validate against it.
# `intake` left this list in v2.232.0. It was the one nav slug that is not a
# board — mail approvals and IMAP settings, an admin surface — and it was
# already off DEFAULT_TABS for exactly that reason, so it could be added to a
# shelf and never was on purpose. A vocabulary with one member that means
# something else is a vocabulary with an exception to explain forever. It
# stays on the desktop nav, where admin lives; if a kiosk-shaped intake is
# ever designed, it joins the shipped boards like everything else.
# `shopping` became `meals` in v2.351.0 and `lists` joined it. The page named
# Shopping was never about shopping in general — it plans dinners and keeps the
# one standing list a grocery run empties — so it is Meals & Groceries now, and
# Shopping & Lists is every OTHER list a family keeps. Stored shelves are
# rewritten by `migrate_shopping_slug_v2351`; `/shopping` still redirects.
NAV_SLUGS = ['home', 'schedule', 'calendar', 'errands', 'meals', 'lists',
             'occasions', 'chores', 'routines', 'trips', 'map', 'moments',
             'music']
# Every destination except the admin one. An earlier six-slug default put more
# than half the app out of reach from the panel, which is not a shelf, it is a
# bookmark bar. The shelf measures itself and moves whatever does not fit into
# a "More" flyout, so the number of destinations is no longer a design
# constraint that has to be guessed here. Intake stays off: it is an admin
# surface (mail approvals, IMAP settings) and the kiosk rule has always been to
# keep it off shared screens.
DEFAULT_TABS = ['home', 'schedule', 'calendar', 'chores', 'routines', 'meals',
                'lists', 'errands', 'occasions', 'trips', 'map', 'moments',
                'music']


# A slug this app used to answer to. ALIASED rather than dropped, which is the
# screensaver's `folder` lesson (v2.235.1): one side stored a word the other
# side had never heard of, and the feature silently fell back forever with
# nothing anywhere saying so. A stored shelf is rewritten once by
# `migrate_shopping_slug_v2351`, but a `?tabs=` on a bookmarked wall panel is
# not ours to rewrite — and an unknown slug in that list VANISHES, so without
# this the Meals button would simply stop existing on the screen most likely to
# be carrying an old URL.
SLUG_ALIASES = {'shopping': 'meals'}


def resolve_tabs(requested: Optional[str] = None, settings: dict = None) -> List[str]:
    """Same precedence as the tiles: URL, then profile, then defaults.

    `?tabs=none` is passed through untouched — that one means "this is an
    embedded card, give it no chrome at all", and it is the one case where
    showing nothing IS the request.

    A household's own boards join the vocabulary as `board:<slug>`, prefixed
    rather than bare so that a board somebody names "Chores" cannot quietly
    shadow the Chores page. They are validated against the boards that actually
    exist, for the same reason the app's own slugs are: an unknown name in this
    list must vanish, not render a button that goes nowhere.
    """
    if requested is not None and requested.strip().lower() in ('', 'none'):
        return []
    known = set(NAV_SLUGS)
    known.update(f'board:{p["slug"]}' for p in own_boards(settings))

    def clean(seq):
        out = []
        for k in seq or []:
            k = str(k).strip().lower()
            k = SLUG_ALIASES.get(k, k)
            if k in known and k not in out:
                out.append(k)
        return out

    if requested is not None:
        # An explicit list is EXACTLY what was asked for. A card that says
        # `?tabs=home,chores` wants two buttons, and quietly adding the
        # household's boards to it would make that card unconfigurable.
        picked = clean(requested.split(','))
        if picked:
            return picked

    settings = settings or {}
    # ORDER plus a HIDDEN SET, since v2.232.0, and the pair matters.
    #
    # `panel_tabs` was one list that, once non-empty, WAS the shelf: anything
    # left out was out. That is defensible while curating is a rare expert act
    # and fatal the moment the editor writes a full order on every drag —
    # every household would be curated on day one, and no board shipped
    # afterwards would ever appear for any of them. Order says where things
    # go; hiding says what is off. Anything known and unlisted is simply new,
    # so it joins the end rather than vanishing.
    order = clean(settings.get('panel_board_order'))
    hidden = set(clean(settings.get('panel_board_hidden')))
    if not order:
        legacy = clean(settings.get('panel_tabs'))
        if legacy:
            # A curated `panel_tabs` meant "these and only these". Read as
            # order + everything else hidden, so a household that curated
            # keeps exactly the shelf they had. Read-only, like every other
            # migration here — nothing is written until somebody saves.
            order, hidden = legacy, (known - set(legacy))
        else:
            order = _with_boards(list(DEFAULT_TABS), settings)
    # Everything that exists and nobody has placed goes on the end, in the
    # order the defaults would have put it.
    tail = [k for k in _with_boards(list(DEFAULT_TABS), settings)
            if k not in order]
    tail += [k for k in sorted(known) if k not in order and k not in tail]
    return [k for k in order + tail if k not in hidden]


def _with_boards(order: List[str], settings: dict = None) -> List[str]:
    """The household's own boards, folded into a shelf order.

    They have to BE in this list, not merely rendered into the shelf beside it.
    The panel asks the profile what it shows and then hides every button the
    answer does not name — so boards that were not in it appeared for a
    fraction of a second on every load and then vanished, and panel mode is the
    only place the shelf exists, so that was the only place it showed.

    Right after Home, because Home is the same kind of thing: the boards are
    one group and the app's destinations are another. A board somebody made on
    purpose for this wall has a stronger claim on a thumb than anything shipped.
    """
    boards = [f'board:{p["slug"]}' for p in own_boards(settings)]
    boards = [b for b in boards if b not in order]
    if not boards:
        return order
    if HOME_SLUG in order:
        at = order.index(HOME_SLUG) + 1
        return order[:at] + boards + order[at:]
    return boards + order


# ── "Follow the sun", and why it is not just `auto` with a better name.
#
# `auto` is a CSS media query, and a media query is only honest when something
# is there to answer it. Embedded in a Home Assistant dashboard there is: HA's
# dark theme sets `color-scheme` on the embedding document and Chromium
# propagates that into our frame, so `auto` tracks the household's HA theme
# automation for free. Opened directly — the PWA over the tunnel, a browser
# pointed at the add-on, a shortcut on a phone — there is no embedder, so the
# query falls back to the device's OS preference, and a wall tablet nobody
# ever told about dark mode reports light at midnight and every other hour.
# That is not the household choosing light; it is nobody answering, and the
# media query cannot tell those two apart.
#
# `sun` resolves the same question on the SERVER instead, and that is the
# whole point: the browser is the thing that cannot reach Home Assistant from
# outside the house, while the add-on always can. HA knows where the house is,
# and `sun.sun` is already the trigger behind most households' theme
# automation — so mirroring it lands the panel on the same answer HA reached,
# without needing HA's own theme state (which lives behind a websocket command
# this REST client has no way to ask for).
_SUN_ENTITY = 'sun.sun'
_DAY = datetime.timedelta(days=1)


def _parse_ha_time(raw) -> Optional[datetime.datetime]:
    """HA timestamps are ISO with an offset. Anything else is not our problem
    to guess at — an unparseable sun time falls back like an absent one."""
    if not raw:
        return None
    try:
        t = datetime.datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def _next_after(t: datetime.datetime, now: datetime.datetime) -> datetime.datetime:
    """The next occurrence of a daily event, given any one instance of it.

    `next_rising` is already in the future, but an offset moves it in both
    directions and both are real: -30 minutes drags it into the PAST when
    sunrise is ten minutes away, and +30 pushes tonight's switch back into the
    FUTURE five minutes after sunset, when `next_setting` has already rolled
    over to tomorrow and would otherwise say the panel goes dark in 24 hours.
    So step by whole days either way. Sunrise drifts a couple of minutes a day,
    which is well inside what anyone notices happening to a wall panel.
    """
    while t <= now:
        t += _DAY
    while t - _DAY > now:
        t -= _DAY
    return t


def sun_theme(settings: dict = None, now: datetime.datetime = None) -> dict:
    """Resolve `sun` to a literal light/dark, plus when it next changes.

    Returns the literal so that every consumer downstream — the cached
    attribute in ha_theme.html, every `[data-panel-theme="light"]` rule in the
    skin — keeps working with no idea this mode exists. `next_flip` is what
    stops a panel that has been up for three weeks from being right only on
    the day somebody loaded it.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})

    def _offset(key):
        try:
            return datetime.timedelta(minutes=int(settings.get(key) or 0))
        except (TypeError, ValueError):
            return datetime.timedelta()

    from services import ha_api
    st = ha_api.get_state(_SUN_ENTITY) or {}
    attrs = st.get('attributes') or {}
    rising = _parse_ha_time(attrs.get('next_rising'))
    setting = _parse_ha_time(attrs.get('next_setting'))

    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)

    if not (rising and setting):
        # No HA, no sun entity, or attributes in a shape we do not recognise.
        # The entity's own state still answers it if it got that far; failing
        # that, dark — a panel that has lost Home Assistant at 2am should not
        # decide to light up the kitchen.
        state = str(st.get('state') or '').lower()
        if state in ('above_horizon', 'below_horizon'):
            return {'theme': 'light' if state == 'above_horizon' else 'dark',
                    'next_flip': None}
        return {'theme': 'dark', 'next_flip': None}

    to_light = _next_after(rising + _offset('panel_theme_sunrise_offset_minutes'), now)
    to_dark = _next_after(setting + _offset('panel_theme_sunset_offset_minutes'), now)
    # Whatever happens NEXT says what is true NOW: if the next change is to
    # light, then right now it is dark.
    if to_light <= to_dark:
        return {'theme': 'dark', 'next_flip': to_light.isoformat()}
    return {'theme': 'light', 'next_flip': to_dark.isoformat()}


def page_summaries(settings: dict = None) -> List[dict]:
    """Every board, without its tiles — what a shelf, a page switcher and the
    editor's own list all need. The tiles are the expensive part and none of
    those three surfaces wants them."""
    return [{'slug': p['slug'], 'name': p['name'], 'icon': p['icon'],
             # Resolved here so the shelf template never learns the key
             # scheme: paths mean "draw a stroked icon", None means "the
             # icon field is emoji text".
             'icon_paths': icon_paths(p['icon']),
             'tiles': len(p['widgets'])}
            for p in normalize_pages(settings)]


def profile(tabs: Optional[str] = None, widgets: Optional[str] = None,
            page: Optional[str] = None) -> dict:
    """Everything a panel needs to know about itself, in one call — so a
    display bolted to a wall can be pointed at a bare URL and still come up
    configured. The alternative is a two-hundred-character bookmark that only
    the person who wrote it can maintain."""
    settings = storage.get_settings() or {}
    # storage.get_settings() returns the STORED dict, not a validated Settings,
    # so model defaults never appear in it. Absent has to mean 180 here or
    # every install that predates this arc reads as "idle return disabled" —
    # which is a silently-off feature, not a default. An explicit 0 is a real
    # choice and stays off.
    raw = settings.get('panel_idle_return_seconds')
    try:
        idle = 180 if raw is None else int(raw)
    except (TypeError, ValueError):
        idle = 180
    theme = str(settings.get('panel_theme') or 'dark').lower()
    if theme not in ('light', 'dark', 'auto', 'sun'):
        theme = 'dark'
    # `sun` never reaches the client as itself — it is resolved here, so the
    # panel is handed the same literal light/dark that a household who picked
    # one by hand would get, and nothing downstream has to learn a new word.
    next_flip = None
    if theme == 'sun':
        resolved = sun_theme(settings)
        theme, next_flip = resolved['theme'], resolved['next_flip']
    page_obj = find_page(page, settings)
    return {'tabs': resolve_tabs(tabs, settings),
            'widgets': resolve_instances(widgets, settings, page=page_obj),
            'spans': page_obj['spans'],
            'row_height': page_obj['row_height'],
            'columns': page_obj['columns'],
            'gap': page_obj['gap'],
            # Every board there is, so the shelf can carry them and a panel can
            # move between them without a round trip per hop.
            'pages': page_summaries(settings),
            'page': page_obj['slug'],
            'theme': theme,
            'next_flip': next_flip,
            'backgrounds': backgrounds(settings),
            'idle_seconds': max(0, idle),
            # Knobs only — the playlist is fetched at activation so a panel
            # that has been up for weeks still shows this week's photos.
            'screensaver': screensaver_config(settings)}


def build(requested: Optional[str] = None, kid_digest_fn: Callable = None,
          now: datetime.datetime = None, page: Optional[str] = None,
          editing: bool = False) -> dict:
    """The whole board in one payload.

    `editing` is the editor's preview: every configured tile and card draws,
    even the ones with nothing to say, because a card that hides itself also
    hides itself from the person trying to fix it. Never set on the wall,
    where rule 1 — do not reserve blank space — is still right."""
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    page_obj = find_page(page, settings)
    instances = resolve_instances(requested, settings, page=page_obj)

    # The whole resolved board, config included — two calendar tiles set to
    # different people are different boards and must not share a cached answer.
    # The PAGE rides in the key too: two pages can hold identical tiles and
    # still differ in the grid they are drawn on, and one cache entry serving
    # both would draw the kitchen board at the hallway's row height.
    # `editing` rides the key: the same board built for the editor holds the
    # empty cards the wall leaves out, and one cache entry serving both would
    # put placeholder boxes on the kitchen wall.
    cache_key = json.dumps([page_obj['slug'], page_obj['columns'],
                            page_obj['row_height'], editing, instances],
                           sort_keys=True)
    held = _CACHE.get(cache_key)
    if held and time.time() - held['at'] < TTL_SECONDS:
        return held['data']

    from services import family_digest
    # `now` threaded through, not left to default: the hero, the tiles and the
    # `over` flag must all be reasoning about the same instant. The schedule is
    # read ONCE and handed round for the same reason it is fetched once — three
    # tiles asking storage for it separately is three chances to draw a board
    # out of step with itself.
    # Every day the board can show comes off its OWN cache row, which the
    # solver rewrites the moment it finishes that day; the global cache they
    # are merged into is only rebuilt by a full-range refresh, five minutes
    # apart. That gap is what made the board say there was nothing left to
    # drive while the Drives page, two taps away, listed it. The calendar tile
    # reaches further than today, so the merge does too — one wall that
    # disagrees with itself by a few minutes per day is not better than one
    # that disagrees by five.
    sched = storage.get_cached_schedule() or {}
    # As deep as the DEEPEST tile asks for. Each day is merged in from its
    # own cache row, and a tile
    # configured for a fortnight against a five-day prefetch would have
    # rendered nine empty days and looked like a quiet calendar rather than
    # like a board that had not read that far.
    depth = max([AGENDA_DAYS]
                + [_cfg_int(i.get('config'), 'days', 1, 1, 14)
                   for i in instances
                   if (i.get('config') or {}).get('days') is not None])
    for i in range(max(1, depth)):
        sched = day_schedule(now.date() + datetime.timedelta(days=i), sched)
    runs = todays_runs(now.date(), sched=sched, now=now)

    tiles = []
    for inst in instances:
        # Rule 1 lives one level down now: a card with nothing to say is not
        # drawn, and a built-in tile whose only card said nothing is not a
        # tile. Reserved empty space is still the thing being avoided.
        tile = _build_tile(inst, now, runs=runs, sched=sched, settings=settings,
                           kid_digest_fn=kid_digest_fn, editing=editing)
        if tile:
            tiles.append(tile)

    # The shared `hass.states` pool, once per PAYLOAD and only when this
    # board actually hosts a custom card. A discovering card — one that
    # builds its own device list by walking `hass.states` — cannot be served
    # by any slice chosen from its config, and the per-tile alternative
    # shipped one copy of the house per card. Gzip makes the pool a few KB;
    # a board with no custom card on it pays nothing at all. Native tiles
    # count too when they carry host cells: a stack of [custom card, gauge]
    # is the config people actually write.
    ha_states = None
    # Tiles AND the cards inside custom tiles: a household whose HA cards
    # all live in custom containers has no top-level ha_card tile at all,
    # and the pool never shipped — the cards still drew (each carries its
    # own states slice) but every surface fed from the pool alone saw an
    # empty house. The card EDITORS were that surface: entity pickers
    # amber, features "not compatible", lock icons wrong.
    drawn = list(tiles) + [c for t in tiles for c in (t.get('cards') or [])]
    if any(t.get('type') == 'ha_card' and isinstance(t.get('data'), dict)
           and (t['data'].get('mode') == 'host' or t['data'].get('hosts'))
           for t in drawn):
        try:
            from services import ha_cards
            ha_states = ha_cards.states_all()
        except Exception as e:
            print(f"[home_board] states pool failed: {e}")

    # The kids belong in the hero, not in a tile of their own. The hero band is
    # full width and was spending it restating the drives tile; a column per
    # child is the thing a family actually walks up to the panel to read, and
    # "Each Kid" was never a phrase anybody says out loud.
    #
    # ONLY WHERE THERE IS A HERO. That condition was missing and it cost the
    # Routines board its digest strip: the board has no hero band — it is
    # lanes, not drives — so the kids tile was lifted out and dropped into an
    # object nothing on that page draws. It vanished with no error anywhere,
    # which is this board's characteristic failure and the one rule 1 exists
    # to prevent. A board without a hero keeps the tile it asked for.
    hero = _hero(now, runs, sched)
    hero['unbuilt'] = _hero_unbuilt(sched)
    kid_tile = next((t for t in tiles if t['type'] == 'kids'), None)
    if kid_tile and any(t['type'] == 'hero' for t in tiles):
        hero['kids'] = kid_tile['data'].get('kids') or []
        hero['kids_empty'] = kid_tile['data'].get('empty')
        tiles = [t for t in tiles if t['type'] != 'kids']

    try:
        weather = family_digest.weather_line(now.date())
    except Exception:
        weather = None

    # The temperature RIGHT NOW, not today's high. On these displays the
    # temperature is the second-largest thing on the screen after the clock,
    # and a forecast high shown that big is wrong for most of the day.
    temp_now, condition = None, None
    try:
        from services import ha_api
        ent = (settings.get('weather_entity') or '').strip()
        if not ent:
            ents = ha_api.get_entities('weather') or []
            ent = (ents[0] or {}).get('entity_id') if ents else None
        if ent:
            st = ha_api.get_state(ent) or {}
            attrs = st.get('attributes') or {}
            if attrs.get('temperature') is not None:
                temp_now = round(float(attrs['temperature']))
            condition = st.get('state')
    except Exception as e:
        print(f"[home_board] current temp failed: {e}")

    try:
        from services import status_protocols
        statuses = status_protocols.active_statuses(now.date().isoformat()) or []
    except Exception:
        statuses = []

    data = {
        'now': now.isoformat(),
        # Built by hand rather than with %-d: that directive is glibc-only and
        # raises on Windows, where this is developed.
        'date_label': f"{now.strftime('%A, %B')} {now.day}",
        'weather': weather,
        'temp_now': temp_now,
        'condition': condition,
        'condition_emoji': (family_digest._WEATHER_EMOJI.get(condition or '', '🌤️')
                            if condition else None),
        # The page's own picture, then the household's. A board made for the
        # hallway is allowed to look different from the one in the kitchen —
        # that is most of what makes it a different board rather than the same
        # board with other tiles on it.
        'background': (_as_background(page_obj['background'])
                       or _background_url(settings)),
        'statuses': [{'label': s.get('label') or s.get('name'),
                      'emoji': s.get('emoji'), 'note': s.get('note')}
                     for s in statuses][:2],
        'hero': hero,
        'tiles': tiles,
        'ha_states': ha_states,
        'widgets': instances,
        # All four come off the PAGE now. `find_page` guarantees one exists and
        # that its numbers are already clamped, so there is no branch here for
        # "no pages configured" — that case produced a page built from the old
        # settings before any of this ran.
        'spans': page_obj['spans'],
        'row_height': page_obj['row_height'],
        'columns': page_obj['columns'],
        'gap': page_obj['gap'],
        'page': {'slug': page_obj['slug'], 'name': page_obj['name'],
                 'icon': page_obj['icon']},
    }
    # Popped before it is set so a rebuilt board moves to the END of the dict:
    # insertion order is then genuinely "least recently built", and the
    # eviction below takes the board nobody is looking at.
    _CACHE.pop(cache_key, None)
    while len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)), None)
    _CACHE[cache_key] = {'at': time.time(), 'data': data}
    return data


TAB_LABELS = {
    'home': 'Home', 'schedule': 'Drives', 'calendar': 'Calendar',
    'errands': 'Errands', 'meals': 'Meals', 'lists': 'Lists',
    'occasions': 'Occasions',
    'chores': 'Chores', 'routines': 'Routines', 'intake': 'Intake',
    'trips': 'Trips', 'map': 'Map', 'moments': 'Moments',
}


def grid_row_height(settings: dict = None) -> int:
    """What one row of the board's grid is worth, in pixels.

    A span of 2 used to mean "as tall as whatever two content-sized rows
    happened to be" — a height decided by the other tiles in those rows, not by
    the household — and in the LAST row it did nothing at all, because there
    was no second row there to occupy. With a fixed unit, `rows` is a real
    measurement everywhere on the board.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    try:
        return max(ROW_MIN, min(ROW_MAX,
                                int(settings.get('panel_grid_row_height', 240))))
    except (TypeError, ValueError):
        return 240


def grid_columns(settings: dict = None) -> int:
    """How many columns the board is divided into.

    Twelve by default, which is Home Assistant's number and is chosen for the
    same reason: it divides by 2, 3, 4 and 6, so halves, thirds and quarters
    are all expressible. The board used to be four columns wide, which made a
    quarter the NARROWEST thing a household could ask for.
    """
    settings = settings if settings is not None else (storage.get_settings() or {})
    try:
        return max(1, min(COLUMN_MAX, int(settings.get('panel_grid_columns', 12))))
    except (TypeError, ValueError):
        return 12


def option_sources() -> dict:
    """The live contents of every `select` option — the household's people,
    drivers and lists, as `{value, label}` rows the editor can render without
    knowing what any of them are.

    Each one is fetched independently and INDEPENDENTLY SURVIVES failure. A
    board editor that will not open because the shopping service threw is a
    worse outcome than a picker with nothing in it, and the tile whose source
    is empty is the only one that should be affected.
    """
    out = {'members': [], 'drivers': [], 'lists': [], 'trips': [],
           'cars': [], 'bus_riders': []}
    try:
        out['members'] = [{'value': m['id'], 'label': m.get('name') or 'Someone'}
                          for m in (storage.get_all_members() or [])]
    except Exception as e:
        print(f"[home_board] member options failed: {e}")
    try:
        out['cars'] = [{'value': str(c['id']), 'label': c.get('name') or 'Car'}
                       for c in (storage.get_all_cars() or [])
                       if not c.get('is_disabled')]
    except Exception as e:
        print(f"[home_board] car options failed: {e}")
    try:
        # WHOSE bus, rather than which entity: a household thinks "show the
        # bus my kids are on", and the entity behind it is this app's problem.
        # Children only — a bus belongs to a child's morning, and offering
        # every adult here is how a grandmother ended up with a school bus.
        out['bus_riders'] = [{'value': m['id'], 'label': m.get('name') or 'Someone'}
                             for m in (storage.get_all_members() or [])
                             if m.get('role') == 'child']
    except Exception as e:
        print(f"[home_board] bus rider options failed: {e}")
    try:
        out['drivers'] = [{'value': d['id'], 'label': d.get('name') or 'Driver'}
                          for d in (storage.get_all_drivers() or [])]
    except Exception as e:
        print(f"[home_board] driver options failed: {e}")
    try:
        out['lists'] = [{'value': l['id'], 'label': l.get('name') or 'List'}
                        for l in (storage.get_shopping_lists() or [])]
    except Exception as e:
        print(f"[home_board] list options failed: {e}")
    try:
        # Trips as they appear on the board, so pinning one means picking the
        # row you can already see. Cached trips first (the real, solved ones),
        # then drafts, deduped by id.
        seen = set()
        for t in ((storage.get_cached_trips() or {}).get('trips') or []) \
                + (storage.get_all_trip_metadata() or []):
            tid = t.get('id')
            if not tid or tid in seen:
                continue
            seen.add(tid)
            out['trips'].append({'value': tid,
                                 'label': t.get('title') or 'Trip'})
    except Exception as e:
        print(f"[home_board] trip options failed: {e}")
    return out


def catalog() -> dict:
    """Everything the setup UI needs to offer a choice. Includes the defaults
    so the editor can show what "leave it alone" actually means — a picker
    whose empty state is indistinguishable from a deliberate empty selection
    is how a blank wall panel gets shipped.

    `title` and `icon` are appended to every type's options here rather than
    declared fifteen times: they are the two options that mean the same thing
    everywhere, and they are the ones a board with two calendar tiles — or
    three cameras — needs most.
    """
    ha_ok = ha_configured()
    widgets = []
    for w in WIDGETS:
        w = dict(w)
        w['options'] = list(w.get('options') or []) + [TITLE_OPTION, ICON_OPTION]
        # The hand path for property 1. These two tiles do not exist without a
        # Home Assistant, so the palette says so instead of letting somebody
        # add one and wonder why the wall never shows it.
        if w['key'] in ('ha', 'ha_image', 'ha_dashboard', 'ha_card', 'music'):
            w['requires'] = 'Home Assistant'
            w['available'] = ha_ok
        # Whether "always show, even when empty" is a question worth asking of
        # this type. It needs a sentence to say when it IS empty, or the flag
        # buys a blank panel instead of an explanation; chrome never vanishes,
        # so there is nothing to keep; and a container draws its cards rather
        # than a state of its own.
        w['requirable'] = (w['key'] in REQUIRED_EMPTY
                           and w['key'] not in BARE_TILES
                           and not w.get('container'))
        widgets.append(w)
    # The shelf's vocabulary, as the editor needs to offer it: the app's own
    # destinations AND the household's boards. One list, because they end up in
    # one ordered setting — a board is a shelf button in exactly the way the
    # Chores page is, and splitting them into two pickers would mean two places
    # to arrange one row of buttons.
    settings = storage.get_settings() or {}
    tabs = [{'slug': s, 'label': TAB_LABELS.get(s, s), 'kind': 'page'}
            for s in NAV_SLUGS]
    tabs += [{'slug': f'board:{p["slug"]}', 'label': p['name'],
              'icon': p['icon'], 'kind': 'board'}
             for p in own_boards(settings)]
    return {
        'widgets': widgets,
        'widget_defaults': list(DEFAULT_WIDGETS),
        'sources': option_sources(),
        'tabs': tabs,
        'tab_defaults': resolve_tabs(None, settings),
        # The icon choices a board can wear on the shelf, in the shelf's own
        # visual language. The editor renders these itself, so the paths ride
        # along rather than a name it would have to resolve.
        # Emitted in GROUP ORDER with the label on each row: the picker needs
        # the grouping and nothing else does, and a flat list of sixty-three
        # is what made a bigger set worth grouping in the first place. Older
        # readers that only want key/paths are unaffected.
        'board_icons': [{'key': k, 'paths': v, 'group': label}
                        for label, items in BOARD_ICON_GROUPS for k, v in items],
        # Which slugs are one of the app's own destinations. The editor needs
        # it for one word: deleting a board like that does not delete it, it
        # puts the shipped one back, and "Delete" is the wrong promise.
        'builtin_pages': sorted(BUILTIN_PAGES),
    }
