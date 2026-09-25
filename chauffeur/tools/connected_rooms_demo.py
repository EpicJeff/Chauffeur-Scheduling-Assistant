"""Fictional data for the isolated hybrid preview; never imported by the app."""
import os
import time
from datetime import date, timedelta


def furniture():
    from services import study, storage
    from datetime import datetime
    result = {
        'board': {'pins':[{'id':'demo-thread','label':'Plan the autumn family weekend','kind':'thread','detail':'Pick a weekend, compare the cabin options, and decide who is driving.'}, {'id':'demo-observation','label':'Tuesday afternoons have more breathing room','kind':'insight','detail':'The piano lesson moved to Wednesday, leaving Tuesday free.'}]},
        'desk': [{'line':'Prepare for the school conference','open_steps':3,'due':True}, {'line':'Finish the hallway refresh','open_steps':2}],
        'tray': {'count':2,'items':[{'title':'School field trip permission slip'}, {'title':'Library renewal reminder'}]},
        'stickies': {'count':2,'items':[{'line':'Confirm the Friday pickup plan','severity':'decide'}, {'line':'Weekend meal plan is ready to review','severity':'approve'}]},
        'calendar': {'days':[{'date':str(date.today()+timedelta(days=i)), 'unassigned':1 if i==2 else 0, 'events':[{'title':['Soccer practice','Piano lesson','School pickup','Library visit','Family dinner','Garden morning','Free afternoon'][i]}]} for i in range(7)]},
        'window': {'ready':True,'label':'Compared with your usual week','worse':[],'signs':['More free evenings this week','Travel time is near your usual range']},
        'contracts': {'count':1,'items':[{'title':'Friday carpool with the neighbors'}]},
        'binders': [{'title':'Piano practice','pulled':True,'detail':'Short practice sessions after school'}, {'title':'Garden journal','pulled':False,'detail':'Weekend observation walk'}],
        'gauges': {'think':4,'think_cap':20,'research':1,'research_cap':5,'ingest_errors':0},
        'monitor': {'clusters':[{'name':'Alex','count':5},{'name':'Maya','count':3},{'name':'Jordan','count':4}]},
        'map': {'trips':[{'title':'Lake weekend','location':'Bear Lake','start_ts':time.time()+86400*9,'upcoming':True}]},
    }
    for key in ('desk','tray','stickies','contracts','binders','map'):
        result[key] = study._SECTIONS[key](datetime.now(), {'id':'room-demo-parent','role':'parent'})
    result['board']['pins'] = result['board']['pins'][:1] + [
        {'id': row['id'], 'label': row.get('line'), 'detail': row.get('detail'), 'kind': 'insight'}
        for row in storage.get_mind_insights() if row.get('state') == 'active'
        and (row.get('snoozed_until') or 0) < time.time()]
    return result


def seed():
    if not os.environ.get('CHAUFFEUR_DATA_DIR'):
        raise RuntimeError('Connected-room fixtures require isolated data storage')
    from services import storage
    from models.schemas import Chore, RoutineItem
    storage.patch_settings({'home_location':'Denver, Colorado'})
    storage.set_cached_geocode('Denver, Colorado',39.7392,-104.9903)
    storage.add_member({'id':'room-demo-parent','name':'Demo Parent','role':'parent'})
    storage.set_member_pin('room-demo-parent','1234')
    storage.add_chore(Chore(title='Water the hallway plants',owner='k1',state='claimed',claimed_by='k1').model_dump())
    storage.add_chore(Chore(title='Put away the clean towels',owner='k2',state='claimed',claimed_by='k2').model_dump())
    storage.add_routine(RoutineItem(member_id='k1',title='Pack school bag',time_of_day='07:00').model_dump())
    storage.add_routine(RoutineItem(member_id='k2',title='Brush teeth',time_of_day='07:00').model_dump())
    storage.add_mind_insight({'id':'demo-observation','slug':'demo-observation','line':'Tuesday afternoons have more breathing room','detail':'Piano moved to Wednesday. Tuesday is now a good time for a family walk.'})
    storage.add_mind_insight({'id':'demo-plan','slug':'demo-plan','state':'in_hand',
        'line':'Prepare for the school conference','detail':'Bring the questions and recent work samples to Friday’s meeting.',
        'plan_json':{'created_ts':time.time(),'steps':[
            {'id':'questions','kind':'human','text':'Write down questions for the teacher','owner_name':'Demo Parent','due':str(date.today()),'status':'open'},
            {'id':'samples','kind':'human','text':'Choose two recent work samples','owner_name':'Demo Parent','due':str(date.today()+timedelta(days=1)),'status':'open'}]}})
    for i,(title,notes) in enumerate([('School field trip permission slip','Sign the form and pack a lunch for the museum visit.'),('Library renewal reminder','Renew the two library books before Friday.')]):
        storage.add_proposal({'id':'demo-intake-'+str(i),'title':title,'notes':notes,
            'source_from':'Demo school office' if i==0 else 'Demo library','source_subject':title,
            'start':str(date.today()+timedelta(days=i+1)),'end':str(date.today()+timedelta(days=i+2)),
            'all_day':True,'calendar_id':'household_task','status':'proposed'})
    storage.add_finding({'id':'demo-finding','identity':'demo:pickup','state':'open','kind':'other',
        'line':'Confirm the Friday pickup plan','severity':'decide','created_at':time.time()})
    storage.add_program({'id':'demo-piano','member_id':'room-demo-parent','title':'Piano practice','state':'active',
        'shape':{'sessions_per_week':3,'minutes':20},'phases':[{'name':'Comfortable hands',
        'what':'Build a relaxed hand position and play a short melody at a steady pace.',
        'session':'Warm up for five minutes, practise the melody slowly, then play it once through.',
        'milestone':'Play the melody with both hands comfortably.',
        'units':[{'title':'A steady beginning','body':'Keep your wrists loose. Count four beats aloud and play one note on each beat.'}]}]})
    storage.add_program({'id':'demo-garden','member_id':'room-demo-parent','title':'Garden journal','state':'active',
        'shape':{'sessions_per_week':1,'minutes':15},'phases':[{'name':'Look closely','what':'Sketch a plant and describe what changed since last weekend.'}]})
    storage.add_deal({'id':'demo-agreement','date':str(date.today()+timedelta(days=1)),
        'seed_event_id':'demo-pickup','seed_title':'Friday carpool with the neighbors','state':'draft',
        'line':'Share the Friday pickup so each family only drives one direction.',
        'parts':[{'id':'demo-part','member_id':'room-demo-parent','state':'proposed','ask_text':'Can you handle the afternoon pickup?'}]})
    for key,title,location,lat,lon in [('paris','Autumn in Paris','Paris, France',48.8566,2.3522),('tokyo','Spring in Tokyo','Tokyo, Japan',35.6762,139.6503),('lake','Lake weekend','Bear Lake, Utah',41.946,-111.332)]:
        storage.set_trip_metadata('demo-trip-'+key,{'id':'metadata-'+key,'title':title,'location':location,
            'audience':'parents','is_draft':True,'mock_start_date':time.time()+86400*9})
        storage.set_cached_geocode(location,lat,lon)


def install():
    if not os.environ.get('CHAUFFEUR_DATA_DIR'):
        raise RuntimeError('Connected-room fixtures require isolated data storage')
    from services import study
    # The existing /api/study/state route still performs its normal person gate.
    study.state=lambda *args,**kwargs:{'furniture':furniture()}
