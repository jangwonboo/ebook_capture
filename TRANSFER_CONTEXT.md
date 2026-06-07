# ebook_capture Transfer Context

> **Current CLI/docs:** see [`USAGE.md`](USAGE.md) and [`README.md`](README.md). Outputs: `images` | `pdf` | `text`. Main command: `run`.

Use this file as a compact handoff for future chats or other projects. It summarizes the key architecture, implementation decisions, solved problems, and reusable patterns from this project.

## Project Purpose

`ebook_capture` captures ebook pages from a target screen/window, optionally runs Google Gemini OCR, and produces **image PDF** and/or **Markdown** (from structured OCR JSON). Designed for Windows, RDP, multi-monitor, and corporate network environments.

Current pipeline:

```text
run --images|pdf|text
  job_plan → confirm (-y) → run_capture / assemble_markdown

Phase I   capture PNG (images / pdf / text)
Phase II  OCR JSON + _ocr.txt (text)
Phase III image PDF merge (pdf)
Assemble  OCR JSON → {title}.md (text)
```

Main entry points:

- `python -m ebook_capture run ...`
- `python -m ebook_capture gui`
- `ebook-capture run ...` after editable install

Current layout:

```text
cli.py
core/
  config.py
  job_plan.py / job_runner.py
  pipeline.py
  google_ocr.py
  image_pdf.py
  assemble_markdown.py
  screen_capture.py
  windows_util.py
  win32_bitmap_capture.py
gui/
  app.py
  snipping.py
  theme.py
  ui_capture.py
default_config.json
assets/
  ocr_default_prompt.txt
  ocr_lang.csv
```

## Core Decisions

Do not mix GUI and capture logic. The GUI collects options, writes a temporary config JSON, and runs the CLI in a subprocess using `QProcess`. The actual capture/OCR/PDF pipeline stays headless in `core/pipeline.py`.

Do not store final outputs in `tmp`. The path standard is:

```text
output/{title}/tmp/{title}_{page:04d}.png
output/{title}/tmp/{title}_{page:04d}.ocr.json
output/{title}/{title}.pdf
output/{title}/{title}.md
output/{title}/{title}_ocr.txt
output/{title}/capture_state.json
```

Long-running phases must be resumable. Per-page artifacts are written to `.part` first, then renamed atomically with `os.replace()`. Resume checks both manifest state and actual file validity.

External API setup is centralized in `core/google_ocr.py`. Do not scatter `genai.Client(...)` calls across the codebase.

## Capture Lessons

Windows/RDP capture is tricky because different APIs report different coordinate systems:

- `GetWindowRect`: outer frame including title bar/borders.
- `GetClientRect`: client size in window-local coordinates.
- `ClientToScreen`: converts client origin to screen coordinates.
- `GetWindowInfo.rcClient`: screen-space client rect, but can reflect physical DPI-scaled dimensions.
- RDP/MSTSC may expose a logical remote framebuffer that differs from the physical local window size.

Backends:

- `printwindow`: preferred for RDP/window capture. Captures the HWND client bitmap and often matches the RDP logical framebuffer.
- `screen`: uses `mss` or `pyautogui` screen-region capture. Better for manual regions, but sensitive to DPI and multi-monitor coordinates.

Important implementation notes:

- Screen-region capture should set Windows DPI awareness before resolving physical screen coordinates.
- PrintWindow capture should not force DPI awareness in the same way, because RDP logical and physical sizes can diverge.
- For multi-monitor capture, prefer `mss`; fallback to `pyautogui.screenshot(..., allScreens=True)` on Windows.
- Debug capture logs must include frame/client/crop rects and cursor position.
- If images are black, first verify HWND/title/backend/rect/DPI. Do not hide the root cause with image trimming.

Mouse cursor handling:

- Some capture environments include the cursor in screenshots.
- Option: `hide_cursor_during_capture`.
- Implementation saves current cursor position, moves cursor outside capture rect just for screen capture, then restores it.
- `PrintWindow` usually does not include the cursor, so this mainly matters for screen-region capture.

## OCR and Markdown

Tesseract was removed. OCR uses Google Gemini through `google-genai`.

Default model:

```text
gemini-2.5-flash
```

Override with:

```env
GOOGLE_OCR_MODEL=gemini-2.5-flash
```

Two OCR modes exist in `core/google_ocr.py`:

- `extract_text_from_image(...)`: plain text OCR.
- `extract_layout_from_image(...)`: structured JSON for Markdown assemble.

Layout OCR output shape:

```json
{
  "image_width": 853,
  "image_height": 1440,
  "text": "...",
  "blocks": [
    {
      "text": "...",
      "bbox": {"x": 0.12, "y": 0.08, "w": 0.74, "h": 0.03},
      "confidence": 0.0
    }
  ]
}
```

Rules:

- `bbox` is normalized `0..1` relative to the full image.
- Prompt must request only valid JSON, no markdown fences.
- JSON parsing should tolerate fenced output but fail clearly if no JSON object exists.

Image PDF:

- Implemented in `core/image_pdf.py`.
- Creates image-only page PDFs from PNG.
- Uses PNG DPI metadata for page size.
- Final PDF path is `output/{title}/{title}.pdf`.

Markdown:

- `core/assemble_markdown.py` reads `tmp/*.ocr.json` and writes `{title}.md`.
- Triggered by `run --text` (via `job_runner`).

## Google API, SSL, and Corporate Networks

Secrets must not be hardcoded. Use `.env` or OS env vars.

Minimum `.env`:

```env
GOOGLE_API_KEY=...
GOOGLE_OCR_MODEL=gemini-2.5-flash
GOOGLE_API_TRUST_MODE=auto
```

Trust modes:

```text
auto     OS trust store when available, otherwise certifi
system   OS trust store only, recommended for corporate Windows/proxy
certifi  public CA bundle only, recommended for open networks
```

Extra CA:

```env
GOOGLE_API_CA_BUNDLE=D:\path\company-ca.cer
```

Implementation details:

- Uses `truststore` for Windows/system certificate store.
- Falls back to `certifi`.
- Supports PEM bundles and DER `.cer` exported from Windows.
- DER `.cer` is converted using `ssl.DER_cert_to_PEM_cert()`.
- Never use `verify=False` as a standard solution.

Common errors:

- `GOOGLE_API_KEY environment variable not set`: missing `.env` or env var.
- `CERTIFICATE_VERIFY_FAILED`: use `GOOGLE_API_TRUST_MODE=system` or add `GOOGLE_API_CA_BUNDLE`.
- `NO_CERTIFICATE_OR_CRL_FOUND`: CA file is not valid PEM or DER certificate.
- `404 NOT_FOUND`: model name is stale. Update `GOOGLE_OCR_MODEL`.
- `429`, quota, rate: reduce pages, retry later, check quota.

## Resume Strategy

Resume is based on file validation plus manifest.

State file:

```text
output/{title}/capture_state.json
```

Example:

```json
{
  "title": "Book",
  "start_page": 1,
  "n_pages": 100,
  "phases": {
    "capture": {"1": {"status": "done", "path": "..."}},
    "ocr": {"1": {"status": "done", "path": "..."}},
    "pdf": {"1": {"status": "done", "path": "..."}}
  },
  "errors": [],
  "outputs": {
    "final_pdf": "...",
    "combined_txt": "...",
    "final_markdown": "..."
  }
```

Validation rules:

- PNG must exist, be non-empty, and open/verify with Pillow.
- OCR JSON must parse and contain expected structure.
- PDF must exist and be non-empty.

CLI patterns:

```powershell
python -m ebook_capture run --config default_config.json --pdf -y
python -m ebook_capture run --config default_config.json --images -y
python -m ebook_capture run --config default_config.json --text -y
python -m ebook_capture run --config default_config.json --text --force-phase ocr -y
python -m ebook_capture run --config default_config.json --no-resume -y
```

Mode defaults:

- `title` default is `unknown` when omitted/blank.
- default output mode is `pdf` (capture + normal image PDF, no OCR).

Capture resume warning:

- Capture phase is tied to the ebook viewer’s current page. If earlier pages are skipped, the viewer must already be positioned at the next page to capture.
- OCR/PDF phases are file-based and safe to resume.

## Logging Standards

Logs are user-facing because GUI shows CLI stdout/stderr.

Use stable prefixes:

```text
Phase I: capture PNG
IMAGE_OK
IMAGE_SKIP
CAPTURE_RESUME_WARN
Phase II: PNG -> TXT + OCR JSON (Google Gemini)
OCR_TEXT_OK
OCR_JSON_OK
OCR_OK
OCR_FAIL
Phase III: image PDF
PDF_PAGE_OK
PDF_PAGE_SKIP
PDF_OK
PDF_FAIL
TEXT_OK
DEBUG_RECT
DEBUG_CAPTURE
```

Never log:

- API keys
- `.env` contents
- cert PEM/DER body
- OAuth tokens
- service account JSON body
- full OCR text or huge JSON responses

Debug logs should include values needed for reproduction, especially:

- target window title
- HWND
- frame/client/crop rects
- backend selection
- image dimensions
- cursor position
- output paths

## Useful Commands

Install/update editable environment:

```powershell
pip install -e .
```

Help:

```powershell
python -m ebook_capture run --help
```

Google client smoke test:

```powershell
python -c "from core.google_ocr import _client; print(type(_client()).__name__)"
```

Gemini call smoke test:

```powershell
python -c "from core.google_ocr import _client; c=_client(); r=c.models.generate_content(model='gemini-2.5-flash', contents='Reply with exactly: OK'); print((r.text or '').strip())"
```

Capture one page only:

```powershell
python -m ebook_capture run --config default_config.json --images --debug-capture --debug-max-pages 1 -y --title smoke_capture
```

OCR existing PNGs:

```powershell
python -m ebook_capture run --config default_config.json --text --debug-max-pages 1 -y --title smoke_text
```

Build image PDF from existing PNG:

```powershell
python -m ebook_capture run --config default_config.json --pdf --debug-max-pages 1 -y --title smoke_pdf
```

Compile check:

```powershell
python -m compileall "core" "gui" "cli.py"
```

## Reuse Checklist for Other Projects

When transferring this knowledge to another project:

- Copy the path helper pattern from `CaptureConfig`.
- Keep external API code centralized.
- Keep GUI and long-running work separated.
- Use per-page artifacts.
- Use `.part` atomic writes.
- Use a manifest, but validate files too.
- Add `--force-phase`, `-y`, and `run --images|pdf|text`.
- Keep SSL trust configurable with `auto`, `system`, `certifi`.
- Support corporate CA files without disabling SSL verification.
- Keep final outputs outside `tmp`.
- Add logs with stable prefixes and no secrets.

Do not copy:

- `.env`
- API keys
- service account JSON
- certificate files unless explicitly intended
- user-specific window titles and output paths
- `verify=False`
- image trimming hacks that hide capture coordinate bugs
