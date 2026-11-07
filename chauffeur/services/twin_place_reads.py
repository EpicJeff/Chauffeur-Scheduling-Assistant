"""Explicit setup reads and person-accepted plot placement.

Reader calls hold no lifecycle or store lock. Publication and person actions
hold LIFECYCLE then _LOCK so plan refits and place changes cannot interleave.
"""
import base64
from copy import deepcopy
import io
import math
import threading
import uuid

from PIL import Image

from services import twin_cost, twin_place, twin_reads, twin_register, twin_store

_FULL = [0, 0, 1, 1]
_CHANGED = 'The plot plan changed while it was being read. Read it again.'
_FAILED = 'The plot plan could not be read. Try again, or place the buildings by hand.'
# Both setup reads use run place. Serialize them to attribute ledger rows to
# their own request without holding the house locks while a provider runs.
_READ_LOCK = threading.Lock()


def _page():
    return twin_store._plot_page(twin_store._place_state())


def _check_plot(generation, page):
    if twin_store.generation() != generation or _page() != page:
        raise ValueError(_CHANGED)


def _cost(kind, before):
    return sum(e['usd'] for e in twin_cost.entries()[before:]
               if e['run'] == 'place' and e['stage'] == f'step:{kind}')


def read_plot(*, reader=twin_reads.read) -> dict:
    with _READ_LOCK:
        with twin_store.LIFECYCLE, twin_store._LOCK:
            page = _page()
            if page is None:
                raise ValueError('Confirm a plot plan page on the lot first.')
            generation = twin_store.generation()
        # Legacy masters may need rendering, which itself takes LIFECYCLE.
        # Do not hold the store lock across that work.
        try:
            image = twin_store.crop(page['source'], page['page'], page['box'] or _FULL)
        except (ValueError, OSError):
            with twin_store.LIFECYCLE, twin_store._LOCK:
                _check_plot(generation, page)
            raise ValueError(_FAILED) from None
        with twin_store.LIFECYCLE, twin_store._LOCK:
            _check_plot(generation, page)
        twin_cost.require_clear()
        before = len(twin_cost.entries())
        raw = reader('plot', [{'mime': image['mime'], 'b64': image['b64']}],
                     {**page, 'box': image['box']}, run='place', step='plot')
        with twin_store.LIFECYCLE, twin_store._LOCK:
            _check_plot(generation, page)
            fragment, problems = twin_reads.parse('plot', raw)
            if (not isinstance(raw, dict) or raw.get('error')
                    or not twin_reads._usable('plot', fragment, problems)):
                raise ValueError(_FAILED)
            crop = {key: image[key] for key in ('box', 'size', 'master')}
            try:
                reg = twin_place.plot_registration(crop, fragment)
                lot_outline = [twin_register.apply(reg, twin_place.to_master(crop, p)) for p in fragment['lot']]
                twin_place.check_footprint(lot_outline)
                suggestions = twin_place.plot_suggestions(fragment, crop, reg)
            except (ValueError, KeyError, TypeError):
                raise ValueError(_FAILED) from None
            edge = fragment.get('street_edge')
            if edge is None:
                pixels = [twin_place.to_master(crop, p) for p in fragment['lot']]
                i = max(range(len(pixels)), key=lambda i: math.dist(pixels[i], pixels[(i + 1) % len(pixels)]))
                edge = [i, (i + 1) % len(pixels)]
            lot = twin_store.place()['lot']
            lot['read'] = {'id': uuid.uuid4().hex, **page, 'crop': crop, 'fragment': fragment,
                           'registration': reg, 'lot': lot_outline, 'street_edge': edge,
                           'suggestions': suggestions, 'matrix': twin_place.sheet_matrix(reg, crop),
                           'cost': _cost('plot', before)}
            if not (lot.get('placement') or {}).get('confirmed'):
                lot['placement'] = None
            twin_store.set_lot(lot)
            return deepcopy(lot)


def _publish(row, changed):
    """Refit all changed built footprints in one edit round, then save place."""
    registry = twin_store._place(row)
    footprints = {b['id']: b['footprint'] for b in registry['buildings'] if b['id'] in changed}
    plan = twin_store.current() if changed else None
    fits = {}
    for building in (plan or {}).get('buildings', []):
        bid = building['id']
        levels = building.get('levels', [])
        if bid not in footprints or (building.get('src') or {}).get('person') or not levels:
            continue
        level = min(levels, key=lambda level: level.get('elevation', 0))
        if len(level.get('outline', [])) >= 3:
            fits[bid], _ = twin_register.fit_outline(level['outline'], footprints[bid])
    if fits:
        def refit(current):
            for building in current['buildings']:
                if building['id'] in fits:
                    move = fits[building['id']]
                    building.update(position=move['offset'], rotation=move['angle'])
            return current

        twin_store.update_current(refit, kind='edit', note='Placed buildings on their confirmed footprints.')
        row = twin_store._state()
        row['place'] = registry
    twin_store._save(row)


def answer_suggestion(sid, action, *, building=None, name=None, kind=None, read=None) -> dict:
    with twin_store.LIFECYCLE, twin_store._LOCK:
        row = twin_store._place_state()
        place = row['place']
        plot = place['lot'].get('read')
        if read is not None and (plot is None or read != plot['id']):
            raise ValueError('This plot plan read is out of date. Read it again.')
        suggestion = next((s for s in (plot or {}).get('suggestions', []) if s['id'] == sid), None)
        if suggestion is None:
            raise ValueError('Choose a suggestion from the plot plan read.')
        if suggestion['state'] != 'open':
            raise ValueError('This suggestion was already answered.')
        if action not in ('accept', 'dismiss'):
            raise ValueError('Accept or dismiss this suggestion.')
        changed = set()
        if action == 'dismiss':
            suggestion['state'] = 'dismissed'
            summary = 'Dismissed the plot plan suggestion.'
        else:
            outline = twin_place.check_footprint(suggestion['outline'])
            if building is not None:
                target = next((b for b in place['buildings'] if b['id'] == building), None)
                if target is None:
                    raise ValueError('Choose a building in your place.')
            else:
                name = twin_store._building_name(place, name)
                twin_store._check_building_kind(kind)
                bid = twin_place.new_id(name, {b['id'] for b in place['buildings']})
                target = twin_store._add_building(place, bid, name, kind)
            if target['footprint'] != outline:
                changed.add(target['id'])
            target.update(footprint=outline, footprint_from='plot')
            suggestion.update(state='accepted', building=target['id'])
            summary = 'Accepted the plot plan footprint.'
        _publish(row, changed)
        return {'lot': deepcopy(place['lot']), 'place': deepcopy(place), 'summary': summary}


def confirm_placement(street_edge, footprints) -> dict:
    with twin_store.LIFECYCLE, twin_store._LOCK:
        row = twin_store._place_state()
        place = row['place']
        lot = place['lot']
        plot = lot.get('read')
        if plot is None:
            raise ValueError('Read the plot plan before confirming its placement.')
        if not isinstance(footprints, list):
            raise ValueError('Give a list of building footprints to place.')
        # Work on a private snapshot and validate every drag before publishing.
        targets = {b['id']: b for b in place['buildings']}
        dragged = {}
        for item in footprints:
            if not isinstance(item, dict) or not isinstance(item.get('building'), str) or item['building'] not in targets:
                raise ValueError('Choose a building in your place.')
            dragged[item['building']] = twin_place.check_footprint(item.get('outline'))
        previous = lot.get('placement')
        same_page = previous and all(previous.get(k) == plot[k] for k in ('source', 'page', 'box'))
        old_reg = previous['registration'] if same_page else plot['registration']
        old_edge = previous['street_edge'] if same_page else plot['street_edge']
        edge = old_edge if street_edge is None else street_edge
        reg = twin_place.plot_registration(plot['crop'], plot['fragment'], edge=edge)
        changed = set()
        if edge != old_edge:
            for bid, target in targets.items():
                if target.get('footprint') and target.get('footprint_from') == 'plot':
                    target['footprint'] = twin_place.check_footprint([
                        twin_register.apply(reg, twin_register.invert(old_reg, p)) for p in target['footprint']])
                    changed.add(bid)
        for bid, outline in dragged.items():
            if targets[bid]['footprint'] != outline:
                changed.add(bid)
            targets[bid]['footprint'] = outline
        lot['placement'] = {**{k: plot[k] for k in ('source', 'page', 'box')},
                            'outline': [twin_register.apply(reg, twin_place.to_master(plot['crop'], p))
                                        for p in plot['fragment']['lot']],
                            'street_edge': deepcopy(edge), 'registration': reg, 'confirmed': True}
        _publish(row, changed)
        twin_store.set_registration(plot['source'], plot['page'], None, reg)
        return deepcopy(lot)


def suggest_photos(*, reader=twin_reads.read) -> dict:
    with _READ_LOCK:
        with twin_store.LIFECYCLE, twin_store._LOCK:
            row = twin_store._place_state()
            generation = row['generation']
            place = row['place']
            sources = [s for s in row['sources'] if s['kind'] == 'photo'][:12]
            if not sources:
                raise ValueError('Upload a photo before asking for photo suggestions.')
            parts = [{**{key: b[key] for key in ('id', 'name', 'kind')},
                      'has_drawings': any(p['building'] == b['id'] for p in row['page_roles'])
                      or any(s['kind'] == 'drawing' and s.get('part') == b['id'] for s in row['sources'])}
                     for b in place['buildings']]
            parts.append({'id': twin_place.LOT, 'name': 'Lot', 'kind': 'lot',
                          'has_drawings': any(p['building'] == twin_place.LOT for p in row['page_roles'])})
            originals = [twin_store.source_images(s['id'])[0] for s in sources]
        images = []
        for original in originals:
            with Image.open(io.BytesIO(base64.b64decode(original['b64']))) as image, io.BytesIO() as output:
                image.thumbnail((768, 768), Image.Resampling.LANCZOS)
                image.convert('RGB').save(output, format='JPEG')
                images.append({'mime': 'image/jpeg', 'b64': base64.b64encode(output.getvalue()).decode('ascii')})
        with twin_store.LIFECYCLE, twin_store._LOCK:
            if generation != twin_store.generation():
                raise ValueError('The house changed while the photos were being read. Try again.')
        twin_cost.require_clear()
        before = len(twin_cost.entries())
        raw = reader('photo_parts', images, {'parts': parts}, run='place', step='photo_parts')
        with twin_store.LIFECYCLE, twin_store._LOCK:
            if generation != twin_store.generation():
                raise ValueError('The house changed while the photos were being read. Try again.')
            fragment, problems = twin_reads.parse('photo_parts', raw)
            if (not isinstance(raw, dict) or raw.get('error')
                    or not twin_reads._usable('photo_parts', fragment, problems)):
                raise ValueError('The photo suggestions could not be read. Try again, or set the photo parts by hand.')
            allowed = {p['id'] for p in parts}
            photo_read = {'photos': [{'source': sources[p['index']]['id'],
                                      'parts': [part for part in p['parts'] if part in allowed]}
                                     for p in fragment.get('photos', []) if p['index'] < len(sources)],
                          'shells': [s for s in fragment.get('shells', [])
                                     if s['building'] in allowed - {twin_place.LOT}],
                          'cost': _cost('photo_parts', before)}
            row = twin_store._place_state()
            row['place']['photo_read'] = photo_read
            twin_store._save(row)
            return deepcopy(photo_read)
