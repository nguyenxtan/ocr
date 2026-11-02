# GPKD–EPORT Implementation Plan

> Execute inline, task by task, following test-driven development. User explicitly requested a short plan followed by implementation.

**Goal:** Three-screen functional web for PDF classification, sourced extraction/editing and conservative comparison.
**Architecture:** Separate FastAPI service, bounded subprocess queue, session-private temp files; existing bot unchanged. Browser JS/SVG for page images and source overlays.
**Tech Stack:** Python/PyMuPDF/Tesseract/FastAPI; vanilla JS/CSS.
**Spec:** docs/superpowers/specs/2026-11-02-gpkd-eport-design.md

## Global Constraints
No sensitive sample content in Git/logs. No hardcoded company, tax ID, page or box from samples. Preserve Telegram. No invented confidence or legal/authenticity claims. Missing/unreadable never equals match. Main remains unchanged until acceptance.

## Review Focus
- Replaced PDF while job is running: cancel and reject stale result.
- Duplicate labels or conflicting identifiers: mark ambiguous, retain sources.
- Rotated/cropped pages: normalized canonical coordinates survive zoom/rotation.
- OCR failure and password PDFs: recoverable error, no stale pass.
- Session guessing, expiry, queue overload: deny or expire cleanly.

### Task 1: Sourced extraction and comparison
Files: app/web_extract.py, app/web_compare.py, tests/test_web_extract.py, tests/test_web_compare.py.
Interfaces: extract(path, kind) -> document dict; classify(lines) -> kind; compare(documents) -> report dict.
- [x] Write/run failing tests for classification by content, missing fields, multipage provenance, owner/legal separation, MST contradiction, authorization review, unreadable seal.
- [x] Implement canonical word/line extraction, labeled fields, seal/signatory reuse and conservative comparison.
- [x] Run new tests and existing Telegram suite; commit.

### Task 2: Session API and jobs
Files: app/web.py, app/web_jobs.py, requirements-web.txt, tests/test_web_api.py.
Interfaces: /api/session, /api/documents/{kind}, /api/jobs, /api/fields/{kind}/{key}, /api/report, scoped /api/pages.
- [x] Write/run failing API tests: invalid/password/oversize/wrong type, isolation, replacement/delete invalidation, edits/history and invalid boxes.
- [x] Implement bounded streamed upload, private session lifecycle, queue/cancel/deadline and revision-aware results; page rendering on demand after result.
- [x] Run API and full pytest; commit.

### Task 3: Three-screen UI
Files: app/static/index.html, app/static/style.css, app/static/app.js, tests/browser.mjs, package.json.
- [x] Write browser checks for upload, step gates, field/region links, edit, zoom/rotation, comparison, replacement and invalid PDF.
- [x] Implement white/purple UI with real API and SVG coordinates; no mock results.
- [x] Run browser against sample PDFs, inspect screenshot; commit.

### Task 4: Delivery and acceptance
Files: README.md, .env.example, Dockerfile.web, compose.web.yaml, benchmarks/web_compare.py, docs/web-validation.md.
- [x] Add isolated web Docker service, configuration, limits and run instructions.
- [x] Measure old/new on identical samples without persisting content; run Telegram regression, browser suite and Docker build.
- [x] Review code, fix important findings with regression tests; record evidence and remaining limitations; commit on feature branch. Merge only if acceptance is satisfied.

## Execution record

Tasks 1–4 implemented in commits on feature branch. Independent review: five Important findings fixed with regression coverage. Full validation and known limitations: `docs/web-validation.md`. Main intentionally not merged; no customer PDFs or extracted values committed.
