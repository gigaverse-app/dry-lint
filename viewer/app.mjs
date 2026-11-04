import {align, decode, sourceUrl} from './diff.mjs';

const byId = id => document.getElementById(id);
const expanded = new Set();
let sources, code, rows;

function fillHead(head, source) {
  const anchor = head.querySelector('a');
  if (source) {
    head.querySelector('.filename').textContent = source.path.split('/').at(-1);
    head.querySelector('.symbol').textContent = source.owner ? `${source.owner}.${source.name}` : source.name;
    head.querySelector('.path').textContent = `${source.repository} / ${source.path}`;
    head.querySelector('small').textContent = `${source.revision.slice(0, 7)} · lines ${source.line}–${source.end_line}`;
    anchor.setAttribute('aria-label', `Open ${source.path}, ${source.name} at ${source.revision.slice(0, 7)} on GitHub`);
    anchor.href = sourceUrl(source); anchor.target = '_blank'; anchor.rel = 'noopener noreferrer';
  } else {
    head.querySelector('.role').textContent = 'Result unavailable';
    head.querySelector('.filename').textContent = 'No remaining function identified';
    head.querySelector('.path').textContent = 'Use the full GitHub diff to follow moves, deletions, or extracted helpers.';
    anchor.hidden = true;
  }
}

function setupHelpers(snapshots, bodies) {
  const select = byId('after-select');
  const choose = index => {
    sources[2] = snapshots[index]; code[2] = bodies[index];
    const head = document.querySelector('#comparison > .head.result');
    fillHead(head, sources[2]);
    head.querySelector('.role').textContent = index === 2 ? 'Remaining function' : 'Called helper';
    byId('after-caption').textContent = index === 2 ? 'At the reviewed commit' : 'Called by the remaining function';
    select.value = String(index);
    expanded.clear(); rows = align(...code); render();
  };
  snapshots.slice(2).forEach((source, offset) => {
    const index = offset + 2;
    const label = `${offset ? 'Called helper' : 'Remaining function'}: ${source.owner ? source.owner + '.' : ''}${source.name}`;
    select.add(new Option(label, String(index)));
    const details = document.createElement('details'), summary = document.createElement('summary');
    details.className = 'implementation'; details.open = offset === 0;
    summary.textContent = `${source.path.split('/').at(-1)} · ${label}`;
    const head = document.querySelector('#comparison > .head.result').cloneNode(true);
    fillHead(head, source); head.querySelector('.role').textContent = offset ? 'Called helper' : 'Remaining function';
    const pre = document.createElement('pre'), text = document.createElement('code');
    text.textContent = bodies[index].join('\n'); pre.append(text);
    const button = document.createElement('button'); button.type = 'button';
    button.textContent = 'Compare this function with the originals';
    button.addEventListener('click', () => {choose(index); byId('after-choice').scrollIntoView({block:'center'});});
    details.append(summary, head, pre, button); byId('implementations').append(details);
  });
  select.addEventListener('change', () => choose(Number(select.value)));
  byId('after-choice').hidden = false; byId('implementation').hidden = false;
  choose(3);
}

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
  const helpers = data.schema === 2 ? data.helpers : [];
  const snapshots = [...sources, ...helpers];
  byId('review').hidden = false;
  document.querySelectorAll('#comparison > .head').forEach((head, i) => fillHead(head, sources[i]));
  const verdict = evidence.verdict;
  const outcomes = {'kept-out':'No longer reported',open:'Still tangled',dismissed:'Dismissed',
    'below threshold': verdict?.label === 'separate' ? 'Not reported: judged separate' : 'Not reported: low confidence',
    separate:'Not reported: judged separate',unjudged:'Not judged',deferred:'Judgment deferred'};
  byId('outcome').textContent = outcomes[data.state] ?? 'Not recorded';
  byId('verdict').textContent = verdict ? verdict.label : 'Not judged';
  byId('confidence').textContent = verdict ? Number(verdict.score).toFixed(2) : 'Not recorded';
  byId('reason').textContent = verdict?.why || 'No reason recorded.';
  byId('judge').textContent = verdict ? `${verdict.judge} · ${evidence.cached ? 'reused verdict' : 'recorded verdict'}` : 'None';
  byId('version').textContent = verdict?.judge_version || 'Not recorded';
  byId('similarity').textContent = Number(evidence.similarity).toFixed(2);
  byId('mapping').textContent = data.result
    ? 'One of the original functions remains at the reviewed commit. It is shown on the right. This alone does not prove that both originals were consolidated; review the full GitHub diff to follow the shared implementation.'
    : 'No single remaining function could be identified. The pair may have been moved, deleted, or judged differently. Review the full GitHub diff to see what happened.';
  if (helpers.length) {
    byId('mapping').textContent = 'The After column starts with a helper called by the remaining function. Switch between the helper and its caller using the selector above. The call site is also shown below; this is a static reference, not a new consolidation judgment.';
  } else if (data.result) {
    byId('mapping').textContent += data.schema === 1 ? ' This older link has no recorded helper references.'
      : ' No direct same-file Python helper was resolved. Imported, dynamic and other-language calls are not followed.';
  }
  if (!data.result) {
    byId('title').textContent = 'Compare the original functions';
    byId('after-caption').textContent = 'No identified result';
  }
  if (typeof data.diff === 'string' && /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/compare\/[a-fA-F0-9]{40}\.\.\.[a-fA-F0-9]{40}$/.test(data.diff)) {
    byId('diff').href = data.diff; byId('diff').hidden = false;
  }
  byId('status').textContent = 'Checking public source access…';
  for (const repository of new Set(snapshots.filter(Boolean).map(source => source.repository))) {
    const response = await fetch(`https://api.github.com/repos/${repository}`, {credentials: 'omit'});
    if (!response.ok) throw new Error('Public repository access could not be verified. Use the GitHub links above.');
    const metadata = await response.json();
    if (metadata.visibility !== 'public' || metadata.private !== false) throw new Error('This viewer only loads public repositories. Use the GitHub links above.');
  }
  const files = new Map();
  const bodies = await Promise.all(snapshots.map(async source => {
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
  code = bodies.slice(0, 3);
  if (helpers.length) setupHelpers(snapshots, bodies);
  else {rows = align(...code); render();}
  byId('status').textContent = helpers.length
    ? 'Compare the originals with the called helper, then inspect the remaining function and its call below.' : data.result
    ? 'Read left to right: the two original functions, then the function that remains after the change.'
    : 'The two original functions are shown below. A resulting implementation could not be identified.';
}

byId('changes').addEventListener('change', () => {if (rows) render();});
byId('wrap').addEventListener('change', event => byId('comparison').classList.toggle('no-wrap', !event.target.checked));
byId('copy').addEventListener('click', async () => {
  try {await navigator.clipboard.writeText(location.href); byId('notice').textContent = 'View link copied';}
  catch {byId('notice').textContent = 'Copy the URL from your address bar';}
});
load().catch(error => {byId('error').hidden = false; byId('error').textContent = error.message; byId('status').textContent = 'Comparison unavailable';});
