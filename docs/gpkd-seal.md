# Xác nhận mộc GPKD — 03/11/2026

- Màn OCR GPKD có trường **Mộc cơ quan cấp trên GPKD**, vùng nguồn trên đúng trang và khả năng xác nhận/sửa Có hoặc Không có, kèm lịch sử. Nhiều vùng phải chọn một vùng trước khi xác nhận.
- Quét tất cả trang, tái sử dụng ảnh đã render và bộ phát hiện mộc hiện có. Chỉ kiểm tra hiện diện mộc cơ quan cấp; không chạy OCR tên/MST doanh nghiệp trên mộc này.
- Màn kết quả có tiêu chí `gpkd_seal` độc lập. Thiếu hoặc mờ là Cần kiểm tra; xác nhận Có là ghi nhận hiện diện, Không có là không đạt tiêu chí hiện diện. Có mộc EPORT không làm tiêu chí GPKD tự đạt.
- Ảnh bằng chứng và nút mở nguồn của tiêu chí mới trỏ GPKD, không trỏ EPORT. Báo cáo giữ loại tài liệu nguồn riêng. Nhãn hiện diện dùng Có/Không có, tránh hiểu là so khớp hình hai mộc.
- Không xác thực thật–giả, mẫu dấu hay giá trị pháp lý. Bộ phát hiện tập trung vào mộc đỏ tròn; mẫu khác, bản scan mờ hoặc tài liệu chỉ có chữ ký số có thể cần kiểm tra/xác nhận thủ công.

Kiểm chứng: **258 pytest qua** trên macOS (11,87 s) và Docker Linux ARM64/2 CPU/2 GB (18,86 s). Docker build thành công. Chromium qua trên hai PDF thật và fixture tổng hợp, gồm chọn trường mộc GPKD, xác nhận/lưu lịch sử và kiểm tra ảnh/nút nguồn ở màn kết quả đúng tài liệu GPKD. Ca unit còn kiểm tra mộc ở trang sau, chưa phát hiện mộc, xác nhận Có/Không có và không dùng OCR mộc doanh nghiệp cho GPKD. Telegram không thay đổi.
