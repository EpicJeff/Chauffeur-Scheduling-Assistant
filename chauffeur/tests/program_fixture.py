"""Build the library/run split from compact curriculum fixtures in program tests."""
import copy
from harness import check  # isolate storage before importing services

from services import library, programs, storage


def add_run(data):
    data = copy.deepcopy(data)
    title = data.pop('title')
    phases = data.pop('phases', [])
    source = data.pop('source', {'hand_written': False})
    row = library.from_curated(title, library.public_profile(data.get('shape') or {}),
                               {'phases': phases, 'source': source}, data.get('created_by'))
    lid = storage.add_library_program(row)
    progress = programs.reconcile_progress({}, storage.get_library_program(lid))
    for phase, original in zip(row['phases'], phases):
        progress['phases'][phase['id']] = {'weeks': phase['weeks'],
                                          'milestone_hit_at': original.get('milestone_hit_at')}
    return storage.add_program({**data, 'library_id': lid, 'progress': progress})


def loaded(run_id):
    return programs.load(storage.get_program(run_id))


def phase_id(run_id, index=0):
    return loaded(run_id)['phases'][index]['id']
