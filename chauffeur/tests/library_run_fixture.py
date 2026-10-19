"""A library-backed run for fixtures that must not import tests/harness.py.

Live tests that need auth enforcement isolate storage themselves, so they
cannot use program_fixture.add_run (it imports the harness first). Same
shape: the curriculum becomes a library row, the run references it with a
reconciled bookmark, phase judgements stay on the run. Since the program
library split a run no longer stores title, phases or source, so a fixture
that writes them straight onto a programs row reads back as unresolved.
"""
import copy


def add_run(data):
    from services import library, programs, storage
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
