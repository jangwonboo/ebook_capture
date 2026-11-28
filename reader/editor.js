/* Markdown Reader — edit mode (Vditor instant rendering). Plugs into app.js like notes.js.
 *
 * Vditor rewrites Markdown in its own style (blank lines, padded pipe tables, "01." -> "1."),
 * so the editor's output is never written as is. On save, the editor's text right after loading
 * (baseline) is compared block by block with its current text, and every block the user did not
 * touch is written back from the original source. Untouched text stays byte-identical.
 */

const YeobaekEditor = (() => {
  /* ---------- Blocks ---------- */

  /**
   * Splits Markdown into blocks separated by blank lines. Fenced code and $$ math blocks stay whole
   * even when they contain blank lines. Returns { lead, blocks: [{ text, sep }] } where `sep` is the
   * exact text between a block and the next one (or the trailing text after the last), so
   * lead + Σ(text + sep) reproduces the input byte for byte.
   */
  function splitBlocks(md) {
    const lines = md.split('\n');
    const starts = []; let offset = 0;
    for (const line of lines) { starts.push(offset); offset += line.length + 1; }
    const ranges = []; let open = -1; let fence = null; let math = false;
    lines.forEach((line, i) => {
      const inside = fence || math;
      if (!inside && line.trim() === '') { if (open >= 0) { ranges.push([open, i - 1]); open = -1; } return; }
      if (open < 0) open = i;
      const mark = /^\s*(`{3,}|~{3,})(.*)$/.exec(line);
      if (fence) { if (mark && mark[1][0] === fence[0] && mark[1].length >= fence.length && !mark[2].trim()) fence = null; }
      else if (math) { if (line.trim() === '$$') math = false; }
      else if (mark) fence = mark[1];
      else if (line.trim() === '$$') math = true;
    });
    if (open >= 0) ranges.push([open, lines.length - 1]);
    const endOf = (i) => starts[i] + lines[i].length;
    const blocks = ranges.map(([a, b], k) => ({
      text: md.slice(starts[a], endOf(b)),
      sep: k + 1 < ranges.length ? md.slice(endOf(b), starts[ranges[k + 1][0]]) : md.slice(endOf(b)),
    }));
    return { lead: ranges.length ? md.slice(0, starts[ranges[0][0]]) : md, blocks };
  }

  const joinBlocks = ({ lead, blocks }) => lead + blocks.map((b) => b.text + b.sep).join('');

  /** Matching key that ignores Vditor's formatting: whitespace, table rule widths, list number padding. */
  const blockKey = (text) => text
    .replace(/^(\s*)0+(\d+[.)]\s)/gm, '$1$2')
    .replace(/-+/g, '-')
    .replace(/\s+/g, '');

  /** Longest-common-subsequence index pairs between arrays a and b. */
  function lcsPairs(a, b) {
    const n = a.length; const m = b.length;
    // Edits are local: trim the equal prefix and suffix so the table stays small.
    let start = 0; while (start < n && start < m && a[start] === b[start]) start += 1;
    let endA = n; let endB = m; while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) { endA -= 1; endB -= 1; }
    const pairs = [];
    for (let i = 0; i < start; i += 1) pairs.push([i, i]);
    const rows = endA - start; const cols = endB - start;
    if (rows && cols) {
      const dp = Array.from({ length: rows + 1 }, () => new Uint32Array(cols + 1));
      for (let i = rows - 1; i >= 0; i -= 1) {
        for (let j = cols - 1; j >= 0; j -= 1) dp[i][j] = a[start + i] === b[start + j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
      let i = 0; let j = 0;
      while (i < rows && j < cols) {
        if (a[start + i] === b[start + j]) { pairs.push([start + i, start + j]); i += 1; j += 1; }
        else if (dp[i + 1][j] >= dp[i][j + 1]) i += 1; else j += 1;
      }
    }
    for (let k = 0; k < n - endA; k += 1) pairs.push([endA + k, endB + k]);
    return pairs;
  }

  /**
   * Units for alignment: every non-blank line, except that a fenced code block or a $$ math block
   * is one unit. Each unit has its text, its matching key, and the exact text that follows it up to
   * the next unit (`sep`), so lead + Σ(text + sep) reproduces the input.
   */
  function splitUnits(md) {
    const lines = md.split('\n');
    const starts = []; let offset = 0;
    for (const line of lines) { starts.push(offset); offset += line.length + 1; }
    const ranges = []; let open = -1; let fence = null; let math = false;
    lines.forEach((line, i) => {
      if (fence || math) {
        const mark = /^\s*(`{3,}|~{3,})(.*)$/.exec(line);
        if (fence && mark && mark[1][0] === fence[0] && mark[1].length >= fence.length && !mark[2].trim()) { ranges.push([open, i]); fence = null; }
        else if (math && line.trim() === '$$') { ranges.push([open, i]); math = false; }
        return;
      }
      if (line.trim() === '') return;
      const mark = /^\s*(`{3,}|~{3,})/.exec(line);
      if (mark) { fence = mark[1]; open = i; return; }
      if (line.trim() === '$$') { math = true; open = i; return; }
      ranges.push([i, i]);
    });
    if (fence || math) ranges.push([open, lines.length - 1]);
    const endOf = (i) => starts[i] + lines[i].length;
    const units = ranges.map(([a, b], k) => {
      const text = md.slice(starts[a], endOf(b));
      return { text, key: blockKey(text), sep: k + 1 < ranges.length ? md.slice(endOf(b), starts[ranges[k + 1][0]]) : md.slice(endOf(b)) };
    });
    return { lead: ranges.length ? md.slice(0, starts[ranges[0][0]]) : md, units };
  }

  /**
   * Text to save for one edited range. `original` is its source, `baseline` the editor's value right
   * after loading it, `current` the editor's value now. Lines the user did not touch come from
   * `original` together with the blank lines around them; only changed or new lines come from the
   * editor. Returns { text, changed, unmatched }: `changed` counts units taken from the editor,
   * `unmatched` untouched units that could not be traced back to the source.
   */
  function preserveSource(original, baseline, current) {
    if (current === baseline) return { text: original, changed: 0, unmatched: 0 };
    const S = splitUnits(original); const B = splitUnits(baseline); const C = splitUnits(current);
    const sourceOfBaseline = new Map();
    for (const [i, j] of lcsPairs(S.units.map((u) => u.key), B.units.map((u) => u.key))) sourceOfBaseline.set(j, i);
    const baselineOfCurrent = new Map();
    for (const [j, k] of lcsPairs(B.units.map((u) => u.text), C.units.map((u) => u.text))) baselineOfCurrent.set(k, j);

    // Each current unit is either a source unit (index into S) or new text from the editor.
    const plan = C.units.map((u, k) => {
      const j = baselineOfCurrent.get(k);
      const i = j === undefined ? undefined : sourceOfBaseline.get(j);
      return i === undefined ? { text: u.text, sep: u.sep, fresh: true, edited: j === undefined } : { src: i };
    });
    let changed = 0; let unmatched = 0; let text = S.lead;
    for (let k = 0; k < plan.length; k += 1) {
      const item = plan[k];
      if (item.src !== undefined) {
        text += S.units[item.src].text;
        const next = plan[k + 1];
        if (!next) text += S.units[S.units.length - 1].sep;
        else if (next.src === item.src + 1 || next.src === undefined) text += S.units[item.src].sep;
        else text += /\n\s*\n/.test(S.units[item.src].sep) ? S.units[item.src].sep : '\n\n';
        continue;
      }
      if (item.edited) changed += 1; else unmatched += 1;
      text += item.text;
      const next = plan[k + 1];
      if (!next) { text += S.units.length ? S.units[S.units.length - 1].sep : item.sep; continue; }
      if (next.src === undefined) { text += item.sep; continue; }
      // Back to source text: reuse the source's spacing in front of that unit when it replaced one.
      const before = next.src - 1;
      text += before >= 0 && plan.slice(0, k).every((x) => x.src === undefined || x.src < before + 1) && plan.some((x) => x.src === before) === false
        ? S.units[before].sep : item.sep;
    }
    return { text, changed, unmatched };
  }

  return { splitBlocks, joinBlocks, splitUnits, blockKey, preserveSource };
})();

if (typeof module === 'object' && module.exports) module.exports = YeobaekEditor;

/* ---------- Edit mode UI (browser only) ---------- */

if (typeof document !== 'undefined') (() => {
  const reader = typeof Yeobaek !== 'undefined' && Yeobaek.reader;
  if (!reader) return;
  const { state, els: app, hooks, notify, esc } = reader;
  const { preserveSource } = YeobaekEditor;

  // Pinned Vditor build. Loaded on first use; move to reader/vendor/ for offline use (EDITOR.md §8.2).
  const VDITOR_CDN = 'https://unpkg.com/vditor@4.0.1';
  const HISTORY_KEEP = 20;
  const $ = (selector) => document.querySelector(selector);
  const ui = {
    toggle: $('#edit-toggle'), controls: $('#edit-controls'), host: $('#editor-host'), mount: $('#editor-mount'), status: $('#edit-status'),
    save: $('#edit-save'), done: $('#edit-done'), diff: $('#edit-diff'),
    ask: $('#edit-ask'), askText: $('#edit-ask-text'), askActions: $('#edit-ask-actions'),
  };
  const E = {
    vd: null, active: false, page: -1, range: null, original: '', baseline: '', dirty: false, saving: false,
  };

  /* ---------- loading Vditor ---------- */

  let loading = null;
  function loadVditor() {
    if (window.Vditor) return Promise.resolve();
    if (loading) return loading;
    loading = new Promise((resolve, reject) => {
      const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = `${VDITOR_CDN}/dist/index.css`;
      document.head.appendChild(css);
      const script = document.createElement('script'); script.src = `${VDITOR_CDN}/dist/index.min.js`;
      script.onload = () => resolve(); script.onerror = () => { loading = null; reject(new Error('편집기를 불러오지 못했습니다. 인터넷 연결을 확인하세요.')); };
      document.head.appendChild(script);
    });
    return loading;
  }

  /* ---------- a small three-way question (no window.confirm: it blocks the page) ---------- */

  function ask(text, choices) {
    ui.askText.textContent = text;
    ui.askActions.innerHTML = choices.map(([value, label, primary]) => `<button class="${primary ? 'primary-button' : 'quiet-button'}" type="button" data-value="${esc(value)}">${esc(label)}</button>`).join('');
    return new Promise((resolve) => {
      const pick = (event) => { const b = event.target.closest('[data-value]'); if (b) finish(b.dataset.value); };
      const cancel = () => finish('cancel');
      const finish = (value) => {
        ui.askActions.removeEventListener('click', pick); ui.ask.removeEventListener('close', cancel);
        if (ui.ask.open) ui.ask.close();
        resolve(value);
      };
      ui.askActions.addEventListener('click', pick); ui.ask.addEventListener('close', cancel);
      ui.ask.showModal();
    });
  }

  /* ---------- entering and leaving ---------- */

  const lines = () => state.rawText.replace(/\r\n?/g, '\n').split('\n');
  const sliceRange = (all, range) => all.slice(range.start, Math.min(range.end, all.length)).join('\n');

  function setStatus() {
    const text = E.saving ? '저장 중…' : E.dirty ? '변경 있음' : '저장됨';
    ui.status.textContent = text; ui.status.dataset.state = E.saving ? 'saving' : E.dirty ? 'dirty' : 'clean';
    ui.save.disabled = !E.dirty || E.saving;
  }

  async function enter() {
    if (E.active || !state.book || state.page < 0) return;
    try { await loadVditor(); } catch (error) { notify(error.message); return; }
    E.page = state.page; E.range = reader.pageRange(E.page);
    E.original = sliceRange(lines(), E.range);
    const spot = readingSpot();
    E.active = true; E.dirty = false;
    document.body.classList.add('editing');
    app.scroll.hidden = true; ui.host.hidden = false; ui.controls.hidden = false; ui.toggle.setAttribute('aria-pressed', 'true');
    ui.mount.innerHTML = '';
    await new Promise((resolve) => {
      E.vd = new window.Vditor(ui.mount, {
        mode: 'ir', value: E.original, height: ui.host.clientHeight,
        cdn: VDITOR_CDN, lang: 'ko_KR', cache: { enable: false }, placeholder: '',
        toolbar: ['headings', 'bold', 'italic', 'strike', '|', 'list', 'ordered-list', 'quote', 'line', 'code', 'inline-code', 'table', 'link', '|', 'undo', 'redo', '|', 'edit-mode'],
        preview: {
          math: { engine: 'KaTeX', inlineDigit: true },
          markdown: { autoSpace: false, fixTermTypo: false, gfmAutoLink: false, paragraphBeginningSpace: false, sanitize: true, mark: false, toc: false, footnotes: true },
        },
        input: () => { E.dirty = E.vd.getValue() !== E.baseline; setStatus(); },
        after: () => { E.baseline = E.vd.getValue(); resolve(); },
      });
    });
    setStatus();
    showSpotInEditor(spot);
  }

  async function leave({ force = false } = {}) {
    if (!E.active) return true;
    if (E.dirty && !force) {
      const choice = await ask('저장하지 않은 변경이 있습니다.', [['save', '저장하고 닫기', true], ['discard', '버리기'], ['cancel', '계속 편집']]);
      if (choice === 'cancel') return false;
      if (choice === 'save' && !(await save())) return false;
    }
    const spot = editorSpot();
    try { E.vd.destroy(); } catch { /* already gone */ }
    E.vd = null; E.active = false; E.dirty = false;
    document.body.classList.remove('editing');
    ui.host.hidden = true; ui.controls.hidden = true; app.scroll.hidden = false; ui.toggle.setAttribute('aria-pressed', 'false');
    showSpotInReader(spot);
    return true;
  }

  /* ---------- keeping the reading position across modes ---------- */

  // A spot is the first block visible at the top of the pane: a snippet of its text, how far into that
  // block the pane's top falls (0..1), where it sits among the blocks, and the scroll fraction as a fallback.
  const squash = (text) => text
    .replace(/^\s*(`{3,}|~{3,})[\w-]*/, '') // the editor shows a code block's opening fence
    .replace(/[\s*_`#>$|\\\-​⁠﻿]+/g, '');
  const firstVisible = (blocks, pane) => {
    const top = pane.getBoundingClientRect().top;
    return [...blocks].find((el) => el.getBoundingClientRect().bottom > top + 4 && squash(el.textContent).length >= 4) || null;
  };
  function spotOf(el, pane, blocks) {
    const fraction = pane.scrollTop / Math.max(1, pane.scrollHeight - pane.clientHeight);
    if (!el) return { text: '', into: 0, gap: 0, order: fraction, fraction };
    const box = el.getBoundingClientRect(); const top = pane.getBoundingClientRect().top;
    const list = [...blocks];
    return {
      text: squash(el.textContent).slice(0, 24),
      into: box.top < top ? Math.min(1, (top - box.top) / Math.max(1, box.height)) : 0,
      gap: Math.max(0, box.top - top),
      order: list.indexOf(el) / Math.max(1, list.length - 1),
      fraction,
    };
  }
  /** The block holding the same text; when several do, the one at the closest relative position. */
  function findBlock(blocks, spot) {
    if (!spot.text) return null;
    const list = [...blocks]; const key = spot.text.slice(0, 12);
    const hits = list.map((el, k) => [el, k]).filter(([el]) => squash(el.textContent).includes(key));
    if (!hits.length) return null;
    // Prefer blocks that begin with the text (another block may merely contain it further down).
    const rank = ([el, k]) => (squash(el.textContent).startsWith(key) ? 0 : 1) + Math.abs(k / Math.max(1, list.length - 1) - spot.order);
    return hits.sort((a, b) => rank(a) - rank(b))[0][0];
  }
  function placeAt(pane, el, spot) {
    if (!el) { pane.scrollTop = spot.fraction * (pane.scrollHeight - pane.clientHeight); return; }
    const box = el.getBoundingClientRect();
    pane.scrollTop += box.top - pane.getBoundingClientRect().top + spot.into * box.height - spot.gap;
  }
  /** Places the spot, then again while late rendering (code colouring, math, images) changes heights above it.
   *  Stops as soon as the user scrolls or types. */
  function settleAt(pane, el, spot) {
    let stopped = false;
    const stop = () => { stopped = true; };
    ['wheel', 'keydown', 'pointerdown', 'touchstart'].forEach((type) => pane.addEventListener(type, stop, { once: true, passive: true }));
    placeAt(pane, el, spot);
    [120, 400, 900, 1600].forEach((ms) => setTimeout(() => { if (!stopped && pane.isConnected) placeAt(pane, el && el.isConnected ? el : null, spot); }, ms));
  }
  const editorPane = () => (E.vd && E.vd.vditor && E.vd.vditor.ir ? E.vd.vditor.ir.element : ui.mount.querySelector('.vditor-ir pre.vditor-reset'));
  const editorBlocks = () => editorPane()?.children || [];
  const readerBlocks = () => app.content.querySelectorAll(':scope > *');

  function readingSpot() { return spotOf(firstVisible(readerBlocks(), app.scroll), app.scroll, readerBlocks()); }
  function editorSpot() { const pane = editorPane(); return pane ? spotOf(firstVisible(editorBlocks(), pane), pane, editorBlocks()) : null; }
  function showSpotInEditor(spot) {
    const pane = editorPane(); if (!pane) return;
    const el = findBlock(editorBlocks(), spot);
    settleAt(pane, el, spot);
    // Caret at the start of that block so typing starts where the reader was.
    if (el) {
      const range = document.createRange(); range.setStart(el, 0); range.collapse(true);
      const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
    }
    pane.focus({ preventScroll: true });
  }
  function showSpotInReader(spot) {
    if (!spot) return;
    requestAnimationFrame(() => settleAt(app.scroll, findBlock(readerBlocks(), spot), spot));
  }

  /* ---------- saving ---------- */

  /** Marks the file as edited in the reader so a pipeline re-run does not overwrite it (EDITOR.md §6.4). */
  function markEdited(text) {
    const stamp = new Date().toISOString().slice(0, 19);
    const fm = /^---\n([\s\S]*?)\n---[ \t]*(\n|$)/.exec(text);
    if (!fm) return `---\nedited: true\nedited_at: ${stamp}\n---\n${text}`;
    const body = fm[1].split('\n').filter((l) => !/^edited(_at)?:/.test(l));
    body.push('edited: true', `edited_at: ${stamp}`);
    return `---\n${body.join('\n')}\n---${fm[2]}${text.slice(fm[0].length)}`;
  }

  async function writeFile(dir, name, text) {
    const handle = await dir.getFileHandle(name, { create: true });
    const writable = await handle.createWritable(); await writable.write(text); await writable.close();
  }

  async function backup(dir, previous) {
    const base = state.sourceName.replace(/\.[^.]+$/, '');
    try { await dir.getFileHandle(`${base}.original.md`); } catch { await writeFile(dir, `${base}.original.md`, previous); }
    const history = await (await dir.getDirectoryHandle('.reader', { create: true })).getDirectoryHandle('history', { create: true });
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    await writeFile(history, `${base}.${stamp}.md`, previous);
    const kept = [];
    for await (const [name, handle] of history.entries()) if (handle.kind === 'file' && name.startsWith(`${base}.`)) kept.push(name);
    kept.sort();
    for (const name of kept.slice(0, Math.max(0, kept.length - HISTORY_KEEP))) await history.removeEntry(name);
  }

  /** The whole file with this chapter replaced; untouched lines stay byte-identical. */
  function buildText() {
    const current = E.vd.getValue();
    const result = preserveSource(E.original, E.baseline, current);
    const all = lines();
    const before = all.slice(0, E.range.start); const after = all.slice(Math.min(E.range.end, all.length));
    const text = [...before, result.text, ...after].join('\n');
    return { text, result, current };
  }

  async function save() {
    if (!E.active || E.saving) return false;
    const { text, result, current } = buildText();
    if (!E.dirty) { notify('바뀐 내용이 없습니다.'); return true; }
    E.saving = true; setStatus();
    try {
      const finalText = markEdited(text);
      if (state.dir) {
        const onDisk = await (await (await state.dir.getFileHandle(state.sourceName)).getFile()).text();
        if (onDisk !== state.rawText) {
          const choice = await ask('책을 연 뒤 파일이 밖에서 바뀌었습니다(파이프라인 재조립 또는 다른 편집기).', [['overwrite', '내 변경으로 덮어쓰기'], ['cancel', '취소', true]]);
          if (choice !== 'overwrite') return false;
        }
        await backup(state.dir, onDisk);
        await writeFile(state.dir, state.sourceName, finalText);
      } else {
        const url = URL.createObjectURL(new Blob([finalText], { type: 'text/markdown' }));
        const link = document.createElement('a'); link.href = url; link.download = state.sourceName; document.body.appendChild(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        notify('폴더 쓰기 권한이 없어 수정본을 내려받았습니다. 책 폴더의 파일과 바꾸세요.');
      }
      // The saved chapter becomes the new starting point for further edits.
      const delta = result.text.split('\n').length - E.original.split('\n').length;
      const shift = finalText.split('\n').length - text.split('\n').length; // front matter lines added
      E.original = result.text; E.baseline = current; E.dirty = false;
      E.range = { start: E.range.start + shift, end: E.range.end === Infinity ? Infinity : E.range.end + delta + shift };
      const page = E.page;
      reader.reopen(finalText);
      if (state.book.pages[page]) reader.goTo(state.book.pages[page].node, { push: false });
      if (state.dir) notify(`저장했습니다. 바뀐 줄 ${result.changed}곳${result.unmatched ? `, 원문과 짝을 못 찾아 편집기 형식으로 쓴 줄 ${result.unmatched}곳` : ''}.`);
      return true;
    } catch (error) {
      notify(`저장하지 못했습니다: ${error.message || error}`);
      return false;
    } finally {
      E.saving = false; if (E.active) setStatus();
    }
  }

  function showDiff() {
    if (!E.active) return;
    const { result } = buildText();
    const a = E.original.split('\n'); const b = result.text.split('\n');
    let s = 0; while (s < a.length && s < b.length && a[s] === b[s]) s += 1;
    let ea = a.length; let eb = b.length; while (ea > s && eb > s && a[ea - 1] === b[eb - 1]) { ea -= 1; eb -= 1; }
    const removed = a.slice(s, ea).map((l) => `- ${l}`); const added = b.slice(s, eb).map((l) => `+ ${l}`);
    const body = removed.length || added.length ? [...removed, ...added].join('\n') : '바뀐 줄이 없습니다.';
    ask(`이 장에서 저장될 변경 (원문 ${E.range.start + s + 1}번째 줄부터)\n\n${body.slice(0, 4000)}`, [['ok', '닫기', true]]);
  }

  /* ---------- events ---------- */

  ui.toggle.addEventListener('click', () => (E.active ? leave() : enter()));
  ui.save.addEventListener('click', save);
  ui.done.addEventListener('click', () => leave());
  ui.diff.addEventListener('click', showDiff);
  window.addEventListener('keydown', (event) => {
    if (E.active && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); save(); return; }
    if (!E.active && state.book && (event.key === 'e' || event.key === 'E' || event.key === 'ㄷ') && !event.ctrlKey && !event.metaKey && !event.altKey
      && !/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) && !event.target.isContentEditable) { event.preventDefault(); enter(); }
  });
  window.addEventListener('beforeunload', (event) => { if (E.active && E.dirty) { event.preventDefault(); event.returnValue = ''; } });

  // Moving to another chapter while editing asks first.
  const previousPageRendered = hooks.pageRendered;
  hooks.pageRendered = () => { previousPageRendered(); };
  const guard = (event) => {
    if (!E.active) return;
    if (event.target.closest('#tree li, #crumb [data-id], .pager-button, #search-results .go, #saved-list .go, .note-card [data-go]')) {
      event.preventDefault(); event.stopImmediatePropagation();
      leave().then((left) => { if (left) event.target.click(); });
    }
  };
  document.addEventListener('click', guard, true);
  // Chapter keys belong to the hidden reading view; do not let them turn pages under the editor.
  document.addEventListener('keydown', (event) => {
    if (E.active && (event.key === 'ArrowLeft' || event.key === 'ArrowRight') && !event.target.isContentEditable) event.stopImmediatePropagation();
  }, true);

  YeobaekEditor.ui = { enter, leave, save, state: E };
})();
