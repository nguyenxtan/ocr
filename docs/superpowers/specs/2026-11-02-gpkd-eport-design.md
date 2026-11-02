# GPKD–EPORT web

Implement the user's six-part specification in the existing Python repository, on `feat/gpkd-eport-web`; preserve Telegram entry point and behavior. Three white/purple screens: validate a pair of PDFs by content, inspect/edit sourced OCR fields, compare with evidence. No illustrative business data or confidence percentages.

Decision: FastAPI with plain browser JS/SVG and local assets, reusing PyMuPDF, Tesseract and existing seal/signatory primitives. This avoids a separate frontend build and OCR duplication. Alternative React/PDF.js adds a build/runtime and coordinate integration; embedding web into Telegram couples unrelated lifecycles. Bot remains unchanged; web has a separate Docker target/service.

PDF text words first if usable; OCR fallback with word boxes. Coordinates normalized to unrotated visible page. Each field has original/normalized value, label, evidence regions, extraction status and edit history. Classification depends on distinctive titles/content, not names. Conflicts/absence remain reviewable. Comparison uses exact identifiers and conservative normalized names. Seal identifier conflicts cannot be overridden by names. Different representatives require authorization review, not a legal verdict. Presence checks remain distinct from identity.

Each browser receives a random HttpOnly session capability; all document/job/image/report access is session-scoped. Bounded queue and subprocess deadline/cancellation; revision checks prevent stale publication. Private temporary directories, periodic TTL cleanup, no document content in request logs. Bind localhost by default. Public deployment requires HTTPS and appropriate access control.

Acceptance: unit/API adversarial cases, real sample PDF extraction, same-input old/new measurements, browser end-to-end, Telegram suite, Docker image build. Report actual failures/blockers, leave main unchanged unless all checks pass.
