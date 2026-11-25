# Design

## Visual world

An editorial reading room: warm paper, ink-black type, a restrained evergreen signal color, and quiet ruled details. The interface feels like a well-made field notebook rather than a dashboard. It must accommodate any book, so no specific book cover, author, or historic motif is treated as the product identity.

## Typography

- Display and book titles use `Noto Serif KR` when available, then Korean serif fallbacks.
- UI labels and dense controls use `Noto Sans KR` and system sans fallbacks.
- Long-form text has a deliberately narrow measure and generous leading.

## Tokens

- Paper: `#eef0eb`; ink: `#1a1c19`; evergreen: `#285448`; muted ink: `#59635d`.
- Night: `#141917`; night paper: `#dfe4dc`; night evergreen: `#8ec4ae`.
- Corners are modestly rounded; elevated elements use soft, offset shadows.

## Interaction

- A reader moves with the table-of-contents tree, previous/next chapter controls, and keyboard shortcuts.
- One chapter (heading level 2 or shallower) fills the reading pane; deeper headings stay inside it and the tree follows the scroll position.
- Saving provides immediate text feedback instead of decorative animation. The notes panel always states where annotations are stored (file, browser only, failed).
- Selecting text raises a small toolbar: four colours, memo, ask AI, copy. A highlight shows ✎ when it has a memo and ✦ when it has an AI thread; an AI-only annotation is underlined instead of filled.
- AI answers carry an "AI" badge, the model name, the date and token counts, and list their source sentences as buttons that jump into the text.
- Markdown heading depth is reflected as a collapsible tree. The arrow only expands or collapses; the title navigates.

## Responsive behavior

- Desktop is two panes plus an optional third: a resizable, collapsible sidebar (tabs: contents, search, saved) on the left, the reading pane, and a 360px notes panel on the right that the reader toggles.
- At 1050px and below the notes panel overlays the text instead of squeezing it.
- At 720px and below the sidebar becomes a drawer with the same tabs; the reading pane keeps a single-column measure.
