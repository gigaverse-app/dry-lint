"""Human-readable case inspection; all content comes from frozen files."""
import json
from common import POS, canonical, read, verdict


def show(args):
    data=read('recordings.json.gz')
    case=next(c for c in data['cases'] if c['id']==args.case and (args.round is None or c['round']==args.round))
    requests=[q for q in data['requests'] if q['id']==case['id'] and q['round']==case['round'] and q['kind']==args.kind]
    q=next(q for q in requests if q['variant'].endswith('baseline')==(args.arm=='baseline'))
    o=next(o for o in data['observations'] if o['request_id']==q['request_id'])
    v,uncertain=verdict(q,o['response'])
    print('# '+case['id']+' / '+case['round']+' / '+q['variant'])
    print('Source: https://github.com/'+case['repository']+'/tree/'+case['revision'])
    print('Source assessment: '+str(case['assessment']['source_label'])+' (scoped operation; not whole-function equivalence)')
    print('Observation: '+('historical baseline, noncontemporaneous' if q['historical'] else 'fresh study call'))
    print('Request ID: '+q['request_id']+'\nWire SHA-256: '+q['wire_sha256'])
    print('Recorded result: '+v['label']+' '+str(v['score'])+'; emitted at 0.8: '+str(not uncertain and v['label']in POS and v['score']>=.8))
    if case.get('withheld'):
        print('\nSource-bearing Candidate, prompt and answer prose withheld. Run hydrate.py locally; numeric answer and usage follow.')
        print(json.dumps(o['response'],indent=2))
        return
    sides=('new','existing') if args.side=='both' else (args.side,)
    if args.part in ('all','original','git'):
        source=read('source-files.json.gz')
        for side in sides:
            f=case['candidate'][side]
            proof=next(p for p in case['source_proofs'] if p['side']==side)
            print('\n## '+side.upper()+': '+f['path']+':'+str(f['line'])+'-'+str(f['end_line']))
            print('Full pinned file SHA-256: '+proof['file_sha256']+'; native body SHA-256: '+proof['body_sha256'])
            print('Native extraction proof: '+canonical(case['native_extraction_proofs'][side]))
            full=source['blobs'][proof['file_sha256']]['text']
            if args.part=='git':
                print('Full raw Git file (including adjacent documentation):\n~~~\n'+full+'\n~~~')
            else:
                print('Full native Candidate body/signature (unclipped):\n~~~\n'+f['code']+'\n~~~')
                print('Native context/documentation (unclipped):\n~~~\n'+f['context']+'\n~~~')
                print('Native declaration metadata: '+json.dumps(f['declaration']))
                span='\n'.join(full.splitlines()[f['line']-1:f['end_line']])
                print('Raw Git line span (not asserted string-equal to native extraction):\n~~~\n'+span+'\n~~~')
    if args.part in ('all','input'):
        context=next(c for c in data['contexts'][case['round']] if c['id']==case['id'])
        print('\n## Selected provider input')
        for side in sides:
            if q['kind']=='jev':
                f=q['request_body']['state'][side+'_function']
                print(side.upper()+'; code_truncated='+str(f['code_truncated'])+'\n~~~\n'+f['code']+'\n~~~')
                print('Source context:\n~~~\n'+f['source_context']+'\n~~~')
            elif q['variant'].endswith('body_coverage'):
                c=context['coverage'][side]
                print(side.upper()+'; complete='+str(c['complete'])+'\n~~~\n'+c['code']+'\n~~~')
            else:
                print(side.upper()+': full native body above / inspect --part original')
            if case['round']=='R2' and q['variant'].endswith('body_coverage'):
                print('Source-to-rendered character maps:\n'+json.dumps(context['coverage'][side]['segments'],indent=2))
    if args.part in ('all','prompt'):
        print('\n## Exact provider settings')
        print('POST '+q['url']+'; model='+q['model']+'; max_tokens='+str(q['max_output_tokens']))
        print('No tools; no temperature or sampling fields set; no retries or fallback. Full stored API object: reproduce.py inspect --part wire.')
        if q['kind']=='claude':
            print('\n## Exact user prompt\n'+q['request_body']['messages'][0]['content'])
        else:
            print('\n## Exact Jev questions (state is shown under selected input)')
            for name,question in q['request_body']['questions'].items():
                print('\n### '+name+'\n'+json.dumps(question,indent=2,ensure_ascii=False))
    if args.part in ('all','answer'):
        print('\n## Recorded provider answer')
        if q['kind']=='claude':
            print(''.join(b['text'] for b in o['response']['content']))
        else:
            print(json.dumps(o['response']['answers'],indent=2))
            print('\nMechanically generated Jev verdict explanation (NOT provider prose):\n'+v['why'])
        print('\nUsage: '+json.dumps(o['response']['usage']))
        print('Study-rate cost USD: '+str(o['physical_cost_usd'])+'; API seconds: '+str(o['seconds']))
