# Dò vùng nghi con dấu trên bản photocopy

Yêu cầu: dấu đóng trên bản gốc có thể chuyển thành đen/xám khi photocopy.
Web phải tìm vùng nguồn từ ảnh thực tế, không dùng vị trí mẫu hay yêu cầu dấu đỏ.

Phương án: giữ nguyên bộ dò đỏ và bot Telegram, thêm bộ dò đơn sắc riêng cho
web, dùng cấu trúc hai vòng tròn/ellipse và nét bên trong. Không coi màu đen,
vòng tròn hoặc hình học là bằng chứng xác thực dấu. Mọi ứng viên đơn sắc ở
trạng thái `Nghi có`/`uncertain`, cần người dùng xác nhận. Không tìm thấy vẫn là
thiếu/chưa xác định, không suy ra không có dấu. Dấu vuông, vỡ nặng hoặc quá mờ
có thể chưa tìm được và vẫn cần khoanh vùng thủ công.

Không dùng riêng ngưỡng màu đỏ (bỏ sót photocopy), không mở rộng trực tiếp bộ
dò của Telegram (tránh đổi hành vi bot), không thêm mô hình/dịch vụ ngoài.

Kế hoạch triển khai:

- [x] Viết và chạy ca thất bại: dấu đen/xám, ellipse, dịch chuyển/đổi tỉ lệ,
  cùng trang có dấu đỏ và đen, chữ/bảng/vòng tròn không dấu, nguồn trang sau.
- [x] Thêm `app/web_stamps.py`, tích hợp cả GPKD/EPORT; giới hạn kích thước
  ảnh phân tích, trả tọa độ ảnh gốc; giữ OCR dấu đen ở trạng thái chưa xác nhận.
- [x] Kiểm thử toàn bộ, Docker build và Chromium với fixture photocopy;
  đo đối chiếu trước/sau trên cùng PDF và ghi giới hạn thực tế.

## Kết quả thực tế — 03/11/2026

- **271 pytest qua** trên macOS/Python 3.12 (12,36 s) và Docker Linux ARM64,
  giới hạn 2 CPU/2 GB (20,03 s), gồm hồi quy Telegram. Bot và detector của bot
  không đổi. Có cảnh báo deprecation sẵn có của PyMuPDF/Starlette, không có lỗi test.
- Docker web build `64befdcb8e32` thành công. Chromium qua cả luồng ba màn với
  hai PDF thật, fixture thường và fixture dấu xám: chọn nguồn, zoom/xoay, sửa/lịch
  sử, đối chiếu, export, xóa/thay file và chọn ứng viên. Fixture dấu xám khẳng định
  cả hai tài liệu có nguồn ở trang 2 và trạng thái `Nghi có` trước khi sửa.
- 13 ca mới: dấu đen, dấu xám nhạt, ellipse, đổi vị trí/kích thước, cùng trang có
  dấu đỏ và đen, chữ/bảng/hình tròn đặc/vòng tròn rỗng, nét ký/chữ đè lên vòng dấu,
  nguồn trên trang sau cho cả GPKD/EPORT và không tự xác nhận MST OCR từ vùng nghi dấu.
- Bộ dò bổ sung giảm ảnh phân tích xuống tối đa 1000 pixel ở cạnh dài, dùng
  contour/ellipse và Hough cho vòng bị giao cắt; bỏ đường bảng dài khi bỏ phiếu,
  kiểm tra lại hai vòng trên ảnh mực gốc. Giữ crop và tọa độ ảnh gốc, không dùng
  vùng hình học đã xóa đường bảng để đọc nội dung. Tối đa ba vùng trên mỗi trang
  như giao diện detector cũ (bộ trích xuất tổng hợp mọi trang).

### Đối chiếu cùng PDF với main trước sửa

Baseline `6cb0a091867b2f2c118c09531a89d828a8b17f50`, ba lần chạy mỗi cặp,
đảo thứ tự bản cũ/mới. Chỉ in metadata, không lưu PDF/giá trị hồ sơ vào Git.
Mỗi PDF còn được render thành scan grayscale 108 dpi trong thư mục tạm riêng
và xóa khi đo xong; đây là mô phỏng photocopy, chưa phải tập bản photo thực tế.

| Đầu vào | Trung vị cũ | Trung vị mới | Vùng dấu cũ → mới |
|---|---:|---:|---|
| GPKD gốc | 0,948 s | 1,305 s | 1 → 1, giữ `read` |
| GPKD scan xám | 0,945 s | 1,298 s | 0/thiếu → 1/`uncertain` |
| EPORT gốc | 5,763 s | 7,266 s | 3 → 3, giữ `read` |
| EPORT scan xám | 2,599 s | 5,429 s | 0/thiếu → 1/`uncertain` |

Phân loại và giá trị/vùng nguồn các trường ngoài dấu giữ nguyên giữa hai bản
trên cùng đầu vào trong mọi lần đo. Mỗi bản scan xám đều tìm được một vùng nghi
dấu; không có nghĩa đã tìm đủ mọi dấu. Phần kiểm tra hình học và OCR vùng mới
làm chậm thêm; không bỏ kiểm tra để giữ số thời gian cũ. Không suy ra tỷ lệ chính
xác từ hai hồ sơ này.

Chạy lại (dùng commit baseline đầy đủ và đường dẫn PDF ngoài repo):

```bash
python -m benchmarks.photocopy_seals --baseline-ref 6cb0a091867b2f2c118c09531a89d828a8b17f50 /path/gpkd.pdf /path/eport.pdf
python tests/make_web_fixtures.py /tmp/ocr-ci-fixtures
GPKD_PDF=/tmp/ocr-ci-fixtures/gpkd-photocopy.pdf EPORT_PDF=/tmp/ocr-ci-fixtures/eport-photocopy.pdf REQUIRE_PHOTOCOPY_SEALS=1 npm run test:browser
```

### Giới hạn

Logo có hai vòng và chữ bên trong vẫn có thể bị nhầm; cần xác nhận vùng trước
khi coi là có dấu. Dấu vuông, dấu thiếu vòng, nét quá vỡ/mờ, dấu bị cắt mép hoặc
ảnh nhiều nhiễu có thể bị bỏ sót; dùng vẽ vùng thủ công. Không xác minh cơ quan
phát hành, chủ sở hữu dấu, tính thật–giả hay thẩm quyền pháp lý. Không thể tách
chắc chữ in/nét ký đè qua dấu trên bản photocopy; nội dung OCR trong vùng nghi
dấu giữ `uncertain`, kể cả khi OCR đọc rõ một MST.
