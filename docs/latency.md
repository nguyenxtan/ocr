# Tối ưu thời gian phản hồi Telegram

## Đã thay đổi

- Bot gửi **kết quả OCR hoàn chỉnh ngay khi tính xong**, không chờ tạo ảnh bằng chứng.
- Giải phóng lượt OCR trước khi gửi kết quả/tạo ảnh; PDF tiếp theo không phải chờ riêng bước ảnh của PDF trước.
- Ảnh có hàng xử lý riêng, chỉ một tác vụ tạo ảnh đồng thời. Nút **Xem bằng chứng** được thêm vào chính tin nhắn kết quả sau khi có ảnh thật; không tạo nút rỗng.
- Lỗi tạo ảnh hoặc `/stop` trong giai đoạn ảnh không được đổi một kết quả đã hoàn thành sang REVIEW.
- Các lần gọi Paddle trong một PDF dùng chung `PADDLE_TOTAL_TIMEOUT_SEC=18` giây. Khi đã lỗi kết nối hoặc hết thời gian chờ, không tiếp tục gọi cùng dịch vụ nhiều lần trong PDF đó. PDF tiếp theo có ngân sách mới và được thử lại.
- Nếu riêng mô hình `seal` không sẵn sàng, không vô hiệu hóa mô hình `general` đang chạy. Vẫn giữ cách chuyển về kết quả Tesseract vốn có khi Paddle không sẵn sàng.

**Không bỏ kiểm tra MST, người ký, các mâu thuẫn, hoặc giảm ngưỡng so khớp.** Đây là tối ưu thời gian chờ và trình tự gửi kết quả, không phải tuyên bố mô hình OCR đã nhanh hơn hay chính xác hơn.

## Cập nhật

```bash
git pull
docker compose -f compose.yaml -f compose.paddle.yaml up -d --build --force-recreate
```

Bản thường: `docker compose up -d --build --force-recreate`. Không cần đổi token hoặc `.env` hiện có. `PADDLE_TOTAL_TIMEOUT_SEC` mặc định là 18 khi chưa khai báo. `EVIDENCE_TIMEOUT_SEC=15` áp dụng **sau khi đã trả kết quả**, gồm cả thời gian chờ đến lượt tạo ảnh. Thời hạn toàn tiến trình `PROCESS_TIMEOUT_SEC` vẫn bảo vệ OCR.

## Chẩn đoán trên máy chạy thật

Log không chứa nội dung PDF, tên file, MST, họ tên hay token. Dòng `PDF latency` ghi thời gian chờ hàng đợi, tải file, OCR, và từ lúc nhận đến lúc gửi kết quả. Dòng `PDF evidence` ghi riêng thời gian tạo ảnh.

```bash
docker compose -f compose.yaml -f compose.paddle.yaml logs --tail=100 bot
```

`queue_s`, `download_s`, `ocr_s`, `verdict_s` giúp xác định chậm ở bước nào thay vì chỉ tăng timeout. Ngân sách Paddle được trừ theo thời gian gọi dịch vụ thực tế; hạn cứng toàn tác vụ vẫn do tiến trình OCR áp dụng.

## Đo kiểm

Các test hồi quy tái hiện việc kết quả bị giữ để chờ ảnh, ảnh lỗi ghi đè verdict, Paddle lỗi bị gọi lặp, hủy bước ảnh, và bảo vệ ảnh theo người gửi.

`benchmarks/response_latency.py` chạy mã xử lý Telegram thật ở hai phiên bản với **OCR/Telegram/ảnh mô phỏng giống nhau**. Nó chỉ đo phần chờ không cần thiết trong handler, **không phải** benchmark tốc độ mô hình, PDF của khách hàng hay VPS thật. CI chạy toàn bộ pytest, thí nghiệm này và build Docker. Tốc độ thực tế trên máy chủ còn phụ thuộc PDF, CPU/RAM, mạng và tình trạng nạp mô hình.
