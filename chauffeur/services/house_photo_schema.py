"""Provider JSON schemas for house photo stages; renderer validation remains authoritative."""
def obj(properties, required=None):
    return {'type':'object','properties':properties,'required':list(properties) if required is None else required,'additionalProperties':False}
def arr(items):return {'type':'array','items':items}
def enum(values):return {'type':'string','enum':list(values)}
def number(lo,hi,integer=False):return {'type':'integer' if integer else 'number','minimum':lo,'maximum':hi}
TEXT={'type':'string'}
BOOL={'type':'boolean'}

def observations_schema():
    region={'at':number(0,1),'width':number(0,1)}
    return obj({'viewpoint':enum(('left','centre','right')),'garage_side':enum(('left','right','unknown')),
      'sections':arr(obj({**region,'description':TEXT})),
      'roofs':arr(obj({**region,'story':number(1,2,True),'ridge':enum(('x','z','unknown')),
         'front_gable':enum(('cross','end','none','unknown')),'evidence':TEXT})),
      'upper':arr(obj({**region,'windows':number(0,40,True)})),
      'porches':arr(obj(region)),'gables':arr(obj(region)),'materials':arr(TEXT),'uncertain':arr(TEXT)})

def house_schema(*, fractional=False):
    from services import house_facade as h
    coord=({'block':enum(('main','garage')),'at':number(0,1),'width':number(0,1)} if fractional else
           {'slot':number(0,17,True),'span':number(1,18,True)})
    roof=obj({'form':enum(h.ROOF_FORMS),'ridge':enum(h.RIDGES),'pitch_deg':number(h.PITCH_MIN,h.PITCH_MAX),'window':BOOL},['form','ridge','pitch_deg'])
    finish=obj({'cladding':enum(h.CLADDINGS),'body':enum(h.STYLE['body'])},[])
    base={'anyOf':[{'type':'null'},obj({'material':enum(h.CLADDINGS),'height':number(h.BASE_H_MIN,h.BASE_H_MAX),'body':enum(h.STYLE['body'])})]}
    block={'depth':number(0,h.DEPTH_MAX),'roof':roof,'cladding':enum(h.CLADDINGS),'body':enum(h.STYLE['body']),'base':base}
    garage=obj({**block,'orientation':enum(h.ORIENTATIONS),'door_colour':enum(h.GARAGE_COLOURS),
      'side_door':obj({'style':enum(h.GARAGE_STYLES),'leaves':number(1,2,True),'width':number(2.4,4.4),'height':number(2.4,4),
                       'third_bay':BOOL,'projection':number(0,3),'front_setback':number(.6,4)},['style','leaves','width','height'])},list(block)+['orientation'])
    def feature(kind,fields,optional=()):
        p={**coord,'kind':enum((kind,)),**fields}
        return obj(p,[k for k in p if k not in optional])
    ground={'anyOf':[
      feature('window',{'size':enum(h.WINDOW_SIZES),'shutters':BOOL,'story':number(1,2,True),'count':number(1,4,True)},('count',)),
      feature('door',{'count':number(1,2,True)},('count',)),feature('garage_door',{'style':enum(h.GARAGE_STYLES),'leaves':number(1,2,True)}),
      feature('porch',{'type':enum(h.PORCH_TYPES),'roof':enum(h.PORCH_ROOFS),'gable_offset':number(0,17,True),'gable_span':number(1,18,True)},('gable_offset','gable_span'))]}
    return obj({'version':{'type':'integer','enum':[3]},'mirror':BOOL,'viewpoint':enum(('left','centre','right')),
      'pitch_deg':number(h.PITCH_MIN,h.PITCH_MAX),'style':obj({k:enum(h.STYLE[k]) for k in ('roof','frame','door','trim')}),
      'blocks':obj({'main':obj(block),'garage':garage}), 'ground':arr(ground),
      'roof':arr(obj({**coord,'kind':enum(('gable','dormer','shed','hip_end')),'window':BOOL,'cladding':enum(h.CLADDINGS)},list(coord)+['kind'])),
      'upper':arr(obj({**coord,'roof':roof})),
      'finishes':arr(obj({**coord,'story':number(1,2,True),**finish['properties']},list(coord)+['story'])),
      'story_finishes':obj({b:obj({'1':finish,'2':finish},[]) for b in ('main','garage')},[]),'unexpressed':{'type':'array','maxItems':h.UNEXPRESSED_MAX,'items':{'type':'string','description':f'At most {h.UNEXPRESSED_LEN} characters; a short phrase.'}}},
      ['version','mirror','pitch_deg','style','blocks','ground','roof','upper','unexpressed'])

def review_schema():
    return obj({'reasons':arr(TEXT),'corrected_observations':observations_schema(),
                'observation_corrections':arr(TEXT),'revised':house_schema()})
