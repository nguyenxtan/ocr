# Kiểm thử web GPKD–EPORT — 02/11/2026

Nhánh: `feat/gpkd-eport-web`. Baseline: `origin/main` tại `79d7207`. Hai PDF do người dùng cung cấp được đọc từ bên ngoài repo; không đưa file, giá trị cá nhân hay ảnh hồ sơ vào Git. Chưa gộp `main`.

## Kết quả đã chạy

| Hạng mục | Kết quả thực tế |
|---|---|
| Baseline trước khi thêm web | 163 pytest qua, macOS ARM64/Python 3.12 |
| Toàn bộ suite sau thay đổi | **242 pytest qua**, macOS, 11,19 giây |
| Toàn bộ suite trong Docker Linux ARM64 | **242 pytest qua**, read-only/2 CPU/2 GB RAM, 16,80 giây |
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

Lệnh: `python -m benchmarks.web_compare <gpkd.pdf> <eport.pdf>`, 2 lượt liên tiếp trên macOS ARM64, Tesseract 5.5.4, Python 3.12.16. Thời gian end-to-end gồm khởi động worker, không gồm ảnh phụ. Đo sau sửa review, trong lúc máy phát triển vẫn chạy Docker và kiểm thử trình duyệt; không phải benchmark máy rảnh. Không in dữ liệu trích xuất vào kết quả benchmark.

| Đầu vào | Bot cũ, lượt 1 / 2 | Web mới, lượt 1 / 2 |
|---|---|---|
| GPKD, 2 trang | 1,324 / 1,467 s | 1,288 / 1,326 s |
| EPORT, 2 trang | 3,433 / 3,705 s | 7,788 / 7,850 s |

Bot cũ kiểm tra một PDF và dấu; web mới đọc một cặp, trường, vùng nguồn, dấu và tên người ký. Hai hợp đồng khác nhau: **không dùng bảng này làm điểm chính xác hoặc tuyên bố tăng tốc**. EPORT web chậm hơn vì các bước đọc bổ sung. Thời gian thay đổi theo CPU, tải máy, chất lượng scan và ngôn ngữ OCR. Thời gian đọc/trích trường/kiểm dấu/chờ hàng đợi được lưu trong từng tài liệu và báo cáo.

Hai bản gốc: bot cũ trả REVIEW cho từng file; web mới phân loại đúng cả hai và trả **Cần kiểm tra** cho cặp. MST và số ĐKKD khớp; ghi nhận có dấu. Tên công ty/đại diện có từ OCR chưa đủ chất lượng; tên tại vị trí ký và MST/tên trên dấu chưa đọc chắc; chữ ký viết tay không tự xác nhận. Không tự nâng các mục đó thành khớp. GPKD có lớp chữ lỗi mã hóa; EPORT có thông tin xoay 270° trong PDF; web đã xử lý bằng OCR và giữ đúng hướng hiển thị.

## Rà soát và quyết định triển khai

Đã sửa: lặp tên khi nhãn và giá trị ở hai dòng; bỏ mất trạng thái mờ ở dòng tiếp; chọn nhầm nguồn người ký khi tên trùng phần khai báo; tệp bị xóa vẫn được công bố sau validation; báo cáo cũ xuất hiện sau chỉnh sửa. Mỗi lỗi có ca hồi quy trong các tệp `test_web_*` hoặc `browser.mjs`. Ngoài ra đã khóa chỉnh sửa bằng cả ID tài liệu và revision, không chỉ revision.

Rà soát độc lập lần 2 (4 lỗi Important, có ca hồi quy trong `tests/test_web_review_fixes.py` và `browser.mjs`):
- So sánh tên doanh nghiệp/người: chỉ **Đạt** khi toàn bộ tên trùng sau chuẩn hóa Unicode NFC, chữ hoa, khoảng trắng và dấu câu; giữ dấu tiếng Việt, loại hình (TNHH/MTV/CỔ PHẦN), từ ngắn và thứ tự. Không dùng bộ so khớp tên lỏng của bot. Chỉ khác dấu hoặc khác cách viết loại hình (ví dụ TNHH ↔ TRÁCH NHIỆM HỮU HẠN) chuyển **Cần kiểm tra**, không bao giờ Đạt. Ứng viên khác dấu không bị gộp thành một.
- PDF lớp chữ có /Rotate 90/180/270: đọc dòng, dòng kế và tên xuống dòng bằng tọa độ bố cục gốc; vùng bằng chứng công bố theo hướng hiển thị.
- Mọi yêu cầu `/api/*` (kể cả GET tạo phiên) có `Origin` khác host hoặc `Sec-Fetch-Site` khác `same-origin`/`none` bị từ chối trước khi tạo phiên; client không gửi các header này (curl, test) vẫn dùng được.
- Sửa trường có nhiều ứng viên mâu thuẫn: giao diện liệt kê ứng viên và bắt chọn một ứng viên hoặc vẽ vùng mới; API từ chối trộn vùng nguồn của các ứng viên khác nhau; hai cách đọc ở cùng một vùng vật lý vẫn có thể được người dùng xác nhận. Ứng viên gốc, `raw` và lịch sử giữ nguyên.

Đã xử lý tiếp các vấn đề bằng chứng: lớp chữ có chế độ ẩn, độ trong suốt, chữ trắng hoặc bị hình/chữ nhật che phủ chuyển sang OCR ảnh trang; PDF chữ hiển thị bình thường vẫn đọc lớp chữ. Đây là kiểm tra hiển thị bảo thủ, không là xác thực nội dung PDF. Xác nhận chữ ký/con dấu bắt chọn một vị trí hoặc vẽ lại; vùng tên công ty xuống dòng vẫn được giữ nhiều khung. Vùng đang chọn có viền riêng và theo cùng phép zoom/xoay. Nút tải JSON xuất bản báo cáo đã hiển thị, có ca sửa dữ liệu sau khi hiển thị rồi kiểm tra bản tải xuống vẫn giữ đúng phiên bản cũ.

Claude đã review và chỉ ra các lỗi, đồng thời đã viết một phần sửa trước khi người dùng giới hạn vai trò. Theo yêu cầu mới, worker Claude đã được dừng; phần chốt sửa, rà code, build và kiểm thử cuối do agent chính thực hiện. Không gọi Claude thêm để sửa.

Đã sửa một lỗi kiểm thử browser không ổn định từng xảy ra ở CI: đo tọa độ kéo trước khi nút vẽ làm cuộn trang. Nay lấy tọa độ sau thao tác vẽ/đưa vùng vào khung nhìn; bỏ cuộn trang trễ ở bước chọn trường. Giữ nguyên mức sai số tọa độ 0,002.

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
