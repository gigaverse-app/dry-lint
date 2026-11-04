import {align, decode, sourceUrl} from './diff.mjs';

const byId = id => document.getElementById(id);
const expanded = new Set();
let sources, code, rows;

function unchanged(row) {
  const active = sources.map((source, i) => source ? i : null).filter(i => i !== null);
  return active.every(i => row[i] !== null) && new Set(active.map(i => code[i][row[i]].trim())).size === 1;
}

function render() {
  const fragment = document.createDocumentFragment();
  let visible = 0;
  function append(row) {
    const element = document.createElement('div');
    element.className = 'row';
    row.forEach((index, side) => {
      const cell = document.createElement('div');
      cell.className = 'cell' + (index === null ? ' empty' : unchanged(row) ? '' : side === 2 ? ' added' : ' old');
      const number = document.createElement('span');
      number.className = 'number';
      number.textContent = index === null ? '' : String(sources[side].line + index);
      const text = document.createElement('code');
      text.textContent = index === null ? ' ' : code[side][index] || ' ';
      cell.append(number, text); element.append(cell);
    });
    fragment.append(element); visible++;
  }
  for (let start = 0; start < rows.length;) {
    let end = start;
    while (end < rows.length && unchanged(rows[end])) end++;
    if (byId('changes').checked && end - start > 6 && !expanded.has(start)) {
      rows.slice(start, start + 2).forEach(append);
      const fold = document.createElement('div'), button = document.createElement('button');
      fold.className = 'fold'; button.type = 'button';
      button.textContent = `Show ${end - start - 4} unchanged lines`;
      const key = start;
      button.addEventListener('click', () => {expanded.add(key); render();});
      fold.append(button); fragment.append(fold);
      rows.slice(end - 2, end).forEach(append); start = end;
    } else if (end > start) {
      rows.slice(start, end).forEach(append); start = end;
    } else {append(rows[start++]);}
  }
  byId('rows').replaceChildren(fragment);
  byId('count').textContent = `${visible} / ${rows.length} aligned rows`;
}

async function load() {
  if (!location.hash) return;
  const data = decode(location.hash), evidence = data.evidence;
  sources = [evidence.a, evidence.b, data.result];
  byId('review').hidden = false;
  document.querySelectorAll('.head').forEach((head, i) => {
    const source = sources[i], anchor = head.querySelector('a');
    if (source) {
      head.querySelector('strong').textContent = source.name;
      head.querySelector('small').textContent = `${source.path} · ${source.revision.slice(0, 7)}`;
      anchor.href = sourceUrl(source); anchor.target = '_blank'; anchor.rel = 'noopener noreferrer';
    } else {
      head.querySelector('strong').textContent = 'Consolidation not established';
      head.querySelector('small').textContent = 'No result was inferred'; anchor.hidden = true;
    }
  });
  const verdict = evidence.verdict;
  byId('verdict').textContent = verdict ? `${verdict.label} · ${Number(verdict.score).toFixed(2)}` : 'Not judged';
  byId('reason').textContent = verdict?.why || 'No reason recorded.';
  byId('judge').textContent = verdict ? `${verdict.judge} · ${evidence.cached ? 'reused verdict' : 'recorded verdict'}` : 'None';
  byId('version').textContent = verdict?.judge_version || 'Not recorded';
  byId('similarity').textContent = Number(evidence.similarity).toFixed(2);
  byId('mapping').textContent = data.result
    ? 'Exactly one original symbol remains at the reviewed commit. The third column shows that implementation. Verify the caller changes and any extracted helpers before concluding that A and B were fully consolidated.'
    : 'There is no uniquely identified remaining implementation. A pair can stop being reported because of deletion, a move, or a changed judgment. The viewer does not guess a consolidated result.';
  if (typeof data.diff === 'string' && /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/compare\/[a-fA-F0-9]{40}\.\.\.[a-fA-F0-9]{40}$/.test(data.diff)) {
    byId('diff').href = data.diff; byId('diff').hidden = false;
  }
  byId('status').textContent = 'Checking public source access…';
  for (const repository of new Set(sources.filter(Boolean).map(source => source.repository))) {
    const response = await fetch(`https://api.github.com/repos/${repository}`, {credentials: 'omit'});
    if (!response.ok) throw new Error('Public repository access could not be verified. Use the GitHub links above.');
    const metadata = await response.json();
    if (metadata.visibility !== 'public' || metadata.private !== false) throw new Error('This viewer only loads public repositories. Use the GitHub links above.');
  }
  const files = new Map();
  code = await Promise.all(sources.map(async source => {
    if (!source) return null;
    const url = sourceUrl(source, true);
    if (!files.has(url)) files.set(url, fetch(url, {credentials: 'omit'}).then(async response => {
      if (!response.ok) throw new Error('A source snapshot is unavailable. Use the GitHub links above.');
      const text = await response.text();
      if (text.length > 2_000_000) throw new Error('Source file exceeds the viewer limit. Use the GitHub links above.');
      const lines = text.replaceAll('\r\n', '\n').split('\n');
      if (lines.at(-1) === '') lines.pop();
      return lines;
    }));
    const lines = await files.get(url);
    if (source.end_line > lines.length) throw new Error('Source coordinates do not match the snapshot. Use the GitHub links above.');
    return lines.slice(source.line - 1, source.end_line);
  }));
  rows = align(...code); render();
  byId('status').textContent = data.result ? 'Compare both originals with the remaining implementation.' : 'Compare the original pair and its recorded judgment.';
}

byId('changes').addEventListener('change', () => {if (rows) render();});
byId('wrap').addEventListener('change', event => byId('comparison').classList.toggle('no-wrap', !event.target.checked));
byId('copy').addEventListener('click', async () => {
  try {await navigator.clipboard.writeText(location.href); byId('notice').textContent = 'View link copied';}
  catch {byId('notice').textContent = 'Copy the URL from your address bar';}
});
load().catch(error => {byId('error').hidden = false; byId('error').textContent = error.message; byId('status').textContent = 'Comparison unavailable';});
