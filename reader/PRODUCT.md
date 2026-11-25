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

- Open a book folder (or a Markdown file) without a server; images follow the Markdown's relative links when the folder is opened.
- Heading tree, one chapter per screen, search, saved positions, fonts, sizes, themes.
- Annotations: highlights, memos with `#tags`, filters, Markdown/JSON export. Stored in `<book>.notes.json` in the book folder (Chrome/Edge with write access) and in browser storage as a second copy.
- Opt-in AI Q&A about a selected passage; the browser calls the Anthropic API with a key entered in Settings. Answers cite the source sentences and can be adopted as the annotation. Default model Claude Sonnet 5.5.
- The API key never goes into the notes file or exports.
- OCR fixes belong to the capture pipeline; the reader only bridges text cut by page breaks in books already produced.

Full specification, decisions and backlog: `SPEC.md`.

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
