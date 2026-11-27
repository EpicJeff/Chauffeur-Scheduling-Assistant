"""The presentation-board contract (spec docs/superpowers/specs/2026-11-27-presentation-boards-design.md).

The server (services/boards.py) produces these shapes and the phone and admin
renderers (templates/components/board_sheet.html, renderBoardCard in
templates/app.html) consume them. tests/fixtures/board_view_v1.json is a sample
of every shape; tests/test_board_contract.py holds the fixture to these key sets,
and the server's own tests hold boards.view / boards.card / boards.row to them,
so a drift on either side fails a test both sides run.

Shapes
------
view (GET api/projects/<pid>/boards/<bid>, boards.view(board, viewer)):
    VIEW_KEYS; slots[] use SLOT_KEYS; options[] use OPTION_KEYS; option.items[]
    use ITEM_KEYS; price and total are {amount: number, currency: str} or null;
    item.image is a relative path IMAGE_PATH or null; can uses CAN_KEYS (all
    false in slice 1: a control is drawn only when its flag is true).
card (ChatMessage.card, boards.card(board)): CARD_KEYS, kind == 'board';
    hero = up to 4 image paths from option 1, nulls dropped.
row (one entry of projects.rows, boards.row(board)): ROW_KEYS with
    kind == 'board', group == 'now', actions == [], sheet uses ROW_SHEET_KEYS
    with kind == 'board'.
mission_done card: gains DONE_CARD_BOARD_KEY, a list of DONE_BOARD_KEYS
    dicts (empty when the mission made no board).

summary_line
    options / compare: "{n options} {noun} · from {price}", or "{n} {noun}"
    when no complete price exists. "from" is the minimum complete option
    total (multi-slot) or the minimum item price (single slot, compare); it is
    omitted when those minimums span currencies.
    list: "{n items} {noun}", never a price.
    Price format: "$118" (USD, whole), "$118.50" (USD, cents), "118 EUR".
    The separator is " · " (U+00B7).

Opening a board on the phone or admin page:
    window.dispatchEvent(new CustomEvent(OPEN_EVENT, {detail: {projectId, boardId}}))
Deep link: "#board-<project_id>-<board_id>" (ids are lowercase hex, no dashes).
"""
import re

LAYOUTS = ('options', 'compare', 'list')
COMMITS = ('buy', 'book', 'contact', 'none')

VIEW_KEYS = frozenset({
    'id', 'project_id', 'title', 'ask', 'layout', 'noun', 'commit', 'version',
    'copied_from', 'summary_line', 'slots', 'options', 'keeps', 'shortlist',
    'reactions', 'can'})
SLOT_KEYS = frozenset({'id', 'role'})
OPTION_KEYS = frozenset({'id', 'title', 'note', 'round', 'total', 'items'})
ITEM_KEYS = frozenset({'id', 'slot_id', 'title', 'url', 'store', 'image', 'price', 'facts'})
MONEY_KEYS = frozenset({'amount', 'currency'})
FACT_KEYS = frozenset({'label', 'value'})
CAN_KEYS = frozenset({'react', 'keep', 'find_more', 'copy', 'commit'})

CARD_KEYS = frozenset({'kind', 'board_id', 'project_id', 'title', 'summary_line', 'kept', 'hero', 'note'})
ROW_KEYS = frozenset({'kind', 'group', 'title', 'subtitle', 'sheet', 'actions'})
ROW_SHEET_KEYS = frozenset({'kind', 'id', 'project_id'})
DONE_CARD_BOARD_KEY = 'boards'
DONE_BOARD_KEYS = frozenset({'board_id', 'project_id', 'title'})

OPEN_EVENT = 'chf-board-open'
DEEP_LINK = re.compile(r'^#board-([0-9a-f]+)-([0-9a-f]+)$')
IMAGE_PATH = re.compile(r'^api/projects/([0-9a-f]+)/boards/([0-9a-f]+)/image/(lk_[0-9a-f]{10})$')
SEPARATOR = ' · '
MAX_FACTS = 4
MAX_HERO = 4
