import assert from 'node:assert/strict';
import test from 'node:test';
import {align, decode, validSource, sourceUrl, MAX_LINES} from './diff.mjs';

test('alignment preserves every line exactly once and in order', () => {
  for (let seed = 0; seed < 80; seed++) {
    const a = Array.from({length: seed % 19}, (_, i) => String((i * 7 + seed) % 11));
    const b = Array.from({length: seed % 23}, (_, i) => String((i * 5 + seed) % 11));
    const c = seed % 2 ? null : Array.from({length: seed % 29}, (_, i) => String((i * 3 + seed) % 11));
    const rows = align(a, b, c);
    [a, b, c].forEach((source, side) => assert.deepEqual(rows.map(row => row[side]).filter(i => i !== null), (source ?? []).map((_, i) => i)));
  }
});

test('unchanged lines align across all three sources', () => {
  assert.deepEqual(align([' a', 'b '], ['a', 'b'], ['a', ' b']), [[0,0,0],[1,1,1]]);
  assert.throws(() => align(Array(MAX_LINES + 1).fill('a'), [], []), /too large/);
});

test('shared original code stays aligned when consolidation replaces it with a helper call', () => {
  const a = ['def a(value):', '  if invalid(value):', '    raise Error()', '  return value'];
  const b = ['def b(value):', '  if invalid(value):', '    raise Error()', '  return value.strip()'];
  const result = ['def b(value):', '  return validated(value).strip()'];
  const rows = align(a, b, result);
  assert.ok(rows.some(row => row[0] === 1 && row[1] === 1));
  assert.ok(rows.some(row => row[0] === 2 && row[1] === 2));
});

const source = {repository:'acme/repo',revision:'a'.repeat(40),path:'src/my file.ts',name:'render',line:2,end_line:3};

test('source URLs only address validated immutable repository paths', () => {
  assert.ok(validSource(source));
  for (const patch of [{path:'../secret'}, {path:'/root'}, {path:'C:\\foo'}, {revision:'main'}, {repository:'evil.example/x/y'}, {line:0}, {end_line:1}]) {
    assert.ok(!validSource({...source,...patch}));
  }
  assert.ok(sourceUrl(source).includes('/src/my%20file.ts#L2-L3'));
  assert.ok(sourceUrl(source, true).startsWith('https://raw.githubusercontent.com/acme/repo/'));
});

test('versioned links preserve Unicode judgments and reject invalid envelopes', () => {
  const data = {schema:1,evidence:{a:source,b:source,verdict:{why:'שלום 🌱 <script>text only</script>'}},result:null};
  const link = '#v1=' + Buffer.from(JSON.stringify(data)).toString('base64url');
  assert.deepEqual(decode(link), data);
  for (const fragment of ['#old=x', '#v1='+'x'.repeat(12000), '#v1='+Buffer.from('{"schema":3}').toString('base64url')]) {
    assert.throws(() => decode(fragment));
  }
});

test('helper references are bounded to the result file and commit; old links still decode', () => {
  const data = {schema:2,evidence:{a:source,b:source},result:source,helpers:[{...source,name:'shared'}]};
  const fragment = data => '#v2=' + Buffer.from(JSON.stringify(data)).toString('base64url');
  assert.deepEqual(decode(fragment(data)), data);
  for (const patch of [{revision:'b'.repeat(40)}, {repository:'private/repo'}, {path:'other.ts'}, {end_line:900}]) {
    assert.throws(() => decode(fragment({...data,helpers:[{...source,...patch}]})));
  }
  for (const patch of [{result:null}, {helpers:Array(6).fill(source)}, {helpers:null}]) {
    assert.throws(() => decode(fragment({...data,...patch})));
  }
  assert.throws(() => decode(fragment({...data,schema:1})));
});
