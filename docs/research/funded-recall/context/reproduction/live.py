#!/usr/bin/env python3
"""Exact payload playback. Dry-run by default; only --execute reads env keys or opens network."""
import argparse
import json
import math
import os
from pathlib import Path
from common import HERE, canonical, cost, digest, read, sha
from build_export import response as sanitize_response

URLS={'jev':'https://api.typesafe.ai/v1/systemone','claude':'https://api.anthropic.com/v1/messages'}
KEYS={'jev':'TYPESAFE_AI_API_KEY','claude':'ANTHROPIC_API_KEY'}


def select(args):
    data=read('recordings.json.gz')
    qs=[q for q in data['requests'] if (args.round=='all' or q['round']==args.round)
        and (not args.case or q['id']==args.case)
        and (args.include_historical or not q['historical'])]
    if args.hydrated:
        replacements={q['request_id']:q for q in json.loads(args.hydrated.read_text())}
        for i,q in enumerate(qs):
            if q.get('withheld'):
                replacement=replacements[q['request_id']]
                if sha(replacement['exact_rendered_json'])!=q['wire_sha256']:
                    raise ValueError('Hydrated request hash mismatch')
                qs[i]=dict(q,request_body=replacement['request_body'],exact_rendered_json=replacement['exact_rendered_json'],withheld=False)
    return qs


def plan(args, qs):
    if not qs:raise ValueError('No matching requests')
    if not 1<=args.max_requests<=88 or not math.isfinite(args.budget_usd) or args.budget_usd<=0:
        raise ValueError('Finite positive budget and 1..88 requests required')
    if not 1024<=args.max_response_bytes<=1048576:raise ValueError('Response byte bound must be 1024..1048576')
    reserved=0
    for q in qs:
        if q['url']!=URLS[q['kind']]:raise ValueError('Unexpected endpoint')
        if q.get('withheld'):continue
        wire=q['exact_rendered_json']
        if sha(wire)!=q['wire_sha256'] or json.loads(wire)!=q['request_body']:
            raise ValueError('Frozen payload mismatch')
        a,b=q['reservation_rates_per_million']
        reserved+=((len(wire.encode())+1024)*a+(q['max_output_tokens']or 0)*b)/1e6
    blocked=[]
    if any(q.get('withheld') for q in qs):blocked.append('source hydration required')
    if len(qs)>args.max_requests:blocked.append('request cap')
    if reserved>args.budget_usd:blocked.append('reservation exceeds frozen-rate budget')
    return dict(mode='execute' if args.execute else 'dry-run',requests=len(qs),maximum_reservation_usd=round(reserved,12),
                budget_usd=args.budget_usd,blocked=blocked,concurrency=1,retries=0,
                max_response_bytes=args.max_response_bytes,claude_output_tokens=1024,
                jev_output_cap='No API token cap in frozen typed-answer request; client response bytes are bounded.',
                prices='Frozen study rates; not an invoice guarantee. Set a provider account spending limit independently.',
                provider_calls=0,request_ids=[q['request_id'] for q in qs])


def execute(args, qs):
    if args.out is None or args.out.exists():raise ValueError('--out must name a new output directory')
    if args.out.resolve()==HERE or HERE in args.out.resolve().parents and not args.out.name.startswith('local-'):
        raise ValueError('Outputs inside kit must use a new local-* directory')
    credentials={kind:os.environ.get(KEYS[kind]) for kind in {q['kind'] for q in qs}}
    if not all(credentials.values()):raise ValueError('Missing user environment key(s): '+', '.join(KEYS[k] for k,v in credentials.items() if not v))
    import time
    import urllib.request
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*unused,**kwargs):
            raise ValueError('Redirect refused')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    args.out.mkdir(parents=True,exist_ok=False)
    spent=0
    for index,q in enumerate(qs):
        intent=dict(request_id=q['request_id'],wire_sha256=q['wire_sha256'],reservation_usd=q['reservation_usd'],
                    status='intent_no_retry',study_historical=q['historical'])
        (args.out/(str(index).zfill(3)+'-intent.json')).write_text(canonical(intent)+'\n')
        headers={'Content-Type':'application/json'}
        if q['kind']=='jev':headers['Authorization']='Bearer '+credentials['jev']
        else:headers.update({'x-api-key':credentials['claude'],'anthropic-version':'2023-06-01'})
        start=time.monotonic();record=dict(request_id=q['request_id'],sent_wire_sha256=q['wire_sha256'])
        try:
            request=urllib.request.Request(q['url'],data=q['exact_rendered_json'].encode(),headers=headers,method='POST')
            with opener.open(request,timeout=90) as returned:
                raw=returned.read(args.max_response_bytes+1)
                if len(raw)>args.max_response_bytes:raise ValueError('Response byte limit exceeded')
                response=sanitize_response(json.loads(raw))
                amount=cost(q,response)
                record.update(response=response,sanitized_response_sha256=digest(response),cost_usd=amount,
                              status='returned',seconds=time.monotonic()-start)
                spent+=amount
                if amount>q['reservation_usd']+1e-10:record['status']='reservation_overrun_stop'
        except Exception as exc:
            record.update(status='unknown_stop',error_class=type(exc).__name__,seconds=time.monotonic()-start)
        (args.out/(str(index).zfill(3)+'-answer.json')).write_text(canonical(record)+'\n')
        if record['status']!='returned':break
    print(canonical(dict(status='finished',observed_new_usd=round(spent,12),out=str(args.out),
                         note='New observations only; frozen recordings were not changed. Unknown attempts are never retried.')))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--round',choices=['R1','R2','all'],default='R2')
    p.add_argument('--case')
    p.add_argument('--include-historical',action='store_true',help='Replay old control baselines as NEW calls')
    p.add_argument('--hydrated',type=Path)
    p.add_argument('--max-requests',type=int,default=4)
    p.add_argument('--budget-usd',type=float,default=.10)
    p.add_argument('--max-response-bytes',type=int,default=65536)
    p.add_argument('--out',type=Path)
    p.add_argument('--execute',action='store_true')
    args=p.parse_args();qs=select(args);receipt=plan(args,qs)
    print(json.dumps(receipt,indent=2))
    if args.execute:
        if receipt['blocked']:raise SystemExit('Blocked: '+', '.join(receipt['blocked']))
        execute(args,qs)

if __name__=='__main__':main()
