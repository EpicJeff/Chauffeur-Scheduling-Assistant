"""Profile personalization and contrast checks, shared by every live audience."""
import os
from pathlib import Path


def check_profile_button(page, selector):
    page.wait_for_function("""selector => {
        const probe = document.createElement('span');
        probe.style.color = getComputedStyle(document.documentElement).getPropertyValue('--pwa-accent');
        return getComputedStyle(document.querySelector(selector)).backgroundColor === probe.style.color;
    }""", arg=selector)


def check_profile_palette(page):
    result = page.evaluate("""() => {
        const root = document.documentElement;
        const me = membersData.find(m=>m.id===selectedMemberId);
        const original = me.color_code, theme = root.dataset.theme;
        const probe = document.createElement('span'); document.body.append(probe);
        const resolve = value => { probe.style.color=value; return getComputedStyle(probe).color.match(/[\\d.]+/g).slice(0,3).map(Number); };
        const lum = c => c.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
        const ratio = (a,b) => (Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
        const samples = [];
        for (const color of ['#c23b61','#1754aa','#ffed00','#ffffff','#000000','#0cf','invalid']) {
            me.color_code=color; pwaSyncProfileColors();
            for (const mode of ['light','dark']) {
                applyTheme(mode);
                const css=getComputedStyle(root), token=name=>css.getPropertyValue(name).trim();
                const accent=resolve(token('--pwa-accent')), wash=resolve(token('--pwa-wash'));
                const bg=resolve('rgb('+token('--c-gray-950')+')'), surface=resolve('rgb('+token('--c-gray-900')+')');
                const ink=resolve('rgb('+token('--c-gray-100')+')'), muted=resolve('rgb('+token('--c-gray-400')+')');
                samples.push({color,mode,accent,bg,ratios:[ratio(accent,wash),ratio(accent,surface),ratio(accent,bg),ratio(ink,bg),ratio(muted,bg)]});
            }
        }
        // Same device, different profile: no previous person's palette survives.
        const previous=selectedMemberId;
        membersData.push({id:'palette-fixture',role:'adult',color_code:'#7d359f'});
        selectedMemberId='palette-fixture'; pwaSyncShell();
        const switched=root.dataset.profileColor;
        selectedMemberId=null; pwaSyncShell();
        const cleared=!root.hasAttribute('data-profile-color');
        selectedMemberId=previous; me.color_code=original; pwaSyncShell(); applyTheme(theme);
        membersData=membersData.filter(m=>m.id!=='palette-fixture');
        probe.remove();
        return {samples,switched,cleared,restored:root.dataset.profileColor,original};
    }""")
    assert result['switched'] == '#7d359f'
    assert result['cleared'] and result['restored'] == result['original']
    for sample in result['samples']:
        assert min(sample['ratios']) >= 4.5, sample
    pink, blue = result['samples'][0], result['samples'][2]
    assert pink['accent'][0] > pink['accent'][2], pink
    assert blue['accent'][2] > blue['accent'][0], blue
    assert pink['bg'] != blue['bg']
    output = os.environ.get('PWA_PALETTE_OUTPUT')
    key = page.evaluate('selectedMemberId')
    if output and key in ('parent','explorer'):
        Path(output).mkdir(parents=True,exist_ok=True)
        if key == 'explorer':
            page.evaluate('void renderMyDay()')
            page.wait_for_selector('.child-greeting')
        for name, color, theme in [('pink-light','#c23b61','light'),('blue-light','#1754aa','light'),('blue-dark','#1754aa','dark')]:
            page.evaluate("([color,theme])=>{membersData.find(m=>m.id===selectedMemberId).color_code=color; pwaSyncProfileColors(); applyTheme(theme)}",[color,theme])
            page.wait_for_timeout(350)
            Path(output,f'{key}-{name}.png').write_bytes(page.screenshot())
        page.evaluate("color=>{membersData.find(m=>m.id===selectedMemberId).color_code=color; pwaSyncProfileColors(); applyTheme('light')}",result['original'])
