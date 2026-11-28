/* Export menu: EPUB, PDF, To Kindle, To Google Drive.
 *
 * A page cannot hand a file to another service by itself, so the last two work like this:
 *  - To Kindle: the EPUB is downloaded and a Gmail message to the Kindle address opens (or Amazon's
 *    Send to Kindle page); the file is attached or dropped there. Addresses come from the local,
 *    untracked config.local.js or from the settings dialog, never from this file.
 *  - To Google Drive: the EPUB is downloaded and the Drive folder opens in the chosen account; or,
 *    when a folder synced by Google Drive for desktop was picked, the file is written straight into it.
 * PDF goes through the browser's print dialog: the whole book is laid out for print and the
 * destination "Save as PDF" writes the file with real text, embedded fonts and vector formulas. */
const YeobaekExport = (() => {
  const reader = typeof Yeobaek !== 'undefined' && Yeobaek.reader;
  if (!reader || typeof YeobaekEpub === 'undefined' || !YeobaekEpub) return null;
  const { state, esc, notify, handles, store } = reader;
  const $ = (selector) => document.querySelector(selector);
  const ui = {
    button: $('#export-button'), menu: $('#export-menu'), driveNote: $('#export-drive-note'),
    driveDialog: $('#drive-settings'), driveFolder: $('#drive-folder'), driveAccount: $('#drive-account'), driveLocal: $('#drive-local'),
    driveLocalPick: $('#drive-local-pick'), driveLocalClear: $('#drive-local-clear'), driveSave: $('#drive-save'), driveCancel: $('#drive-cancel'),
    kindleNote: $('#export-kindle-note'), kindleDialog: $('#kindle-settings'), kindleMethod: $('#kindle-method'), kindleSender: $('#kindle-sender'), kindleReceiver: $('#kindle-receiver'),
    kindleSave: $('#kindle-save'), kindleCancel: $('#kindle-cancel'),
  };
  if (!ui.button || !ui.menu) return null;

  const KINDLE_URL = 'https://www.amazon.com/sendtokindle';
  const DRIVE_URL = 'https://drive.google.com/drive/my-drive';
  const DRIVE_KEY = 'export-drive';
  const E = { busy: false, drive: null };

  /* ---------- Menu ---------- */

  const items = () => [...ui.menu.querySelectorAll('[role="menuitem"]:not([hidden])')];
  function openMenu() {
    if (!state.book) { notify('먼저 책을 여세요.'); return; }
    ui.menu.hidden = false; ui.button.setAttribute('aria-expanded', 'true');
    items()[0]?.focus();
  }
  function closeMenu(focusButton = false) {
    if (ui.menu.hidden) return;
    ui.menu.hidden = true; ui.button.setAttribute('aria-expanded', 'false');
    if (focusButton) ui.button.focus();
  }
  ui.button.addEventListener('click', () => (ui.menu.hidden ? openMenu() : closeMenu()));
  document.addEventListener('pointerdown', (event) => { if (!ui.menu.hidden && !event.target.closest('.menu-wrap')) closeMenu(); });
  ui.menu.addEventListener('keydown', (event) => {
    const list = items(); const at = list.indexOf(document.activeElement);
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeMenu(true); }
    else if (event.key === 'ArrowDown') { event.preventDefault(); event.stopPropagation(); list[(at + 1) % list.length].focus(); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); event.stopPropagation(); list[(at - 1 + list.length) % list.length].focus(); }
    else if (event.key === 'Tab') closeMenu();
  });
  ui.menu.addEventListener('click', (event) => {
    const item = event.target.closest('[data-export]');
    if (!item) return;
    closeMenu();
    if (item.dataset.export === 'kindle-settings') { openKindleSettings(); return; }
    if (item.dataset.export === 'drive-settings') { openDriveSettings(); return; }
    const action = { epub: toEpub, pdf: toPdf, kindle: toKindle, drive: toDrive }[item.dataset.export];
    if (action) guarded(action);
  });

  async function guarded(action) {
    if (E.busy) { notify('내보내는 중입니다. 잠시만 기다리세요.'); return null; }
    if (document.body.classList.contains('editing')) { notify('편집을 끝낸 뒤 내보내세요.'); return null; }
    E.busy = true; ui.button.textContent = '만드는 중…'; ui.button.disabled = true;
    try { return await action(); } catch (error) {
      notify(`내보내지 못했습니다: ${error.message || error}`); return { error: String(error.message || error) };
    } finally { E.busy = false; ui.button.textContent = 'Export'; ui.button.disabled = false; }
  }
  /* ---------- EPUB ---------- */

  const toEpub = () => YeobaekEpub.run();

  /* ---------- To Kindle ---------- */

  /** Opens `url` in a new tab right away (while the click still counts) and cuts the link back to this page. */
  function openTab(url) {
    const tab = window.open(url, '_blank');
    if (tab) { try { tab.opener = null; } catch { /* already detached */ } }
    return !!tab;
  }
  // How the book reaches the Kindle. Defaults come from config.local.js (kept out of git because it
  // holds mail addresses); the settings dialog overrides them in this browser.
  const GMAIL_LIMIT = 25 * 1048576;
  const validMail = (value) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  function kindleSettings() {
    const base = (window.YeobaekConfig && window.YeobaekConfig.kindle) || {};
    const saved = store.get('kindle', null) || {};
    const pick = (key) => String(saved[key] ?? base[key] ?? '').trim();
    const sender = pick('sender'); const receiver = pick('receiver');
    const method = (pick('method') || (receiver ? 'email' : 'web')) === 'email' && validMail(receiver) ? 'email' : 'web';
    return { method, sender, receiver };
  }
  /** Gmail's compose window, addressed to the Kindle and opened in the sender's account. */
  function gmailCompose({ sender, receiver }, title) {
    const params = new URLSearchParams({ view: 'cm', fs: '1', to: receiver, su: title });
    if (validMail(sender)) params.set('authuser', sender);
    return `https://mail.google.com/mail/?${params}`;
  }
  function refreshKindle() {
    const k = kindleSettings();
    ui.kindleNote.textContent = k.method === 'email' ? `EPUB을 내려받고 ${k.receiver}로 보낼 메일 열기` : 'EPUB을 내려받고 Send to Kindle 열기';
  }
  async function toKindle() {
    const k = kindleSettings(); const byMail = k.method === 'email';
    const opened = openTab(byMail ? gmailCompose(k, state.book.title) : KINDLE_URL);
    const result = await YeobaekEpub.build();
    if (!result || !result.blob) return result;
    YeobaekEpub.download(result.blob, result.name);
    const where = byMail ? 'Gmail 작성 창' : 'Send to Kindle 창';
    let message = opened ? `${result.name}을 내려받았습니다. 열린 ${where}에 ${byMail ? '첨부해 보내세요' : '끌어다 놓으세요'}.`
      : `${result.name}을 내려받았습니다. 새 창이 막혔습니다. 팝업을 허용하고 다시 누르세요.`;
    if (byMail && result.bytes > GMAIL_LIMIT) message = `${result.name}은 ${(result.bytes / 1048576).toFixed(0)}MB라 Gmail 첨부 한도(25MB)를 넘습니다. To Kindle 설정에서 ‘Send to Kindle 웹’으로 바꾸세요.`;
    notify(message);
    return { ...result, opened, method: k.method };
  }
  function openKindleSettings() {
    const k = kindleSettings();
    ui.kindleMethod.value = k.method; ui.kindleSender.value = k.sender; ui.kindleReceiver.value = k.receiver;
    ui.kindleDialog.showModal();
  }
  ui.kindleCancel.addEventListener('click', () => ui.kindleDialog.close());
  ui.kindleSave.addEventListener('click', () => {
    const sender = ui.kindleSender.value.trim(); const receiver = ui.kindleReceiver.value.trim(); const method = ui.kindleMethod.value;
    if (method === 'email' && !validMail(receiver)) { notify('받는 Kindle 주소를 확인하세요 (예: 이름@kindle.com).'); ui.kindleReceiver.focus(); return; }
    if (sender && !validMail(sender)) { notify('보내는 Gmail 주소를 확인하세요.'); ui.kindleSender.focus(); return; }
    store.set('kindle', { method, sender, receiver });
    ui.kindleDialog.close(); refreshKindle();
    notify('To Kindle 설정을 이 브라우저에 저장했습니다.');
  });

  /* ---------- To Google Drive ---------- */

  // Where the book goes on Drive. Defaults come from config.local.js (kept out of git: a folder link and
  // an account are personal); the settings dialog overrides them in this browser.
  //  - a folder on this PC synced by Google Drive for desktop, when one was chosen: the file is written there
  //  - otherwise the Drive folder is opened in the account and the file is downloaded for dropping in
  function driveSettings() {
    const base = (window.YeobaekConfig && window.YeobaekConfig.drive) || {};
    const saved = store.get('drive', null) || {};
    const pick = (key) => String(saved[key] ?? base[key] ?? '').trim();
    return { folder: pick('folder'), account: pick('account') };
  }
  /** Accepts a folder link or a bare folder id. */
  const driveFolderId = (value) => (/\/folders\/([A-Za-z0-9_-]{10,})/.exec(value) || /^([A-Za-z0-9_-]{10,})$/.exec(value) || [])[1] || '';
  function driveUrl({ folder, account }) {
    const id = driveFolderId(folder);
    const url = new URL(id ? `https://drive.google.com/drive/folders/${id}` : DRIVE_URL);
    if (validMail(account)) url.searchParams.set('authuser', account);
    return url.href;
  }
  async function refreshDrive() {
    E.drive = window.showDirectoryPicker ? await handles.get(DRIVE_KEY) : null;
    const d = driveSettings();
    ui.driveNote.textContent = E.drive ? `‘${E.drive.name}’ 폴더에 EPUB 저장`
      : driveFolderId(d.folder) ? `EPUB을 내려받고 Drive 폴더 열기${d.account ? ` (${d.account})` : ''}` : 'EPUB을 내려받고 Google Drive 열기';
  }
  async function writeInto(dir, result) {
    const file = await dir.getFileHandle(result.name, { create: true });
    const writable = await file.createWritable(); await writable.write(result.blob); await writable.close();
  }
  async function saveToDriveFolder(dir) {
    // Asked first, while the click still counts as a user action.
    let granted = false;
    try { granted = (await dir.queryPermission({ mode: 'readwrite' })) === 'granted' || (await dir.requestPermission({ mode: 'readwrite' })) === 'granted'; } catch { /* treated as refused */ }
    if (!granted) { notify('Drive 폴더에 쓸 권한이 없습니다.'); return { error: 'permission' }; }
    const result = await YeobaekEpub.build();
    if (!result || !result.blob) return result;
    await writeInto(dir, result);
    notify(`‘${dir.name}’ 폴더에 ${result.name}을 저장했습니다 (${result.summary}). Google Drive가 올립니다.`);
    return { ...result, folder: dir.name };
  }
  async function toDrive() {
    await refreshDrive();
    if (E.drive) return saveToDriveFolder(E.drive);
    const d = driveSettings();
    const opened = openTab(driveUrl(d));
    const result = await YeobaekEpub.build();
    if (!result || !result.blob) return result;
    YeobaekEpub.download(result.blob, result.name);
    const where = driveFolderId(d.folder) ? 'Drive 폴더 창' : 'Google Drive 창';
    notify(opened ? `${result.name}을 내려받았습니다. 열린 ${where}에 끌어다 놓으세요.` : `${result.name}을 내려받았습니다. 새 창이 막혔습니다. 팝업을 허용하고 다시 누르세요.`);
    return { ...result, opened };
  }
  function showDriveLocal() {
    ui.driveLocal.textContent = E.drive ? `PC 폴더 ‘${E.drive.name}’에 바로 저장합니다.` : 'PC 폴더를 정하지 않았습니다. Drive 폴더를 새 창으로 엽니다.';
    ui.driveLocalClear.hidden = !E.drive; ui.driveLocalPick.hidden = typeof window.showDirectoryPicker !== 'function';
  }
  async function openDriveSettings() {
    await refreshDrive();
    const d = driveSettings();
    ui.driveFolder.value = d.folder; ui.driveAccount.value = d.account;
    showDriveLocal();
    ui.driveDialog.showModal();
  }
  ui.driveCancel.addEventListener('click', () => ui.driveDialog.close());
  ui.driveLocalPick.addEventListener('click', async () => {
    let dir;
    try { dir = await window.showDirectoryPicker({ id: 'yeobaek-drive', mode: 'readwrite' }); } catch { return; }
    await handles.set(DRIVE_KEY, dir); await refreshDrive(); showDriveLocal();
  });
  ui.driveLocalClear.addEventListener('click', async () => { await handles.remove(DRIVE_KEY); await refreshDrive(); showDriveLocal(); });
  ui.driveSave.addEventListener('click', async () => {
    const folder = ui.driveFolder.value.trim(); const account = ui.driveAccount.value.trim();
    if (folder && !driveFolderId(folder)) { notify('Drive 폴더 주소를 확인하세요 (…/drive/folders/… 형태).'); ui.driveFolder.focus(); return; }
    if (account && !validMail(account)) { notify('Google 계정 주소를 확인하세요.'); ui.driveAccount.focus(); return; }
    store.set('drive', { folder, account });
    ui.driveDialog.close(); await refreshDrive();
    notify('To Google Drive 설정을 이 브라우저에 저장했습니다.');
  });

  /* ---------- PDF ---------- */

  /** Lays the whole book out in #print-root. Returns counts; nothing is printed yet. */
  async function preparePdf() {
    const book = state.book;
    const ids = new Map(book.nodes.map((n, k) => [n.id, `pdf-h${k + 1}`]));
    const formulas = new Map(); let pictures = 0; let missing = 0;
    const collect = {
      math(tex, display) { const key = YeobaekEpub.mathKey(tex, display); if (!formulas.has(key)) formulas.set(key, { tex: tex.trim(), display }); return ''; },
      image: () => '', link: () => '#', id: () => 'x',
    };
    book.pages.forEach((p, index) => reader.exportPage(index, collect));
    const failed = await YeobaekEpub.typeset(formulas, (done, total) => notify(`수식을 준비하는 중 ${done}/${total}`));
    for (const item of formulas.values()) {
      if (item.failed) { item.html = YeobaekEpub.rawMath(item); continue; }
      const svg = item.node.cloneNode(true);
      svg.removeAttribute('width'); svg.removeAttribute('height');
      svg.setAttribute('class', 'math'); svg.setAttribute('style', YeobaekEpub.mathStyle(item)); svg.setAttribute('aria-label', item.tex);
      item.html = item.display ? `<span class="math-display">${svg.outerHTML}</span>` : svg.outerHTML;
    }
    const render = {
      math: (tex, display) => formulas.get(YeobaekEpub.mathKey(tex, display)).html,
      image(src) { const url = reader.imageUrl(src); if (url) pictures += 1; else missing += 1; return url; },
      link: (target) => `#${ids.get(target.id)}`,
      id: (n) => ids.get(n.id),
    };
    const toc = (nodes) => (nodes.length ? `<ol>${nodes.map((n) => `<li><a href="#${n.container ? ids.get(book.pages[n.pageIndex].node.id) : ids.get(n.id)}">${esc(n.title)}</a>${toc(n.children)}</li>`).join('')}</ol>` : '');
    const today = new Date().toISOString().slice(0, 10);
    const html = `<section class="pdf-title"><h1>${esc(book.title)}</h1><p>Markdown Reader · ${today}</p></section>` +
      `<nav class="pdf-toc"><h2>차례</h2>${toc(book.roots)}</nav>` +
      book.pages.map((p, index) => `<section class="pdf-chapter">${reader.exportPage(index, render)}</section>`).join('');

    donePdf();
    const root = document.createElement('div');
    root.id = 'print-root'; root.lang = 'ko'; root.innerHTML = html;
    root.querySelectorAll('img[loading]').forEach((img) => img.removeAttribute('loading'));
    root.querySelectorAll('a[target]').forEach((a) => a.removeAttribute('target'));
    document.body.appendChild(root); document.body.classList.add('printing-book');
    // Pictures must be decoded before the print dialog takes its snapshot.
    await Promise.all([...root.querySelectorAll('img')].map((img) => (img.complete ? null : new Promise((resolve) => { img.onload = resolve; img.onerror = resolve; setTimeout(resolve, 8000); }))));
    try { await document.fonts.ready; } catch { /* fonts fall back */ }
    E.title = document.title; document.title = YeobaekEpub.fileBase(book.title);
    return { chapters: book.pages.length, images: pictures, missingImages: missing, formulas: formulas.size, mathFailed: failed };
  }
  function donePdf() {
    document.getElementById('print-root')?.remove(); document.body.classList.remove('printing-book');
    if (E.title) { document.title = E.title; E.title = ''; }
  }
  async function toPdf() {
    notify('PDF 준비 중입니다.');
    const stats = await preparePdf();
    const parts = [`장 ${stats.chapters}`, `그림 ${stats.images}`, `수식 ${stats.formulas - stats.mathFailed}`];
    if (stats.missingImages) parts.push(`못 찾은 그림 ${stats.missingImages}`);
    if (stats.mathFailed) parts.push(`변환 못한 수식 ${stats.mathFailed}`);
    notify(`인쇄 창에서 대상을 ‘PDF로 저장’으로 고르세요 (${parts.join(' · ')}).`);
    await new Promise((resolve) => setTimeout(resolve, 150));
    window.addEventListener('afterprint', donePdf, { once: true });
    window.print(); // in Chrome this returns when the dialog closes; afterprint then clears the print layout
    return stats;
  }

  refreshDrive(); refreshKindle();
  return { toEpub: () => guarded(toEpub), toPdf: () => guarded(toPdf), toKindle: () => guarded(toKindle), toDrive: () => guarded(toDrive), preparePdf, donePdf, kindleSettings, driveSettings, driveUrl, state: E };
})();
