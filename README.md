# OCR PDF Verification Bot (POC)

Bot Telegram kiểm tra, trích xuất và **so khớp nội dung chứng từ PDF**. Repo hiện lưu đặc tả POC, **chưa có mã nguồn triển khai**.

## Phạm vi

- Chỉ nhận **PDF**, gồm PDF scan, PDF có lớp văn bản và PDF có chữ ký số.
- Phát hiện dấu tròn doanh nghiệp; trích xuất **MST** và **tên doanh nghiệp** trên dấu.
- So khớp với tên và MST khai báo trong chứng từ.
- Đối chiếu tên/chức vụ tại vị trí ký với thông tin người đại diện được khai báo trên chứng từ, nếu có đủ dữ liệu.
- Nhận diện chữ ký số nhúng **riêng biệt** với hình con dấu trên giấy.

## Quy tắc đối chiếu con dấu (đã chốt)

1. **Ưu tiên MST**: nếu đọc được MST trên dấu với độ tin cậy đủ cao:
   - Khớp MST chứng từ → `PASS_MST`.
   - Mâu thuẫn MST chứng từ → `FAIL`; không dùng tên để bỏ qua sai lệch.
2. **Fallback theo tên**: nếu MST trên dấu không đọc được/chưa đủ tin cậy:
   - Tên doanh nghiệp trên dấu khớp rõ ràng với tên trên chứng từ → `PASS_NAME_FALLBACK`.
   - Tên mâu thuẫn rõ ràng → `FAIL`.
   - Dữ liệu mờ, thiếu hoặc không chắc chắn → `REVIEW`.
3. Không phát hiện dấu → `FAIL` nếu hồ sơ được cấu hình bắt buộc có dấu.
4. Chữ ký số không tự động được coi là dấu tròn vật lý.

`PASS` nghĩa là **đạt kiểm tra đối chiếu nội dung theo tiêu chí đã chọn**, không phải xác nhận pháp lý.

## Phản hồi Telegram ngắn gọn (đã chốt)

Bot chỉ trả **kết luận, thông tin chính, phương án đối chiếu và lý do khi có lỗi**. Có nút `🔍 Xem chi tiết` để mở ảnh dấu/bằng chứng OCR khi cần.

### 1. PASS bằng MST

```text
✅ HỒ SƠ ĐẠT
🏢 Doanh nghiệp: [Tên doanh nghiệp]
🔴 Con dấu: Có
✅ MST: [MST] (Khớp)
✅ Người ký: [Tên] (Khớp)
🔎 Đối chiếu: MST
```

### 2. PASS bằng tên (fallback)

```text
✅ HỒ SƠ ĐẠT
🏢 Doanh nghiệp: [Tên doanh nghiệp]
🔴 Con dấu: Có
⚠️ MST trên dấu: Không đọc được
✅ Tên doanh nghiệp: Khớp
✅ Người ký: [Tên] (Khớp)
🔎 Đối chiếu: Tên doanh nghiệp (Fallback)
```

### 3. FAIL

```text
❌ HỒ SƠ KHÔNG ĐẠT
🏢 Doanh nghiệp: [Tên doanh nghiệp]
🔴 Con dấu: Không phát hiện
⚠️ Chữ ký số: Có
📌 Lý do: Thiếu dấu doanh nghiệp theo tiêu chí kiểm tra.
```

Trạng thái: `PASS`, `FAIL`, `REVIEW` (chưa đủ dữ liệu). Ghi nhận phương thức `MST_MATCH` hoặc `NAME_FALLBACK` trong dữ liệu kết quả, dù câu trả lời cho người dùng dùng tiếng Việt dễ hiểu. Nếu MST đọc được nhưng **không khớp**, không được fallback theo tên để bỏ qua mâu thuẫn. Trường tên/chức vụ chỉ hiện “Khớp” khi có đủ dữ liệu đọc được. `FAIL` do không có dấu chỉ áp dụng khi quy trình bắt buộc dấu tròn vật lý.

## Công nghệ POC dự kiến

Python, Telegram Bot API, PyMuPDF (đọc/render PDF), OpenCV (xác định vùng con dấu), PaddleOCR (nhận dạng chữ), RapidFuzz (so khớp tên có kiểm soát), pyHanko (chữ ký số). AI Vision chỉ dự phòng cho trường hợp OCR khó.

## Không thuộc phạm vi

- Không phân biệt con dấu thật/giả.
- Không kết luận tư cách người đại diện theo pháp luật hay giá trị pháp lý của chữ ký.
- Không hỗ trợ ảnh hoặc Word gửi trực tiếp; chỉ nhận PDF.

## Lưu ý dữ liệu

Không đưa PDF khách hàng, giấy tờ định danh, token Telegram hoặc khóa bí mật lên repo công khai. File tải lên chỉ xử lý tạm thời; xóa sau khi hoàn tất.

## Trạng thái

Đã chốt yêu cầu và logic fallback. Chưa triển khai/kiểm thử bot, OCR và benchmark thực tế.
