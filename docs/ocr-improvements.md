# Cải tiến độ đọc và thời gian OCR — 03/11/2026

Mục tiêu: cải thiện luồng OCR hiện có, giữ nguyên ba màn và bot Telegram. Baseline web: commit `fa5e78a0676fd1ee332014f4b8cb3fa965e4db1b`.

## Thay đổi

- Đọc và render PDF trên một thread. Chỉ công việc Tesseract chạy tối đa hai trang song song, phù hợp giới hạn 2 CPU của container. Kết quả vẫn ghép theo thứ tự trang; toàn bộ bước kiểm tra nội dung/trường/dấu được giữ nguyên. Lỗi một trang không trả hồ sơ hoàn tất một phần.
- Với trường tên còn `uncertain`, chỉ đọc lại các vùng nguồn đã có trong ảnh OCR: tên doanh nghiệp, tên Anh, chủ sở hữu, đại diện pháp luật/có thẩm quyền. Cắt đúng vùng từng dòng, thêm lề trắng và dùng chế độ một dòng. Không đoán giá trị hoặc lấy tên từ tài liệu khác.
- Chỉ xác nhận `read` khi toàn bộ nội dung đọc lại trùng bản đầu sau chuẩn hóa giữ dấu, và mọi dòng đạt ngưỡng chữ rõ hiện có. Giữ nguyên raw/value/normalized/trang/vùng nguồn và lịch sử sửa tay. Trường có nhiều ứng viên, dữ liệu đã rõ/đã sửa, nguồn quá rộng hoặc thiếu ảnh không được tự nâng trạng thái.
- Giới hạn tối đa 6 vùng đọc lại mỗi PDF, 3 giây mỗi vùng, có giới hạn kích thước ảnh. Lỗi/timeout, thiếu chữ, khác dấu, khác nội dung hoặc điểm không hợp lệ đều giữ kết quả ban đầu để kiểm tra. Không thay ngưỡng đối chiếu hoặc xác nhận chữ ký/dấu bằng tên in.
- Ghi riêng thời gian `recheck` và số vùng đã thử/số trường xác nhận. Đây không phải phần trăm độ chính xác hay xác suất thật–giả.

Việc dùng phân đoạn phù hợp cho vùng nhỏ và thêm lề dựa trên [hướng dẫn chính thức của Tesseract](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html). Chỉ giữ cách xử lý sau khi đo và kiểm tra trên đầu vào thực tế.

## Đo trước–sau

`benchmarks/web_quality.py` tải mã baseline từ commit rõ ràng, luân phiên thứ tự cũ/mới trong 3 lượt, dùng đúng cùng hai PDF người dùng cung cấp. Chỉ in metadata. Script xác nhận raw/value/normalized/vùng nguồn và loại tài liệu không đổi trong cả 6 cặp so sánh. Không đưa PDF hay giá trị cá nhân vào Git.

Máy macOS ARM64/Python 3.12/Tesseract 5.5.4, thời gian xử lý trong worker; không gồm mạng tải lên hoặc ảnh bằng chứng phụ:

| PDF | Trung vị trước | Trung vị sau | Thay đổi |
|---|---:|---:|---:|
| GPKD, 2 trang | 0,934 s | 0,842 s | giảm 9,9% |
| EPORT, 2 trang | 6,076 s | 5,333 s | giảm 12,2% |

Trạng thái được xác nhận rõ hơn trên mẫu: tên Anh GPKD; tên doanh nghiệp và đại diện có thẩm quyền EPORT. Chỉ trạng thái/metadata đọc lại thay đổi; giá trị gốc và vị trí nguồn không đổi. Tên người ký và thông tin dấu chưa đọc chắc vẫn cần kiểm tra. Kết quả trên hai file không là tỷ lệ chính xác chung hay cam kết tốc độ cho mọi PDF.

Lệnh đo lại (chỉ dùng baseline từ repo tin cậy):

```bash
python -m benchmarks.web_quality \
  --baseline-ref fa5e78a0676fd1ee332014f4b8cb3fa965e4db1b \
  /duong/dan/gpkd.pdf /duong/dan/eport.pdf
```

## Kiểm chứng

- Kiểm tra ghép trang đúng thứ tự, PDF không vào thread OCR, hai công việc OCR thực sự có thể đồng thời.
- Kiểm tra giữ nguyên nguồn/giá trị gốc; đọc lại nhiều dòng phải khớp đủ; khác dấu/tên, thiếu chữ, điểm thấp/NaN/Inf, timeout, ảnh ngoài trang hoặc quá ngân sách không được tự xác nhận.
- Chạy toàn bộ pytest (gồm hồi quy bot), Docker build/suite và Chromium với hai PDF thật cùng fixture sai loại/mơ hồ/vùng chữ ký. Kết quả cụ thể được chốt sau các lượt chạy bên dưới.

Kết quả chốt:

- macOS: **254 pytest qua**, 8,93 giây (gồm hồi quy Telegram).
- Docker Linux ARM64, read-only/2 CPU/2 GB: **254 pytest qua**, 18,96 giây.
- Docker Compose build và khởi động web thành công.
- Chromium: qua luồng với hai PDF thực; qua fixture sai loại, nhiều ứng viên, nhiều vị trí nghi chữ ký, nguồn khi zoom/xoay và báo cáo snapshot.
- Bot/thuật toán đối chiếu và các lệnh Docker cũ không đổi. Không gọi thêm Claude hay worker khác.
