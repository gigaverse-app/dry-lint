#!/usr/bin/env python3
"""Integrity, local Markdown links, and secret/private-content scan, including gzip payloads."""
import gzip
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote
HERE=Path(__file__).resolve().parent
PATTERNS=[r'sk-ant-[A-Za-z0-9_-]{20,}',r'sk-proj-[A-Za-z0-9_-]{20,}',r'gh[pousr]_[A-Za-z0-9]{30,}',r'github_pat_[A-Za-z0-9_]{40,}',r'AKIA[0-9A-Z]{16}',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'gigaverse-(?:ai|backend)/']
def main():
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    failures=[];archives=0;links=0
    for p in files:
        raw=p.read_bytes()
        if p.suffix=='.gz':raw=gzip.decompress(raw);archives+=1
        text=raw.decode()
        for pattern in PATTERNS:
            if re.search(pattern,text):failures.append({'path':str(p.relative_to(HERE)),'reason':'credential/private-repository pattern; value suppressed'})
        if p.suffix=='.md':
            for link in re.findall(r'\]\(([^)]+)\)',text):
                if '://' in link or link.startswith('#'):continue
                target=unquote(link.split('#')[0])
                if target and not (p.parent/target).exists():failures.append({'path':str(p.relative_to(HERE)),'reason':'missing local link: '+target})
                links+=1
    hashes=HERE/'SHA256SUMS'
    if hashes.exists():
        for line in hashes.read_text().splitlines():
            expected,path=line.split('  ',1)
            if hashlib.sha256((HERE/path).read_bytes()).hexdigest()!=expected:failures.append({'path':path,'reason':'hash mismatch'})
    records=json.loads((HERE/'data/recordings.json').read_text())
    # No opaque raw transport strings are published. Response bodies use explicit observable allowlists.
    def inspect(x):
        if isinstance(x,dict):
            if x.get('type') in ('thinking','reasoning','redacted_thinking'):raise ValueError('Hidden content block')
            if any(k in x for k in ['signature','authorization','x-api-key']):raise ValueError('Opaque signature/auth field')
            for v in x.values():inspect(v)
        elif isinstance(x,list):
            for v in x:inspect(v)
    inspect(records)
    if failures:raise SystemExit(json.dumps({'status':'FAIL','failures':failures},indent=2))
    print(json.dumps({'status':'PASS','files':len(files),'decompressed_archives':archives,'local_markdown_links':links,'credential_pattern_matches':0,'limits':'Allowlisted OSS provenance and structured response sanitization plus pattern scan; regex is not a universal secret detector.'},indent=2))
if __name__=='__main__':main()
