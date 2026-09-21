"""Photo architecture IR and deterministic compiler. No provider or storage access.

All intervals share the visible facade's photo-left 0..1 axis. IDs own geometry;
porch roofs and cross-gables never change a building volume's underlying roof.
"""
import copy
import math
from services.house_photo_schema import obj, arr, enum, number, TEXT, BOOL

ANALYSIS_PROMPT = '''Schema version 2: explicitly classify each wall face as front/left/right/rear/unknown,
relative to the HOUSE'S FRONT, not the camera. coordinate_frame is house_front.
A side-facing end gable does NOT imply a perpendicular ridge: roof.ridge always means
parallel/perpendicular to the front facade, regardless of which photo shows the ridge.
Record per-image observations: feature ID, image number, physical face and 2D bounding box
in THAT image's normalized coordinates. Keep these boxes separate from front at/width.
Record image-1 evidence for front features when possible. Missing observation annotations
are uncertainty metadata, not an instruction to remove declared front geometry. Use feature="finishes" for collective material
evidence because finish bands have no IDs. Other observations use exact feature IDs.
Only explicitly front-facing rows compile into facade slots.
Side doors/windows/gables must retain their physical face; never move them to the front
just because a supplemental camera sees them. Side garage doors determine side entry.
Volumes describe rectangular WALL faces up to their eaves. A side attic triangle is
not a second front story. Count full front wall stories using visible horizontal eaves.
Use separate side volume rows for side geometry; their at/width is face-local and is
not projected into front slots. Finishes also identify the physical wall face.
Analyze the ORIGINAL HOUSE PHOTO. Return the supplied architecture schema only.
Do not design a house configuration or assign blocks, slots, mirror flags or renderer values.
All FRONT at/width intervals use ONE axis: the ENTIRE visible front facade, photo-left 0 to
photo-right 1. Exclude landscaping and driveway. at is the left edge, width is extent.
Describe rectangular wall volumes (not triangles) with stable unique ids. Adjacent FRONT
wall volumes must not overlap. stories counts full rectangular walls below the eave, not
window rows. A window inside an attic triangle is an opening owned by a gable, not an
extra story. Use unknown where evidence is insufficient.
Each volume owns one underlying roof. parallel means ridge across the front facade;
perpendicular means front-to-back. Examine roof planes BEHIND the front triangles.
Dormers are separate roof openings owned by a volume, with gable or shed caps.
Cross-gables are separate gables owned by a volume; an end gable is already part of a
perpendicular roof. Porch gables are owned by a porch, never by a building roof.
Each porch references its wall volume. Give one continuous covered porch interval even
when a small entrance gable interrupts it. Gables on a shed porch produce a mixed roof.
Openings have owner ids of an existing volume or gable and explicit count of FRAMED units,
not panes. Ground-floor doors/windows under a porch preferably reference its wall volume;
a porch owner is also accepted and resolves through the porch to that same wall volume.
Upper openings must reference a two-story volume; attic windows must reference a gable.
List each separated upstairs window independently. Include shutters when visible.
Record finish bands by global interval and story. base bands have story=base.
Materials and colours must use the nearest permitted values, unknown if uncertain.
Projecting depth is relative to neighbouring walls, not total building depth.
An L-shaped wing may have BOTH parallel and perpendicular intersecting ridges. Describe
both in roof evidence and limitations; the single roof field records the dominant visible
roof, not a claim that the other ridge is absent. Do not infer an extra full story from
an intersecting roof or projecting wing. Do not force a hand-built simplified gable
approximation to be the literal architecture seen in the photo.
Unsupported elements and uncertainties belong in limitations; never invent roof/room shapes
for details such as bay windows, metal awnings or hidden garage entrances.
'''


def analysis_schema(version=2):
    from services import house_facade as h
    region={'at':number(0,1),'width':number(0,1)}
    roof=obj({'form':enum(('gable','hip','shed','flat','unknown')),
              'ridge':enum(('parallel','perpendicular','unknown')),
              'pitch':enum(('low','medium','steep','unknown')),'evidence':TEXT})
    schema = obj({'schema_version':{'type':'integer','enum':[version]},
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
    if version==2:
        face=enum(('front','left','right','rear','unknown'))
        for layer in ('volumes','porches','gables','dormers','openings','finishes'):
            item=schema['properties'][layer]['items']
            item['properties']['face']=face
            item['required'].append('face')
        schema['properties']['coordinate_frame']=enum(('house_front',))
        schema['properties']['observations']=arr(obj({'feature':{**TEXT,'description':'Exact feature id; use reserved finishes for collective material evidence (finish bands have no ids).'},'image':number(1,3,True),
            'face':face,'box':obj({'x':number(0,1),'y':number(0,1),
                'width':number(0,1),'height':number(0,1)}),'evidence':TEXT}))
        schema['required']+=['coordinate_frame','observations']
    return schema


def review_schema():
    return obj({'analysis':analysis_schema(),'reasons':arr(TEXT),
        'structural_review':obj({key:enum(('matched','corrected','uncertain')) for key in
            ('wall_faces','story_boundaries','roof_directions','opening_ownership','porch_placement')})})


def validate_analysis(value, *, _shape_only=False, _fit_openings=False):
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
    walk(value,analysis_schema(2 if isinstance(value,dict) and value.get('schema_version')==2 else 1),'analysis')
    if errors or _shape_only:return errors
    if value.get('schema_version')==2:
        try:
            front,_,_=project_front_analysis(value)
            return validate_analysis(front)
        except ValueError as ex:return [str(ex)]
    if not value['volumes']:return ['analysis needs at least one wall volume']
    ids={}
    for layer in ('volumes','porches','gables','dormers','openings','finishes'):
        for row in value[layer]:
            if row['width']<=0 or row['at']+row['width']>1.001:errors.append(layer+' interval lies outside the facade')
            if 'id' in row:
                if not row['id'].strip() or row['id'] in ids:errors.append('missing or duplicate architectural id')
                ids[row['id']]=(layer,row)
    vols=sorted(value['volumes'],key=lambda r:r['at'])
    for left,right in zip(vols,vols[1:]):
        overlap=left['at']+left['width']-right['at']
        if overlap>.001:
            errors.append(f"wall volumes overlap: {left['id']} / {right['id']} by {overlap:.3f} of facade; intersecting footprints need explicit representation")
    for layer,allowed in [('porches',('volumes',)),('gables',('volumes','porches')),('dormers',('volumes',)),('openings',('volumes','gables','porches'))]:
        for row in value[layer]:
            owner=ids.get(row['owner'])
            if not owner or owner[0] not in allowed:
                errors.append(row['id']+' has invalid owner '+repr(row['owner'])+'; expected '+', '.join(allowed));continue
            parent=owner[1]
            if layer != 'porches' and not (_fit_openings and layer=='openings' and row['level']!='attic') and (row['at']<parent['at']-.02 or row['at']+row['width']>parent['at']+parent['width']+.02):
                errors.append(row['id']+' extends beyond its owner')
            if layer=='openings':
                if owner[0]=='porches':
                    wall=ids.get(parent['owner'])
                    if row['level']!='ground' or row['kind'] not in ('window','door'):
                        errors.append(row['id']+' porch opening must be a ground-floor window or door')
                    if not wall or wall[0]!='volumes':
                        errors.append(row['id']+' porch has no valid wall volume')
                    elif row['at']<wall[1]['at']-.02 or row['at']+row['width']>wall[1]['at']+wall[1]['width']+.02:
                        errors.append(row['id']+' extends beyond its porch wall volume')
                if row['level']=='upper' and (owner[0]!='volumes' or parent['stories']!='two'):errors.append(row['id']+' upper opening has no second-story wall')
                if (row['level']=='attic') != (owner[0]=='gables'):errors.append(row['id']+' attic opening must belong to a gable')
                if row['level']=='attic' and row['kind']!='window':errors.append(row['id']+' attic opening must be a window')
    return errors


def project_front_analysis(value):
    """Project explicitly classified faces, never project another camera's pixels."""
    a=copy.deepcopy(value);notes=[];excluded=[];unplaced=[];unevidenced=[]
    layers=('volumes','porches','gables','dormers','openings','finishes')
    rows=[r for layer in layers for r in a[layer] if 'id' in r]
    ids={r['id']:r for r in rows}
    if len(ids)!=len(rows):raise ValueError('duplicate architectural id')
    kinds={r['id']:layer for layer in layers for r in a[layer] if 'id' in r}
    allowed={'porches':('volumes',),'gables':('volumes','porches'),
             'dormers':('volumes',),'openings':('volumes','porches','gables')}
    for layer in allowed:
        for row in a[layer]:
            if kinds.get(row['owner']) not in allowed[layer]:
                raise ValueError(row['id']+' has invalid owner '+row['owner'])
    for obs in a['observations']:
        if obs['feature']=='finishes' and obs['feature'] not in ids:
            if not any(f['face']==obs['face'] for f in a['finishes']):
                notes.append('Finish evidence for '+obs['face']+' has no matching finish band; retained as an annotation, not applied to another face.')
        else:
            if obs['feature'] not in ids:raise ValueError('observation references unknown feature '+obs['feature'])
            if obs['face']!=ids[obs['feature']]['face']:raise ValueError('observation face conflicts with '+obs['feature'])
        box=obs['box']
        if box['width']<=0 or box['height']<=0 or box['x']+box['width']>1.001 or box['y']+box['height']>1.001:
            raise ValueError('observation box outside image')
    evidence_gaps=[]
    for row in rows:
        observed=[o for o in a['observations'] if o['feature']==row['id']]
        if not observed:unevidenced.append(row['id'])
        if row['face']=='front' and not any(o['image']==1 for o in observed):
            evidence_gaps.append(row['id'])
        elif not observed:
            notes.append(row['id']+': non-front feature lacks image evidence; retained as an annotation, not used to set geometry.')
    if evidence_gaps:
        notes.append('Primary evidence annotations incomplete for '+', '.join(evidence_gaps)+
                     '; declared front geometry retained. Photo accuracy is unverified.')
    # An explicit owner must also contain the opening in the same source image.
    # This catches a below-eave wall window mislabeled as an attic/gable window.
    primary={o['feature']:o['box'] for o in a['observations'] if o['image']==1 and o['face']=='front'}
    for opening in a['openings']:
        if opening['face']!='front' or opening['id'] in unplaced:continue
        owner=ids[opening['owner']]
        if kinds[opening['owner']]=='porches':owner=ids[owner['owner']]
        child=primary.get(opening['id']);parent=primary.get(owner['id'])
        if child and parent and (child['x']<parent['x']-.02 or child['y']<parent['y']-.02 or
                child['x']+child['width']>parent['x']+parent['width']+.02 or
                child['y']+child['height']>parent['y']+parent['height']+.02):
            raise ValueError(opening['id']+' image evidence lies outside its owner wall/gable')
    side_doors=[o for o in a['openings'] if o['kind']=='garage_door' and o['face'] in ('left','right') and o['id'] not in unevidenced]
    faces={o['face'] for o in side_doors}
    if len(faces)>1:notes.append('Garage doors on both sides cannot be represented; retaining configured side.')
    elif faces:
        side=next(iter(faces))
        if a['garage_side'] not in ('unknown',side):raise ValueError('garage side conflicts with observed door face')
        a['garage_side']=side
    kept={r['id'] for r in rows if r['face']=='front'}
    for layer in layers:
        front=[]
        for row in a[layer]:
            face=row.pop('face')
            if row.get('id') in unplaced:
                excluded.append({'id':row['id'],'face':face,'kind':row.get('kind',layer),'reason':'unresolved_primary_evidence_or_owner'})
            elif face!='front':
                excluded.append({'id':row.get('id',layer),'face':face,'kind':row.get('kind',layer)})
                notes.append(row.get('id',layer)+': '+face+' face kept out of front-facade slots.')
            elif 'owner' in row and row['owner'] not in kept:
                raise ValueError(row['id']+' front feature has a non-front owner')
            else:front.append(row)
        a[layer]=front
    a['schema_version']=1
    a.pop('coordinate_frame');a.pop('observations')
    return a,notes,{'excluded_faces':excluded,'unplaced_features':unplaced,'unplaced_openings':[i for i in unplaced if kinds[i]=='openings'],'unevidenced_features':unevidenced,'evidence_gaps':evidence_gaps,'side_garage':bool(side_doors),
                   'side_garage_count':sum(o['count'] for o in side_doors)}


def prepare_analysis(value):
    """Resolve redundant labels and small boundary rounding, never infer new massing."""
    errors=validate_analysis(value,_shape_only=True)
    if errors:raise ValueError('; '.join(errors[:6]))
    a=copy.deepcopy(value);notes=[]
    if a.get('schema_version')==2:
        a,notes,_=project_front_analysis(a)
    # Duplicate IDs remain strict errors; never pick one ambiguous owner.
    rows=[r for layer in ('volumes','porches','gables','dormers','openings') for r in a[layer]]
    ids=[r['id'] for r in rows]
    if len(ids)!=len(set(ids)):
        raise ValueError('missing or duplicate architectural id')
    gables={g['id'] for g in a['gables']}
    for opening in a['openings']:
        if opening['kind']=='window' and opening['level']=='upper' and opening['owner'] in gables:
            opening['level']='attic'
            notes.append(opening['id']+': upper label resolved to attic from explicit gable owner.')
    volumes=sorted(a['volumes'],key=lambda r:r['at'])
    for left,right in zip(volumes,volumes[1:]):
        end=left['at']+left['width'];overlap=end-right['at']
        # Only adjacent edge noise, not nested or intersecting architectural volumes.
        if (.001<overlap<=.02+1e-9 and overlap<=min(left['width'],right['width'])*.1+1e-9
                and left['at']<right['at'] and end<right['at']+right['width']):
            seam=(end+right['at'])/2;right_end=right['at']+right['width']
            left['width']=seam-left['at'];right['at']=seam;right['width']=right_end-seam
            notes.append(left['id']+' / '+right['id']+': small wall-boundary overlap shared at midpoint.')
    # Photo estimates include roof overhangs and imprecise shared edges. Keep
    # explicit ownership authoritative when the gable is centred on its owner
    # and most of its width overlaps it. Never reassign it to a different wall.
    owners={r['id']:r for layer in ('volumes','porches') for r in a[layer]}
    for g in a['gables']:
        parent=owners.get(g['owner'])
        if not parent:continue  # strict ownership validation below
        lo,hi=parent['at'],parent['at']+parent['width']
        start,end=g['at'],g['at']+g['width']
        overlap=min(end,hi)-max(start,lo)
        if (g['width']>0 and (start<lo-.02 or end>hi+.02) and
                lo<=(start+end)/2<=hi and overlap>=g['width']*.5):
            g['at']=max(start,lo);g['width']=min(end,hi)-g['at']
            notes.append(g['id']+': approximate gable bounds fitted to declared owner '+g['owner']+'.')
    if value.get('schema_version')==2:
        walls={v['id']:v for v in a['volumes']}
        for opening in a['openings']:
            wall=walls.get(opening['owner'])
            if wall and opening['level']!='attic' and (opening['at']<wall['at']-.02 or opening['at']+opening['width']>wall['at']+wall['width']+.02):
                notes.append(opening['id']+': approximate opening coordinates extend beyond declared wall; placement constrained to that wall.')
    errors=validate_analysis(a,_fit_openings=value.get('schema_version')==2)
    if errors:raise ValueError('; '.join(errors[:6]))
    return a,notes


def compile_analysis(analysis):
    """Return spec, notes, provenance; identical analysis always yields identical output."""
    from services import house_facade as h
    a,adjustments=prepare_analysis(analysis)
    projection=project_front_analysis(analysis)[2] if analysis.get('schema_version')==2 else {}
    notes=list(a['limitations'])+adjustments;mapping=[]
    # Fit the fixed block seam to a real wall-volume boundary. A uniform scale
    # can cut a single perpendicular roof into two independently capped towers.
    # Use one continuous monotonic map for EVERY layer, including openings.
    seams={}
    for mirrored in (False,True):
        rows=sorted((1-v['at']-v['width'] if mirrored else v['at'],
                     1-v['at'] if mirrored else v['at']+v['width']) for v in a['volumes'])
        boundaries=[(left[1]+right[0])/2 for left,right in zip(rows,rows[1:])
                    if abs(left[1]-right[0])<=.025 and .2<=(left[1]+right[0])/2<=.5]
        seams[mirrored]=min(boundaries,key=lambda x:(abs(x-1/3),x)) if boundaries else 1/3
    def interval(row,mirror,fit=True):
        left=1-row['at']-row['width'] if mirror else row['at']
        seam=seams[mirror] if fit else 1/3
        def project(x):
            return x*6/seam if x<=seam else 6+(x-seam)*12/(1-seam)
        start=max(0,min(17,int(math.floor(round(project(left),10)+.5))))
        end=max(start+1,min(18,int(math.floor(round(project(left+row['width']),10)+.5))))
        return start,end
    def score(mirror):
        cost=0
        for v in a['volumes']:
            start,end=interval(v,mirror,False)
            if start<6<end:cost+=min(6-start,end-6)*(5 if v['stories']=='two' else 1)
        for p in a['porches']:
            start,end=interval(p,mirror,False);cost+=max(0,min(end,3)-start)*12
        for o in a['openings']:
            start,end=interval(o,mirror,False)
            if o['kind']=='door' and start<6:cost+=100
            if o['kind']=='garage_door' and start>=3:cost+=100
        return cost
    side=a['garage_side']
    mirror=side=='right' if side!='unknown' else score(True)<score(False)
    if side=='unknown':notes.append('Garage side is unseen; block mapping chosen from wall/porch/entry fit, not inferred as a visible garage.')
    if abs(seams[mirror]-1/3)>.001:
        notes.append('Facade proportions fitted to the fixed block boundary at an observed wall-volume seam.')
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
    for o in sorted(a['openings'],key=lambda o:(o['kind']=='window',interval(o,mirror)[0],o['id'])):
        if o['level']=='attic':continue
        if o['kind']=='garage_door' and projection.get('side_garage'):
            notes.append(o['id']+': additional front garage entry omitted while preserving side entry.')
            continue
        level=2 if o['level']=='upper' else 1
        start,end=interval(o,mirror);count=o['count']
        wall_owner=porches[o['owner']]['owner'] if o['owner'] in porches else o['owner']
        owner=volumes[wall_owner]
        if wall_owner!=o['owner']:
            notes.append(o['id']+': porch opening resolved to wall volume '+wall_owner+'.')
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
        mapping.append({'id':o['id'],'kind':o['kind'],'owner':o['owner'],'wall_owner':wall_owner,'slot':cell,'span':width,'count':count})
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
    if projection.get('side_garage'):
        notes.append('Side garage uses the renderer side-entry layout and default door dimensions; supplemental image coordinates are not projected onto the front.')
        if any(o['kind']=='garage_door' for o in a['openings']):
            notes.append('Front and side garage entries cannot both be placed exactly; preserving side entry.')
            spec['ground']=[g for g in spec['ground'] if g['kind']!='garage_door']
        spec['blocks']['garage']['orientation']='side'
        spec['blocks']['garage']['side_door']={'style':'panel','leaves':min(2,projection['side_garage_count']),'width':4.4,'height':3.0}
    notes=list(dict.fromkeys(notes))
    before=copy.deepcopy(spec)
    spec,normalization=h.normalize(spec)
    notes+=normalization
    errors=h.validate_block_model(spec)
    if errors:raise ValueError('Compiled house failed validation: '+'; '.join(errors[:6]))
    # Capture normalization losses explicitly; never claim the analysis was reproduced exactly.
    spec['unexpressed']=[n[:h.UNEXPRESSED_LEN] for n in notes[:h.UNEXPRESSED_MAX]]
    return spec,notes,{'compiler_version':4,'face_projection':projection,'prepared_analysis':copy.deepcopy(a),'analysis_adjustments':adjustments,'block_seam':seams[mirror],'mirror_scores':{'normal':score(False),'mirrored':score(True)},
                       'mapping':mapping,'before_normalization':before,'normalization_notes':normalization}
