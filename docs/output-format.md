# Telegram result contract

Show only PASS/FAIL/REVIEW, seal page, match result, and MST status.

PASS_NAME example:

```text
✅ HỒ SƠ ĐẠT
🔴 Dấu đỏ · Trang 2
🏢 Tên doanh nghiệp: Khớp 86%
🧾 MST: Chưa thấy trên chứng từ
```

`86%` is distinctive-name-token OCR coverage, not confidence and not a static setting.
The display omits "Dự phòng" but backend still records `NAME_FALLBACK`.

MST states: `MATCH` (matches); `MISMATCH` (confidently different); `UNREADABLE` (stamp unclear); `NO_DOC` (no labeled MST on PDF); `CONFLICT` (contradictory evidence). Do not mistake absent readings for mismatches.
