"""Recipes cannot execute code; jobs never silently exceed their API budget."""
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from harness import check
from services import house_authoring as author

RECIPE={'version':1,'parts':[{'type':'box','material':'wood','position':[0,1,0],'size':[.4,1,.2]}]}


def rejected(recipe):
    try:author.validate(recipe)
    except ValueError:return True
    return False


def scenario_validation():
    check(author.validate(RECIPE)==RECIPE,'valid bounded recipe')
    bad=copy.deepcopy(RECIPE);bad['parts'][0]['url']='https://example.com'
    check(rejected(bad),'no external assets')
    bad=copy.deepcopy(RECIPE);bad['parts'][0]['size'][0]=float('nan')
    check(rejected(bad),'reject NaN geometry')
    bad=copy.deepcopy(RECIPE);bad['parts']*=141
    check(rejected(bad),'hard part limit')
    bad=copy.deepcopy(RECIPE);bad['parts'][0]['repeat']={'count':24,'step':[.01,0,0]};bad['parts']*=6
    check(rejected(bad),'expanded repeated detail also obeys part budget')
    bad=copy.deepcopy(RECIPE);bad['parts'][0]['type']='eval'
    check(rejected(bad),'no code primitives')
    bad=copy.deepcopy(RECIPE);bad['parts'][0]['position'][0]=999
    check(rejected(bad),'bound coordinate input before rendering')


def scenario_resume_and_budget():
    with tempfile.TemporaryDirectory() as tmp:
        directory=Path(tmp);image=directory/'fake.png';image.write_bytes(b'image')
        calls=[];renders=[]
        def request(stage,prompt,images,metrics):
            calls.append(stage);metrics['promptTokenCount']=42
            return {'changes':['refine waist']} if stage=='review' else copy.deepcopy(RECIPE)
        def render(label,recipe):
            renders.append(label)
            return {'gate_pass':True,'room_image':str(image),'detail_image':str(image)}
        job=author.run(directory,'gemini-test',request,render)
        check(job['status']=='review_required','never auto-publish self-reviewed art')
        check(calls==['design','review','correction'],'exactly three requests')
        author.run(directory,'gemini-test',request,render)
        check(len(calls)==3 and len(renders)==4,'completed jobs resume without spending or rebuilding')
    with tempfile.TemporaryDirectory() as tmp:
        directory=Path(tmp);image=directory/'fake.png';image.write_bytes(b'image')
        def render(label,recipe):return {'gate_pass':True,'room_image':str(image),'detail_image':str(image)}
        attempts=[]
        def failed(*args):attempts.append(1);raise RuntimeError('SECRET_KEY_MUST_NOT_PERSIST')
        for _ in range(4):
            try:author.run(directory,'gemini-test',failed,render)
            except RuntimeError:pass
        check(len(attempts)==3,'failed attempts also count; no hidden retries')
        text=(directory/'job.json').read_text()
        check('SECRET_KEY' not in text,'sanitize upstream exceptions')
        job=json.loads(text);job['calls'][0]['status']='running';author._save(directory/'job.json',job)
        try:author.run(directory,'gemini-test',failed,render)
        except RuntimeError:pass
        check(len(attempts)==3,'uncertain interrupted call cannot be replayed')


def scenario_metered_transport():
    from services.llm import _call_llm_json
    import io
    payload={'usageMetadata':{'promptTokenCount':12,'candidatesTokenCount':7},
             'modelVersion':'gemini-test',
             'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ok":true}'}]}}]}
    metrics={}
    with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as send:
        result=_call_llm_json('gemini','','fixture-key','gemini-test','system','user',
                              metrics=metrics,max_output_tokens=100,transient_retries=0,
                              thinking_level='low',strict_json=True)
    check(result=={'ok':True} and metrics['promptTokenCount']==12,'usage retained without altering caller result')
    sent=json.loads(send.call_args.args[0].data)
    check(sent['generationConfig']['maxOutputTokens']==100,'generation cap reaches provider')
    check(sent['generationConfig']['thinkingConfig']['thinkingLevel']=='low','reasoning level reaches provider')
    payload['candidates'][0]['finishReason']='MAX_TOKENS'
    with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
        try:
            _call_llm_json('gemini','','key','gemini-test','s','u',strict_json=True)
            complete=True
        except RuntimeError:complete=False
    check(not complete,'never salvage truncated nested JSON into a successful recipe')


if __name__=='__main__':
    scenario_validation();scenario_resume_and_budget();scenario_metered_transport()
    print('House authoring passed')
