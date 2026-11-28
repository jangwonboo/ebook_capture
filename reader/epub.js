/* EPUB export for Kindle (Send to Kindle) and other e-readers.
 * One reader screen (a level-1/2 heading) becomes one XHTML file, so the table of contents and
 * chapter breaks match the reader. Math becomes SVG pictures (MathJax), Pretendard is embedded.
 * Libraries and the font come from CDNs the first time an export runs. */
const YeobaekEpub = (() => {
  const reader = typeof Yeobaek !== 'undefined' && Yeobaek.reader;
  if (!reader) return null;
  const { state, esc, notify } = reader;

  const JSZIP_URL = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
  const MATHJAX_URL = 'https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js';
  const FONT_BASE = 'https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/public/static/';
  const FONTS = [
    { file: 'Pretendard-Regular.otf', weight: 400 },
    { file: 'Pretendard-Bold.otf', weight: 700 },
  ];
  // MathJax's SVG output sizes in ex with 1ex = 0.5em; e-readers handle em more reliably.
  const EX_TO_EM = 0.5;

  const scripts = new Map();
  const loadScript = (url) => {
    if (!scripts.has(url)) {
      scripts.set(url, new Promise((resolve, reject) => {
        const tag = document.createElement('script');
        tag.src = url; tag.async = true;
        tag.onload = resolve; tag.onerror = () => { scripts.delete(url); reject(new Error(`불러오지 못함: ${url}`)); };
        document.head.appendChild(tag);
      }));
    }
    return scripts.get(url);
  };
  async function mathJax() {
    if (!window.MathJax || !window.MathJax.tex2svgPromise) {
      window.MathJax = { svg: { fontCache: 'none' }, startup: { typeset: false } };
      await loadScript(MATHJAX_URL);
      await window.MathJax.startup.promise;
    }
    return window.MathJax;
  }
  const fontCache = new Map();
  async function fontBytes(file) {
    if (!fontCache.has(file)) {
      const res = await fetch(FONT_BASE + file);
      if (!res.ok) throw new Error(`글꼴을 받지 못함: ${file} (${res.status})`);
      fontCache.set(file, await res.arrayBuffer());
    }
    return fontCache.get(file);
  }

  /* ---------- Small helpers ---------- */

  const pad = (n) => String(n).padStart(3, '0');
  const chapterFile = (index) => `ch${pad(index + 1)}.xhtml`;
  const xmlEsc = (value) => esc(String(value)).replace(/'/g, '&#39;');
  function stableUuid(text) {
    // Two FNV-1a passes give 128 bits; good enough for a stable book identifier.
    let a = 0x811c9dc5; let b = 0x01000193; let c = 0x9e3779b9; let d = 0x85ebca6b;
    for (let i = 0; i < text.length; i += 1) {
      const k = text.charCodeAt(i);
      a = Math.imul(a ^ k, 16777619); b = Math.imul(b ^ k, 2246822519); c = Math.imul(c ^ k, 3266489917); d = Math.imul(d ^ k, 668265263);
    }
    const hex = [a, b, c, d].map((x) => (x >>> 0).toString(16).padStart(8, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-5${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
  }
  const MEDIA = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', gif: 'image/gif', svg: 'image/svg+xml', webp: 'image/webp' };
  const extOf = (name) => (/\.([a-z0-9]+)$/i.exec(name || '') || [])[1]?.toLowerCase() || '';

  /** Screen HTML → XHTML body markup. */
  function toXhtml(html) {
    const doc = new DOMParser().parseFromString(`<!doctype html><html><body>${html}</body></html>`, 'text/html');
    doc.querySelectorAll('[data-node]').forEach((el) => el.removeAttribute('data-node'));
    doc.querySelectorAll('a[target]').forEach((el) => el.removeAttribute('target'));
    doc.querySelectorAll('img[loading]').forEach((el) => el.removeAttribute('loading'));
    const out = new XMLSerializer();
    return [...doc.body.childNodes].map((n) => out.serializeToString(n)).join('').replace(/ xmlns="http:\/\/www\.w3\.org\/1999\/xhtml"/g, '');
  }
  const page = (title, body, type = 'chapter') => '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n' +
    '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ko" xml:lang="ko">\n' +
    `<head><meta charset="UTF-8"/><title>${xmlEsc(title)}</title><link rel="stylesheet" type="text/css" href="../styles/book.css"/></head>\n` +
    `<body><section epub:type="${type}">${body}</section></body>\n</html>\n`;

  const CSS = `@font-face { font-family: "Pretendard"; font-weight: 400; font-style: normal; src: url(../fonts/Pretendard-Regular.otf); }
@font-face { font-family: "Pretendard"; font-weight: 700; font-style: normal; src: url(../fonts/Pretendard-Bold.otf); }
body { font-family: "Pretendard", sans-serif; line-height: 1.75; margin: 0; }
p { margin: 0 0 0.8em; text-indent: 0; }
h1, h2, h3, h4 { font-family: "Pretendard", sans-serif; font-weight: 700; line-height: 1.4; page-break-after: avoid; }
h1 { font-size: 1.6em; margin: 2em 0 0.6em; }
h2 { font-size: 1.35em; margin: 0 0 0.4em; }
h3 { font-size: 1.15em; margin: 1.6em 0 0.5em; }
h4 { font-size: 1em; margin: 1.3em 0 0.4em; }
.page-head { margin: 0 0 1.4em; }
.kicker { font-size: 0.8em; color: #555; margin: 0 0 0.3em; }
.source-pages { font-size: 0.75em; color: #666; margin: 0.2em 0 0; }
strong { font-weight: 700; }
figure { margin: 1em 0; text-align: center; page-break-inside: avoid; }
figure img { max-width: 100%; }
figcaption { font-size: 0.85em; color: #444; margin-top: 0.3em; }
blockquote { margin: 1em 0 1em 1em; padding-left: 0.8em; border-left: 3px solid #999; }
ul, ol { margin: 0 0 0.8em 1.4em; padding: 0; }
li { margin: 0 0 0.3em; }
pre { white-space: pre-wrap; word-wrap: break-word; font-family: monospace; font-size: 0.82em; line-height: 1.5; background: #f1f1f1; padding: 0.6em 0.8em; margin: 0 0 1em; }
code { font-family: monospace; font-size: 0.9em; }
.table-wrap { margin: 0 0 1em; }
table { border-collapse: collapse; font-size: 0.88em; line-height: 1.5; }
th, td { border: 1px solid #888; padding: 0.2em 0.45em; vertical-align: top; }
th { font-weight: 700; background: #eee; }
.insight { border: 1px solid #888; padding: 0.6em 0.9em; margin: 1em 0; }
.insight-label { font-weight: 700; font-size: 0.78em; letter-spacing: 0.08em; margin-bottom: 0.3em; }
.math-display { display: block; text-align: center; margin: 0.8em 0; page-break-inside: avoid; }
img.math { border: 0; margin: 0; }
.title-page { text-align: center; margin-top: 30%; }
.title-page p { color: #555; font-size: 0.85em; }
`;

  /* ---------- Math ---------- */

  /**
   * Typesets collected formulas in place. Each item gets `node` (the <svg> element), `svg` (its markup)
   * and `width`/`height`/`valign` in em; `failed` is set instead when TeX cannot be parsed.
   */
  async function typeset(formulas, progress = () => {}) {
    if (!formulas.size) return 0;
    await mathJax();
    let failed = 0; let done = 0;
    for (const item of formulas.values()) {
      done += 1;
      if (done % 25 === 0) progress(done, formulas.size);
      try {
        // OCR'd formulas carry bare # and % (e.g. E_{##ing}); TeX needs them escaped.
        const tex = item.tex.replace(/\\?[#%]/g, (m) => (m.length === 2 ? m : `\\${m}`));
        const svg = (await window.MathJax.tex2svgPromise(tex, { display: item.display })).querySelector('svg');
        if (!svg || svg.querySelector('[data-mml-node="merror"]')) throw new Error('TeX 오류');
        const size = (attr) => parseFloat(svg.getAttribute(attr)) * EX_TO_EM;
        item.width = size('width'); item.height = size('height');
        item.valign = parseFloat((/vertical-align:\s*(-?[\d.]+)ex/.exec(svg.getAttribute('style') || '') || [])[1] || 0) * EX_TO_EM;
        item.node = svg; item.svg = new XMLSerializer().serializeToString(svg);
      } catch { failed += 1; item.failed = true; }
    }
    return failed;
  }
  /** Inline: a fixed em box on the baseline. Display: an em width that shrinks to the page, height follows. */
  const mathStyle = (item) => (item.display ? `width:${item.width.toFixed(3)}em;max-width:100%;height:auto`
    : `width:${item.width.toFixed(3)}em;height:${item.height.toFixed(3)}em;vertical-align:${item.valign.toFixed(3)}em`);
  const mathKey = (tex, display) => `${display ? 'D' : 'I'}${tex.trim()}`;
  const rawMath = (item) => `<code>${xmlEsc(item.display ? `$$${item.tex}$$` : `$${item.tex}$`)}</code>`;

  /* ---------- Export ---------- */

  async function buildEpub() {
    const book = state.book;
    if (!book) return;
    const ids = new Map(book.nodes.map((n, k) => [n.id, `h${k + 1}`]));
    const hrefOf = (n) => {
      const index = n.pageIndex >= 0 ? n.pageIndex : 0;
      return n.container ? chapterFile(index) : `${chapterFile(index)}#${ids.get(n.id)}`;
    };

    // Pass 1: find every formula and image so the slow work (MathJax, file reads) happens once.
    const formulas = new Map(); const images = new Map(); const missing = new Set();
    const collect = {
      math(tex, display) { const key = mathKey(tex, display); if (!formulas.has(key)) formulas.set(key, { tex: tex.trim(), display }); return ''; },
      image(src) {
        if (/^(https?:|data:)/i.test(src)) return '';
        const source = reader.imageSource(src);
        if (!source) { missing.add(src); return ''; }
        if (!images.has(source.key)) images.set(source.key, { path: `images/img${pad(images.size + 1)}.${extOf(source.name) || 'jpg'}`, blob: source.blob });
        return '';
      },
      link: () => '#', id: () => 'x',
    };
    book.pages.forEach((p, index) => reader.exportPage(index, collect));

    notify('EPUB 준비 중: 라이브러리와 글꼴을 불러옵니다.');
    const [JSZip, fonts] = await Promise.all([
      loadScript(JSZIP_URL).then(() => window.JSZip),
      Promise.all(FONTS.map((f) => fontBytes(f.file))),
    ]);

    // Math → SVG files. Identical formulas share one file.
    const failed = await typeset(formulas, (done, total) => notify(`수식을 그림으로 바꾸는 중 ${done}/${total}`));
    const svgs = [];
    for (const item of formulas.values()) {
      if (item.failed) { item.html = rawMath(item); continue; }
      const path = `math/m${String(svgs.length + 1).padStart(4, '0')}.svg`;
      svgs.push({ path, data: `<?xml version="1.0" encoding="UTF-8"?>\n${item.svg}` });
      const img = `<img class="math" src="../${path}" alt="${xmlEsc(item.tex)}" style="${mathStyle(item)}"/>`;
      // A display formula gets its own centred line even when the source runs it into a sentence.
      item.html = item.display ? `<span class="math-display">${img}</span>` : img;
    }

    // Image bytes: opened files are at hand, a library on a web server is fetched now.
    for (const [key, item] of images) {
      try { item.data = await (await item.blob()).arrayBuffer(); } catch { images.delete(key); missing.add(key); }
    }

    // Pass 2: the real chapter pages.
    const render = {
      math: (tex, display) => formulas.get(mathKey(tex, display)).html,
      image(src) { const source = !/^(https?:|data:)/i.test(src) && reader.imageSource(src); return source && images.has(source.key) ? `../${images.get(source.key).path}` : ''; },
      link: (target) => hrefOf(target),
      id: (n) => ids.get(n.id),
    };
    const chapters = book.pages.map((p, index) => ({
      file: chapterFile(index), title: p.node.title, body: toXhtml(reader.exportPage(index, render)),
    }));

    const zip = new JSZip();
    zip.file('mimetype', 'application/epub+zip', { compression: 'STORE' });
    zip.file('META-INF/container.xml', '<?xml version="1.0" encoding="UTF-8"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n' +
      '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>\n</container>\n');
    zip.file('OEBPS/styles/book.css', CSS);
    FONTS.forEach((f, k) => zip.file(`OEBPS/fonts/${f.file}`, fonts[k]));
    for (const item of images.values()) zip.file(`OEBPS/${item.path}`, item.data);
    svgs.forEach((s) => zip.file(`OEBPS/${s.path}`, s.data));
    const today = new Date().toISOString().slice(0, 10);
    zip.file('OEBPS/text/title.xhtml', page(book.title, `<div class="title-page"><h1>${xmlEsc(book.title)}</h1><p>Markdown Reader에서 만듦 · ${today}</p></div>`, 'titlepage'));
    chapters.forEach((c) => zip.file(`OEBPS/text/${c.file}`, page(c.title, c.body)));

    // Table of contents: EPUB 3 nav and EPUB 2 NCX from the same heading tree.
    const navList = (nodes) => (nodes.length ? `<ol>${nodes.map((n) => `<li><a href="${hrefOf(n)}">${xmlEsc(n.title)}</a>${navList(n.children)}</li>`).join('')}</ol>` : '');
    zip.file('OEBPS/text/nav.xhtml', '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n' +
      '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ko" xml:lang="ko">\n' +
      `<head><meta charset="UTF-8"/><title>차례</title><link rel="stylesheet" type="text/css" href="../styles/book.css"/></head>\n` +
      `<body><nav epub:type="toc" id="toc"><h1>차례</h1>${navList(book.roots)}</nav>` +
      `<nav epub:type="landmarks" hidden="hidden"><ol><li><a epub:type="toc" href="nav.xhtml">차례</a></li><li><a epub:type="bodymatter" href="${chapterFile(0)}">본문</a></li></ol></nav></body>\n</html>\n`);
    let order = 0;
    const navPoints = (nodes) => nodes.map((n) => {
      order += 1;
      return `<navPoint id="np${order}" playOrder="${order}"><navLabel><text>${xmlEsc(n.title)}</text></navLabel><content src="text/${hrefOf(n)}"/>${navPoints(n.children)}</navPoint>`;
    }).join('');
    const uuid = stableUuid(`${book.title}|${book.nodes.length}|${book.pages.length}`);
    zip.file('OEBPS/toc.ncx', '<?xml version="1.0" encoding="UTF-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n' +
      `<head><meta name="dtb:uid" content="urn:uuid:${uuid}"/></head><docTitle><text>${xmlEsc(book.title)}</text></docTitle>\n` +
      `<navMap>${navPoints(book.roots)}</navMap>\n</ncx>\n`);

    const manifest = [
      '<item id="nav" href="text/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
      '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
      '<item id="css" href="styles/book.css" media-type="text/css"/>',
      '<item id="title" href="text/title.xhtml" media-type="application/xhtml+xml"/>',
      ...FONTS.map((f, k) => `<item id="font${k + 1}" href="fonts/${f.file}" media-type="font/otf"/>`),
      ...[...images.values()].map((item, k) => `<item id="img${k + 1}" href="${item.path}" media-type="${MEDIA[extOf(item.path)] || 'image/jpeg'}"/>`),
      ...svgs.map((s, k) => `<item id="m${k + 1}" href="${s.path}" media-type="image/svg+xml"/>`),
      ...chapters.map((c, k) => `<item id="c${k + 1}" href="text/${c.file}" media-type="application/xhtml+xml"/>`),
    ];
    const spine = ['<itemref idref="title"/>', '<itemref idref="nav"/>', ...chapters.map((c, k) => `<itemref idref="c${k + 1}"/>`)];
    zip.file('OEBPS/content.opf', '<?xml version="1.0" encoding="UTF-8"?>\n' +
      '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="ko">\n' +
      '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n' +
      `<dc:identifier id="bookid">urn:uuid:${uuid}</dc:identifier>\n<dc:title>${xmlEsc(book.title)}</dc:title>\n<dc:language>ko</dc:language>\n` +
      `<meta property="dcterms:modified">${new Date().toISOString().replace(/\.\d+Z$/, 'Z')}</meta>\n` +
      '</metadata>\n' +
      `<manifest>\n${manifest.join('\n')}\n</manifest>\n<spine toc="ncx">\n${spine.join('\n')}\n</spine>\n</package>\n`);

    const blob = await zip.generateAsync({ type: 'blob', mimeType: 'application/epub+zip', compression: 'DEFLATE', compressionOptions: { level: 6 } });
    const name = `${fileBase(book.title)}.epub`;
    const stats = { name, bytes: blob.size, chapters: chapters.length, images: images.size, missingImages: missing.size, formulas: formulas.size, svgs: svgs.length, mathFailed: failed };
    const parts = [`장 ${chapters.length}`, `그림 ${images.size}`, `수식 ${svgs.length}`];
    if (missing.size) parts.push(`못 찾은 그림 ${missing.size}`);
    if (failed) parts.push(`변환 못한 수식 ${failed}(원문으로 넣음)`);
    return { ...stats, blob, summary: `${(blob.size / 1048576).toFixed(1)}MB · ${parts.join(' · ')}` };
  }

  const fileBase = (title) => title.replace(/[\\/:*?"<>|]+/g, '_').trim() || 'book';
  function download(blob, name) {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob); link.download = name;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 60000);
  }

  let busy = false;
  /** Builds the EPUB once at a time; `null` when there is nothing to export or a build is running. */
  async function build() {
    if (busy || !state.book) return null;
    if (document.body.classList.contains('editing')) { notify('편집을 끝낸 뒤 내보내세요.'); return null; }
    busy = true;
    try { return await buildEpub(); } catch (error) {
      notify(`EPUB을 만들지 못했습니다: ${error.message || error}`); return { error: String(error.message || error) };
    } finally { busy = false; }
  }
  /** Builds and downloads. */
  async function run() {
    const result = await build();
    if (result && result.blob) { download(result.blob, result.name); notify(`EPUB을 만들었습니다 (${result.summary}).`); }
    return result;
  }

  return { run, build, download, typeset, mathStyle, mathKey, rawMath, fileBase, isBusy: () => busy };
})();
