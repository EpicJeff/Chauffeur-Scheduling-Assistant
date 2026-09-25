"""Radio music-card parity with intercepted APIs; never contacts household speakers."""
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from test_house_hybrid_live import seed, live_app, ha_api


def main():
    ha_api.get_states=lambda *a,**k:[]
    ha_api.get_state=lambda *a,**k:None
    served=live_app(seed)
    out=Path('../scratch/radio-parity');out.mkdir(parents=True,exist_ok=True)
    track={'uri':'library://track/1','name':'Blue in Green','media_type':'track','favorite':False}
    player={'entity_id':'media_player.living','name':'Living room','state':'playing','volume_level':.4,
            'media_title':track['name'],'media_content_id':track['uri'],'shuffle':False,'repeat':'off'}
    personal=[];writes=[];searches=[];editable=True;fail=False
    queued=[{'id':'one','index':0,'name':'Blue in Green','current':True},
            {'id':'two','index':1,'name':'So What','current':False}]
    def reply(r,data,status=200):r.fulfill(status=status,content_type='application/json',body=json.dumps(data))
    def api(r):
        nonlocal fail
        path=urlparse(r.request.url).path;args=parse_qs(urlparse(r.request.url).query)
        method=r.request.method;body=r.request.post_data_json if method=='POST' else None
        if method!='GET':writes.append((path,body,args))
        if path.endswith('/media_players'):return reply(r,[player])
        if path.endswith('/command') and '/media_players/' in path:
            if fail:return reply(r,{'detail':'Unavailable'},503)
            command=body['command']
            if command=='shuffle_set':player['shuffle']=body['shuffle']
            elif command=='repeat_set':player['repeat']=body['repeat']
            elif command in ('pause','play','stop'):player['state']={'pause':'paused','play':'playing','stop':'idle'}[command]
            return reply(r,{'ok':True})
        if path=='/api/music/now':return reply(r,track)
        if path=='/api/music/favorites':return reply(r,{'items':[dict(track,favorite=True)] if args.get('media_type')==['track'] and track['favorite'] else []})
        if path=='/api/music/my':return reply(r,{'favorites':personal,'recent':[track]})
        if path=='/api/music/my/favorites':
            if method=='POST':personal.append(body['item'])
            else:personal.clear()
            return reply(r,{'ok':True})
        if path=='/api/music/house/favorites':track['favorite']=method=='POST';return reply(r,{'ok':True})
        if path=='/api/music/queue':return reply(r,{'can_edit':editable,'items':queued,'source':'ma'})
        if path=='/api/music/queue/command':return reply(r,{'ok':True})
        if path=='/api/music/play':return reply(r,{'ok':True})
        if path=='/api/music/search':searches.append(args);return reply(r,{'groups':[{'type':'track','items':[track]}],'providers':[{'domain':'spotify','name':'Spotify'}]})
        if path=='/api/music/playlists/editable':return reply(r,[{'item_id':'mix','name':'Family mix'}])
        if path in ('/api/music/playlists/add','/api/music/playlists/create'):return reply(r,{'ok':True})
        if path=='/api/music/shelves':return reply(r,{'available':True,'recently_played':[track],'recommendations':[{'name':'For you','items':[track]}]})
        reply(r,{})
    try:
        with served.browser(reduced_motion='reduce',has_touch=True) as page:
            page.set_default_timeout(15000)
            page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=204,body=''))
            page.route('**/api/members',lambda r:reply(r,[{'id':'alex','name':'Alex'}]))
            page.route('**/api/ha/media_players**',api);page.route('**/api/music/**',api)
            page.goto(served.url('house?compare=living&light=day'))
            page.wait_for_function('window.chfHouseComparison?.readyMs>0')
            assert not writes
            page.locator('#hybrid-hotspots [data-card=music]').click()
            page.wait_for_function('HouseRadio.state().available')
            # Real panel theme rules must not paint over the photographed scene.
            for theme in ('light','dark'):
                page.evaluate('(theme)=>{document.documentElement.setAttribute("data-panel", "");document.documentElement.dataset.panelTheme=theme;}',theme)
                assert page.locator('#radio-output').evaluate('e=>getComputedStyle(e).backgroundColor==="rgba(0, 0, 0, 0)" && getComputedStyle(e).backgroundImage==="none"')
                page.screenshot(path=str(out/('theme-'+theme+'.png')))
            page.evaluate('()=>{document.documentElement.removeAttribute("data-panel");document.documentElement.removeAttribute("data-panel-theme");}')
            def press(command):
                with page.expect_response('**/command') as response:page.locator('[data-radio-command='+command+']').click()
                assert response.value.ok
                page.wait_for_function('!HouseRadio.state().busy')
            for command in ('previous','next','stop'):press(command)
            assert [w[1]['command'] for w in writes[-3:]]==['previous','next','stop']
            with page.expect_response('**/command'):page.locator('#radio-power').click()
            page.wait_for_function('!HouseRadio.state().busy')
            press('shuffle');assert page.locator('[data-radio-command=shuffle]').get_attribute('aria-pressed')=='true'
            for mode in ('all','one','off'):
                press('repeat');assert page.locator('[data-radio-command=repeat]').get_attribute('aria-label')=='Repeat: '+mode
            assert page.locator('.radio-shelf-rail').is_hidden()
            for selector in ('#radio-power','#radio-volume','#radio-tune','#radio-transport button'):
                assert page.locator(selector).first.evaluate('e=>getComputedStyle(e).backgroundImage==="none" && getComputedStyle(e).boxShadow==="none"')
            scene=page.locator('#house-radio').bounding_box()
            for i,x in enumerate((540,599,657,715,774)):
                target=page.locator('#radio-transport button').nth(i).bounding_box()
                assert abs((target['x']+target['width']/2-scene['x'])/scene['width']*1536-x)<3
                assert abs((target['y']+target['height']/2-scene['y'])/scene['height']*1024-534)<3
            page.screenshot(path=str(out/'radio-desktop.png'))
            page.locator('#house-compare-light').select_option('night')
            page.wait_for_selector('#house-radio[data-light="night"]')
            page.screenshot(path=str(out/'radio-night.png'))
            page.locator('#house-compare-light').select_option('day')
            page.locator('#radio-queue-open').click()
            panel=page.locator('#radio-music-panel')
            assert panel.evaluate('el=>el.parentElement.classList.contains("radio-glass") && el.tagName==="SECTION"')
            with page.expect_response('**/api/music/play'):page.locator('[data-radio-command=radio]').click()
            assert writes[-1][1]['radio_mode'] is True
            page.wait_for_function('!HouseRadio.state().busy')
            panel.get_by_role('button',name='Move up So What',exact=True).wait_for()
            for label,command in [('Move up So What','move_up'),('Move down So What','move_down'),('Remove So What','remove'),('Play queued So What','play_index'),('Clear queue','clear')]:
                with page.expect_response('**/api/music/queue/command'):panel.get_by_role('button',name=label,exact=True).click()
                assert writes[-1][1]['action']==command
                page.wait_for_function('!HouseRadio.state().busy')
            page.screenshot(path=str(out/'queue-desktop.png'))
            editable=False
            page.locator('#radio-panel-view').select_option('queue')
            panel.get_by_text('Up next — this connection provides a read-only queue.').wait_for()
            assert panel.get_by_role('button',name='Clear queue').count()==0
            page.locator('#radio-panel-view').select_option('search')
            page.locator('#radio-panel-query').fill('Miles')
            panel.get_by_role('button',name='Find',exact=True).click()
            panel.get_by_role('button',name='Play Blue in Green',exact=True).wait_for()
            page.locator('#radio-panel-type').select_option('track')
            page.locator('#radio-panel-provider').select_option('spotify')
            page.locator('#radio-panel-library').check()
            page.wait_for_function('document.querySelector("#radio-panel-status").textContent==="1 items"')
            assert searches[-1].get('provider')==['spotify'] and searches[-1].get('library_only')==['true']
            for label,enqueue in [('Play next Blue in Green','next'),('Add to queue Blue in Green','add')]:
                with page.expect_response('**/api/music/play'):panel.get_by_role('button',name=label,exact=True).click()
                assert writes[-1][1]['enqueue']==enqueue
                page.wait_for_function('!HouseRadio.state().busy')
            with page.expect_response('**/api/music/house/favorites'):panel.get_by_role('button',name='Favorite Blue in Green',exact=True).click()
            panel.get_by_role('button',name='Favorite Blue in Green',exact=True).wait_for()
            page.wait_for_function('document.getElementById("radio-now-favorite").getAttribute("aria-pressed")==="true"')
            page.locator('#radio-panel-member').select_option('alex')
            page.wait_for_function('document.getElementById("radio-now-favorite").getAttribute("aria-pressed")==="false"')
            with page.expect_response('**/api/music/my/favorites'):page.locator('#radio-now-favorite').click()
            assert writes[-1][1]['member_id']=='alex' and personal
            panel.get_by_role('button',name='Add Blue in Green to a playlist',exact=True).click()
            with page.expect_response('**/api/music/playlists/add'):panel.get_by_role('button',name='Add to Family mix',exact=True).click()
            assert writes[-1][1]=={'playlist_id':'mix','uri':track['uri']}
            panel.get_by_role('button',name='Add Blue in Green to a playlist',exact=True).click()
            panel.get_by_role('textbox',name='New playlist name').fill('Road trip')
            with page.expect_response('**/api/music/playlists/create'):panel.get_by_role('button',name='Create playlist',exact=True).click()
            assert writes[-1][1]=={'name':'Road trip','uri':track['uri']}
            for tab in ('recent','recommendations'):
                page.locator('#radio-panel-view').select_option(tab);panel.get_by_role('button',name='Play Blue in Green',exact=True).wait_for()
            for w,h in ((390,844),(844,390)):
                page.set_viewport_size({'width':w,'height':h})
                box=panel.bounding_box();assert box['x']>=0 and box['y']>=0 and box['width']<=w and box['height']<=h
                page.screenshot(path=str(out/f'panel-{w}.png'))
                assert page.locator('#house-radio').bounding_box()==page.locator('#hybrid-detail-picture').bounding_box()
            page.keyboard.press('Escape');assert not panel.is_visible()
            assert page.locator('#house-radio').is_visible(), 'Escape closes only the music panel'
            box=page.locator('#radio-transport').bounding_box();assert box['x']>=0 and box['y']>=0
            page.screenshot(path=str(out/'radio-landscape.png'))
            page.locator('#hybrid-view-back').click()
            assert page.locator('#radio-transport').is_hidden()
            assert not served.errors(),served.errors()
        print('PASS radio transport, shuffle/repeat, radio mode, editable/read-only queue, search filters, house/personal hearts, playlists, responsive panel and lifecycle')
    finally:served.stop()


if __name__=='__main__':main()
