export const MAX_LINES = 600;

function match(old, result, equal = (a, b) => a.trim() === b.trim()) {
  const n = old.length, m = result.length;
  const table = Array.from({length: n + 1}, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      table[i][j] = equal(old[i], result[j]) ? 1 + table[i + 1][j + 1] : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const mapped = new Map(), gaps = new Map();
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && equal(old[i], result[j])) {
      mapped.set(j++, i++);
    } else if (i < n && (j === m || table[i + 1][j] >= table[i][j + 1])) {
      if (!gaps.has(j)) gaps.set(j, []);
      gaps.get(j).push(i++);
    } else {
      mapped.set(j++, null);
    }
  }
  return {mapped, gaps};
}

export function align(a, b, result) {
  if ([a, b, result].some(lines => lines && lines.length > MAX_LINES)) throw new Error('This function is too large for the viewer. Use the GitHub source links.');
  const originals = match(a, b), paired = [], rows = [];
  for (let index = 0; index <= b.length; index++) {
    for (const ai of originals.gaps.get(index) ?? []) paired.push([ai, null]);
    if (index < b.length) paired.push([originals.mapped.get(index) ?? null, index]);
  }
  if (result === null) return paired.map(row => [...row, null]);
  const merged = match(paired, result, (row, line) => row.some((index, side) => index !== null && [a, b][side][index].trim() === line.trim()));
  for (let index = 0; index <= result.length; index++) {
    for (const original of merged.gaps.get(index) ?? []) rows.push([...paired[original], null]);
    if (index < result.length) {
      const original = merged.mapped.get(index);
      rows.push([...(original === null ? [null, null] : paired[original]), index]);
    }
  }
  return rows;
}

export function sourceUrl(source, raw = false) {
  const path = source.path.split('/').map(encodeURIComponent).join('/');
  return raw ? `https://raw.githubusercontent.com/${source.repository}/${source.revision}/${path}`
    : `https://github.com/${source.repository}/blob/${source.revision}/${path}#L${source.line}-L${source.end_line}`;
}

export function validSource(source) {
  return source && /^[\w.-]+\/[\w.-]+$/.test(source.repository) && /^[a-fA-F0-9]{40}$/.test(source.revision)
    && typeof source.path === 'string' && !!source.path && !source.path.startsWith('/') && !/[\\:]/.test(source.path)
    && !source.path.split('/').includes('..') && Number.isInteger(source.line) && source.line > 0
    && Number.isInteger(source.end_line) && source.end_line >= source.line && source.end_line - source.line < MAX_LINES;
}

export function decode(fragment) {
  if (!fragment.startsWith('#v1=') || fragment.length > 12000) throw new Error('Invalid or oversized comparison link. Use the GitHub source links.');
  const encoded = fragment.slice(4).replaceAll('-', '+').replaceAll('_', '/');
  const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
  const data = JSON.parse(new TextDecoder().decode(bytes));
  if (data.schema !== 1 || !validSource(data.evidence?.a) || !validSource(data.evidence?.b) || (data.result != null && !validSource(data.result))) {
    throw new Error('Unsupported comparison evidence. Use the GitHub source links.');
  }
  return data;
}
