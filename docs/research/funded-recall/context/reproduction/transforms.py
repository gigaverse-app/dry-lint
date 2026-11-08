"""Exact frozen windows() implementation; Apache-2.0, Gigaverse. See implementation archive."""
from common import sha

def windows(code, first_line):
    if len(code)<=8000:
        return dict(code=code,complete=True,original_sha256=sha(code),rendered_sha256=sha(code),segments=[dict(
            original_start_char=0,original_end_char_exclusive=len(code),original_start_line=first_line,
            original_end_line=first_line+code.count('\n'),rendered_start_char=0,rendered_end_char_exclusive=len(code))])
    chunks=[];mapping=[];used=[];rendered=''
    for fraction in (0,1/3,2/3,1):
        raw_start=round((len(code)-1600)*fraction)
        start=code.rfind('\n',0,raw_start)+1
        # Avoid crossing a distant preceding line on minified input.
        if raw_start-start>200:start=raw_start
        limit=min(len(code),start+1600)
        end=code.rfind('\n',start,limit)
        if end<=start:end=limit
        if fraction==1:
            end=len(code);start=max(0,end-1600)
            n=code.find('\n',start,end)
            if 0<=n<start+200:start=n+1
        if any(max(start,a)<min(end,b)for a,b in used):
            raise ValueError('overlapping_coverage_windows')
        used.append((start,end))
        marker='\n/* PARTIAL SOURCE WINDOW chars '+str(start)+':'+str(end)+' of '+str(len(code))+'; intervening code omitted */\n'
        rendered+=marker;offset=len(rendered);rendered+=code[start:end]
        mapping.append(dict(original_start_char=start,original_end_char_exclusive=end,
            original_start_line=first_line+code[:start].count('\n'),original_end_line=first_line+code[:end].count('\n'),
            original_start_column=start-(code.rfind('\n',0,start)+1),
            rendered_start_char=offset,rendered_end_char_exclusive=len(rendered),segment_sha256=sha(code[start:end])))
    assert len(rendered)<=7200
    return dict(code=rendered,complete=False,original_sha256=sha(code),rendered_sha256=sha(rendered),segments=mapping,
        omission='Partial disjoint source excerpts, never a full native function; missing intervals remain unknown.')
