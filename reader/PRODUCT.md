# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

delegated: dependency-free HTML, CSS, and browser JavaScript chosen so a reader can open local Markdown files without a server or build step.

## Users

Individuals who hold OCR Markdown or authored Markdown and want a calm, searchable reading experience on their own computer.

## Product Purpose

Turn local ebook source files into a readable browser experience. Success means a reader can open a source, orient themselves, read comfortably, search it, and return to their place without uploading private documents.

## Positioning

The reader turns a local Markdown document into a reflowable, hierarchical reading experience while remaining entirely local to the browser.

## Operating Context

The reader opens one book (a Markdown file, ideally its whole folder) from a desktop browser by double-clicking `index.html`. There is no server.

## Capabilities and Constraints

- Accept Markdown through the file picker or drag and drop.
- Keep reading position, saved positions, read marks, and annotations in `<book>.notes.json` inside the book folder when the folder was opened with write access (Chrome/Edge), and always in browser local storage as a second copy. Reading settings stay in the browser.
- No account, server, or collaboration. Nothing leaves the browser unless the reader turns on AI Q&A (below).
- Opening or dropping the book folder follows the Markdown's relative image links; a Markdown file opened alone shows images only when they are selected with it, because a browser cannot read paths next to a picked file.
- Two same-level sub-headings in a row with no text between them are read as one heading split by OCR and joined.
- Text cut by page breaks is rejoined when the book is read: a body paragraph that stops without sentence punctuation continues into the next one (the book's own vocabulary decides whether the seam needs a space), and a short dangling phrase right before a sub-heading becomes that heading's first line. The Markdown file itself is not changed.
- Annotations: highlight selected text in four colours, attach a memo with `#tags`, and filter the right-hand panel by scope, colour, kind and tag. Export to Markdown or JSON; import JSON.
- AI Q&A (opt-in): ask Claude about a selected passage. The browser calls the Anthropic API directly with a key the reader enters in Settings; each question sends the passage, the current chapter, the book title and outline, and that annotation's earlier turns. Answers link to the source sentences they cite and can be adopted as the annotation. Default model: Claude Sonnet 5.5.
- The API key lives only in the browser (memory, or local storage when the reader chooses to remember it). It is never written to the notes file or exports.
- Body font choice: Noto Serif KR, Pretendard, KoPub Batang, KoPub Dotum. Installed fonts are used first.

## Evidence on Hand

- Functional plan: `docs/기능기획.md`; annotations, saving and AI Q&A: `docs/추가기획.md`.
- Example scanned book sources outside the repository are used only as a design and content-shape reference.

## Product Principles

- The book, not the interface, holds the reader's attention.
- Source fidelity and reflowable readability coexist instead of competing.
- Local-first behavior is the default, not an optional privacy mode. Sending book text to an AI is a separate, explicit choice per book.
- What a person wrote and what an AI wrote are never visually interchangeable.
- Navigation should work from a reading need as well as from a table of contents.

## Accessibility & Inclusion

- Keyboard-operable navigation and visible focus states.
- Adjustable font size.
- Light, dark, and high-contrast reading themes.
