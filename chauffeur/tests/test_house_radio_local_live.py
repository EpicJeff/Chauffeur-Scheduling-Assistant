"""Radio uses the music card's stable local player and resolves its queue entity."""
from test_house_hybrid_live import seed, live_app, ha_api


def main():
    ha_api.get_states=lambda *a,**k:[]
    ha_api.get_state=lambda *a,**k:None
    served=live_app(seed)
    remote={'entity_id':'media_player.kitchen','name':'Kitchen','state':'paused','volume_level':.2}
    local={'entity_id':'media_player.renamed_panel','name':'Renamed panel','state':'paused','volume_level':.4,'shuffle':False}
    writes=[]
    exposed=True
    try:
        with served.browser(reduced_motion='reduce') as page:
            page.add_init_script("""Object.defineProperty(window,'MusicLogic',{configurable:true,set(logic){
              Object.defineProperty(window,'MusicLogic',{value:logic,writable:true});
              logic.thisDevice=async()=>({named:true,label:'Kitchen panel'});
              logic.localPlayer=(identity,opts)=>{
                window.localIdentity=identity;window.localCommands=[];window.localStarts=0;
                const p=window.testLocal={active:false,connecting:false,wanted:false,
                  start(){window.localStarts++;p.active=true;opts.onState();},
                  nowPlaying(){return {media_title:'Local music',volume_level:.4};},
                  isPlaying(){return false;},
                  entityIn(players){return players.find(x=>x.entity_id==='media_player.renamed_panel');},
                  command(command,extra){window.localCommands.push({command,extra});return true;}
                };return p;
              };
            }});""")
            def api(route):
                url=route.request.url
                if '/api/ha/media_players' in url:
                    if url.endswith('/command'):
                        writes.append((url,route.request.post_data_json));return route.fulfill(json={'ok':True})
                    return route.fulfill(json=([remote,local] if exposed else [remote]))
                if '/api/music/play' in url:
                    writes.append((url,route.request.post_data_json));return route.fulfill(json={'ok':True})
                if '/api/music/favorites' in url:return route.fulfill(json={'items':[]})
                route.fallback()
            page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=204,body=''))
            page.route('**/api/**',api)
            page.goto(served.url('house?compare=living&light=day'))
            page.locator('#hybrid-hotspots [data-card=music]').click()
            page.locator('#house-radio').wait_for(state='visible')
            output=page.locator('#radio-output')
            page.wait_for_function("document.querySelector('#radio-output option[value=__local__]')")
            assert page.evaluate('localStarts')==0
            output.select_option('__local__')
            page.wait_for_function('HouseRadio.state().available')
            assert page.evaluate('localIdentity.key')==page.evaluate("'chauffeur_sendspin_id::screen::'+MusicLogic.deviceId()")
            assert page.evaluate('localIdentity.name')=='Kitchen panel'
            assert page.locator('#radio-output option[value="media_player.renamed_panel"]').count()==0
            page.locator('#radio-power').click()
            page.wait_for_function("localCommands.some(c=>c.command==='play')")
            page.evaluate("HouseRadio.command('volume_set',{volume:.6})")
            assert page.evaluate('localCommands.at(-1).extra.volume')==.6
            page.evaluate("HouseRadio.command('shuffle_set',{shuffle:true})")
            assert 'media_player.renamed_panel' in writes[-1][0]
            page.evaluate("HouseRadio.playItem({uri:'library://track/1',media_type:'track'})")
            assert writes[-1][1]['entity_id']=='media_player.renamed_panel'
            exposed=False
            count=len(writes)
            page.evaluate("HouseRadio.command('repeat_set',{repeat:'all'})")
            assert len(writes)==count
            assert 'not exposed' in page.locator('#radio-notice').inner_text()
            output.select_option('media_player.kitchen')
            assert page.evaluate('testLocal.wanted') is False
            page.locator('#radio-power').click()
            page.wait_for_function("!HouseRadio.state().busy")
            assert 'media_player.kitchen' in writes[-1][0]
            output.select_option('__local__')
            page.reload()
            page.locator('#hybrid-hotspots [data-card=music]').click()
            page.wait_for_function("HouseRadio.state().selected==='__local__' && HouseRadio.state().available")
            assert not served.errors(),served.errors()
            print('PASS radio local choice, stable identity, transport, queue targeting, missing entity and saved selection')
    finally:served.stop()


if __name__=='__main__':main()
