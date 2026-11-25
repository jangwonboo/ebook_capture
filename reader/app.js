/* 여백 — local Markdown reader. Left: heading tree. Right: one chapter per screen. */

const Yeobaek = (() => {
  // Headings at this level or shallower open a new screen; deeper ones stay inside it.
  const PAGE_LEVEL = 2;

  const slugify = (value, fallback) =>
    (value || '').toLowerCase().replace(/[^\w가-힣]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64) || fallback;
  const plain = (value) => value.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/[*`]/g, '');

  function blockText(block) {
    switch (block.type) {
      case 'paragraph': case 'code': return block.text;
      case 'quote': return block.paragraphs.join(' ');
      case 'list': return block.items.join(' ');
      case 'table': return [block.header || [], ...block.rows].flat().join(' ');
      case 'image': return block.alt;
      case 'insight': return block.blocks.map(blockText).join(' ');
      default: return '';
    }
  }

  function parseTable(lines) {
    const rows = lines.map((line) => line.replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim()));
    const hasHeader = rows.length > 1 && rows[1].every((cell) => /^:?-{2,}:?$/.test(cell));
    return hasHeader ? { type: 'table', header: rows[0], rows: rows.slice(2) } : { type: 'table', header: null, rows };
  }

  /** Markdown text -> flat heading nodes, each holding the blocks that follow its heading. */
  function parseNodes(text) {
    const source = text.replace(/^﻿/, '').replace(/\r\n?/g, '\n')
      .replace(/^---\n[\s\S]*?\n---[ \t]*(\n|$)/, ''); // front matter only at the very start
    const nodes = [];
    let node = null; let target = null; let open = null; let code = null;

    const startNode = (level, title) => {
      node = { level, title, blocks: [], pages: '' };
      nodes.push(node); target = node.blocks;
    };
    const ensure = () => { if (!node) startNode(PAGE_LEVEL, '처음'); };
    const close = () => {
      if (!open) return;
      ensure();
      if (open.type === 'paragraph') target.push({ type: 'paragraph', text: open.lines.join(' ').replace(/\s+/g, ' ') });
      else if (open.type === 'quote') {
        const paragraphs = open.lines.join('\n').split(/\n\s*\n/).map((part) => part.replace(/\s+/g, ' ').trim()).filter(Boolean);
        if (paragraphs.length) target.push({ type: 'quote', paragraphs });
      } else if (open.type === 'list') target.push({ type: 'list', ordered: open.ordered, items: open.items });
      else if (open.type === 'table') target.push(parseTable(open.lines));
      open = null;
    };

    for (const raw of source.split('\n')) {
      if (code) {
        if (/^\s*(```|~~~)/.test(raw)) { ensure(); target.push({ type: 'code', text: code.join('\n') }); code = null; } else code.push(raw);
        continue;
      }
      const line = raw.trim();
      if (/^(```|~~~)/.test(line)) { close(); code = []; continue; }

      const heading = /^(#{1,6})\s+(.+?)\s*#*$/.exec(line);
      if (heading) {
        close();
        const title = plain(heading[2]).trim();
        if (/^insight$/i.test(title)) {
          ensure();
          const insight = { type: 'insight', blocks: [] };
          node.blocks.push(insight); target = insight.blocks;
        } else startNode(heading[1].length, title);
        continue;
      }
      if (/^<!--.*-->$/.test(line)) {
        const pages = /pages:\s*(\d+)\s*-\s*(\d+)/.exec(line);
        if (pages) { ensure(); node.pages = pages[1] === pages[2] ? pages[1] : `${pages[1]}–${pages[2]}`; }
        continue;
      }
      if (!line || /^([-*_])(\s*\1){2,}$/.test(line)) { close(); continue; }

      const image = /^!\[([^\]]*)\]\(([^)\s]+)[^)]*\)$/.exec(line);
      if (image) { close(); ensure(); target.push({ type: 'image', alt: image[1], src: image[2] }); continue; }

      const quote = /^>\s?(.*)$/.exec(line);
      if (quote) { if (open?.type !== 'quote') { close(); open = { type: 'quote', lines: [] }; } open.lines.push(quote[1]); continue; }

      if (line.startsWith('|')) { if (open?.type !== 'table') { close(); open = { type: 'table', lines: [] }; } open.lines.push(line); continue; }

      const item = /^([-*+]|\d+[.)])\s+(.*)$/.exec(line);
      if (item) {
        const ordered = /\d/.test(item[1]);
        if (open?.type !== 'list' || open.ordered !== ordered) { close(); open = { type: 'list', ordered, items: [] }; }
        open.items.push(item[2]); continue;
      }
      if (open?.type === 'list') { open.items[open.items.length - 1] += ` ${line}`; continue; }
      if (open?.type !== 'paragraph') { close(); open = { type: 'paragraph', lines: [] }; }
      open.lines.push(line);
    }
    close();
    if (code) { ensure(); target.push({ type: 'code', text: code.join('\n') }); }
    const merged = mergeSplitHeadings(nodes);
    mergeLeadIns(merged);
    mergeCutParagraphs(merged);
    return merged;
  }

  /* ---- Repairing text that page breaks and OCR line breaks cut apart ---- */

  const ENDS_SENTENCE = /[.?!…。:;”"]["'”’」』》)\]]*$/;
  const lettersOnly = (token) => token.replace(/[^0-9A-Za-z가-힣]/g, '');

  /**
   * A short phrase left dangling right before a heading ("마흔," / "삶에서") is the heading's first line:
   * only Hangul, at most 15 characters, ending in a comma or a particle that cannot close a sentence.
   */
  function isLeadIn(text) {
    const phrase = text.replace(/^\*+|\*+$/g, '').trim();
    if (!phrase || phrase.length > 15 || !/^[가-힣\s,]+$/.test(phrase)) return false;
    // Single syllables are limited to particles that rarely end a noun, so labels like "내면" or "태도" stay put.
    return /(,|에서|에게|으로|부터|까지|처럼|보다|으면|하면|라면|이면|하고|이고|하며|이며|해서|지만|에는|에도|[을를은는에])$/.test(phrase);
  }
  function mergeLeadIns(nodes) {
    for (let i = 1; i < nodes.length; i += 1) {
      const node = nodes[i]; const blocks = nodes[i - 1].blocks; const last = blocks[blocks.length - 1];
      if (node.level <= PAGE_LEVEL || !last || last.type !== 'paragraph' || !isLeadIn(last.text)) continue;
      blocks.pop();
      node.title = `${last.text.replace(/^\*+|\*+$/g, '').trim()} ${node.title}`;
    }
  }

  /** Counts, for every word in the book, each of its leading substrings — the book is its own dictionary. */
  function wordStarts(nodes) {
    const starts = new Map();
    const visit = (blocks) => blocks.forEach((block) => {
      if (block.type === 'insight') { visit(block.blocks); return; }
      for (const token of blockText(block).split(/\s+/)) {
        const word = lettersOnly(token);
        for (let length = 1; length <= Math.min(word.length, 10); length += 1) {
          const prefix = word.slice(0, length); starts.set(prefix, (starts.get(prefix) || 0) + 1);
        }
      }
    });
    nodes.forEach((node) => visit(node.blocks));
    return starts;
  }

  /**
   * Decides whether a paragraph cut by a page break was cut inside a word ("순" + "탄하지") or between
   * words ("삶의" + "의미를"), and returns the glue: '' or ' '.
   */
  function glueFor(before, after, starts) {
    const lastToken = before.split(/\s+/).pop(); const firstToken = after.split(/\s+/)[0];
    const head = lettersOnly(lastToken); const tail = lettersOnly(firstToken);
    if (!/[가-힣]$/.test(lastToken) && !/[’'」』》)\]]$/.test(lastToken)) return ' '; // after a comma, digit or Latin letter
    if (!/^[가-힣]/.test(firstToken) || !tail) return ' ';
    if (/^[은는을를에의와과도로만씩며고면]$/.test(tail) || /^다[.!?]/.test(firstToken)) return ''; // a bare particle or ending cannot start a word
    // "정착" + "하지": a verb ending attaches to the noun before it, unless that noun already carries a particle.
    if (/^(하지|하고|하며|하는|하게|하여|해서|한다|했다|되는|되고|되지|된다|됐다)$/.test(tail) && !/[의와과을를에도만은는이가로서]$/.test(head)) return '';
    if (!/[가-힣]$/.test(lastToken)) return ' ';
    if (head && (starts.get(head + tail[0]) || 0) > 0) return ''; // the joined form occurs elsewhere as a word
    // The first half is a finished word ("인터넷의" + "정보들이"): it ends in a particle or a common ending.
    if (/(에서|으로|까지|부터|이나|거나|라는|라고|이며|이고|인데|이지만|하기|하는|하다|이다|습니다|였다|밖에|위해|통해|에게|처럼|보다|만큼|[의와과을를에도만은는이가로])$/.test(head)) return ' ';
    if (tail.length >= 2 && (starts.get(tail.slice(0, 2)) || 0) < 2) return ''; // the second half never starts a word elsewhere
    return ' ';
  }

  /** A paragraph of body-text length that stops without sentence punctuation continues in the next paragraph. */
  function mergeCutParagraphs(nodes) {
    const starts = wordStarts(nodes);
    const fold = (blocks) => {
      const out = [];
      for (const block of blocks) {
        if (block.type === 'insight') block.blocks = fold(block.blocks);
        const last = out[out.length - 1];
        const cut = last && last.type === 'paragraph' && block.type === 'paragraph' && last.text.length >= 40 && !ENDS_SENTENCE.test(last.text.replace(/\*+$/, ''));
        if (cut) last.text += glueFor(last.text, block.text, starts) + block.text; else out.push(block);
      }
      return out;
    };
    nodes.forEach((node) => { node.blocks = fold(node.blocks); });
  }

  /**
   * OCR turns a heading printed on two lines into two headings. Two same-level headings in a row,
   * the first with no text of its own, are read as one phrase unless they look like separate items.
   */
  function isSplitHeading(first, second) {
    if (first.level !== second.level || first.level <= PAGE_LEVEL) return false;
    if (first.blocks.length || first.pages) return false;
    if (first.title.length + second.title.length > 60) return false;
    if (/[.?!…。:;]["'”’」』)\]]?$/.test(first.title)) return false; // the first already ends a sentence
    const numbered = /^(\(?\d+[.)]|제\s*\d+|[①-⑳]|[IVX]+[.)]|[A-Z][.)]|[-•·■□▶◆])/;
    return !numbered.test(second.title);
  }
  function mergeSplitHeadings(nodes) {
    const merged = [];
    for (const node of nodes) {
      const prev = merged[merged.length - 1];
      if (prev && isSplitHeading(prev, node)) { prev.title = `${prev.title} ${node.title}`; prev.blocks = node.blocks; prev.pages = node.pages; } else merged.push(node);
    }
    return merged;
  }

  /** Builds the heading tree and decides which headings become screens. */
  function parseBook(text, sourceName) {
    const fallbackTitle = sourceName.replace(/\.[^.]+$/, '');
    let nodes = parseNodes(text);
    let title = fallbackTitle;

    const hasContent = (n) => n.blocks.some((block) => block.type !== 'insight' || block.blocks.length);
    const topLevel = nodes.filter((n) => n.level === 1);
    // A leading "# Title" with no text of its own is the book title, not a chapter:
    // either it is the only level-1 heading, or the next heading is another level-1 (e.g. "# Part 1").
    const first = nodes[0];
    if (nodes.length > 1 && first.level === 1 && !hasContent(first) && (topLevel.length === 1 || nodes[1].level === 1)) {
      title = first.title; nodes = nodes.slice(1);
    }
    if (!nodes.length) nodes = [{ level: PAGE_LEVEL, title: fallbackTitle, pages: '', blocks: [{ type: 'paragraph', text: '표시할 본문을 찾지 못했습니다.' }] }];

    const used = new Map(); const byId = new Map(); const roots = []; const stack = [];
    nodes.forEach((n, index) => {
      const base = slugify(n.title, `section-${index + 1}`);
      const count = (used.get(base) || 0) + 1; used.set(base, count);
      n.id = count === 1 ? base : `${base}-${count}`;
      byId.set(n.id, n);
      while (stack.length && stack[stack.length - 1].level >= n.level) stack.pop();
      n.parent = stack[stack.length - 1] || null; n.children = [];
      (n.parent ? n.parent.children : roots).push(n);
      stack.push(n);
      const body = n.blocks.map(blockText).join(' ');
      n.text = plain(body); n.lower = `${n.title} ${n.text}`.toLowerCase();
    });

    const pages = []; let page = null;
    nodes.forEach((n, index) => {
      const next = nodes[index + 1];
      const isContainer = n.level <= PAGE_LEVEL && !hasContent(n) && next && next.level > n.level && next.level <= PAGE_LEVEL;
      if (isContainer) { page = null; n.container = true; return; }
      if (n.level <= PAGE_LEVEL || !page) {
        page = { node: n, inline: [] }; pages.push(page);
        n.pageIndex = pages.length - 1; n.isPage = true;
      } else { page.inline.push(n); n.pageIndex = pages.length - 1; }
    });
    // A heading with no text of its own (e.g. "Part 1") opens the first screen below it.
    let following = pages.length - 1;
    for (let i = nodes.length - 1; i >= 0; i -= 1) {
      if (nodes[i].container) nodes[i].pageIndex = following; else following = nodes[i].pageIndex;
    }
    nodes.forEach((n) => { n.pageIds = []; });
    pages.forEach((p) => { for (let a = p.node.parent; a; a = a.parent) a.pageIds.push(p.node.id); });

    return { title, nodes, roots, pages, byId };
  }

  return { PAGE_LEVEL, slugify, parseBook };
})();

if (typeof module === 'object' && module.exports) module.exports = Yeobaek;

if (typeof document !== 'undefined') (() => {
  const { PAGE_LEVEL, slugify, parseBook } = Yeobaek;
  const $ = (selector) => document.querySelector(selector);
  const els = {
    fileInput: $('#file-input'), open: $('#open-button'), bookTitle: $('#book-title'),
    folderInput: $('#folder-input'), folderButton: $('#folder-button'),
    chooser: $('#chooser'), chooserList: $('#chooser-list'), chooserCancel: $('#chooser-cancel'), fontSelect: $('#font-select'),
    sideToggle: $('#side-toggle'), grip: $('#grip'), scrim: $('#scrim'),
    tabs: [...document.querySelectorAll('.tab')], paneToc: $('#pane-toc'),
    tocFilter: $('#toc-filter'), expandAll: $('#expand-all'), collapseAll: $('#collapse-all'), tree: $('#tree'),
    search: $('#search-input'), searchStatus: $('#search-status'), searchResults: $('#search-results'),
    savedList: $('#saved-list'), savedCount: $('#saved-count'), clearSaved: $('#clear-saved-button'),
    welcome: $('#welcome'), readerView: $('#reader-view'), crumb: $('#crumb'), progress: $('#progress-label'), progressBar: $('#progress-bar'),
    bookmark: $('#bookmark-button'), scroll: $('#scroll'), content: $('#content'), prev: $('#prev-button'), next: $('#next-button'),
    fontDown: $('#font-down'), fontUp: $('#font-up'), theme: $('#theme-button'), toast: $('#toast'), drop: $('#drop-zone'),
  };
  const state = {
    book: null, bookId: '', page: -1, activeId: '', open: new Set(), read: new Set(), saved: [],
    files: new Map(), names: new Map(), urls: new Map(), baseDir: '', dir: null, sourceName: '', spyLockUntil: 0, toastTimer: null, font: 12,
  };
  const narrow = window.matchMedia('(max-width:720px)');
  // notes.js (annotations, notes file, AI) plugs in here; the reader works without it.
  const hooks = { pageRendered() {}, bookOpened() {}, changed() {}, key() {} };

  const esc = (value = '') => String(value).replace(/[&<>'"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[c]);
  const store = {
    get(key, fallback) { try { return JSON.parse(localStorage.getItem(`yeobaek:${key}`)) ?? fallback; } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem(`yeobaek:${key}`, JSON.stringify(value)); } catch { /* storage unavailable */ } },
  };
  const bookKey = (suffix) => `book:${state.bookId}:${suffix}`;
  const notify = (message) => {
    clearTimeout(state.toastTimer); els.toast.textContent = message; els.toast.classList.add('show');
    state.toastTimer = setTimeout(() => els.toast.classList.remove('show'), 2200);
  };
  const ancestors = (node) => { const list = []; for (let a = node.parent; a; a = a.parent) list.unshift(a); return list; };
  const pathOf = (node) => [...ancestors(node), node].map((n) => n.title).join(' › ');
  const hashFor = (node) => `#/${encodeURIComponent(node.id)}`;
  const nodeFromHash = () => {
    if (!state.book || !location.hash.startsWith('#/')) return null;
    try { return state.book.byId.get(decodeURIComponent(location.hash.slice(2))) || null; } catch { return null; }
  };
  const setHash = (node, push) => { try { history[push ? 'pushState' : 'replaceState'](null, '', hashFor(node)); } catch { /* ignore */ } };

  /* ---------- Rendering: content ---------- */

  function inline(value) {
    return esc(value)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*\s][^*]*)\*/g, '<em>$1</em>')
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, url) => {
        if (/^https?:\/\//i.test(url)) return `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`;
        const target = url.startsWith('#') && state.book.nodes.find((n) => esc(n.title) === label.replace(/<[^>]+>/g, ''));
        return target ? `<a href="${hashFor(target)}">${label}</a>` : label;
      });
  }

  const normalizePath = (value) => {
    const parts = [];
    for (const part of value.replace(/\\/g, '/').split('/')) {
      if (!part || part === '.') continue;
      if (part === '..') parts.pop(); else parts.push(part);
    }
    return parts.join('/').toLowerCase();
  };

  /** Follows a Markdown image link: relative to the Markdown file inside the opened folder, else by file name. */
  function imageUrl(src) {
    if (/^(https?:|data:image\/)/i.test(src)) return src;
    let link = src.split(/[?#]/)[0];
    try { link = decodeURIComponent(link); } catch { /* keep the raw link */ }
    const absolute = /^([a-z]:|[\\/]|file:)/i.test(link);
    const file = (!absolute && state.files.get(normalizePath(`${state.baseDir}/${link}`))) || state.names.get(normalizePath(link).split('/').pop());
    if (!file) return '';
    if (!state.urls.has(file)) state.urls.set(file, URL.createObjectURL(file));
    return state.urls.get(file);
  }

  function renderBlock(block) {
    switch (block.type) {
      case 'paragraph': return `<p>${inline(block.text)}</p>`;
      case 'quote': return `<blockquote>${block.paragraphs.map((text) => `<p>${inline(text)}</p>`).join('')}</blockquote>`;
      case 'list': { const tag = block.ordered ? 'ol' : 'ul'; return `<${tag}>${block.items.map((item) => `<li>${inline(item)}</li>`).join('')}</${tag}>`; }
      case 'code': return `<pre><code>${esc(block.text)}</code></pre>`;
      case 'table': {
        const head = block.header ? `<thead><tr>${block.header.map((cell) => `<th>${inline(cell)}</th>`).join('')}</tr></thead>` : '';
        const body = block.rows.map((row) => `<tr>${row.map((cell) => `<td>${inline(cell)}</td>`).join('')}</tr>`).join('');
        return `<div class="table-wrap"><table>${head}<tbody>${body}</tbody></table></div>`;
      }
      case 'image': {
        const url = imageUrl(block.src);
        const caption = block.alt && block.alt !== '그림' ? `<figcaption>${esc(block.alt)}</figcaption>` : '';
        return url
          ? `<figure><img src="${esc(url)}" alt="${esc(block.alt)}" loading="lazy">${caption}</figure>`
          : `<div class="figure-missing">이미지 없음 · ${esc(block.src)}<br>‘폴더 열기’로 책 폴더를 열면 이 링크를 따라 그림을 표시합니다.</div>`;
      }
      case 'insight': return block.blocks.length ? `<aside class="insight"><div class="insight-label">INSIGHT</div>${block.blocks.map(renderBlock).join('')}</aside>` : '';
      default: return '';
    }
  }

  function pageHtml(index) {
    const page = state.book.pages[index]; const node = page.node;
    const kicker = ancestors(node).map((n) => n.title).join(' · ');
    const pageRange = [node, ...page.inline].map((n) => n.pages).find(Boolean);
    return `<header class="page-head">${kicker ? `<p class="kicker">${esc(kicker)}</p>` : ''}<h2 class="page-title">${esc(node.title)}</h2>` +
      `${pageRange ? `<p class="source-pages">원문 p.${esc(pageRange)}</p>` : ''}</header>` +
      node.blocks.map(renderBlock).join('') +
      page.inline.map((n) => {
        const tag = n.level <= PAGE_LEVEL + 1 ? 'h3' : 'h4';
        return `<${tag} data-node="${esc(n.id)}">${esc(n.title)}</${tag}>${n.blocks.map(renderBlock).join('')}`;
      }).join('');
  }

  function renderPage(index) {
    const { pages } = state.book;
    state.page = index;
    els.content.innerHTML = pageHtml(index);
    const setPager = (button, target) => {
      button.disabled = !target; button.querySelector('span').textContent = target ? target.node.title : '';
    };
    setPager(els.prev, pages[index - 1]); setPager(els.next, pages[index + 1]);
    els.scroll.scrollTop = 0;
    hooks.pageRendered();
  }

  const anchorOf = (node) => (node.isPage ? null : [...els.content.querySelectorAll('[data-node]')].find((el) => el.dataset.node === node.id));
  const scrollToEl = (el) => { els.scroll.scrollTop += el.getBoundingClientRect().top - els.scroll.getBoundingClientRect().top - 16; };

  /** Opens the screen holding `node` and scrolls to it. */
  function goTo(node, { push = true, focus = false, word = '' } = {}) {
    if (!state.book || !node) return;
    if (node.pageIndex !== state.page) renderPage(node.pageIndex);
    const landing = node.container ? state.book.pages[node.pageIndex].node : node;
    const anchor = anchorOf(landing);
    if (anchor) scrollToEl(anchor); else els.scroll.scrollTop = 0;
    if (word) revealText(landing, word);
    state.spyLockUntil = performance.now() + 200;
    setActive(landing, { push });
    updateProgress();
    if (focus) els.content.focus({ preventScroll: true });
    if (narrow.matches) setDrawer(false);
  }

  function revealText(node, word) {
    const start = anchorOf(node) || els.content.querySelector('.page-head');
    for (let el = start.nextElementSibling; el && !el.dataset.node; el = el.nextElementSibling) {
      if (!el.textContent.toLowerCase().includes(word)) continue;
      scrollToEl(el); el.classList.add('hit'); setTimeout(() => el.classList.remove('hit'), 1600);
      return;
    }
  }

  /* ---------- Rendering: tree ---------- */

  const treeItem = (id) => [...els.tree.querySelectorAll('li')].find((li) => li.dataset.id === id);
  const visibleItems = () => [...els.tree.querySelectorAll('li')].filter((li) => li.offsetParent !== null);

  function metaFor(node) {
    if (node.pageIds.length) return `${node.pageIds.filter((id) => state.read.has(id)).length}/${node.pageIds.length}`;
    return node.isPage && state.read.has(node.id) ? '●' : '';
  }

  function renderTree() {
    const query = els.tocFilter.value.trim().toLowerCase();
    const matches = (node) => !query || node.title.toLowerCase().includes(query) || node.children.some(matches);
    const build = (list, depth, hidden = false) => `<ul role="${depth ? 'group' : 'tree'}"${depth ? '' : ' aria-label="문서 목차"'}${hidden ? ' hidden' : ''}>${list.filter(matches).map((node) => {
      const kids = node.children.filter(matches);
      const isOpen = query ? true : state.open.has(node.id);
      const meta = metaFor(node);
      return `<li role="treeitem" tabindex="-1" data-id="${esc(node.id)}" aria-level="${depth + 1}" aria-selected="false"${kids.length ? ` aria-expanded="${isOpen}"` : ''}>` +
        `<div class="row"><span class="chev"${kids.length ? ' data-toggle' : ''}></span><span class="label" title="${esc(node.title)}">${esc(node.title)}</span>` +
        `<span class="meta"${meta === '●' ? ' title="읽음"' : ''}>${meta}</span></div>` +
        `${kids.length ? build(kids, depth + 1, !isOpen) : ''}</li>`;
    }).join('')}</ul>`;
    const html = build(state.book.roots, 0);
    els.tree.innerHTML = html.includes('<li') ? html : '<p class="empty-copy">일치하는 목차 항목이 없습니다.</p>';
    markActiveInTree();
  }

  function markActiveInTree() {
    els.tree.querySelectorAll('li.active').forEach((li) => { li.classList.remove('active'); li.setAttribute('aria-selected', 'false'); });
    els.tree.querySelectorAll('li[tabindex="0"]').forEach((li) => { li.tabIndex = -1; });
    const li = treeItem(state.activeId);
    if (li) { li.classList.add('active'); li.setAttribute('aria-selected', 'true'); }
    const focusable = (li && li.offsetParent !== null ? li : null) || visibleItems()[0];
    if (focusable) focusable.tabIndex = 0;
    if (!li || els.paneToc.hidden) return;
    const row = li.firstElementChild.getBoundingClientRect(); const pane = els.paneToc.getBoundingClientRect();
    if (row.top < pane.top) els.paneToc.scrollTop -= pane.top - row.top + 8;
    else if (row.bottom > pane.bottom) els.paneToc.scrollTop += row.bottom - pane.bottom + 8;
  }

  function setOpen(id, open, persist = true) {
    if (open) state.open.add(id); else state.open.delete(id);
    const li = treeItem(id);
    if (li && li.hasAttribute('aria-expanded')) {
      li.setAttribute('aria-expanded', String(open));
      li.querySelector(':scope > ul').hidden = !open;
    }
    if (persist) store.set(bookKey('open'), [...state.open]);
  }

  function refreshMeta() {
    els.tree.querySelectorAll('li').forEach((li) => {
      const node = state.book.byId.get(li.dataset.id); const meta = metaFor(node);
      const span = li.querySelector(':scope > .row > .meta');
      span.textContent = meta; if (meta === '●') span.title = '읽음'; else span.removeAttribute('title');
    });
  }

  /* ---------- Active position, progress ---------- */

  function setActive(node, { push = false } = {}) {
    if (state.activeId === node.id) { if (push) setHash(node, true); return; }
    state.activeId = node.id;
    ancestors(node).forEach((a) => setOpen(a.id, true, false));
    store.set(bookKey('open'), [...state.open]);
    markActiveInTree();
    const trail = ancestors(node);
    els.crumb.innerHTML = trail.map((a) => `<button type="button" data-id="${esc(a.id)}">${esc(a.title)}</button><span aria-hidden="true">›</span>`).join('') + `<b>${esc(node.title)}</b>`;
    updateBookmarkButton();
    store.set(bookKey('pos'), node.id); hooks.changed();
    setHash(node, push);
  }

  function updateProgress() {
    const total = state.book.pages.length; const room = els.scroll.scrollHeight - els.scroll.clientHeight;
    const fraction = room > 0 ? Math.min(1, els.scroll.scrollTop / room) : 1;
    const percent = Math.round(((state.page + fraction) / total) * 100);
    els.progress.textContent = `${state.page + 1} / ${total}장 · ${percent}%`;
    els.progressBar.style.width = `${percent}%`;
    if (room - els.scroll.scrollTop <= 24) {
      const id = state.book.pages[state.page].node.id;
      if (!state.read.has(id)) { state.read.add(id); store.set(bookKey('read'), [...state.read]); refreshMeta(); hooks.changed(); }
    }
  }

  function spy() {
    if (!state.book || state.page < 0) return;
    updateProgress();
    if (performance.now() < state.spyLockUntil) return;
    const line = els.scroll.getBoundingClientRect().top + 96;
    let current = state.book.pages[state.page].node;
    for (const el of els.content.querySelectorAll('[data-node]')) {
      if (el.getBoundingClientRect().top > line) break;
      current = state.book.byId.get(el.dataset.node);
    }
    setActive(current);
  }

  /* ---------- Sidebar: tabs, search, saved ---------- */

  function switchTab(name) {
    els.tabs.forEach((tab) => {
      const selected = tab.dataset.tab === name;
      tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1;
      $(`#pane-${tab.dataset.tab}`).hidden = !selected;
    });
    if (name === 'toc') markActiveInTree();
  }

  function runSearch() {
    const word = els.search.value.trim().toLowerCase();
    if (!state.book || !word) { els.searchStatus.textContent = state.book ? '제목과 본문에서 찾습니다.' : ''; els.searchResults.innerHTML = ''; return; }
    const hits = state.book.nodes.filter((n) => n.lower.includes(word));
    els.searchStatus.textContent = hits.length ? `결과 ${hits.length}건${hits.length > 50 ? ' · 앞 50건만 표시' : ''}` : '일치하는 문장을 찾지 못했습니다.';
    els.searchResults.innerHTML = hits.slice(0, 50).map((n) => {
      const at = n.text.toLowerCase().indexOf(word);
      const excerpt = at < 0 ? esc(n.text.slice(0, 100))
        : `${at > 30 ? '…' : ''}${esc(n.text.slice(Math.max(0, at - 30), at))}<mark>${esc(n.text.slice(at, at + word.length))}</mark>${esc(n.text.slice(at + word.length, at + word.length + 70))}`;
      return `<div class="result-item"><button class="go" type="button" data-id="${esc(n.id)}"${at < 0 ? '' : ' data-hit'}><span class="result-title">${esc(pathOf(n))}</span><span class="result-copy">${excerpt}</span></button></div>`;
    }).join('');
  }

  function renderSaved() {
    const items = state.book ? state.saved.filter((item) => state.book.byId.has(item.id)) : [];
    els.savedCount.textContent = items.length || '';
    els.clearSaved.disabled = !items.length;
    els.savedList.innerHTML = items.length ? items.map((item) => {
      const node = state.book.byId.get(item.id);
      return `<div class="result-item removable"><button class="go" type="button" data-id="${esc(item.id)}"><span class="result-title">${esc(node.title)}</span><span class="result-copy">${esc(pathOf(node))}</span></button>` +
        `<button class="remove" type="button" data-remove="${esc(item.id)}" aria-label="${esc(node.title)} 저장 해제">×</button></div>`;
    }).join('') : '<p class="empty-copy">아직 저장한 위치가 없습니다. 본문 위의 ‘위치 저장’을 누르면 여기에 쌓입니다.</p>';
  }

  function updateBookmarkButton() {
    const saved = state.saved.some((item) => item.id === state.activeId);
    els.bookmark.textContent = saved ? '★ 저장됨' : '☆ 위치 저장';
    els.bookmark.setAttribute('aria-pressed', String(saved));
  }

  function toggleSaved(id) {
    const exists = state.saved.some((item) => item.id === id);
    state.saved = exists ? state.saved.filter((item) => item.id !== id) : [{ id, createdAt: Date.now() }, ...state.saved];
    store.set(bookKey('saved'), state.saved); renderSaved(); updateBookmarkButton(); hooks.changed();
    notify(exists ? '저장을 해제했습니다.' : '이 위치를 저장했습니다.');
  }

  /* ---------- Sidebar: open/close, width ---------- */

  function setDrawer(open) {
    document.body.classList.toggle('side-open', open); els.scrim.hidden = !open;
    if (narrow.matches) els.sideToggle.setAttribute('aria-expanded', String(open));
  }
  function toggleSidebar() {
    if (narrow.matches) { setDrawer(!document.body.classList.contains('side-open')); return; }
    const collapsed = document.body.classList.toggle('side-collapsed');
    els.sideToggle.setAttribute('aria-expanded', String(!collapsed)); store.set('sideCollapsed', collapsed);
  }
  function showSidebar() {
    if (narrow.matches) setDrawer(true);
    else if (document.body.classList.contains('side-collapsed')) toggleSidebar();
  }
  function setSideWidth(width, persist = true) {
    const clamped = Math.round(Math.max(200, Math.min(width, 520, window.innerWidth - 320)));
    document.documentElement.style.setProperty('--side-w', `${clamped}px`);
    if (persist) store.set('sideWidth', clamped);
    return clamped;
  }

  /* ---------- Reading settings ---------- */

  // Text size in points for the body, the left panes and the notes panel; menus stay at 12pt.
  const FONT_MIN = 9; const FONT_MAX = 20; const FONT_DEFAULT = 12;
  function setFont(size, announce = true) {
    state.font = Math.max(FONT_MIN, Math.min(size, FONT_MAX));
    document.documentElement.style.setProperty('--reader-size', `${state.font}pt`);
    els.fontDown.disabled = state.font <= FONT_MIN; els.fontUp.disabled = state.font >= FONT_MAX;
    store.set('fontPt', state.font);
    if (announce) notify(`글자 크기 ${state.font}pt`);
  }
  // Installed fonts are used first; `css` is fetched only as a fallback source for machines without them.
  const FONTS = {
    serif: { stack: 'var(--serif)' },
    pretendard: { stack: '"Pretendard", "Pretendard Variable", var(--sans)', css: 'https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css' },
    'kopub-batang': { stack: '"Yeobaek KoPub Batang", "KoPub Batang", var(--serif)', css: 'https://fonts.googleapis.com/earlyaccess/kopubbatang.css' },
    'kopub-dotum': { stack: '"Yeobaek KoPub Dotum", "Pretendard", var(--sans)', installedOnly: '"Yeobaek KoPub Dotum"' },
  };
  function setReaderFont(id, announce = false) {
    const key = FONTS[id] ? id : 'serif'; const font = FONTS[key];
    document.documentElement.style.setProperty('--reader-font', font.stack);
    if (font.css && ![...document.styleSheets].some((sheet) => sheet.href === font.css)) {
      const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = font.css; document.head.appendChild(link);
    }
    els.fontSelect.value = key; store.set('fontFamily', key);
    if (announce && font.installedOnly) {
      const missing = () => notify('이 PC에 KoPub 고딕(돋움)이 설치되어 있지 않아 대체 글꼴로 표시합니다.');
      document.fonts.load(`16px ${font.installedOnly}`, '가').then((faces) => { if (!faces.length) missing(); }, missing);
    }
  }
  const THEMES = ['', 'night', 'high-contrast'];
  function setTheme(name) {
    document.body.classList.remove('night', 'high-contrast');
    if (name) document.body.classList.add(name);
    store.set('theme', name);
  }

  /* ---------- Opening files ---------- */

  function openBook(name, text) {
    const book = parseBook(text, name);
    state.book = book; state.bookId = slugify(name.replace(/\.[^.]+$/, ''), 'ebook'); state.sourceName = name;
    state.page = -1; state.activeId = '';
    state.read = new Set(store.get(bookKey('read'), []));
    state.saved = store.get(bookKey('saved'), []).filter((item) => item && typeof item.id === 'string');
    const storedOpen = store.get(bookKey('open'), null);
    state.open = new Set(storedOpen || (book.roots.length <= 8 ? book.roots.map((n) => n.id) : []));

    els.bookTitle.textContent = book.title; document.title = `${book.title} — Markdown Reader`;
    els.welcome.hidden = true; els.readerView.hidden = false;
    els.tocFilter.value = ''; els.search.value = '';
    renderTree(); renderSaved(); runSearch(); switchTab('toc');
    goTo(nodeFromHash() || book.byId.get(store.get(bookKey('pos'), '')) || book.pages[0].node, { push: false });
    const links = book.nodes.flatMap((n) => n.blocks.flatMap((b) => (b.type === 'insight' ? b.blocks : [b]))).filter((b) => b.type === 'image');
    const found = links.filter((b) => imageUrl(b.src)).length;
    hooks.bookOpened(text);
    notify(`${book.pages.length}개 장을 열었습니다.${links.length ? ` 이미지 ${found}/${links.length}개 연결.` : ''}`);
  }

  const MARKDOWN = /\.(md|markdown)$/i; const IMAGE = /\.(png|jpe?g|gif|webp|svg|bmp|avif)$/i;
  const fromFileList = (list) => [...list].map((file) => ({ file, path: file.webkitRelativePath || file.name }));

  function addImages(images) {
    images.forEach(({ file, path }) => {
      state.files.set(normalizePath(path), file);
      const name = file.name.toLowerCase(); if (!state.names.has(name)) state.names.set(name, file);
    });
  }

  /** A dropped folder arrives as directory entries; walk it and keep Markdown and image files with their paths. */
  async function fromDrop(dataTransfer) {
    const files = fromFileList(dataTransfer.files);
    const roots = [...dataTransfer.items].map((item) => item.webkitGetAsEntry?.()).filter(Boolean); // must be read synchronously
    if (!roots.some((entry) => entry.isDirectory)) return files;
    const found = [];
    const walk = async (entry) => {
      if (entry.isFile) {
        if (MARKDOWN.test(entry.name) || IMAGE.test(entry.name)) found.push({ file: await new Promise((resolve, reject) => entry.file(resolve, reject)), path: entry.fullPath.replace(/^\//, '') });
        return;
      }
      if (entry.name.startsWith('.') || entry.name === 'node_modules') return;
      const reader = entry.createReader();
      for (;;) {
        const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        if (!batch.length) break;
        for (const child of batch) await walk(child);
      }
    };
    for (const root of roots) await walk(root);
    return found;
  }

  /**
   * Opens the book folder with write access (Chrome/Edge) so notes can be saved next to the Markdown.
   * Other browsers fall back to the read-only folder input.
   */
  async function openFolder() {
    if (!window.showDirectoryPicker) { els.folderInput.click(); return; }
    let root;
    try { root = await window.showDirectoryPicker({ mode: 'readwrite' }); } catch (error) {
      if (error.name !== 'AbortError') els.folderInput.click();
      return;
    }
    const found = [];
    const walk = async (dir, prefix, depth) => {
      for await (const [name, handle] of dir.entries()) {
        if (handle.kind === 'file') { if (MARKDOWN.test(name) || IMAGE.test(name)) found.push({ handle, dir, path: prefix + name }); }
        else if (depth < 4 && !name.startsWith('.') && name !== 'node_modules') await walk(handle, `${prefix}${name}/`, depth + 1);
      }
    };
    try {
      await walk(root, '', 0);
      openEntries(await Promise.all(found.map(async (entry) => ({ file: await entry.handle.getFile(), path: entry.path, dir: entry.dir }))));
    } catch { notify('폴더를 읽지 못했습니다.'); }
  }

  function chooseMarkdown(candidates) {
    const depth = (entry) => entry.path.split('/').length;
    const sorted = [...candidates].sort((a, b) => depth(a) - depth(b) || a.path.localeCompare(b.path));
    els.chooserList.innerHTML = sorted.map((entry, index) => `<div class="result-item"><button class="go" type="button" data-index="${index}"><span class="result-title">${esc(entry.file.name)}</span><span class="result-copy">${esc(entry.path)}</span></button></div>`).join('');
    return new Promise((resolve) => {
      const pick = (event) => { const button = event.target.closest('[data-index]'); if (button) finish(sorted[Number(button.dataset.index)]); };
      const cancel = () => finish(null);
      const finish = (value) => {
        els.chooserList.removeEventListener('click', pick); els.chooser.removeEventListener('close', cancel);
        if (els.chooser.open) els.chooser.close();
        resolve(value);
      };
      els.chooserList.addEventListener('click', pick); els.chooser.addEventListener('close', cancel);
      els.chooser.showModal();
    });
  }

  async function openEntries(entries) {
    const markdowns = entries.filter((entry) => MARKDOWN.test(entry.file.name));
    const images = entries.filter((entry) => IMAGE.test(entry.file.name));
    if (!markdowns.length) {
      if (!state.book || !images.length) { notify('Markdown 파일을 찾지 못했습니다.'); return; }
      addImages(images);
      const node = state.book.byId.get(state.activeId);
      state.page = -1; goTo(node, { push: false });
      notify(`이미지 ${images.length}개를 연결했습니다.`);
      return;
    }
    const markdown = markdowns.length === 1 ? markdowns[0] : await chooseMarkdown(markdowns);
    if (!markdown) return;
    const text = await markdown.file.text();
    state.urls.forEach((url) => URL.revokeObjectURL(url));
    state.urls.clear(); state.files.clear(); state.names.clear();
    state.baseDir = markdown.path.split('/').slice(0, -1).join('/');
    state.dir = markdown.dir || null; // writable folder handle when the folder was opened through the picker
    addImages(images);
    openBook(markdown.file.name, text);
  }

  /* ---------- Events ---------- */

  els.open.addEventListener('click', () => els.fileInput.click());
  els.folderButton.addEventListener('click', openFolder);
  [els.fileInput, els.folderInput].forEach((input) => input.addEventListener('change', () => { openEntries(fromFileList(input.files)); input.value = ''; }));
  els.chooserCancel.addEventListener('click', () => els.chooser.close());
  els.fontSelect.addEventListener('change', () => setReaderFont(els.fontSelect.value, true));

  els.sideToggle.addEventListener('click', toggleSidebar);
  els.scrim.addEventListener('click', () => setDrawer(false));
  narrow.addEventListener('change', () => {
    setDrawer(false);
    els.sideToggle.setAttribute('aria-expanded', String(!narrow.matches && !document.body.classList.contains('side-collapsed')));
  });

  els.grip.addEventListener('pointerdown', (event) => {
    event.preventDefault(); els.grip.setPointerCapture(event.pointerId); els.grip.classList.add('dragging');
    const move = (e) => setSideWidth(e.clientX, false);
    const up = (e) => {
      els.grip.classList.remove('dragging'); els.grip.removeEventListener('pointermove', move); els.grip.removeEventListener('pointerup', up);
      setSideWidth(e.clientX);
    };
    els.grip.addEventListener('pointermove', move); els.grip.addEventListener('pointerup', up);
  });
  els.grip.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault(); event.stopPropagation();
    setSideWidth(els.grip.previousElementSibling.offsetWidth + (event.key === 'ArrowRight' ? 16 : -16));
  });

  els.tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    tab.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault(); event.stopPropagation();
      const next = els.tabs[(index + (event.key === 'ArrowRight' ? 1 : els.tabs.length - 1)) % els.tabs.length];
      switchTab(next.dataset.tab); next.focus();
    });
  });

  els.tree.addEventListener('click', (event) => {
    const li = event.target.closest('li'); if (!li || !state.book) return;
    const id = li.dataset.id;
    if (event.target.closest('[data-toggle]')) { setOpen(id, li.getAttribute('aria-expanded') !== 'true'); markActiveInTree(); return; }
    if (li.getAttribute('aria-expanded') === 'false') setOpen(id, true);
    // Hand focus to the text so ←/→ turn chapters right after picking one with the mouse.
    goTo(state.book.byId.get(id), { focus: !narrow.matches });
  });
  els.tree.addEventListener('keydown', (event) => {
    const li = event.target.closest('li'); if (!li || !state.book) return;
    const items = visibleItems(); const at = items.indexOf(li);
    const expanded = li.getAttribute('aria-expanded');
    const focus = (target) => { if (!target) return; items.forEach((item) => { item.tabIndex = -1; }); target.tabIndex = 0; target.focus(); };
    const actions = {
      ArrowDown: () => focus(items[at + 1]),
      ArrowUp: () => focus(items[at - 1]),
      Home: () => focus(items[0]),
      End: () => focus(items[items.length - 1]),
      ArrowRight: () => { if (expanded === 'false') setOpen(li.dataset.id, true); else if (expanded === 'true') focus(visibleItems()[at + 1]); },
      ArrowLeft: () => { if (expanded === 'true') setOpen(li.dataset.id, false); else focus(li.parentElement.closest('li')); },
      Enter: () => goTo(state.book.byId.get(li.dataset.id), { focus: !narrow.matches }),
      ' ': () => goTo(state.book.byId.get(li.dataset.id)),
    };
    if (!actions[event.key]) return;
    event.preventDefault(); event.stopPropagation(); actions[event.key]();
  });
  els.tocFilter.addEventListener('input', () => { if (state.book) renderTree(); });
  const setAllOpen = (open) => {
    if (!state.book) return;
    state.open = new Set(open ? state.book.nodes.filter((n) => n.children.length).map((n) => n.id) : []);
    store.set(bookKey('open'), [...state.open]); renderTree();
  };
  els.expandAll.addEventListener('click', () => setAllOpen(true));
  els.collapseAll.addEventListener('click', () => setAllOpen(false));

  els.search.addEventListener('input', runSearch);
  els.searchResults.addEventListener('click', (event) => {
    const button = event.target.closest('[data-id]'); if (!button) return;
    goTo(state.book.byId.get(button.dataset.id), { word: button.hasAttribute('data-hit') ? els.search.value.trim().toLowerCase() : '' });
  });
  els.savedList.addEventListener('click', (event) => {
    const remove = event.target.closest('[data-remove]'); const go = event.target.closest('[data-id]');
    if (remove) toggleSaved(remove.dataset.remove); else if (go) goTo(state.book.byId.get(go.dataset.id));
  });
  els.clearSaved.addEventListener('click', () => {
    if (!state.book) return;
    state.saved = []; store.set(bookKey('saved'), []); renderSaved(); updateBookmarkButton(); hooks.changed(); notify('저장한 위치를 비웠습니다.');
  });
  els.bookmark.addEventListener('click', () => { if (state.book) toggleSaved(state.activeId); });
  els.crumb.addEventListener('click', (event) => {
    const button = event.target.closest('[data-id]'); if (button) goTo(state.book.byId.get(button.dataset.id));
  });

  const turn = (step) => { const page = state.book?.pages[state.page + step]; if (page) goTo(page.node, { focus: true }); };
  els.prev.addEventListener('click', () => turn(-1));
  els.next.addEventListener('click', () => turn(1));
  let spyQueued = false;
  els.scroll.addEventListener('scroll', () => {
    if (spyQueued) return; spyQueued = true;
    requestAnimationFrame(() => { spyQueued = false; spy(); });
  }, { passive: true });
  window.addEventListener('resize', () => { if (state.book && state.page >= 0) updateProgress(); });
  window.addEventListener('hashchange', () => { const node = nodeFromHash(); if (node && node.id !== state.activeId) goTo(node, { push: false }); });

  els.fontDown.addEventListener('click', () => setFont(state.font - 1));
  els.fontUp.addEventListener('click', () => setFont(state.font + 1));
  els.theme.addEventListener('click', () => {
    const current = THEMES.findIndex((name) => name && document.body.classList.contains(name));
    const next = THEMES[(Math.max(0, current) + 1) % THEMES.length];
    setTheme(next); notify(next === 'night' ? '어두운 테마' : next ? '고대비 테마' : '밝은 테마');
  });

  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && document.body.classList.contains('side-open')) { setDrawer(false); els.sideToggle.focus(); return; }
    if (event.ctrlKey || event.metaKey || event.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return;
    if (event.key === '/') { event.preventDefault(); showSidebar(); switchTab('search'); els.search.focus(); return; }
    if (!state.book) return;
    if (event.key === 'ArrowLeft') turn(-1);
    else if (event.key === 'ArrowRight') turn(1);
    else if (event.key === '+' || event.key === '=') setFont(state.font + 1);
    else if (event.key === '-') setFont(state.font - 1);
    else hooks.key(event);
  });

  let dragDepth = 0;
  const hasFiles = (event) => [...(event.dataTransfer?.types || [])].includes('Files');
  window.addEventListener('dragenter', (event) => { if (!hasFiles(event)) return; event.preventDefault(); dragDepth += 1; els.drop.classList.add('visible'); });
  window.addEventListener('dragover', (event) => { if (hasFiles(event)) event.preventDefault(); });
  window.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) els.drop.classList.remove('visible'); });
  window.addEventListener('drop', (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault(); dragDepth = 0; els.drop.classList.remove('visible');
    fromDrop(event.dataTransfer).then(openEntries, () => notify('놓은 항목을 읽지 못했습니다.'));
  });

  /* ---------- Startup ---------- */

  const savedTheme = store.get('theme', '');
  setTheme(THEMES.includes(savedTheme) ? savedTheme : '');
  setFont(Number(store.get('fontPt', FONT_DEFAULT)) || FONT_DEFAULT, false);
  setReaderFont(store.get('fontFamily', 'serif'));
  const savedWidth = Number(store.get('sideWidth', 0)); if (savedWidth) setSideWidth(savedWidth, false);
  if (store.get('sideCollapsed', false) && !narrow.matches) toggleSidebar();

  Yeobaek.reader = {
    state, els, store, hooks, narrow, esc, notify, bookKey, pathOf, goTo, scrollToEl, pageHtml,
    updateProgress, renderSaved, updateBookmarkButton, refreshMeta,
  };
})();
