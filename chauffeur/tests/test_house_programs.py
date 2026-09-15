"""Active program objects and session material remain a narrow family projection."""
import datetime
from unittest.mock import patch
from harness import check
from services import storage, house_programs


def scenario_objects_and_sessions():
    row = {'id':'guitar', 'member_id':'kid', 'state':'active', 'title':'Learn electric guitar',
           'starting_point':'private note', 'sessions':[],
           'phases':[{'name':'First chords', 'steps':['Tune the guitar', 'Play E minor']} ]}
    member = {'id':'kid','role':'child','name':'Maya','color_code':'#448899'}
    with patch.object(storage,'get_programs',return_value=[row]), \
         patch.object(storage,'get_all_members',return_value=[member]), \
         patch.object(storage,'get_program',return_value=row), \
         patch.object(storage,'get_member',return_value=member), \
         patch('services.programs.practice_windows',return_value=[]):
        objects=house_programs.objects()
        check(objects[0]['kind']=='guitar' and objects[0]['variant']=='electric','named aim selects its instrument')
        check('starting_point' not in objects[0] and 'sessions' not in objects[0], 'object feed contains no private record')
        session=house_programs.session('guitar',datetime.datetime(2026,9,14,10))
        check(session['program_id']=='guitar' and session['steps']==row['phases'][0]['steps'], 'unscheduled tap opens current program material')
        check(not row['sessions'] and 'starting_point' not in session, 'opening neither logs nor leaks notes')
        row['state']='paused'
        check(house_programs.session('guitar') is None,'paused program cannot start')
    check(house_programs.appearance({'title':'Read novels','starting_point':'guitar'})=='book', 'private notes do not drive appearances')
    check(house_programs.appearance({'title':'Learn piano'})=='piano','piano has its own object')
    check(house_programs.appearance({'title':'Meditation practice'})=='meditation','meditation selects garden')


if __name__=='__main__':
    scenario_objects_and_sessions()
    print('House program projection passed')
