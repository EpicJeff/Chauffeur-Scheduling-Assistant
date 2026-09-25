"""Populated kitchen fixtures for an explicitly isolated local preview server.

Imported by scratch/serve_hybrid.py, never by the application. Dates follow
today; shopping uses real temporary storage so check/undo remains interactive.
"""
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from tinydb import Query


def schedule(**_):
    today = date.today()
    entries = [(-12, 'School picture day', 9, 1), (-5, 'Piano lesson', 16, 1),
               (-2, 'Library books due', 10, 1), (0, 'Soccer practice', 16, 2),
               (0, 'Parent–teacher conference', 17, 1), (0, 'Pick up birthday cake', 18, 1),
               (0, 'Family movie night', 19, 2), (1, 'Dentist · Alex', 10, 1),
               (2, 'Maya’s birthday picnic', 12, 3), (3, 'Weekend hike', 9, 4),
               (4, 'School orchestra rehearsal', 16, 2), (6, 'Dinner with grandparents', 18, 2),
               (8, 'Community garden morning', 9, 2), (12, 'School fall festival', 15, 3)]
    events = []
    for i, (offset, title, hour, duration) in enumerate(entries):
        start = datetime.combine(today + timedelta(days=offset), datetime.min.time()).replace(hour=hour)
        events.append({'id':f'kitchen-demo-event-{i}', 'title':title,
                       'start':start.isoformat(), 'end':(start+timedelta(hours=duration)).isoformat(),
                       'calendar_ids':['demo-family' if i%2 else 'demo-kids'],
                       'location':'Demo location', 'description':'Sample event for reviewing the kitchen calendar.'})
    return {'events':events, 'assignments':{}, 'drivers':[], 'passengers':[],
            'calendar_metadata':{'demo-family':{'summary':'Family','backgroundColor':'#54795a'},
                                 'demo-kids':{'summary':'Kids','backgroundColor':'#647ba7'}}}


MEALS = [('Lemon chicken', 'Roasted potatoes · Green beans', 25, 30),
         ('Tomato & basil pasta', 'Garden salad', 20, 0),
         ('Black bean tacos', 'Avocado · Lime rice', 20, 0),
         ('Homemade pizza', 'Cucumber salad', 30, 18),
         ('Salmon with herbs', 'Couscous · Roasted broccoli', 20, 20),
         ('Slow-cooked vegetable curry', 'Basmati rice · Naan', 15, 90),
         ('Leftover night', 'Fruit salad', 10, 0)]


def meal_week(**_):
    week = []
    for i, (name, sides, hands, oven) in enumerate(MEALS):
        day = date.today()+timedelta(days=i)
        dishes = [{'id':f'kitchen-demo-dish-{i}', 'name':name, 'type':'entree'}]
        dishes += [{'name':n, 'type':'side'} for n in sides.split(' · ')]
        week.append({'date':day.isoformat(), 'weekday':day.strftime('%a'), 'dishes':dishes,
                     'finish_mins':hands, 'unattended_mins':oven, 'cook_window_mins':20 if i==2 else 90})
    return {'week':week, 'spans':[{'key':'next','start':week[0]['date'],'days':7,'week':week}],
            'window':{'start':week[0]['date'],'days':7}}


def seed():
    from services import storage
    if not os.environ.get('CHAUFFEUR_DATA_DIR'):
        raise RuntimeError('Kitchen demo fixtures require CHAUFFEUR_DATA_DIR isolation')
    groceries = storage.get_shopping_lists()[0]
    for i, name in enumerate(['Oat milk · 2 cartons','Free-range eggs','Sourdough bread',
        'Cherry tomatoes','Fresh basil','Chicken thighs · 1.5 lb','Lemons · 4',
        'Whole-wheat pasta','Black beans · 2 cans','Avocados','Dishwasher tablets',
        'Unsweetened Greek yogurt · large tub','Strawberries','Birthday candles']):
        row={'id':f'kitchen-demo-item-{i}', 'name':name, 'list_id':groceries['id'],
             'is_checked':i in (2,6), 'created_at':time.time()+i,
             'note':'For Saturday’s picnic' if i==12 else ''}
        storage.shopping_items_table.upsert(row, Query().id==row['id'])
    for i, (name, _, hands, oven) in enumerate(MEALS):
        row={'id':f'kitchen-demo-dish-{i}','name':name,'active':True,'type':'entree',
             'category_ids':[],'hands_on_mins':hands,'total_mins':hands+oven}
        storage.dishes_table.upsert(row,Query().id==row['id'])
    channel={'id':'kitchen-demo-album','kind':'event','event_id':'kitchen-demo-weekend','title':'Weekend together'}
    storage.chat_channels_table.upsert(channel,Query().id==channel['id'])
    members=storage.get_all_members()
    for i, (asset, caption) in enumerate([('picnic','A picnic and a whole afternoon together.'),
                                        ('dog','Someone found the tennis ball!'),
                                        ('painting','The newest masterpieces for the fridge.')]):
        row={'id':f'kitchen-demo-moment-{i}','channel_id':channel['id'],
             'sender_member_id':members[i%len(members)]['id'], 'body':caption,
             'ts':time.time()-86400*(i+1), 'attachment':{'kind':'photo','url':f'/demo/kitchen-media/{asset}.png'}}
        storage.chat_messages_table.upsert(row,Query().id==row['id'])
    storage.patch_settings({'weather_entity':'weather.kitchen_demo'})
    storage.get_cached_schedule=lambda *a,**kw:schedule()


def install(app, assets):
    from fastapi.staticfiles import StaticFiles
    from services import storage, ha_api
    if not os.environ.get('CHAUFFEUR_DATA_DIR'):
        raise RuntimeError('Kitchen demo fixtures require CHAUFFEUR_DATA_DIR isolation')
    assets=Path(assets)
    app.mount('/demo/kitchen-media',StaticFiles(directory=assets),name='kitchen-demo-media')
    old_state=ha_api.get_state
    ha_api.get_state=lambda entity,*a,**kw: ({'entity_id':entity,'state':'rainy',
        'attributes':{'temperature':64,'temperature_unit':'°F'}} if entity=='weather.kitchen_demo' else old_state(entity,*a,**kw))
    ha_api.get_weather_forecast=lambda *a,**kw: [
        {'datetime':(date.today()+timedelta(days=i)).isoformat(), 'condition':cond,
         'temperature':hi,'templow':lo,'precipitation_probability':rain}
        for i,(cond,hi,lo,rain) in enumerate([('rainy',66,54,85),('cloudy',69,52,20),
            ('sunny',74,55,0),('sunny',76,57,0),('partlycloudy',71,53,15)])]
    storage.get_cached_schedule=lambda *a,**kw:schedule()
    for route in app.routes:
        if getattr(route,'path','')=='/api/schedule':route.dependant.call=schedule
        if getattr(route,'path','')=='/api/meals/week':route.dependant.call=meal_week
