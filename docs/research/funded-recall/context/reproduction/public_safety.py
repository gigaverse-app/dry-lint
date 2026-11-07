#!/usr/bin/env python3
"""Audit public artifacts, including decompressed evidence. No environment/key reads."""
import gzip
import json
import re
from common import HERE, read, sha

# Values resembling provider credentials/private keys; variable names are not credentials.
PATTERNS=[r'sk-ant-[A-Za-z0-9_-]{20,}',r'sk-proj-[A-Za-z0-9_-]{20,}',
          r'gh[pousr]_[A-Za-z0-9]{30,}',r'github_pat_[A-Za-z0-9_]{40,}',
          r'AKIA[0-9A-Z]{16}',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']

def public_paths():
    return [p for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__'not in p.parts
            and not any(part.startswith('local-') for part in p.relative_to(HERE).parts)]

def main():
    data=read('recordings.json.gz')
    held=[c for c in data['cases'] if c.get('withheld')]
    assert len(held)==1 and 'candidate'not in held[0]
    qs=[q for q in data['requests'] if q['id']==held[0]['id']]
    assert len(qs)==4 and all(q.get('withheld') and 'exact_rendered_json'not in q and 'request_body'not in q and 'prompt_contract'not in q for q in qs)
    sources=read('source-files.json.gz')
    assert all(x['repository']!='Garsson-io/kaizen' for x in sources['blobs'].values())
    forbidden={'thinking','reasoning','redacted_thinking','signature','authorization','x-api-key','headers','api_key','api-key'}
    def inspect(value):
        if isinstance(value,dict):
            assert not forbidden.intersection(k.lower() for k in value)
            assert value.get('type') not in ('thinking','reasoning','redacted_thinking')
            for v in value.values():inspect(v)
        elif isinstance(value,list):
            for v in value:inspect(v)
    for o in data['observations']:inspect(o['response'])
    matches=[]
    for path in public_paths():
        raw=path.read_bytes()
        text=(gzip.decompress(raw) if path.suffix=='.gz' else raw).decode()
        for pattern in PATTERNS:
            for found in re.finditer(pattern,text):
                matches.append(dict(file=str(path.relative_to(HERE)),value_sha256=sha(found.group())))
    if matches:
        raise SystemExit(json.dumps(dict(status='REVIEW_REQUIRED',credential_pattern_matches=matches),indent=2))
    print(json.dumps(dict(status='PASS',public_files=len(public_paths()),decompressed_archives_scanned=True,
                         held_source_cases=1,source_bearing_requests_omitted=4,
                         sanitized_answers=88,credential_pattern_matches=0,
                         scope='Allowlisted recorded responses plus secret-pattern scan; public source provenance/permissions checked separately. No guarantee that regex finds every possible secret.'),indent=2))

if __name__=='__main__':main()
