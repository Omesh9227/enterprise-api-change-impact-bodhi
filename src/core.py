from __future__ import annotations
from copy import deepcopy
from collections import deque
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, yaml

BASE = Path(__file__).resolve().parents[1]
CACHE: dict[str, dict] = {}
HTTP_METHODS = {'get','post','put','patch','delete','head','options','trace'}

def load_json(name):
    return json.loads((BASE/'data'/name).read_text(encoding='utf-8'))

def repair_double_encoded_json(value):
    """Best-effort repair for a common MCP-client integration bug: the caller
    sends a JSON/YAML string that still carries one extra layer of
    JSON-string escaping (literal backslash-quote sequences like `\\"openapi\\"`
    instead of real quotes `"openapi"`), typically because an upstream
    workflow/agent step ran json.dumps() (or equivalent) on the spec text an
    extra time before handing it to this tool. Detect that pattern and undo
    exactly one layer of escaping. Returns the repaired string, or None if
    the value doesn't look like it needs (or can't safely receive) repair.
    """
    if not isinstance(value, str) or '\\"' not in value:
        return None
    try:
        repaired = json.loads(f'"{value}"')
    except (json.JSONDecodeError, ValueError):
        return None
    return repaired if isinstance(repaired, str) else None

def _parsed_openapi_doc(value):
    """Parse a YAML/JSON string and return it only if it looks like a real
    OpenAPI document (dict with 'openapi' and 'paths'). Returns None on any
    parse failure or on a successful-but-wrong-shaped parse -- notably,
    double-encoded JSON often parses "successfully" into a garbage dict of
    literal backslash-quote keys instead of raising, so a shape check is
    required in addition to catching exceptions.
    """
    try:
        doc = yaml.safe_load(value)
    except yaml.YAMLError:
        return None
    return doc if isinstance(doc, dict) and 'openapi' in doc and 'paths' in doc else None

def parse_spec(value):
    if isinstance(value, dict):
        doc = deepcopy(value)
    elif isinstance(value, str):
        doc = _parsed_openapi_doc(value)
        if doc is None:
            repaired = repair_double_encoded_json(value)
            if repaired is not None:
                doc = _parsed_openapi_doc(repaired)
        if doc is None:
            raise ValueError(
                'Invalid OpenAPI document: openapi and paths are required '
                '(also tried undoing one layer of JSON-string escaping in case '
                'this text was double-encoded by an intermediate agent/expression '
                'step; if it still fails, check whether the text was JSON-escaped '
                'more than once before reaching this tool).'
            )
    else:
        raise ValueError('OpenAPI input must be a dict or YAML/JSON string')
    if not isinstance(doc, dict) or 'openapi' not in doc or 'paths' not in doc:
        raise ValueError('Invalid OpenAPI document: openapi and paths are required')
    return doc

def resolve_schema(schema, spec):
    if not isinstance(schema, dict): return {}
    ref = schema.get('$ref')
    prefix = '#/components/schemas/'
    if ref and ref.startswith(prefix):
        return deepcopy(spec.get('components',{}).get('schemas',{}).get(ref[len(prefix):], schema))
    return deepcopy(schema)

def content_schema(container, spec):
    content = (container or {}).get('content',{})
    if not content: return {}
    media = content.get('application/json') or next(iter(content.values()),{})
    return resolve_schema(media.get('schema',{}), spec)

def op_id(service, method, path, op):
    return op.get('operationId') or f'{service}:{method.upper()}:{path}'

def add(out, operation_id, method, path, location, change_type, severity, reason, old=None, new=None):
    out.append({'change_id':f'CHG-{len(out)+1:03d}','operation_id':operation_id,'method':method.upper(),'path':path,'location':location,'change_type':change_type,'severity':severity,'reason':reason,'old_value':old,'new_value':new,'confidence':1.0})

def compare_schema(out, oid, method, path, loc, old, new):
    old, new = old or {}, new or {}
    if old.get('type') and new.get('type') and old['type'] != new['type']:
        add(out,oid,method,path,loc,'TYPE_CHANGED','BREAKING','Schema type changed',old['type'],new['type'])
    old_req, new_req = set(old.get('required',[])), set(new.get('required',[]))
    for f in sorted(new_req-old_req):
        add(out,oid,method,path,f'{loc}.{f}','OPTIONAL_TO_REQUIRED','BREAKING','Optional property became required',False,True)
    op, np = old.get('properties',{}), new.get('properties',{})
    for f in sorted(set(op)|set(np)):
        a,b = op.get(f), np.get(f); fl=f'{loc}.{f}'
        if a is not None and b is None:
            add(out,oid,method,path,fl,'PROPERTY_REMOVED','BREAKING','Property removed',a,None); continue
        if a is None and b is not None:
            sev='BREAKING' if f in new_req else 'NON_BREAKING'
            add(out,oid,method,path,fl,'PROPERTY_ADDED',sev,'Required property added' if sev=='BREAKING' else 'Optional property added',None,b); continue
        if a is None or b is None: continue
        if a.get('type') and b.get('type') and a['type'] != b['type']:
            add(out,oid,method,path,fl,'TYPE_CHANGED','BREAKING','Property type changed',a['type'],b['type'])
        if a.get('enum') is not None and b.get('enum') is not None:
            removed=sorted(set(a['enum'])-set(b['enum'])); added=sorted(set(b['enum'])-set(a['enum']))
            if removed: add(out,oid,method,path,fl,'ENUM_VALUES_REMOVED','BREAKING','Enum values removed',removed,None)
            if added: add(out,oid,method,path,fl,'ENUM_VALUES_ADDED','CONDITIONALLY_BREAKING','New enum values may break exhaustive consumers',None,added)

def diff(service, old_value, new_value):
    old,new=parse_spec(old_value),parse_spec(new_value); out=[]
    for path in sorted(set(old['paths'])|set(new['paths'])):
        a,b=old['paths'].get(path,{}),new['paths'].get(path,{})
        am={m for m in a if m.lower() in HTTP_METHODS}; bm={m for m in b if m.lower() in HTTP_METHODS}
        for m in sorted(am-bm): add(out,op_id(service,m,path,a[m]),m,path,'operation','ENDPOINT_REMOVED','BREAKING','API operation removed',True,False)
        for m in sorted(bm-am): add(out,op_id(service,m,path,b[m]),m,path,'operation','ENDPOINT_ADDED','NON_BREAKING','API operation added',False,True)
        for m in sorted(am&bm):
            ao,bo=a[m],b[m]; oid=op_id(service,m,path,bo)
            compare_schema(out,oid,m,path,'request.body',content_schema(ao.get('requestBody',{}),old),content_schema(bo.get('requestBody',{}),new))
            ar,br=ao.get('responses',{}),bo.get('responses',{})
            for s in sorted(set(ar)|set(br)):
                if s in ar and s not in br: add(out,oid,m,path,f'responses.{s}','RESPONSE_STATUS_REMOVED','BREAKING',f'Response {s} removed',True,False)
                elif s not in ar and s in br: add(out,oid,m,path,f'responses.{s}','RESPONSE_STATUS_ADDED','NON_BREAKING',f'Response {s} added',False,True)
                else: compare_schema(out,oid,m,path,f'responses.{s}.body',content_schema(ar[s],old),content_schema(br[s],new))
            if ao.get('security') != bo.get('security'):
                sev='BREAKING' if ao.get('security') in (None,[]) and bo.get('security') not in (None,[]) else 'CONDITIONALLY_BREAKING'
                add(out,oid,m,path,'security','SECURITY_REQUIREMENT_CHANGED',sev,'Security requirements changed',ao.get('security'),bo.get('security'))
    return old,new,out

def service_impacts(provider, operation_ids, max_depth=4):
    edges=load_json('dependencies.json')['dependencies']; result={}; q=deque()
    for e in edges:
        if e['provider']==provider and (not e.get('operation_id') or e.get('operation_id') in operation_ids):
            ev=[f"{e['consumer']} -> {provider}:{e.get('operation_id','unknown')}",f"source={e.get('evidence_source','catalog')}"]
            result[e['consumer']]={'service':e['consumer'],'impact_type':'DIRECT','depth':1,'confidence':e.get('confidence',0.8),'evidence':ev}; q.append((e['consumer'],1,ev,e.get('confidence',0.8)))
    rev={}
    for e in edges: rev.setdefault(e['provider'],[]).append(e)
    while q:
        cur,d,ev,conf=q.popleft()
        if d>=max_depth: continue
        for e in rev.get(cur,[]):
            c=e['consumer']
            if c==provider or c in result: continue
            nconf=round(min(conf,e.get('confidence',0.75))*0.95,2); nev=ev+[f'{c} -> {cur}',f"source={e.get('evidence_source','catalog')}"]
            result[c]={'service':c,'impact_type':'TRANSITIVE','depth':d+1,'confidence':nconf,'evidence':nev}; q.append((c,d+1,nev,nconf))
    return sorted(result.values(), key=lambda x:(x['depth'],x['service']))

def frontend_impacts(operation_ids):
    out=[]
    for s in load_json('frontend_mappings.json')['screens']:
        matches=sorted(operation_ids & set(s.get('api_operations',[])))
        if matches: out.append({'application':s['application'],'screen':s['screen'],'route':s.get('route'),'matched_operations':matches,'confidence':s.get('confidence',1.0),'evidence':[f'mapped operation: {m}' for m in matches]+[f"source={s.get('evidence_source','catalog')}"]})
    return out

def recommend_tests(operation_ids, services, screens, breaking_count):
    s_names={x['service'] for x in services}; screen_names={f"{x['application']} > {x['screen']}" for x in screens}; out=[]
    for t in load_json('test_catalog.json')['tests']:
        score=0; reasons=[]; m=operation_ids & set(t.get('covers_operations',[]))
        if m: score+=.45; reasons.append('covers changed operation(s): '+', '.join(sorted(m)))
        if t.get('service') in s_names: score+=.20; reasons.append('covers impacted service: '+t['service'])
        sm=screen_names & set(t.get('covers_screens',[]))
        if sm: score+=.20; reasons.append('covers impacted screen(s): '+', '.join(sorted(sm)))
        score+=min(t.get('business_criticality',1),5)/5*.10
        if 'critical' in t.get('tags',[]): score+=.05; reasons.append('critical business test')
        score=min(score+min(breaking_count*.05,.15),1.0)
        if score>=.25: out.append({'test_id':t['test_id'],'name':t['name'],'priority':'MANDATORY' if score>=.65 else 'RECOMMENDED','score':round(score,2),'estimated_duration_seconds':t.get('average_duration_seconds',60),'reasons':reasons})
    return sorted(out,key=lambda x:(x['priority']!='MANDATORY',-x['score'],x['test_id']))

def risk(changes, services, screens):
    b=[c for c in changes if c['severity']=='BREAKING']; cb=[c for c in changes if c['severity']=='CONDITIONALLY_BREAKING']; d=[s for s in services if s['impact_type']=='DIRECT']; tr=[s for s in services if s['impact_type']=='TRANSITIVE']; sec=[c for c in changes if 'SECURITY' in c['change_type']]
    score=min(min(len(b)*18,45)+min(len(cb)*7,14)+min(len(d)*8,24)+min(len(tr)*3,12)+min(len(screens)*7,14)+min(len(sec)*15,15)+(8 if changes and not services and not screens else 0),100)
    level='CRITICAL' if score>=75 else 'HIGH' if score>=50 else 'MEDIUM' if score>=25 else 'LOW'
    factors=[]
    if b:factors.append(f'{len(b)} breaking change(s)')
    if cb:factors.append(f'{len(cb)} conditionally breaking change(s)')
    if d:factors.append(f'{len(d)} direct consumer(s)')
    if tr:factors.append(f'{len(tr)} transitive consumer(s)')
    if screens:factors.append(f'{len(screens)} frontend screen(s)')
    if sec:factors.append('security requirement changed')
    return {'score':score,'level':level,'factors':factors}

def analyze(provider_service, old_openapi, new_openapi, release_notes=None):
    old,new,changes=diff(provider_service,old_openapi,new_openapi); ids={c['operation_id'] for c in changes}; services=service_impacts(provider_service,ids); screens=frontend_impacts(ids); tests=recommend_tests(ids,services,screens,sum(c['severity']=='BREAKING' for c in changes)); r=risk(changes,services,screens)
    payload=json.dumps({'service':provider_service,'old':old,'new':new},sort_keys=True,separators=(',',':')).encode(); aid='ANL-'+hashlib.sha256(payload).hexdigest()[:12].upper()
    unknowns=[]
    if changes and not services: unknowns.append('No known backend consumer found; this does not prove no impact.')
    if changes and not screens: unknowns.append('No known frontend mapping found.')
    report={'analysis_id':aid,'created_at':datetime.now(timezone.utc).isoformat(),'provider_service':provider_service,'release_notes':release_notes,'changes':changes,'impacted_services':services,'impacted_frontend_screens':screens,'recommended_regression_tests':tests,'risk':r,'unknowns':unknowns,'approval_required':r['level'] in {'HIGH','CRITICAL'}}
    report['summary']={'total_changes':len(changes),'breaking_changes':sum(c['severity']=='BREAKING' for c in changes),'direct_service_impacts':sum(s['impact_type']=='DIRECT' for s in services),'transitive_service_impacts':sum(s['impact_type']=='TRANSITIVE' for s in services),'frontend_screens':len(screens),'recommended_tests':len(tests)}
    CACHE[aid]=report; return {'analysis_id':aid,'summary':report['summary'],'risk':r,'approval_required':report['approval_required']}

def get_report(aid):
    if aid not in CACHE: raise ValueError(f'Unknown analysis_id {aid}; run analyze_api_change first')
    return deepcopy(CACHE[aid])
