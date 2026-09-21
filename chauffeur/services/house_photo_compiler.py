"""Photo architecture IR and deterministic compiler. No provider or storage access.

All intervals share the visible facade's photo-left 0..1 axis. IDs own geometry;
porch roofs and cross-gables never change a building volume's underlying roof.
"""
import copy
import math
from services.house_photo_schema import obj, arr, enum, number, TEXT, BOOL

ANALYSIS_PROMPT = '''Analyze the ORIGINAL HOUSE PHOTO. Return the supplied architecture schema only.
Do not design a house configuration or assign blocks, slots, mirror flags or renderer values.
All at/width intervals use ONE axis: the ENTIRE visible front facade, photo-left 0 to
photo-right 1. Exclude landscaping and driveway. at is the left edge, width is extent.
Describe rectangular wall volumes (not triangles) with stable unique ids. Adjacent wall
volumes must not overlap. stories counts full rectangular walls below the eave, not
window rows. A window inside an attic triangle is an opening owned by a gable, not an
extra story. Use unknown where evidence is insufficient.
Each volume owns one underlying roof. parallel means ridge across the front facade;
perpendicular means front-to-back. Examine roof planes BEHIND the front triangles.
Dormers are separate roof openings owned by a volume, with gable or shed caps.
Cross-gables are separate gables owned by a volume; an end gable is already part of a
perpendicular roof. Porch gables are owned by a porch, never by a building roof.
Each porch references its wall volume. Give one continuous covered porch interval even
when a small entrance gable interrupts it. Gables on a shed porch produce a mixed roof.
Openings have owner ids of a volume or gable and explicit count of FRAMED units, not panes.
List each separated upstairs window independently. Include shutters when visible.
Record finish bands by global interval and story. base bands have story=base.
Materials and colours must use the nearest permitted values, unknown if uncertain.
Projecting depth is relative to neighbouring walls, not total building depth.
Unsupported elements and uncertainties belong in limitations; never invent roof/room shapes
for details such as bay windows, metal awnings or hidden garage entrances.
'''


def analysis_schema():
    from services import house_facade as h
    region={'at':number(0,1),'width':number(0,1)}
    roof=obj({'form':enum(('gable','hip','shed','flat','unknown')),
              'ridge':enum(('parallel','perpendicular','unknown')),
              'pitch':enum(('low','medium','steep','unknown')),'evidence':TEXT})
    return obj({'schema_version':{'type':'integer','enum':[1]},
      'viewpoint':enum(('left','centre','right')),'garage_side':enum(('left','right','unknown')),
      'volumes':arr(obj({'id':TEXT,**region,'stories':enum(('one','two','unknown')),
        'projection':enum(('flush','forward','recessed','unknown')),'roof':roof,'evidence':TEXT})),
      'porches':arr(obj({'id':TEXT,'owner':TEXT,**region,'roof':enum(('shed','flat','gable','open','unknown'))})),
      'gables':arr(obj({'id':TEXT,'owner':TEXT,**region,'kind':enum(('cross','end','unknown')),'evidence':TEXT})),
      'dormers':arr(obj({'id':TEXT,'owner':TEXT,**region,'roof':enum(('gable','shed')),'window':BOOL})),
      'openings':arr(obj({'id':TEXT,'owner':TEXT,**region,'kind':enum(('window','door','garage_door')),
        'level':enum(('ground','upper','attic')),'count':number(1,4,True),
        'size':enum(('small','standard','tall','unknown')),'shutters':BOOL})),
      'finishes':arr(obj({**region,'story':enum(('ground','upper','base')),
        'material':enum((*h.CLADDINGS,'unknown')),'colour':enum((*h.STYLE['body'],'unknown'))})),
      'palette':obj({role:enum((*h.STYLE[role],'unknown')) for role in ('roof','frame','door','trim')}),
      'limitations':arr(TEXT)})


def review_schema():
    return obj({'analysis':analysis_schema(),'reasons':arr(TEXT)})


def validate_analysis(value):
    """Validate our small JSON-schema subset, then architecture relationships."""
    errors=[]
    def walk(v,s,path):
        kind=s['type']
        ok={'object':lambda:isinstance(v,dict),'array':lambda:isinstance(v,list),
            'string':lambda:isinstance(v,str),'boolean':lambda:type(v) is bool,
            'integer':lambda:type(v) is int,'number':lambda:type(v) in (int,float) and math.isfinite(v)}[kind]()
        if not ok:errors.append(path+' must be '+kind);return
        if 'enum' in s and v not in s['enum']:errors.append(path+' has an unknown value')
        if kind in ('integer','number') and not s.get('minimum',-math.inf)<=v<=s.get('maximum',math.inf):errors.append(path+' outside range')
        if kind=='object':
            for k in s['required']:
                if k not in v:errors.append(path+'.'+k+' missing')
            for k,x in v.items():
                if k=='_model' and path=='analysis':continue
                if k not in s['properties']:errors.append(path+'.'+k+' is not an analysis field')
                else:walk(x,s['properties'][k],path+'.'+k)
        elif kind=='array':
            if len(v)>64:errors.append(path+' has too many entries');return
            for i,x in enumerate(v):walk(x,s['items'],f'{path}[{i}]')
    walk(value,analysis_schema(),'analysis')
    if errors:return errors
    if not value['volumes']:return ['analysis needs at least one wall volume']
    ids={}
    for layer in ('volumes','porches','gables','dormers','openings','finishes'):
        for row in value[layer]:
            if row['width']<=0 or row['at']+row['width']>1.001:errors.append(layer+' interval lies outside the facade')
            if 'id' in row:
                if not row['id'].strip() or row['id'] in ids:errors.append('missing or duplicate architectural id')
                ids[row['id']]=(layer,row)
    vols=sorted(value['volumes'],key=lambda r:r['at'])
    if any(a['at']+a['width']>b['at']+.001 for a,b in zip(vols,vols[1:])):errors.append('wall volumes overlap')
    for layer,allowed in [('porches',('volumes',)),('gables',('volumes','porches')),('dormers',('volumes',)),('openings',('volumes','gables'))]:
        for row in value[layer]:
            owner=ids.get(row['owner'])
            if not owner or owner[0] not in allowed:errors.append(row['id']+' has invalid owner');continue
            parent=owner[1]
            if layer != 'porches' and (row['at']<parent['at']-.02 or row['at']+row['width']>parent['at']+parent['width']+.02):
                errors.append(row['id']+' extends beyond its owner')
            if layer=='openings':
                if row['level']=='upper' and (owner[0]!='volumes' or parent['stories']!='two'):errors.append(row['id']+' upper opening has no second-story wall')
                if (row['level']=='attic') != (owner[0]=='gables'):errors.append(row['id']+' attic opening must belong to a gable')
                if row['level']=='attic' and row['kind']!='window':errors.append(row['id']+' attic opening must be a window')
    return errors


def compile_analysis(analysis):
    """Return spec, notes, provenance; identical analysis always yields identical output."""
    from services import house_facade as h
    errors=validate_analysis(analysis)
    if errors:raise ValueError('; '.join(errors[:6]))
    a=copy.deepcopy(analysis);notes=list(a['limitations']);mapping=[]
    def interval(row,mirror):
        left=1-row['at']-row['width'] if mirror else row['at']
        start=max(0,min(17,int(math.floor(left*18+.5))))
        end=max(start+1,min(18,int(math.floor((left+row['width'])*18+.5))))
        return start,end
    def score(mirror):
        cost=0
        for v in a['volumes']:
            start,end=interval(v,mirror)
            if start<6<end:cost+=min(6-start,end-6)*(5 if v['stories']=='two' else 1)
        for p in a['porches']:
            start,end=interval(p,mirror);cost+=max(0,min(end,3)-start)*12
        for o in a['openings']:
            start,end=interval(o,mirror)
            if o['kind']=='door' and start<6:cost+=100
            if o['kind']=='garage_door' and start>=3:cost+=100
        return cost
    side=a['garage_side']
    mirror=side=='right' if side!='unknown' else score(True)<score(False)
    if side=='unknown':notes.append('Garage side is unseen; block mapping chosen from wall/porch/entry fit, not inferred as a visible garage.')
    spec=copy.deepcopy(h.CANONICAL)
    spec.update(mirror=mirror,ground=[],roof=[],upper=[],finishes=[],story_finishes={},unexpressed=[])
    for role,c in a['palette'].items():
        if c!='unknown':spec['style'][role]=c
        else:notes.append(role+': colour unknown; using renderer default.')
    def roof_of(v):
        r=v['roof'];form=r['form'];ridge=r['ridge']
        if form not in ('gable','hip'):
            notes.append(v['id']+': underlying '+form+' roof approximated by a gable; renderer limitation.')
            form='gable'
        if ridge=='unknown':notes.append(v['id']+': unseen ridge defaults to parallel; review required.')
        if r['pitch']=='unknown':notes.append(v['id']+': unknown roof pitch defaults to 30 degrees.')
        return {'form':form,'ridge':'z' if ridge=='perpendicular' else 'x',
                'pitch_deg':{'low':22.5,'medium':30,'steep':35,'unknown':30}[r['pitch']]}
    volumes={v['id']:v for v in a['volumes']}
    def parts(row):
        start,end=interval(row,mirror)
        return [(max(start,lo),min(end,hi)) for lo,hi in ((0,6),(6,18)) if max(start,lo)<min(end,hi)]
    for name,lo,hi in [('garage',0,6),('main',6,18)]:
        ranked=sorted(a['volumes'],key=lambda v:(-max(0,min(interval(v,mirror)[1],hi)-max(interval(v,mirror)[0],lo)),v['id']))
        dominant=ranked[0];spec['blocks'][name]=h._block(orientation='side') if name=='garage' else h._block()
        spec['blocks'][name]['roof']=roof_of(dominant)
        if dominant['projection']=='forward':spec['blocks'][name]['depth']=1.5
        if dominant['projection'] in ('recessed','unknown'):notes.append(dominant['id']+': absolute depth is not observable; using default depth.')
        for v in ranked[1:]:
            start,end=interval(v,mirror)
            if max(start,lo)<min(end,hi) and v['stories']!='two' and roof_of(v)!=spec['blocks'][name]['roof']:
                notes.append(v['id']+': differing ground roof within '+name+' cannot be represented independently.')
    spec['pitch_deg']=spec['blocks']['main']['roof']['pitch_deg']
    for name,lo,hi in [('garage',0,6),('main',6,18)]:
        ground_finishes=[f for f in a['finishes'] if f['story']=='ground' and
                         max(interval(f,mirror)[0],lo)<min(interval(f,mirror)[1],hi)]
        if ground_finishes:
            chosen=max(ground_finishes,key=lambda f:min(interval(f,mirror)[1],hi)-max(interval(f,mirror)[0],lo))
            if chosen['material']!='unknown':spec['blocks'][name]['cladding']=chosen['material']
            if chosen['colour']!='unknown':spec['blocks'][name]['body']=chosen['colour']
    for v in a['volumes']:
        if v['stories']=='unknown':notes.append(v['id']+': uncertain wall height represented as one story.')
        if v['stories']=='two':
            for start,end in parts(v):spec['upper'].append({'slot':start,'span':end-start,'roof':roof_of(v)})
        mapping.append({'id':v['id'],'kind':'volume','slots':[list(x) for x in parts(v)]})
    porches={p['id']:p for p in a['porches']}
    for p in a['porches']:
        spans=parts(p)
        if p['roof'] in ('open','unknown'):notes.append(p['id']+': '+p['roof']+' porch roof uses the default renderer cover; review required.')
        # A front porch cannot occupy the fixed garage driveway bay.
        spans=[(max(start,3),end) for start,end in spans if end>3]
        if not spans:notes.append(p['id']+': porch falls in the fixed garage bay and cannot be placed.');continue
        for start,end in spans:
            row={'slot':start,'span':end-start,'kind':'porch','type':'stoop' if p['roof']=='open' else 'covered',
                 'roof':p['roof'] if p['roof'] in ('flat','shed','gable') else 'flat'}
            owned=[g for g in a['gables'] if g['owner']==p['id']]
            if owned:
                gs,ge=interval(owned[0],mirror);gs=max(start,min(end-1,gs));ge=max(gs+1,min(end,ge))
                row.update(roof='mixed',gable_offset=gs-start,gable_span=ge-gs)
                if len(owned)>1:notes.append(p['id']+': only one porch gable per span is supported.')
            spec['ground'].append(row);mapping.append({'id':p['id'],'kind':'porch','slot':start,'span':end-start})
    gables={g['id']:g for g in a['gables']}
    for g in a['gables']:
        if g['owner'] in porches:continue
        if g['kind']=='unknown':notes.append(g['id']+': uncertain gable type omitted; review required.');continue
        spans=parts(g);start,end=max(spans,key=lambda x:x[1]-x[0])
        if len(spans)>1:notes.append(g['id']+': gable clipped at a fixed block boundary.')
        attic=[o for o in a['openings'] if o['owner']==g['id']]
        if len(attic)>1 or any(o['count']>1 for o in attic):notes.append(g['id']+': renderer supports one centred attic window.')
        if g['kind']=='cross' and volumes[g['owner']]['roof']['ridge']=='perpendicular':
            notes.append(g['id']+': cross-gable conflicts with perpendicular underlying ridge; omitted for review.')
            continue
        if g['kind']=='cross':
            spec['roof'].append({'slot':start,'span':end-start,'kind':'gable','window':bool(attic)})
        elif attic:
            parent=next((u['roof'] for u in spec['upper'] if u['slot']<=start<u['slot']+u['span']),spec['blocks']['garage' if start<6 else 'main']['roof'])
            if parent['ridge']=='z' and parent['form']=='gable':parent['window']=True
            else:notes.append(g['id']+': end-gable window conflicts with the underlying roof; omitted.')
        mapping.append({'id':g['id'],'kind':'gable','owner':g['owner'],'slot':start,'span':end-start})
    for d in a['dormers']:
        spans=parts(d);start,end=max(spans,key=lambda x:x[1]-x[0])
        spec['roof'].append({'slot':start,'span':end-start,'kind':'shed' if d['roof']=='shed' else 'dormer','window':d['window']})
        mapping.append({'id':d['id'],'kind':'dormer','owner':d['owner'],'slot':start,'span':end-start})
    occupied={1:set(),2:set()}
    # Place doors first, then windows; use the closest free interval without losing count.
    for o in sorted(a['openings'],key=lambda o:(o['kind']=='window',o['at'],o['id'])):
        if o['level']=='attic':continue
        level=2 if o['level']=='upper' else 1
        start,end=interval(o,mirror);count=o['count']
        owner=volumes[o['owner']]
        spans=parts(owner)
        if o['kind']=='door':spans=[(max(6,s),e) for s,e in spans if e>6]
        if o['kind']=='garage_door':spans=[(0,3)]
        size=max(count if o['kind']=='window' else 1,end-start)
        if o['kind']=='door':size=1
        choices=[]
        for lo,hi in spans:
            if level==2 and not any(u['slot']<=lo and hi<=u['slot']+u['span'] for u in spec['upper']):continue
            for w in range(min(size,hi-lo), (count if o['kind']=='window' else 1)-1,-1):
                for cell in range(lo,hi-w+1):
                    if not occupied[level].intersection(range(cell,cell+w)):
                        choices.append((abs(cell+w/2-(start+end)/2)+abs(w-size)*.25,cell,w))
        if not choices:notes.append(o['id']+': opening cannot fit available slots without overlap; omitted.');continue
        _,cell,width=min(choices)
        row={'slot':cell,'span':width,'kind':o['kind']}
        if o['kind']=='window':row.update(size=o['size'] if o['size']!='unknown' else 'standard',shutters=o['shutters'],story=level,count=count)
        elif o['kind']=='garage_door':row.update(style='panel',leaves=2 if count>1 else 1);spec['blocks']['garage']['orientation']='front'
        elif count>1:notes.append(o['id']+': multiple entry door leaves use the renderer\'s single entry door.')
        if cell!=start or width!=end-start:notes.append(o['id']+': opening quantized/repositioned to fit fixed slots.')
        occupied[level].update(range(cell,cell+width));spec['ground'].append(row)
        mapping.append({'id':o['id'],'kind':o['kind'],'owner':o['owner'],'slot':cell,'span':width,'count':count})
    for f in a['finishes']:
        fields={}
        if f['material']!='unknown':fields['cladding']=f['material']
        if f['colour']!='unknown':fields['body']=f['colour']
        for start,end in parts(f):
            if f['story']=='base':
                name='garage' if start<6 else 'main'
                spec['blocks'][name]['base']={'material':fields.get('cladding','brick'),'body':fields.get('body','painted_brick'),'height':.8}
                notes.append('Base band height defaults to 0.8 scene units and wraps its block.')
            else:spec['finishes'].append({'slot':start,'span':end-start,'story':2 if f['story']=='upper' else 1,**fields})
    notes=list(dict.fromkeys(notes))
    before=copy.deepcopy(spec)
    spec,normalization=h.normalize(spec)
    notes+=normalization
    errors=h.validate_block_model(spec)
    if errors:raise ValueError('Compiled house failed validation: '+'; '.join(errors[:6]))
    # Capture normalization losses explicitly; never claim the analysis was reproduced exactly.
    spec['unexpressed']=[n[:h.UNEXPRESSED_LEN] for n in notes[:h.UNEXPRESSED_MAX]]
    return spec,notes,{'compiler_version':1,'mirror_scores':{'normal':score(False),'mirrored':score(True)},
                       'mapping':mapping,'before_normalization':before,'normalization_notes':normalization}
