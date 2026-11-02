# Kiểm thử web GPKD–EPORT — 02/11/2026

Nhánh: `feat/gpkd-eport-web`. Baseline: `origin/main` tại `79d7207`. Hai PDF do người dùng cung cấp được đọc từ bên ngoài repo; không đưa file, giá trị cá nhân hay ảnh hồ sơ vào Git. Chưa gộp `main`.

## Kết quả đã chạy

| Hạng mục | Kết quả thực tế |
|---|---|
| Baseline trước khi thêm web | 163 pytest qua, macOS ARM64/Python 3.12 |
| Toàn bộ suite sau thay đổi | **208 pytest qua**, macOS, 8,98 giây |
| Toàn bộ suite trong Docker Linux ARM64 | **208 pytest qua**, read-only/2 CPU/2 GB RAM, 15,10 giây |
| Browser Chromium, hai PDF người dùng | Qua toàn luồng bằng API/OCR thật; không mock kết quả OCR |
| Browser Chromium, PDF tổng hợp cho CI | Qua; không cần đưa hồ sơ khách hàng vào CI |
| Build Docker bot | Qua; import `app.bot` trong image thành công, không bật polling thật |
| Build Docker web trực tiếp và qua Compose | Qua; `ocr-review-web` chạy tại `127.0.0.1:8000` |
| Kiểm tra diff Telegram | Không thay `app/bot.py`, `analysis.py`, `signatories.py`, `runtime.py`, `worker.py`, `requirements.txt`, `Dockerfile`, `compose.yaml` |
| Rà soát độc lập | 5 lỗi Important phát hiện và sửa bằng ca hồi quy; không có Critical được báo |

Suite có cảnh báo deprecation của PyMuPDF/Starlette TestClient; không có lỗi kiểm thử. Đây là kiểm thử handler Telegram và worker, không phải kiểm thử gửi tin nhắn/polling tới Telegram đang hoạt động.

Các kiểm tra trình duyệt: PDF giả; tải GPKD vào ô EPORT và chặn bước; tải đủ hai loại; bước OCR; trường → vùng/trang và vùng → trường; zoom 125% + xoay 90°; kéo vẽ vùng dùng ma trận nghịch đảo và xác nhận tọa độ lưu sai số dưới 0,002; chỉnh giá trị/lý do/lịch sử; trì hoãn báo cáo rồi sửa trường và kiểm tra không xuất hiện báo cáo cũ; màn đối chiếu và hai vùng bằng chứng; tải JSON; xóa file làm vô hiệu kết quả đối chiếu. Browser test cố ý sửa MST để kiểm tra luồng chỉnh sửa/mâu thuẫn; ảnh sau chỉnh sửa không phải kết luận của hai bản gốc.

Unit/API còn kiểm tra: nội dung thay vì tên file; sai/mơ hồ loại; nhiều trang; tách chủ sở hữu/người đại diện; PDF mật khẩu; giả PDF; vượt dung lượng/số trang; chữ lỗi mã hóa/ký tự điều khiển; xoay trang PDF; dấu quá nhạt giữ chưa xác định; sai MST/tên; MST dấu mâu thuẫn không bị tên ghi đè; đại diện khác yêu cầu xem ủy quyền; không khớp khi thiếu/độ đọc thấp; nhiều giá trị; mất OCR; nguồn tên trùng ở vùng khai báo và vùng ký phải khác nhau; tên xuống dòng; lịch sử và giá trị gốc; vùng ngoài trang; phiên khác không đọc ảnh; CSRF; phiên hết hạn/dọn tệp; cache ảnh giới hạn; hủy/hàng đợi đầy/worker timeout; thay file không nhận chỉnh sửa cũ; xóa trong lúc PUT đang kiểm tra không làm tệp xuất hiện lại; dọn thư mục sau crash ở lần khởi động sau; ảnh xem trước lỗi không bị cache thành ảnh hợp lệ và có thể tạo lại.

## Thời gian trên cùng hai PDF

Lệnh: `python -m benchmarks.web_compare <gpkd.pdf> <eport.pdf>`, 2 lượt liên tiếp trên macOS ARM64, Tesseract 5.5.4, Python 3.12.16. Thời gian end-to-end gồm khởi động worker, không gồm ảnh phụ. Không in dữ liệu trích xuất vào kết quả benchmark.

| Đầu vào | Bot cũ, lượt 1 / 2 | Web mới, lượt 1 / 2 |
|---|---|---|
| GPKD, 2 trang | 1,097 / 1,064 s | 1,148 / 1,130 s |
| EPORT, 2 trang | 2,892 / 3,112 s | 6,495 / 7,041 s |

Bot cũ kiểm tra một PDF và dấu; web mới đọc một cặp, trường, vùng nguồn, dấu và tên người ký. Hai hợp đồng khác nhau: **không dùng bảng này làm điểm chính xác hoặc tuyên bố tăng tốc**. EPORT web chậm hơn vì các bước đọc bổ sung. Thời gian thay đổi theo CPU, tải máy, chất lượng scan và ngôn ngữ OCR. Thời gian đọc/trích trường/kiểm dấu/chờ hàng đợi được lưu trong từng tài liệu và báo cáo.

Hai bản gốc: bot cũ trả REVIEW cho từng file; web mới phân loại đúng cả hai và trả **Cần kiểm tra** cho cặp. MST và số ĐKKD khớp; ghi nhận có dấu. Tên công ty/đại diện có từ OCR chưa đủ chất lượng; tên tại vị trí ký và MST/tên trên dấu chưa đọc chắc; chữ ký viết tay không tự xác nhận. Không tự nâng các mục đó thành khớp. GPKD có lớp chữ lỗi mã hóa; EPORT có thông tin xoay 270° trong PDF; web đã xử lý bằng OCR và giữ đúng hướng hiển thị.

## Rà soát và quyết định triển khai

Đã sửa: lặp tên khi nhãn và giá trị ở hai dòng; bỏ mất trạng thái mờ ở dòng tiếp; chọn nhầm nguồn người ký khi tên trùng phần khai báo; tệp bị xóa vẫn được công bố sau validation; báo cáo cũ xuất hiện sau chỉnh sửa. Mỗi lỗi có ca hồi quy trong các tệp `test_web_*` hoặc `browser.mjs`. Ngoài ra đã khóa chỉnh sửa bằng cả ID tài liệu và revision, không chỉ revision.

Quyết định: dịch vụ FastAPI/SVG riêng, không thêm framework/frontend build; giữ toàn bộ bot gốc. Chi phí: trình xem hiển thị ảnh raster từ PDF thay vì PDF vector/text selection; các vùng vẫn liên kết và biến đổi tọa độ đúng. Dùng trạng thái phiên trong bộ nhớ, một uvicorn worker; không có lưu trữ lâu dài hoặc đồng bộ nhiều máy. Không thêm đăng nhập/dashboard ngoài phạm vi.

## Giới hạn còn lại

- Mới có hai hồ sơ thực do người dùng cung cấp và bộ hồ sơ tổng hợp. Chưa có bộ dữ liệu có nhãn đủ đại diện để công bố tỷ lệ chính xác hoặc nghiệm thu mọi mẫu GPKD/EPORT. Không hardcode tên, MST hay vị trí từ hai mẫu.
- Trích trường theo nhãn/nội dung và bố cục dòng; mẫu cũ, bảng phức tạp, chữ viết tay, scan mờ, tên chức danh OCR sai, hồ sơ song ngữ hoặc chủ sở hữu là tổ chức có thể cần sửa tay. Số ĐKKD dạng cũ ngoài 10/13 chữ số chưa được đối chiếu tự động, sẽ cần kiểm tra.
- Nét nghi chữ ký chỉ là ứng viên để duyệt, không là bằng chứng chắc chắn. Không thấy ứng viên không có nghĩa là không có chữ ký. Tên in gần ký cũng có thể chưa đọc được. Người dùng có thể chọn vùng và xác nhận hiện diện/giá trị, với lịch sử đầy đủ.
- Dấu mờ, chữ cong và nhiều dấu dễ có nội dung không đọc được hoặc mâu thuẫn. Không sao chép tên khai báo vào trường đọc trên dấu; tên chỉ được dùng sau khi MST dấu không đọc rõ, và vẫn phải có nguồn đủ đọc. Không so hình dấu với dấu của cơ quan cấp GPKD.
- Tệp đính kèm nhiều loại trong cùng một PDF có thể bị đánh dấu chưa xác định. PDF có mật khẩu không được hỗ trợ mở khóa.
- Báo cáo xuất JSON, chưa có bản báo cáo PDF. Dữ liệu/lịch sử chỉ sống trong phiên; đóng trình duyệt không tự xóa ngay nhưng hết TTL hoặc Hoàn thành sẽ xóa. Local bị kill/crash cần khởi động lại để dọn thư mục cũ; Docker dùng tmpfs.
- Chưa thử đa máy, tải lớn hoặc triển khai công khai. Bản bàn giao bind localhost. Không có xác thực tài khoản; nếu đưa lên mạng cần thêm lớp truy cập của đơn vị và HTTPS.

Giữ nhánh riêng để người dùng xem và duyệt kết quả thực tế; không tự gộp main chỉ vì các kiểm thử kỹ thuật đã xanh.
