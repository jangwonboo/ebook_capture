// Block-level save: untouched text stays byte-identical even though the editor rewrites Markdown.
// Run: node reader/tests/editor_merge.test.js
// The "baseline" strings mimic what Vditor 4.0.1 actually returned for untouched input
// (measured 2026-11-25 on three real books): blank lines tightened, pipe tables padded,
// table rules resized, "01." renumbered to "1.". Math, code and HTML tables come back unchanged.
const assert = require('assert');
const E = require('../editor.js');

const source = [
  '## 2장 시작',
  '',
  '첫 문단입니다. 끊긴 문장이',
  '',
  '- 항목 하나',
  '',
  '- 항목 둘',
  '',
  '| 이름 | 값 |',
  '| --- | --- |',
  '| a | $x_1$ |',
  '',
  '$$',
  'P(c|x) = \\frac{P(c)P(x|c)}{P(x)}',
  '$$',
  '',
  '```python',
  'def f(x):',
  '',
  '    return x',
  '```',
  '',
  '<table><tr><td colspan="2">병합</td></tr></table>',
  '',
  '01. 첫 장 1',
  '02. 둘째 장 5',
  '',
  '마지막 문단입니다.',
  '',
].join('\n');

const baseline = [
  '## 2장 시작',
  '',
  '첫 문단입니다. 끊긴 문장이',
  '',
  '- 항목 하나',
  '- 항목 둘',
  '',
  '| 이름 | 값    |',
  '| ---- | ----- |',
  '| a    | $x_1$ |',
  '',
  '$$',
  'P(c|x) = \\frac{P(c)P(x|c)}{P(x)}',
  '$$',
  '',
  '```python',
  'def f(x):',
  '',
  '    return x',
  '```',
  '',
  '<table><tr><td colspan="2">병합</td></tr></table>',
  '',
  '1. 첫 장 1',
  '2. 둘째 장 5',
  '',
  '마지막 문단입니다.',
  '',
].join('\n');

const replaceLine = (text, from, to) => { assert.ok(text.includes(from), from); return text.replace(from, to); };
const diffLines = (a, b) => {
  const x = a.split('\n'); const y = b.split('\n');
  let s = 0; while (s < x.length && s < y.length && x[s] === y[s]) s += 1;
  let ex = x.length; let ey = y.length; while (ex > s && ey > s && x[ex - 1] === y[ey - 1]) { ex -= 1; ey -= 1; }
  return { removed: x.slice(s, ex), added: y.slice(s, ey) };
};
let passed = 0;
const test = (name, fn) => { fn(); passed += 1; console.log('ok -', name); };

test('split/join is lossless', () => {
  assert.strictEqual(E.joinBlocks(E.splitBlocks(source)), source);
  const u = E.splitUnits(source);
  assert.strictEqual(u.lead + u.units.map((x) => x.text + x.sep).join(''), source);
});

test('untouched: source comes back byte for byte', () => {
  assert.strictEqual(E.preserveSource(source, baseline, baseline).text, source);
});

test('editing one paragraph changes only that line', () => {
  const current = replaceLine(baseline, '첫 문단입니다. 끊긴 문장이', '첫 문단입니다. 끊긴 문장이 이어집니다.');
  const res = E.preserveSource(source, baseline, current);
  assert.deepStrictEqual(diffLines(source, res.text), { removed: ['첫 문단입니다. 끊긴 문장이'], added: ['첫 문단입니다. 끊긴 문장이 이어집니다.'] });
  assert.strictEqual(res.changed, 1); assert.strictEqual(res.unmatched, 0);
});

test('a table cell edit keeps the other rows and the loose list as in the source', () => {
  const current = replaceLine(baseline, '| a    | $x_1$ |', '| a    | $x_2$ |');
  const res = E.preserveSource(source, baseline, current);
  const d = diffLines(source, res.text);
  assert.deepStrictEqual(d.removed, ['| a | $x_1$ |']);
  assert.deepStrictEqual(d.added, ['| a    | $x_2$ |']);
  assert.ok(res.text.includes('- 항목 하나\n\n- 항목 둘'), 'loose list spacing kept');
  assert.ok(res.text.includes('01. 첫 장 1'), 'list numbers kept');
});

test('deleting a paragraph removes just that paragraph', () => {
  const current = replaceLine(baseline, '마지막 문단입니다.\n', '');
  const res = E.preserveSource(source, baseline, current);
  const d = diffLines(source, res.text);
  assert.ok(d.removed.includes('마지막 문단입니다.')); assert.ok(d.added.every((l) => !l.trim()));
});

test('inserting a paragraph adds just that paragraph', () => {
  const current = replaceLine(baseline, '마지막 문단입니다.', '새 문단.\n\n마지막 문단입니다.');
  const res = E.preserveSource(source, baseline, current);
  const d = diffLines(source, res.text);
  assert.deepStrictEqual(d.added.filter((l) => l.trim()), ['새 문단.']);
  assert.deepStrictEqual(d.removed.filter((l) => l.trim()), []);
});

test('math, code with blank lines and HTML tables stay one unit each', () => {
  const kinds = E.splitUnits(source).units.map((u) => u.text.split('\n')[0]);
  assert.ok(kinds.includes('$$')); assert.ok(kinds.includes('```python'));
  assert.ok(E.splitUnits(source).units.some((u) => u.text.includes('def f(x):\n\n    return x')));
});

console.log(`${passed} passed`);
