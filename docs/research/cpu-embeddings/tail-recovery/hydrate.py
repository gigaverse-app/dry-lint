"""Authorized local hydration only. Never contacts a provider or fetches a repository."""
from pathlib import Path
import argparse, hashlib, json

HOME=Path(__file__).resolve().parent
def sha(raw):return hashlib.sha256(raw).hexdigest()
def rows(path):return [json.loads(line) for line in path.read_text().splitlines() if line]

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lab-root',type=Path,required=True,help='Authorized improve-cpu-retrieval/.lab-results')
    parser.add_argument('--judge-root',type=Path,required=True,help='Authorized judge-improvement-wave/.lab-results')
    parser.add_argument('--case',required=True)
    parser.add_argument('--output-dir',type=Path,required=True,help='Private output outside this public package')
    args=parser.parse_args();out=args.output_dir.resolve()
    if out==HOME or HOME in out.parents:parser.error('Private hydration output must be outside the public package')
    contract=next(r for r in rows(HOME/'held-hydration.jsonl') if r['id']==args.case)
    packet=next(r for r in rows(args.lab_root/contract['local_queue_locator']) if r['id']==args.case)
    assert packet['revision']==contract['revision'] and packet['repository']==contract['repository']
    assert sha(json.dumps(packet['candidate'],sort_keys=True).encode())==contract['candidate_sha256']
    assert [p['body_sha256'] for p in packet['source_proofs']]==contract['body_sha256']
    assert [p['file_sha256'] for p in packet['source_proofs']]==contract['file_sha256']
    assert packet['background_proof']['sha256']==contract['background_sha256']
    selection=next(r for r in rows(args.lab_root/contract['local_selection_locator']) if r['id']==args.case)
    intake=args.judge_root/contract['central_intake_locator']
    feedback=next(r for r in rows(intake/'method-feedback.jsonl') if r['id']==args.case)
    requests=[r for r in json.loads((intake/'requests.json').read_text()) if r['case_id']==args.case]
    assert sorted(r['request_key'] for r in requests)==sorted(contract['request_keys'])
    observations=[]
    for item in feedback['observations']:
        path=args.judge_root/'physical-account/observations'/(item['request_key']+'.json')
        assert sha(path.read_bytes())==item['provenance']['sha256']
        observations.append(json.loads(path.read_text()))
    # Full exact source/context, recorded questions/answers and admissions stay private.
    directory=(args.lab_root/contract['local_queue_locator']).parent
    campaign=selection['source_selection']['background']+':'+selection['ranks']['query']
    ledgers={name:[r for r in rows(directory/name) if r['campaign']==campaign] for name in ['admissions.jsonl','original-standalone-ledger.jsonl']}
    out.mkdir(parents=True,exist_ok=True)
    destination=out/(args.case+'-PRIVATE.json')
    if destination.exists():parser.error('Refusing to replace an existing hydrated record')
    destination.write_text(json.dumps({'contract':contract,'packet':packet,'selection':selection,'requests':requests,'observations':observations,'ledgers':ledgers},indent=2)+'\n')
    print('Hydrated exact authorized private record:',destination)
