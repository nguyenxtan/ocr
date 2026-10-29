# Telegram output contract (POC)

Status labels: PASS, FAIL, REVIEW. Telegram body shows physical stamp page, company name OCR token coverage, tax-code status, and signer comparison. Embedded PDF signature status is separate from ink-seal presence.

- Name matching percentage is **distinctive token coverage**, not confidence or authenticity.
- No visible 'Fallback/Dự phòng' label; internal method remains `NAME_FALLBACK`.
- `MST: Chưa thấy trên chứng từ` when no clearly labeled tax number was read.
- `MST: Chưa đọc rõ trên dấu` when document MST exists but the stamp code is unreadable.
- `MST: Không khớp` only when reliable, complete tax codes contradict.
- `Người ký: Chưa đọc rõ` for low-confidence handwriting. No auto-PASS from the declared name.
- Digital signing and physical ink seals are separate; a signed PDF can fail a physical-seal-required check.
