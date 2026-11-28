/* 여백 — annotations (highlight, memo, AI Q&A), the notes file, and AI settings. Plugs into app.js. */

(() => {
  const reader = typeof Yeobaek !== 'undefined' && Yeobaek.reader;
  if (!reader) return;
  const { state, els: app, store, hooks, esc, notify, bookKey, pathOf, goTo, pageHtml } = reader;

  const $ = (selector) => document.querySelector(selector);
  const ui = {
    toggle: $('#notes-toggle'), badge: $('#notes-badge'), panel: $('#notes-panel'), count: $('#notes-count'), close: $('#notes-close'),
    status: $('#save-status'), scopeAll: $('#scope-all'), scopePage: $('#scope-page'),
    color: $('#filter-color'), kind: $('#filter-kind'), tag: $('#filter-tag'), search: $('#notes-search'), list: $('#notes-list'),
    exportMd: $('#export-md'), exportJson: $('#export-json'), importJson: $('#import-json'), importInput: $('#import-input'),
    bar: $('#hl-bar'), barMemo: $('#hl-bar-memo'), barAsk: $('#hl-bar-ask'), barCopy: $('#hl-bar-copy'), barDelete: $('#hl-bar-delete'),
    settingsButton: $('#settings-button'), settings: $('#settings'), settingsHint: $('#settings-hint'), key: $('#ai-key'), remember: $('#ai-remember'),
    model: $('#ai-model'), presets: $('#ai-presets'), settingsSave: $('#settings-save'), settingsCancel: $('#settings-cancel'), keyClear: $('#ai-key-clear'),
    consent: $('#consent'), consentOk: $('#consent-ok'), consentCancel: $('#consent-cancel'),
  };

  const COLORS = ['yellow', 'green', 'blue', 'pink'];
  const SDK_URL = 'https://esm.sh/@anthropic-ai/sdk@1.12.0?bundle'; // single-file build of the official SDK, pinned
  const MODELS = { 'claude-sonnet-5-5': 'Claude Sonnet 5.5', 'claude-opus-5-5': 'Claude Opus 5.5', 'claude-haiku-5-5': 'Claude Haiku 5.5' };
  const DEFAULT_MODEL = 'claude-sonnet-5-5';
  const DEFAULT_PRESETS = [
    ['쉽게 풀어 줘', '이 대목을 처음 읽는 사람에게 설명하듯 쉽게 풀어 줘.'],
    ['앞뒤 맥락', '이 대목이 이 장의 논지에서 맡은 역할과 앞뒤 내용과의 연결을 설명해 줘.'],
    ['용어·인물', '이 대목에 나온 용어, 인물, 책이나 사건을 짧게 설명해 줘.'],
    ['반론', '이 대목의 주장에 대한 가장 강한 반론과 그 근거를 들어 줘.'],
  ];
  const overlay = window.matchMedia('(max-width:1050px)');

  const N = {
    list: [], deleted: {}, updatedAt: 0, hash: '',
    scope: 'all', lastColor: 'yellow', editing: '', asking: new Set(), drafts: new Map(),
    live: new Map(),      // annotation id -> { question, text, stream }
    key: '',              // API key kept in memory when "remember" is off
    fileState: 'local',   // local | file | saving | error
    saveTimer: 0, loaded: false,
  };

  const newId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  const find = (id) => N.list.find((item) => item.id === id);
  const tagsOf = (note) => [...new Set((note || '').match(/#[0-9A-Za-z가-힣_]+/g) || [])];
  const notesFileName = () => `${state.sourceName.replace(/\.[^.]+$/, '')}.notes.json`;
  const hashText = (text) => { let h = 5381; for (let i = 0; i < text.length; i += 1) h = ((h << 5) + h + text.charCodeAt(i)) >>> 0; return h.toString(16); };

  /* ---------- Blocks: numbering and lookup ---------- */

  /** Numbers the blocks under each heading. The same numbering is used on screen and off screen. */
  function tagBlocks(container, pageIndex) {
    let owner = state.book.pages[pageIndex].node.id; let index = 0;
    for (const el of container.children) {
      if (el.classList.contains('page-head')) continue;
      if (el.dataset.node) { owner = el.dataset.node; index = 0; continue; }
      el.dataset.owner = owner; el.dataset.block = index; index += 1;
    }
  }
  const blocksIn = (container, owner) => [...container.querySelectorAll('[data-block]')].filter((el) => el.dataset.owner === owner);
  const marksOf = (id) => [...app.content.querySelectorAll('mark.hl')].filter((mark) => mark.dataset.hl === id);

  const inert = document.implementation.createHTMLDocument('');
  const pageCache = new Map();
  /** A page rendered into a document that never loads images or runs anything; used to search and to feed the AI. */
  function offscreenPage(index) {
    if (!pageCache.has(index)) {
      const box = inert.createElement('div'); box.innerHTML = pageHtml(index); tagBlocks(box, index);
      pageCache.set(index, box);
    }
    return pageCache.get(index);
  }

  /* ---------- Painting ---------- */

  function paintRange(blockEl, start, end, annotation) {
    const walker = document.createTreeWalker(blockEl, NodeFilter.SHOW_TEXT); const pieces = []; let position = 0;
    while (walker.nextNode()) {
      const text = walker.currentNode; const from = Math.max(start, position); const to = Math.min(end, position + text.data.length);
      if (from < to) pieces.push([text, from - position, to - position]);
      position += text.data.length;
    }
    for (const [text, from, to] of pieces) {
      const range = document.createRange(); range.setStart(text, from); range.setEnd(text, to);
      const mark = document.createElement('mark'); mark.className = `hl hl-${annotation.color || 'none'}`; mark.dataset.hl = annotation.id;
      range.surroundContents(mark);
    }
  }
  function decorate(annotation) {
    const marks = marksOf(annotation.id);
    marks.forEach((mark, index) => {
      mark.className = `hl hl-${annotation.color || 'none'}`;
      if (index === marks.length - 1) {
        mark.classList.toggle('has-note', Boolean(annotation.note && annotation.note.trim()));
        mark.classList.toggle('has-ai', annotation.thread.length > 0);
      }
    });
  }
  function paint(annotation) {
    for (const part of annotation.anchor) {
      const blocks = blocksIn(app.content, part.node); if (!blocks.length) continue;
      let el = blocks[part.block]; let start = part.start;
      if (!el || el.textContent.slice(start, start + part.text.length) !== part.text) {
        el = [blocks[part.block], ...blocks].find((block) => block && block.textContent.includes(part.text));
        if (!el) continue;
        start = el.textContent.indexOf(part.text);
      }
      paintRange(el, start, start + part.text.length, annotation);
    }
    decorate(annotation);
  }
  function unpaint(id) {
    marksOf(id).forEach((mark) => { const parent = mark.parentNode; mark.replaceWith(...mark.childNodes); parent.normalize(); });
  }
  function repaintPage() {
    if (!state.book || state.page < 0) return;
    app.content.querySelectorAll('mark.hl').forEach((mark) => { const parent = mark.parentNode; mark.replaceWith(...mark.childNodes); parent.normalize(); });
    tagBlocks(app.content, state.page);
    N.list.forEach(paint);
  }

  /* ---------- Finding an annotation again after the book changed ---------- */

  /** Re-locates every anchor against the current text. Returns how many annotations could not be placed. */
  function reanchorAll() {
    const pages = state.book.pages.map((_, index) => offscreenPage(index));
    const allBlocks = pages.flatMap((box) => [...box.querySelectorAll('[data-block]')]);
    const place = (part, el, at) => { part.node = el.dataset.owner; part.block = Number(el.dataset.block); part.start = at; part.end = at + part.text.length; };
    let lost = 0;
    for (const annotation of N.list) {
      let missing = false;
      for (const part of annotation.anchor) {
        const node = state.book.byId.get(part.node);
        const own = node ? blocksIn(pages[node.pageIndex], part.node) : [];
        const exact = own[part.block];
        if (exact && exact.textContent.slice(part.start, part.start + part.text.length) === part.text) continue;
        const context = `${part.before || ''}${part.text}${part.after || ''}`;
        const samePage = node ? [...pages[node.pageIndex].querySelectorAll('[data-block]')] : [];
        const hit = own.find((el) => el.textContent.includes(part.text))
          || samePage.find((el) => el.textContent.includes(context)) || samePage.find((el) => el.textContent.includes(part.text))
          || allBlocks.find((el) => el.textContent.includes(context)) || allBlocks.find((el) => el.textContent.includes(part.text));
        if (hit) place(part, hit, hit.textContent.indexOf(part.text)); else missing = true;
      }
      annotation.lost = missing || undefined;
      if (missing) lost += 1;
    }
    return lost;
  }

  /* ---------- Creating and changing annotations ---------- */

  /** Splits the current selection into per-block text ranges. */
  function selectionParts() {
    const selection = window.getSelection();
    if (!state.book || !selection.rangeCount || selection.isCollapsed) return [];
    const range = selection.getRangeAt(0); const parts = [];
    for (const block of app.content.querySelectorAll('[data-block]')) {
      if (!range.intersectsNode(block)) continue;
      const inner = document.createRange(); inner.selectNodeContents(block);
      if (range.compareBoundaryPoints(Range.START_TO_START, inner) > 0) inner.setStart(range.startContainer, range.startOffset);
      if (range.compareBoundaryPoints(Range.END_TO_END, inner) < 0) inner.setEnd(range.endContainer, range.endOffset);
      const before = document.createRange(); before.selectNodeContents(block); before.setEnd(inner.startContainer, inner.startOffset);
      const text = inner.toString();
      if (!text.trim()) continue;
      const start = before.toString().length; const whole = block.textContent;
      parts.push({ node: block.dataset.owner, block: Number(block.dataset.block), start, end: start + text.length, text,
        before: whole.slice(Math.max(0, start - 20), start), after: whole.slice(start + text.length, start + text.length + 20) });
    }
    return parts;
  }

  const sameSpan = (a, b) => a.length === b.length && a.every((part, i) => part.node === b[i].node && part.block === b[i].block && part.start === b[i].start && part.end === b[i].end);

  /** Turns the selection into an annotation (or returns the one already covering exactly that span). */
  function annotateSelection(color) {
    const parts = selectionParts(); if (!parts.length) return null;
    let annotation = N.list.find((item) => sameSpan(item.anchor, parts));
    if (annotation) { if (color && annotation.color !== color) { annotation.color = color; touch(annotation); decorate(annotation); } }
    else {
      const now = Date.now();
      annotation = { id: newId(), anchor: parts, quote: parts.map((part) => part.text).join(' ').replace(/\s+/g, ' ').trim(), color, note: '', tags: [], thread: [], createdAt: now, updatedAt: now };
      N.list.push(annotation); touch(annotation); paint(annotation);
    }
    if (color) N.lastColor = color;
    window.getSelection().removeAllRanges(); hideBar(); renderList();
    return annotation;
  }

  function touch(annotation) { annotation.updatedAt = Date.now(); changed(); }
  function changed() { N.updatedAt = Date.now(); schedulePersist(); }

  function removeAnnotation(id) {
    const live = N.live.get(id); if (live && live.stream) live.stream.abort();
    N.list = N.list.filter((item) => item.id !== id); N.deleted[id] = Date.now(); N.asking.delete(id);
    unpaint(id); hideBar(); changed(); renderList(); notify('주석을 지웠습니다.');
  }

  /* ---------- Selection toolbar ---------- */

  function showBar(rect, editingId = '') {
    N.editing = editingId; ui.barDelete.hidden = !editingId; ui.barCopy.hidden = Boolean(editingId); ui.bar.hidden = false;
    const width = ui.bar.offsetWidth; const height = ui.bar.offsetHeight;
    const left = Math.max(8, Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 8));
    const top = rect.top - height - 8 < 60 ? rect.bottom + 8 : rect.top - height - 8;
    ui.bar.style.left = `${left}px`; ui.bar.style.top = `${top}px`;
  }
  function hideBar() { ui.bar.hidden = true; N.editing = ''; }

  /** The annotation the toolbar acts on: the clicked one, or a new one made from the selection. */
  const target = (color) => (N.editing ? find(N.editing) : annotateSelection(color));

  function focusCard(id, selector) {
    setPanel(true);
    if (!cardOf(id)) { resetFilters(); renderList(); }
    const card = cardOf(id); if (!card) return;
    card.scrollIntoView({ block: 'nearest' });
    const field = card.querySelector(selector); if (field) field.focus();
  }
  function startMemo() {
    const annotation = target(N.lastColor); if (!annotation) return;
    hideBar(); focusCard(annotation.id, '[data-memo]');
  }
  function startAsk() {
    const annotation = target(null); if (!annotation) return;
    hideBar(); N.asking.add(annotation.id); renderList(); focusCard(annotation.id, '[data-ask]');
  }

  /* ---------- Panel ---------- */

  const cardOf = (id) => [...ui.list.querySelectorAll('.note-card')].find((card) => card.dataset.id === id);
  function resetFilters() { N.scope = 'all'; ui.color.value = ''; ui.kind.value = ''; ui.tag.value = ''; ui.search.value = ''; }

  function setPanel(open, persist = true) {
    ui.panel.hidden = !open; ui.toggle.setAttribute('aria-pressed', String(open));
    if (persist) store.set('notesPanel', open);
    if (state.book && state.page >= 0) reader.updateProgress();
  }

  function visibleList() {
    const { nodes, pages } = state.book;
    const order = new Map(nodes.map((n, index) => [n.id, index]));
    const rank = (a) => [a.lost ? Infinity : (order.get(a.anchor[0].node) ?? Infinity), a.anchor[0].block, a.anchor[0].start];
    const here = state.page >= 0 ? new Set([pages[state.page].node, ...pages[state.page].inline].map((n) => n.id)) : new Set();
    const query = ui.search.value.trim().toLowerCase();
    return [...N.list]
      .filter((a) => N.scope !== 'page' || here.has(a.anchor[0].node))
      .filter((a) => !ui.color.value || (a.color || 'none') === ui.color.value)
      .filter((a) => !ui.kind.value || (ui.kind.value === 'memo' ? Boolean(a.note && a.note.trim()) : a.thread.length > 0))
      .filter((a) => !ui.tag.value || a.tags.includes(ui.tag.value))
      .filter((a) => !query || `${a.quote} ${a.note} ${a.thread.map((turn) => turn.text).join(' ')}`.toLowerCase().includes(query))
      .sort((a, b) => { const x = rank(a); const y = rank(b); return x[0] - y[0] || x[1] - y[1] || x[2] - y[2]; });
  }

  const paragraphs = (text) => esc(text).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').split(/\n{2,}/).map((part) => `<p>${part.replace(/\n/g, '<br>')}</p>`).join('');
  const day = (at) => new Date(at).toISOString().slice(0, 10);

  function turnHtml(annotation, turn, index) {
    if (turn.role === 'user') return `<div class="turn user"><span class="who">Q</span><div class="answer"><p>${esc(turn.text)}</p></div></div>`;
    const cites = (turn.citations || []).map((cite, i) => {
      const node = state.book.byId.get(cite.node);
      return `<button class="cite" type="button" data-cite="${index}:${i}" title="${esc(cite.quote)}">근거 ${i + 1}${node ? ` · ${esc(node.title)}` : ''}</button>`;
    }).join('');
    const pinned = annotation.pinned === index;
    return `<div class="turn ai${pinned ? ' pinned' : ''}"><span class="who ai">AI</span><div class="answer">${paragraphs(turn.text)}</div>` +
      `<div class="cites">${cites || '<span class="no-cite">근거 문장 없음 (책 밖의 설명일 수 있음)</span>'}</div>` +
      `<div class="turn-actions"><button class="mini" type="button" data-pin="${index}" aria-pressed="${pinned}">${pinned ? '★ 채택됨' : '☆ 주석으로 채택'}</button>` +
      `<button class="mini" type="button" data-to-memo="${index}">메모로 복사</button></div></div>`;
  }

  // Wrap in quotes unless the passage already starts and ends with them.
  const quoted = (text) => (/^[“"'‘「『]/.test(text) && /[”"'’」』]$/.test(text) ? text : `“${text}”`);

  function cardHtml(annotation) {
    const node = state.book.byId.get(annotation.anchor[0].node);
    const live = N.live.get(annotation.id);
    const asking = N.asking.has(annotation.id) || annotation.thread.length > 0 || Boolean(live);
    const presets = aiSettings().presets.map(([label], index) => `<button class="pill" type="button" data-preset="${index}">${esc(label)}</button>`).join('');
    return `<article class="note-card hl-${annotation.color || 'none'}" data-id="${esc(annotation.id)}">` +
      `<header><button class="quote" type="button" data-go${node && !annotation.lost ? '' : ' disabled'}>${esc(quoted(annotation.quote))}</button>` +
      `<button class="remove" type="button" data-remove aria-label="주석 삭제">×</button></header>` +
      `${annotation.lost || !node ? '<div class="where">원문에서 위치를 찾지 못함</div>' : ''}` +
      `<textarea class="memo" data-memo rows="1" placeholder="메모 · #태그" aria-label="메모">${esc(annotation.note || '')}</textarea>` +
      `<div class="tags">${annotation.tags.map((tag) => `<span>${esc(tag)}</span>`).join(' ')}</div>` +
      `<div class="thread">${annotation.thread.map((turn, index) => turnHtml(annotation, turn, index)).join('')}` +
      (live ? `<div class="turn user"><span class="who">Q</span><div class="answer"><p>${esc(live.question)}</p></div></div>` +
        `<div class="turn ai live"><span class="who ai">AI</span><div class="answer" data-live>${paragraphs(live.text || '답을 기다리는 중…')}</div>` +
        `<div class="turn-actions"><button class="mini" type="button" data-stop>중지</button></div></div>` : '') + `</div>` +
      (asking ? `<div class="ask"><div class="presets">${presets}</div><div class="ask-row">` +
        `<input class="field" data-ask type="text" placeholder="${annotation.thread.length ? '이어서 묻기…' : '이 대목에 대해 묻기…'}" aria-label="AI에게 묻기" value="${esc(N.drafts.get(annotation.id) || '')}"${live ? ' disabled' : ''}>` +
        `<button class="mini primary" type="button" data-send${live ? ' disabled' : ''}>보내기</button></div></div>`
        : `<div class="card-foot"><button class="mini" type="button" data-open-ask>AI에게 묻기</button></div>`) +
      `</article>`;
  }

  function renderList() {
    if (!state.book) return;
    const list = visibleList();
    ui.badge.textContent = N.list.length || ''; ui.count.textContent = list.length === N.list.length ? (N.list.length || '') : `${list.length} / ${N.list.length}`;
    ui.scopeAll.setAttribute('aria-pressed', String(N.scope === 'all')); ui.scopePage.setAttribute('aria-pressed', String(N.scope === 'page'));
    const tags = [...new Set(N.list.flatMap((a) => a.tags))].sort(); const chosen = ui.tag.value;
    ui.tag.innerHTML = `<option value="">태그 전체</option>${tags.map((tag) => `<option value="${esc(tag)}">${esc(tag)}</option>`).join('')}`;
    ui.tag.value = tags.includes(chosen) ? chosen : '';
    ui.exportMd.disabled = ui.exportJson.disabled = !N.list.length;
    ui.list.innerHTML = list.length ? list.map(cardHtml).join('')
      : `<p class="empty-copy">${N.list.length ? '조건에 맞는 주석이 없습니다.' : '본문에서 문장을 드래그한 뒤 색을 고르거나, 메모·AI에게 묻기를 누르면 여기에 모입니다.'}</p>`;
    ui.list.querySelectorAll('textarea').forEach(autoGrow);
  }
  const autoGrow = (area) => { area.style.height = 'auto'; area.style.height = `${area.scrollHeight + 2}px`; };

  function openAnnotation(id) {
    const annotation = find(id); const node = annotation && state.book.byId.get(annotation.anchor[0].node);
    if (!node) return;
    goTo(node);
    const marks = marksOf(id);
    if (marks[0]) {
      app.scroll.scrollTop += marks[0].getBoundingClientRect().top - app.scroll.getBoundingClientRect().top - app.scroll.clientHeight / 3;
      state.spyLockUntil = performance.now() + 200;
      marks.forEach((mark) => { mark.classList.add('flash'); setTimeout(() => mark.classList.remove('flash'), 1600); });
    }
    if (overlay.matches) setPanel(false);
  }

  function openCitation(annotation, turnIndex, citeIndex) {
    const cite = annotation.thread[turnIndex]?.citations?.[citeIndex]; const node = cite && state.book.byId.get(cite.node);
    if (!node) return;
    goTo(node);
    const el = blocksIn(app.content, cite.node)[cite.block]; if (!el) return;
    app.scroll.scrollTop += el.getBoundingClientRect().top - app.scroll.getBoundingClientRect().top - app.scroll.clientHeight / 3;
    state.spyLockUntil = performance.now() + 200;
    el.classList.add('hit'); setTimeout(() => el.classList.remove('hit'), 1800);
    if (overlay.matches) setPanel(false);
  }

  /* ---------- Saving: browser storage always, the notes file when the folder is writable ---------- */

  function notesDocument() {
    return {
      version: 1,
      book: { title: state.book.title, file: state.sourceName, contentHash: N.hash },
      position: state.activeId, read: [...state.read], saved: state.saved,
      annotations: N.list, deleted: N.deleted, updatedAt: N.updatedAt,
    };
  }

  function setFileState(value) {
    N.fileState = value;
    const text = { file: '파일에 저장됨', saving: '저장 중…', error: '파일 저장 실패', local: '브라우저에만 저장됨' }[value];
    ui.status.textContent = text; ui.status.dataset.state = value;
    ui.status.title = value === 'file' ? `${notesFileName()}에 저장했습니다.`
      : value === 'local' ? '주석이 이 브라우저에만 있습니다. 누르면 책 폴더를 골라 주석 파일로 저장합니다.' : text;
  }

  function schedulePersist() {
    if (!state.book || !N.loaded) return;
    clearTimeout(N.saveTimer); N.saveTimer = setTimeout(persist, 800);
    if (state.dir) setFileState('saving');
  }
  async function persist() {
    if (!state.book || !N.loaded) return;
    const doc = notesDocument();
    store.set(bookKey('notes'), doc);
    if (!state.dir) { setFileState('local'); return; }
    try {
      const handle = await state.dir.getFileHandle(notesFileName(), { create: true });
      const writable = await handle.createWritable();
      await writable.write(JSON.stringify(doc, null, 1)); await writable.close();
      setFileState('file');
    } catch { setFileState('error'); }
  }

  async function readNotesFile() {
    try { const handle = await state.dir.getFileHandle(notesFileName()); return JSON.parse(await (await handle.getFile()).text()); } catch { return null; }
  }

  const validAnnotation = (a) => a && typeof a.id === 'string' && Array.isArray(a.anchor) && a.anchor.length && a.anchor.every((part) => part && typeof part.text === 'string');
  const normalize = (a) => ({ ...a, quote: a.quote || a.anchor.map((part) => part.text).join(' '), color: COLORS.includes(a.color) ? a.color : null, note: a.note || '', tags: tagsOf(a.note), thread: Array.isArray(a.thread) ? a.thread : [], updatedAt: a.updatedAt || a.createdAt || 0 });

  /** Keeps the newest copy of every annotation; a deletion wins when it is newer than the copy. */
  function mergeDocs(...docs) {
    const byId = new Map(); const deleted = {};
    for (const doc of docs.filter(Boolean)) {
      Object.entries(doc.deleted || {}).forEach(([id, at]) => { deleted[id] = Math.max(deleted[id] || 0, at); });
      for (const raw of (doc.annotations || []).filter(validAnnotation)) {
        const item = normalize(raw); const known = byId.get(item.id);
        if (!known || item.updatedAt > known.updatedAt) byId.set(item.id, item);
      }
    }
    return { annotations: [...byId.values()].filter((item) => !(deleted[item.id] > item.updatedAt)), deleted };
  }

  /** Highlights saved by the previous version: { id, color, parts, text }. */
  const legacyDoc = () => ({
    annotations: store.get(bookKey('hl'), []).filter((hl) => hl && Array.isArray(hl.parts) && hl.parts.length)
      .map((hl) => ({ id: hl.id, anchor: hl.parts, quote: hl.text, color: hl.color, createdAt: hl.createdAt, updatedAt: hl.createdAt })),
  });

  async function loadNotes(text) {
    N.loaded = false; N.bookId = ''; N.list = []; N.hash = hashText(text); N.asking.clear(); N.drafts.clear(); N.live.clear(); pageCache.clear();
    const bookId = state.bookId;
    const local = store.get(bookKey('notes'), null);
    const file = state.dir ? await readNotesFile() : null;
    if (state.bookId !== bookId) return; // another book was opened meanwhile
    const merged = mergeDocs(local || legacyDoc(), file);
    N.list = merged.annotations; N.deleted = merged.deleted;
    N.updatedAt = Math.max(local?.updatedAt || 0, file?.updatedAt || 0);

    // The file is the durable copy: when it is newer, it also restores position, read marks and saved places.
    if (file && (file.updatedAt || 0) > (local?.updatedAt || 0)) {
      if (Array.isArray(file.read)) { state.read = new Set(file.read); store.set(bookKey('read'), file.read); reader.refreshMeta(); }
      if (Array.isArray(file.saved)) { state.saved = file.saved.filter((item) => item && typeof item.id === 'string'); store.set(bookKey('saved'), state.saved); reader.renderSaved(); reader.updateBookmarkButton(); }
      const node = state.book.byId.get(file.position);
      if (node && !location.hash.startsWith('#/')) goTo(node, { push: false });
    }

    const previous = file?.book?.contentHash || local?.book?.contentHash;
    let report = '';
    if (N.list.length && previous !== N.hash) {
      const lost = reanchorAll();
      if (previous) report = `책 내용이 바뀌어 주석 위치를 다시 찾았습니다: ${N.list.length}개 중 ${N.list.length - lost}개 확인${lost ? `, ${lost}개는 찾지 못함` : ''}.`;
    }
    N.loaded = true; N.bookId = bookId;
    repaintPage(); renderList(); setFileState(state.dir ? 'saving' : 'local'); persist();
    if (report) notify(report);
  }

  /** Lets a book that was opened read-only (file picker, drag and drop) start saving into its folder. */
  async function enableFileSave() {
    if (!state.book) return;
    if (!window.showDirectoryPicker) { notify('이 브라우저는 폴더에 직접 저장할 수 없습니다. ‘JSON 내보내기’를 쓰세요.'); return; }
    let dir;
    try { dir = await window.showDirectoryPicker({ mode: 'readwrite' }); } catch { return; }
    try { await dir.getFileHandle(state.sourceName); } catch { notify(`고른 폴더에 ${state.sourceName} 파일이 없습니다. 책이 있는 폴더를 고르세요.`); return; }
    state.dir = dir;
    const file = await readNotesFile();
    if (file) { const merged = mergeDocs(notesDocument(), file); N.list = merged.annotations; N.deleted = merged.deleted; repaintPage(); renderList(); }
    N.updatedAt = Date.now(); persist();
  }

  /* ---------- Export and import ---------- */

  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const link = document.createElement('a'); link.href = url; link.download = name; document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function notesMarkdown() {
    const { nodes, pages, byId } = state.book;
    const order = new Map(nodes.map((n, index) => [n.id, index]));
    const sorted = [...N.list].sort((a, b) => (order.get(a.anchor[0].node) ?? Infinity) - (order.get(b.anchor[0].node) ?? Infinity) || a.anchor[0].block - b.anchor[0].block || a.anchor[0].start - b.anchor[0].start);
    const lines = [`# ${state.book.title} — 주석`, '']; let chapter = null;
    for (const annotation of sorted) {
      const node = byId.get(annotation.anchor[0].node);
      const title = node && !annotation.lost ? pages[node.pageIndex].node.title : '위치를 찾지 못한 주석';
      if (title !== chapter) { chapter = title; lines.push(`## ${title}`, ''); }
      lines.push(`> ${annotation.quote}`, '');
      if (annotation.note && annotation.note.trim()) lines.push(annotation.note.trim(), '');
      const pinned = annotation.thread[annotation.pinned];
      if (pinned && pinned.role === 'assistant') {
        const question = annotation.thread[annotation.pinned - 1];
        lines.push(`**AI 답변** (${MODELS[pinned.model] || pinned.model || 'AI'}, ${day(pinned.at)})${question ? ` — 질문: ${question.text}` : ''}`, '', pinned.text.trim(), '');
      }
    }
    return lines.join('\n');
  }

  async function exportMarkdown() {
    const name = `${state.sourceName.replace(/\.[^.]+$/, '')}.notes.md`; const text = notesMarkdown();
    if (state.dir) {
      try {
        const handle = await state.dir.getFileHandle(name, { create: true }); const writable = await handle.createWritable();
        await writable.write(text); await writable.close(); notify(`책 폴더에 ${name}를 썼습니다.`); return;
      } catch { /* fall back to a download */ }
    }
    download(name, text, 'text/markdown'); notify(`${name}를 내려받았습니다.`);
  }

  async function importNotes(file) {
    let doc; try { doc = JSON.parse(await file.text()); } catch { notify('JSON 파일을 읽지 못했습니다.'); return; }
    if (!doc || !Array.isArray(doc.annotations)) { notify('주석 파일 형식이 아닙니다.'); return; }
    const before = N.list.length;
    const merged = mergeDocs(notesDocument(), doc); N.list = merged.annotations; N.deleted = merged.deleted;
    const lost = reanchorAll(); changed(); repaintPage(); renderList();
    notify(`주석 ${N.list.length - before}개를 더했습니다.${lost ? ` ${lost}개는 위치를 찾지 못했습니다.` : ''}`);
  }

  /* ---------- AI settings ---------- */

  function aiSettings() {
    const saved = store.get('ai', {});
    const presets = Array.isArray(saved.presets) && saved.presets.length ? saved.presets : DEFAULT_PRESETS;
    return { model: MODELS[saved.model] ? saved.model : DEFAULT_MODEL, remember: saved.remember !== false, presets, key: N.key || store.get('aiKey', '') };
  }

  function openSettings(hint = '') {
    const settings = aiSettings();
    ui.settingsHint.textContent = hint; ui.settingsHint.hidden = !hint;
    ui.key.value = settings.key; ui.remember.checked = settings.remember; ui.model.value = settings.model;
    ui.presets.value = settings.presets.map(([label, prompt]) => `${label} | ${prompt}`).join('\n');
    ui.settings.showModal(); if (hint) ui.key.focus();
  }

  function saveSettings() {
    const key = ui.key.value.trim(); const remember = ui.remember.checked;
    const presets = ui.presets.value.split('\n').map((line) => line.split('|').map((part) => part.trim())).filter((parts) => parts.length >= 2 && parts[0] && parts[1]).map((parts) => [parts[0], parts.slice(1).join(' | ')]);
    store.set('ai', { model: ui.model.value, remember, presets });
    N.key = key;
    if (remember && key) store.set('aiKey', key); else { try { localStorage.removeItem('yeobaek:aiKey'); } catch { /* ignore */ } }
    ui.settings.close(); renderList(); notify('설정을 저장했습니다.');
  }

  function askConsent() {
    if (store.get(bookKey('aiConsent'), false)) return Promise.resolve(true);
    return new Promise((resolve) => {
      const finish = (value) => {
        ui.consentOk.removeEventListener('click', agree); ui.consent.removeEventListener('close', decline);
        if (ui.consent.open) ui.consent.close();
        resolve(value);
      };
      const agree = () => { store.set(bookKey('aiConsent'), true); finish(true); };
      const decline = () => finish(false);
      ui.consentOk.addEventListener('click', agree); ui.consent.addEventListener('close', decline);
      ui.consent.showModal();
    });
  }

  /* ---------- AI Q&A ---------- */

  let sdkPromise = null;
  const loadSdk = () => {
    if (!sdkPromise) {
      const timeout = new Promise((resolve, reject) => setTimeout(() => reject(new Error('timeout')), 20000));
      sdkPromise = Promise.race([import(SDK_URL).then((module) => module.default), timeout]).catch((error) => { sdkPromise = null; throw error; });
    }
    return sdkPromise;
  };

  /** The chapter as one plain-text document, plus where each block sits in it so citations can be mapped back. */
  function chapterDocument(pageIndex) {
    const box = offscreenPage(pageIndex); let text = ''; const spans = [];
    for (const el of box.children) {
      if (el.classList.contains('page-head')) { text += `${el.querySelector('.page-title').textContent}\n\n`; continue; }
      if (el.dataset.node) { text += `${el.textContent}\n\n`; continue; }
      if (el.matches('figure, .figure-missing')) continue;
      const body = el.textContent.trim(); if (!body) continue;
      spans.push({ start: text.length, end: text.length + body.length, node: el.dataset.owner, block: Number(el.dataset.block) });
      text += `${body}\n\n`;
    }
    return { text, spans, title: state.book.pages[pageIndex].node.title };
  }

  function systemPrompt() {
    const outline = state.book.pages.map((page) => `- ${page.node.title}`).join('\n');
    return [
      '당신은 독자가 책을 읽으며 붙이는 주석을 돕는다. 독자는 첨부된 문서(지금 읽고 있는 장의 전문)에서 한 대목을 골라 질문한다.',
      '',
      '답하는 방법:',
      '- 문서에 근거가 있는 내용은 문서의 해당 문장을 인용해 답한다.',
      '- 문서에 없는 배경 지식을 더할 때는 그 문단을 "책 밖의 설명:"으로 시작해 독자가 구분할 수 있게 한다.',
      '- 원문을 길게 옮겨 적지 않는다. 답은 본문 옆의 좁은 패널에서 읽히므로 서너 문단 이내의 평문으로 쓰고, 제목·표·목록 기호는 쓰지 않는다.',
      '- 문서는 스캔본을 문자 인식한 것이라 오탈자나 끊긴 문장이 있을 수 있다. 문맥으로 읽되, 뜻이 불확실하면 그렇다고 말한다.',
      '- 독자가 쓴 언어로 답한다.',
      '',
      `책: ${state.book.title}`,
      '목차:',
      outline,
    ].join('\n');
  }

  function failureMessage(Anthropic, error) {
    if (!Anthropic) return 'AI 라이브러리를 불러오지 못했습니다. 인터넷 연결을 확인하세요.';
    if (error instanceof Anthropic.APIUserAbortError) return '';
    if (error instanceof Anthropic.AuthenticationError) return 'API 키가 올바르지 않습니다. 설정에서 키를 확인하세요.';
    if (error instanceof Anthropic.PermissionDeniedError) return '이 API 키로는 선택한 모델을 쓸 수 없습니다.';
    if (error instanceof Anthropic.NotFoundError) return '선택한 모델을 찾지 못했습니다. 설정에서 모델을 바꿔 보세요.';
    if (error instanceof Anthropic.RateLimitError) {
      const wait = Number(error.headers?.get?.('retry-after'));
      return `요청이 많아 잠시 막혔습니다.${wait ? ` ${wait}초 뒤에 다시 보내세요.` : ' 잠시 뒤에 다시 보내세요.'}`;
    }
    if (error instanceof Anthropic.APIConnectionError) return 'Anthropic API에 연결하지 못했습니다. 인터넷 연결을 확인하세요.';
    if (error instanceof Anthropic.APIError) return `API 오류 (${error.status || '알 수 없음'}): ${error.message}`;
    return `답을 받지 못했습니다: ${error.message || error}`;
  }

  async function ask(id, question) {
    const annotation = find(id); const text = question.trim();
    if (!annotation || !text || N.live.has(id)) return;
    const settings = aiSettings();
    if (!settings.key) { N.drafts.set(id, text); openSettings('AI 문답을 쓰려면 Anthropic API 키를 입력하세요.'); return; }
    if (!(await askConsent())) { N.drafts.set(id, text); return; }
    const node = state.book.byId.get(annotation.anchor[0].node);
    if (!node) { notify('이 주석의 원문 위치를 찾지 못해 물을 수 없습니다.'); return; }

    const live = { question: text, text: '', stream: null };
    N.live.set(id, live); N.drafts.delete(id); N.asking.add(id); renderList();
    let Anthropic = null;
    try {
      Anthropic = await loadSdk();
      const client = new Anthropic({ apiKey: settings.key, dangerouslyAllowBrowser: true });
      const chapter = chapterDocument(node.pageIndex);
      const history = annotation.thread.filter((turn) => turn.text);
      const opening = history.length ? history[0].text : text;
      const messages = [
        { role: 'user', content: [
          // Stable prefix (system + this chapter) is cached, so follow-up questions in the same chapter reuse it.
          { type: 'document', source: { type: 'text', media_type: 'text/plain', data: chapter.text }, title: chapter.title, citations: { enabled: true }, cache_control: { type: 'ephemeral' } },
          { type: 'text', text: `독자가 고른 대목:\n"""\n${annotation.quote}\n"""\n\n질문: ${opening}` },
        ] },
        ...history.slice(1).map((turn) => ({ role: turn.role, content: turn.text })),
        ...(history.length ? [{ role: 'user', content: text }] : []),
      ];
      const stream = client.messages.stream({ model: settings.model, max_tokens: 64000, output_config: { effort: 'medium' }, system: systemPrompt(), messages });
      live.stream = stream;
      stream.on('text', (delta, snapshot) => {
        live.text = snapshot;
        const el = cardOf(id)?.querySelector('[data-live]'); if (el) el.innerHTML = paragraphs(snapshot);
      });
      const message = await stream.finalMessage();
      if (message.stop_reason === 'refusal') throw new Error('모델이 이 질문에는 답하지 않았습니다.');
      const blocks = message.content.filter((block) => block.type === 'text');
      const answer = blocks.map((block) => block.text).join('').trim();
      if (!answer) throw new Error('빈 답이 돌아왔습니다.');
      const citations = [];
      for (const cite of blocks.flatMap((block) => block.citations || [])) {
        if (cite.type !== 'char_location') continue;
        const span = chapter.spans.find((item) => cite.start_char_index >= item.start && cite.start_char_index < item.end + 2);
        if (span && !citations.some((known) => known.node === span.node && known.block === span.block)) citations.push({ quote: cite.cited_text.trim().slice(0, 300), node: span.node, block: span.block });
      }
      const now = Date.now();
      annotation.thread.push({ role: 'user', text, at: now });
      annotation.thread.push({
        role: 'assistant', text: answer, citations, model: message.model, at: now, truncated: message.stop_reason === 'max_tokens' || undefined,
        usage: { input: message.usage.input_tokens + (message.usage.cache_read_input_tokens || 0) + (message.usage.cache_creation_input_tokens || 0), cached: message.usage.cache_read_input_tokens || 0, output: message.usage.output_tokens },
      });
      touch(annotation); decorate(annotation);
    } catch (error) {
      const reason = failureMessage(Anthropic, error);
      N.drafts.set(id, text); // the question goes back into the box so nothing typed is lost
      if (reason) notify(reason);
      if (Anthropic && error instanceof Anthropic.AuthenticationError) openSettings(reason);
    } finally {
      N.live.delete(id); renderList();
    }
  }

  /* ---------- Events ---------- */

  let selectionTimer = 0;
  document.addEventListener('selectionchange', () => {
    clearTimeout(selectionTimer);
    selectionTimer = setTimeout(() => {
      const selection = window.getSelection();
      if (selection.isCollapsed) { if (!N.editing) hideBar(); return; }
      if (selectionParts().length) showBar(selection.getRangeAt(0).getBoundingClientRect());
    }, 120);
  });
  app.content.addEventListener('click', (event) => {
    const mark = event.target.closest('mark.hl');
    if (mark && window.getSelection().isCollapsed) showBar(mark.getBoundingClientRect(), mark.dataset.hl);
  });
  document.addEventListener('pointerdown', (event) => {
    if (!ui.bar.hidden && !ui.bar.contains(event.target) && !event.target.closest?.('mark.hl')) hideBar();
  });
  app.scroll.addEventListener('scroll', () => { if (!ui.bar.hidden) hideBar(); }, { passive: true });

  ui.bar.addEventListener('mousedown', (event) => event.preventDefault()); // keep the text selection
  ui.bar.addEventListener('click', (event) => {
    const swatch = event.target.closest('[data-color]');
    if (swatch) {
      const annotation = find(N.editing);
      if (annotation) { annotation.color = swatch.dataset.color; N.lastColor = annotation.color; touch(annotation); decorate(annotation); hideBar(); renderList(); }
      else annotateSelection(swatch.dataset.color);
    } else if (event.target === ui.barMemo) startMemo();
    else if (event.target === ui.barAsk) startAsk();
    else if (event.target === ui.barCopy) {
      const text = window.getSelection().toString();
      navigator.clipboard.writeText(text).then(() => notify('선택한 문장을 복사했습니다.'), () => notify('클립보드에 복사하지 못했습니다.'));
      hideBar();
    } else if (event.target === ui.barDelete && N.editing) removeAnnotation(N.editing);
  });

  ui.toggle.addEventListener('click', () => setPanel(ui.panel.hidden));
  ui.close.addEventListener('click', () => { setPanel(false); ui.toggle.focus(); });
  ui.scopeAll.addEventListener('click', () => { N.scope = 'all'; renderList(); });
  ui.scopePage.addEventListener('click', () => { N.scope = 'page'; renderList(); });
  [ui.color, ui.kind, ui.tag].forEach((select) => select.addEventListener('change', renderList));
  ui.search.addEventListener('input', renderList);
  ui.status.addEventListener('click', () => { if (N.fileState === 'local') enableFileSave(); else if (N.fileState === 'error') persist(); });
  ui.exportMd.addEventListener('click', exportMarkdown);
  ui.exportJson.addEventListener('click', () => { download(notesFileName(), JSON.stringify(notesDocument(), null, 1), 'application/json'); notify(`${notesFileName()}를 내려받았습니다.`); });
  ui.importJson.addEventListener('click', () => ui.importInput.click());
  ui.importInput.addEventListener('change', () => { const file = ui.importInput.files[0]; ui.importInput.value = ''; if (file && state.book) importNotes(file); });

  ui.list.addEventListener('click', (event) => {
    const card = event.target.closest('.note-card'); if (!card) return;
    const id = card.dataset.id; const annotation = find(id); if (!annotation) return;
    const on = (selector) => event.target.closest(selector);
    if (on('[data-remove]')) removeAnnotation(id);
    else if (on('[data-go]')) openAnnotation(id);
    else if (on('[data-open-ask]')) { N.asking.add(id); renderList(); focusCard(id, '[data-ask]'); }
    else if (on('[data-send]')) ask(id, card.querySelector('[data-ask]').value);
    else if (on('[data-preset]')) ask(id, aiSettings().presets[Number(on('[data-preset]').dataset.preset)][1]);
    else if (on('[data-stop]')) N.live.get(id)?.stream?.abort();
    else if (on('[data-cite]')) { const [turn, cite] = on('[data-cite]').dataset.cite.split(':').map(Number); openCitation(annotation, turn, cite); }
    else if (on('[data-pin]')) {
      const index = Number(on('[data-pin]').dataset.pin);
      if (annotation.pinned === index) delete annotation.pinned; else annotation.pinned = index;
      touch(annotation); renderList();
    } else if (on('[data-to-memo]')) {
      const turn = annotation.thread[Number(on('[data-to-memo]').dataset.toMemo)];
      annotation.note = `${annotation.note ? `${annotation.note.trim()}\n\n` : ''}${turn.text}`; annotation.tags = tagsOf(annotation.note);
      touch(annotation); decorate(annotation); renderList(); notify('답을 메모로 복사했습니다. 메모에서 고쳐 쓸 수 있습니다.');
    }
  });
  ui.list.addEventListener('input', (event) => {
    const card = event.target.closest('.note-card'); const annotation = card && find(card.dataset.id); if (!annotation) return;
    if (event.target.matches('[data-memo]')) {
      annotation.note = event.target.value; annotation.tags = tagsOf(annotation.note); touch(annotation); decorate(annotation); autoGrow(event.target);
      card.querySelector('.tags').innerHTML = annotation.tags.map((tag) => `<span>${esc(tag)}</span>`).join(' ');
    } else if (event.target.matches('[data-ask]')) N.drafts.set(annotation.id, event.target.value);
  });
  ui.list.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.isComposing && event.target.matches('[data-ask]')) {
      event.preventDefault(); ask(event.target.closest('.note-card').dataset.id, event.target.value);
    }
  });

  ui.settingsButton.addEventListener('click', () => openSettings());
  ui.settingsSave.addEventListener('click', saveSettings);
  ui.settingsCancel.addEventListener('click', () => ui.settings.close());
  ui.keyClear.addEventListener('click', () => { ui.key.value = ''; N.key = ''; try { localStorage.removeItem('yeobaek:aiKey'); } catch { /* ignore */ } notify('저장된 API 키를 지웠습니다.'); });
  ui.consentCancel.addEventListener('click', () => ui.consent.close());

  /* ---------- Hooks from the reader ---------- */

  hooks.pageRendered = () => {
    hideBar();
    if (!state.book) return;
    tagBlocks(app.content, state.page);
    if (N.bookId !== state.bookId) return; // this book's notes are not loaded yet; loadNotes paints when they are
    N.list.forEach(paint);
    if (N.scope === 'page') renderList();
  };
  hooks.bookOpened = (text) => { ui.toggle.hidden = false; loadNotes(text); };
  hooks.changed = schedulePersist;
  hooks.key = (event) => {
    const key = event.key.toLowerCase();
    if (key === 'h' || key === 'ㅗ') annotateSelection(N.lastColor);
    else if (key === 'm' || key === 'ㅡ') { if (selectionParts().length) startMemo(); }
    else if (key === 'a' || key === 'ㅁ') { if (selectionParts().length) startAsk(); }
  };

  window.addEventListener('beforeunload', () => { if (state.book && N.loaded) store.set(bookKey('notes'), notesDocument()); });
  setPanel(Boolean(store.get('notesPanel', store.get('hlPanel', false))), false);
  setFileState('local');
})();
