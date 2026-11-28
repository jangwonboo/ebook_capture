/* Library: pick a book from a folder of books instead of opening folders one by one.
 *
 * Two sources, the same list:
 *  - a connected folder (Chrome/Edge): the folder is chosen once and remembered; books open with
 *    write access, so notes files and edits are saved next to the Markdown as before
 *  - library/index.json next to the app, when the reader is served over http(s): read-only
 *
 * A book is a Markdown file; its images are found through its own image links. */
const YeobaekLibrary = (() => {
  const reader = typeof Yeobaek !== 'undefined' && Yeobaek.reader;
  if (!reader) return null;
  const { state, els, store, esc, notify, MARKDOWN } = reader;
  const $ = (selector) => document.querySelector(selector);
  const ui = {
    view: $('#library'), list: $('#library-list'), status: $('#library-status'), hint: $('#library-hint'),
    connect: $('#library-connect'), refresh: $('#library-refresh'), button: $('#library-button'),
  };
  if (!ui.view) return null;

  const canPick = typeof window.showDirectoryPicker === 'function';
  const served = /^https?:$/.test(location.protocol);
  // Files the reader writes next to a book are not books themselves.
  const NOT_A_BOOK = /(\.original|\.notes)\.(md|markdown)$|^readme\.(md|markdown)$/i;
  const SKIP_DIRS = new Set(['assets', 'images', 'tmp', 'node_modules']);
  const L = { root: null, needsPermission: false, local: null, remote: null, covers: [], busy: false };

  const remember = (handle) => reader.handles.set('library', handle);
  const recall = () => reader.handles.get('library');

  /* ---------- Finding books ---------- */

  const prettyTitle = (name) => name.replace(/\.[^.]+$/, '').replace(/_/g, ' ').trim();
  const sizeText = (bytes) => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(bytes / 1024))}KB`);
  const firstImage = (text) => { const m = /!\[[^\]]*\]\(([^)\s]+)\)/.exec(text); return m && !/^(https?:|data:)/i.test(m[1]) ? m[1] : ''; };
  const imageLinks = (text) => [...new Set([...text.matchAll(/!\[[^\]]*\]\(([^)\s]+)\)/g)].map((m) => m[1]).filter((src) => !/^(https?:|data:)/i.test(src)))];
  const clean = (src) => { const link = src.split(/[?#]/)[0]; try { return decodeURIComponent(link); } catch { return link; } };

  /** Follows a relative link from a folder handle; null when any part is missing. */
  async function resolveFile(dir, link) {
    const parts = clean(link).replace(/\\/g, '/').split('/').filter((part) => part && part !== '.');
    if (!parts.length || parts.includes('..') || /^[a-z]:$/i.test(parts[0])) return null;
    try {
      let at = dir;
      for (const part of parts.slice(0, -1)) at = await at.getDirectoryHandle(part);
      return await (await at.getFileHandle(parts[parts.length - 1])).getFile();
    } catch { return null; }
  }

  async function scan(root) {
    const books = [];
    const walk = async (dir, prefix, depth) => {
      const subdirs = [];
      for await (const [name, handle] of dir.entries()) {
        if (handle.kind === 'file') {
          if (MARKDOWN.test(name) && !NOT_A_BOOK.test(name)) books.push({ dir, md: handle, name, where: prefix });
        } else if (!name.startsWith('.') && !SKIP_DIRS.has(name.toLowerCase())) subdirs.push([name, handle]);
      }
      if (depth < 3) for (const [name, handle] of subdirs) await walk(handle, `${prefix}${name}/`, depth + 1);
    };
    await walk(root, '', 0);
    for (const book of books) {
      const file = await book.md.getFile();
      book.id = `local:${book.where}${book.name}`; book.title = prettyTitle(book.name);
      book.bytes = file.size; book.modified = file.lastModified;
      book.coverLink = firstImage(await file.slice(0, 60000).text());
    }
    return books.sort((a, b) => b.modified - a.modified);
  }

  async function loadIndex() {
    try {
      const res = await fetch('library/index.json', { cache: 'no-cache' });
      if (!res.ok) return null;
      const data = await res.json();
      const urlOf = (path) => new URL(`library/${path.split('/').map(encodeURIComponent).join('/')}`, location.href).href;
      return (data.books || []).map((b) => ({
        id: `web:${b.md}`, title: b.title || prettyTitle(b.md.split('/').pop()), name: b.md.split('/').pop(),
        where: b.md.split('/').slice(0, -1).join('/'), bytes: b.bytes || 0, modified: b.modified ? Date.parse(b.modified) : 0,
        url: urlOf(b.md), coverUrl: b.cover ? urlOf(b.cover) : '', chapters: b.chapters || 0,
      })).sort((a, b) => b.modified - a.modified);
    } catch { return null; }
  }

  /* ---------- Opening ---------- */

  async function openLocal(book) {
    const file = await book.md.getFile();
    const text = await file.text();
    const entries = [{ file, path: book.name, dir: book.dir }];
    const links = imageLinks(text);
    const files = await Promise.all(links.map((src) => resolveFile(book.dir, src)));
    files.forEach((image, k) => { if (image) entries.push({ file: image, path: clean(links[k]).replace(/\\/g, '/').replace(/^\.\//, ''), dir: book.dir }); });
    await reader.openEntries(entries);
  }
  async function openWeb(book) {
    const res = await fetch(book.url, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`${res.status}`);
    reader.openRemote(book.name, await res.text(), new URL('.', book.url).href);
  }
  async function open(id) {
    const book = books().find((b) => b.id === id);
    if (!book || L.busy) return;
    L.busy = true;
    try {
      await (book.md ? openLocal(book) : openWeb(book));
      store.set('library:last', book.id);
    } catch (error) { notify(`책을 열지 못했습니다: ${error.message || error}`); } finally { L.busy = false; }
  }

  /* ---------- Screen ---------- */

  const books = () => L.local || L.remote || [];
  function render() {
    const list = books(); const last = store.get('library:last', '');
    const show = canPick || !!L.remote;
    ui.view.hidden = !show; els.welcome.classList.toggle('has-library', show);
    if (!show) return;

    ui.connect.hidden = !canPick; ui.refresh.hidden = !L.local;
    ui.connect.textContent = L.needsPermission ? '서재 열기' : L.root ? '다른 폴더 연결' : '서재 폴더 연결';
    ui.status.textContent = L.local ? `${L.root.name} · ${list.length}권` : L.remote ? `${list.length}권 · 읽기 전용` : '';
    const hint = L.needsPermission ? `지난번에 연결한 ‘${L.root.name}’ 폴더를 다시 쓰려면 ‘서재 열기’를 누르고 접근을 허용하세요.`
      : !L.root && canPick ? `책 폴더들이 들어 있는 폴더를 한 번 연결하면 여기에 책 목록이 나옵니다. 앱 폴더의 library를 고르거나, 책을 모아 둔 다른 폴더를 골라도 됩니다.${L.remote ? ' 연결하면 주석과 편집이 책 폴더에 저장됩니다.' : ''}`
        : L.local && !list.length ? '이 폴더에서 Markdown 책을 찾지 못했습니다. 책마다 폴더를 만들고 그 안에 .md와 assets를 두세요.' : '';
    ui.hint.hidden = !hint; ui.hint.textContent = hint;

    ui.list.innerHTML = list.map((book) => {
      const reading = state.book && store.get('library:last', '') === book.id;
      const day = book.modified ? new Date(book.modified).toISOString().slice(0, 10) : '';
      const meta = [sizeText(book.bytes), day].filter(Boolean).join(' · ');
      return `<button class="book-card${reading ? ' current' : ''}" type="button" data-book="${esc(book.id)}" title="${esc(book.title)}">` +
        `<span class="book-cover">${book.id === last ? `<span class="book-badge">${reading ? '읽는 중' : '최근'}</span>` : ''}<span class="cover-text">${esc(book.title)}</span>` +
        `${book.coverUrl ? `<img src="${esc(book.coverUrl)}" alt="" loading="lazy">` : ''}</span>` +
        `<span class="book-name">${esc(book.title)}</span><span class="book-meta">${esc(meta)}</span></button>`;
    }).join('');
    ui.list.querySelectorAll('img').forEach((img) => img.addEventListener('error', () => img.remove()));
    if (L.local) fillCovers(list);
  }
  /** Local covers are read after the list is on screen, one book at a time. */
  async function fillCovers(list) {
    const token = (L.coverToken = {});
    L.covers.forEach((url) => URL.revokeObjectURL(url)); L.covers = [];
    for (const book of list) {
      if (!book.coverLink) continue;
      const file = await resolveFile(book.dir, book.coverLink);
      if (L.coverToken !== token) return;
      if (!file) continue;
      const cover = [...ui.list.querySelectorAll('.book-card')].find((card) => card.dataset.book === book.id)?.querySelector('.book-cover');
      if (!cover) continue;
      const url = URL.createObjectURL(file); L.covers.push(url);
      const img = document.createElement('img'); img.alt = ''; img.src = url; cover.appendChild(img);
    }
  }

  async function useRoot(root) {
    L.root = root; L.needsPermission = false;
    ui.status.textContent = '책을 찾는 중…';
    try { L.local = await scan(root); } catch { L.local = []; notify('서재 폴더를 읽지 못했습니다.'); }
    render();
  }
  async function connect() {
    if (L.needsPermission) {
      let granted = false;
      try { granted = (await L.root.requestPermission({ mode: 'readwrite' })) === 'granted'; } catch { /* dismissed */ }
      if (granted) await useRoot(L.root); else notify('폴더 접근이 허용되지 않았습니다.');
      return;
    }
    let root;
    try { root = await window.showDirectoryPicker({ id: 'yeobaek-library', mode: 'readwrite' }); } catch { return; }
    await remember(root);
    await useRoot(root);
    notify(`서재 ‘${root.name}’: ${L.local.length}권`);
  }
  function show() {
    if (document.body.classList.contains('editing')) { notify('편집을 끝낸 뒤 서재로 가세요.'); return; }
    if (ui.view.hidden) { notify(canPick ? '서재를 쓸 수 없습니다.' : '이 브라우저에서는 서재 폴더를 연결할 수 없습니다. ‘파일 열기’를 쓰세요.'); return; }
    els.readerView.hidden = true; els.welcome.hidden = false;
    render();
  }

  ui.list.addEventListener('click', (event) => { const card = event.target.closest('[data-book]'); if (card) open(card.dataset.book); });
  ui.connect.addEventListener('click', connect);
  ui.refresh.addEventListener('click', () => { if (L.root) useRoot(L.root); });
  if (ui.button) ui.button.addEventListener('click', show);

  async function start() {
    render();
    if (served) { L.remote = await loadIndex(); render(); }
    if (!canPick) return;
    const root = await recall();
    if (!root) return;
    L.root = root;
    let permission = 'prompt';
    try { permission = await root.queryPermission({ mode: 'readwrite' }); } catch { /* treat as not granted */ }
    if (permission === 'granted') await useRoot(root); else { L.needsPermission = true; render(); }
  }
  const ready = start();

  return { show, connect, open, ready, state: L, books };
})();
