# OCR PDF Bot · Telegram (POC)

## Web đối chiếu GPKD–EPORT

Web là dịch vụ riêng; bot Telegram và lệnh chạy cũ bên dưới giữ nguyên. Web không cần token Telegram và Compose web không truyền token vào container.

### Chạy bằng Docker

Cần Docker Engine và Docker Compose (Docker Desktop trên macOS, hoặc Colima). Từ thư mục repo:

```bash
# Không thay .env đã điền token. Chỉ sao chép nếu chưa có file này.
test -f .env || cp .env.example .env
docker compose -f compose.web.yaml up -d --build
# Mở http://localhost:8000
docker compose -f compose.web.yaml logs --tail=30 web
docker compose -f compose.web.yaml down
```

Bot vẫn chạy riêng bằng `docker compose up -d --build`. Web bind localhost; không cần khởi động bot để dùng web. Trên máy phát triển hiện tại có profile Colima `ocr-test`: `colima start --profile ocr-test` nếu Docker chưa chạy.

### Chạy Python trực tiếp

```bash
# macOS: cài Python và OCR trước
brew install python@3.12 tesseract tesseract-lang
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-web.txt
python -m uvicorn app.web:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

### Ba bước sử dụng

1. **Tải & kiểm tra loại:** hai PDF độc lập, tối đa 20 MB/file, 20 trang/file. Kiểm tra nội dung PDF, mật khẩu, cấu trúc, kích thước trang và tiêu đề loại chứng từ. Sai loại hoặc chưa xác định sẽ chặn bước tiếp theo. Thay/xóa file hủy tác vụ và bỏ kết quả cũ; thay bằng tệp lỗi cũng không giữ kết quả cũ.
2. **Nhận diện OCR:** chọn tài liệu/trang bên trái, chọn trường bên phải hoặc khung trên trang. Lưu giá trị gốc, giá trị hiện tại/chuẩn hóa, trạng thái, ứng viên và các vùng nguồn. Có zoom, xoay, vẽ lại vùng và chỉnh giá trị kèm lý do/lịch sử. Để sửa sang trang khác: chọn trường, chọn trang khác trong cùng tài liệu, vẽ vùng rồi lưu. Trường thiếu cũng phải chọn vùng trước khi xác nhận. Với hiện diện chữ ký/con dấu, nhập `Có` hoặc `Không có` sau khi kiểm tra bản gốc; chữ in tên người không tự chứng minh có chữ ký.
3. **Đối chiếu:** 9 tiêu chí có hai giá trị, lý do và bằng chứng. MST, số ĐKKD, tên doanh nghiệp, đại diện và tên tại vị trí ký được đối chiếu riêng. Đại diện khác nhau cần kiểm tra ủy quyền; không tự kết luận sai thẩm quyền. Chữ ký đánh giá hiện diện trên EPORT; mộc được kiểm tra riêng trên cả GPKD và EPORT. GPKD có trường “Mộc cơ quan cấp trên GPKD”, cho chọn vùng và xác nhận Có/Không có. Không tìm thấy hoặc chưa đọc rõ mộc GPKD giữ Cần kiểm tra; mộc EPORT không thay thế tiêu chí này. Không so tên/MST doanh nghiệp hay hình mộc EPORT với mộc cơ quan cấp trên GPKD. MST dấu rõ mà khác không được bỏ qua bằng tên; tên chỉ là phương án khi MST dấu chưa đọc rõ. Thiếu, mờ hoặc nhiều giá trị luôn cần kiểm tra. Báo cáo JSON chứa đầy đủ trường/vùng/lịch sử/thời gian; nút Hoàn thành xóa hồ sơ phiên.

Tên được so toàn bộ, giữ dấu tiếng Việt, loại hình doanh nghiệp, từ ngắn và thứ tự. Chỉ khác dấu/cách viết loại hình cần kiểm tra, không tự coi là khớp. Khi có nhiều ứng viên phải chọn nguồn hoặc vẽ lại; xác nhận hiện diện chữ ký/con dấu chỉ gắn một vùng. JSON tải xuống là đúng phiên bản báo cáo đang hiển thị.

Không có tỷ lệ “tin cậy” minh họa. Các con số phần trăm trên trình xem chỉ là mức zoom. Kết luận Đạt/Cần kiểm tra/Không đạt không xác thực thật–giả hay thẩm quyền pháp lý.

Web dò cả dấu đỏ và **vùng nghi con dấu đen/xám trên bản photocopy**, dựa trên
vòng tròn/ellipse và nét bên trong, trên mọi trang. Ứng viên đơn sắc luôn là
`Nghi có`, cần kiểm tra/chọn vùng và xác nhận; nội dung OCR trong vùng này cũng
chưa được tự xác nhận. Logo có cấu trúc tương tự vẫn có thể bị nhầm; dấu vuông,
vỡ nhiều hoặc quá mờ có thể cần vẽ vùng thủ công. Xem [kiểm thử photocopy](docs/photocopy-seals.md).

### Xử lý và lưu tạm

- Ưu tiên lớp chữ khi đủ chất lượng; ký tự điều khiển, lỗi mã hóa, ít chữ hoặc lớp chữ có dấu hiệu ẩn/không hiển thị sẽ chuyển sang OCR ảnh trang. Giữ thông tin xoay PDF khi tạo ảnh/vùng nguồn. Hệ tọa độ chuẩn là trang hiển thị sau xoay gốc PDF, chuẩn hóa `[x0,y0,x1,y1]` trong `[0,1]`; SVG áp dụng chung phép xoay/zoom cho ảnh và khung, thao tác kéo dùng ma trận nghịch đảo.
- Tái sử dụng Tesseract, bộ phát hiện dấu, bộ đọc riêng mực dấu và các primitive tên người ký. Web không sửa thuật toán hoặc handler Telegram. Không dùng lớp chữ khai báo công ty làm nội dung “đọc được trên dấu”.
- Một tiến trình OCR đang chạy, tối đa ba tác vụ chờ; tác vụ có thể hủy, worker giới hạn 180 giây và bị dừng cả nhóm tiến trình khi hủy/quá hạn. Kết quả có trước ảnh xem trước/ảnh bằng chứng phụ; ảnh tạo theo yêu cầu và cache tối đa 64 MB cho cả dịch vụ.
- Phiên ngẫu nhiên bằng cookie HttpOnly/SameSite, kiểm tra nguồn yêu cầu ghi. Tối đa 8 phiên, mỗi phiên chỉ hai hồ sơ, thời gian sống cố định mặc định 30 phút, dọn mỗi 10 giây. Tệp nằm trong thư mục riêng quyền 0700; không dùng tên file người dùng làm đường dẫn. Mọi ảnh, tác vụ, sửa trường và báo cáo đều kiểm tra phiên, ID tài liệu và phiên bản chỉnh sửa. Không dùng nhiều uvicorn workers vì trạng thái nằm trong bộ nhớ.
- Dữ liệu và lịch sử không lưu lâu dài. Dừng dịch vụ bình thường xóa thư mục phiên; Docker dùng tmpfs và xóa khi container dừng. Nếu tiến trình local bị kill/crash, các thư mục do web tạo còn sót được dọn ở lần khởi động sau khi quá `max(TTL, 3600)` giây. Không ghi nội dung, tên hồ sơ, MST, người ký hoặc token vào log. Không bật access log; không commit báo cáo hay ảnh có dữ liệu cá nhân.
- Compose: read-only, user không đặc quyền, giới hạn RAM 2 GB/CPU 2/PID 128, tmpfs 512 MB. Mặc định chỉ dùng local. Nếu triển khai qua mạng cần HTTPS, `WEB_SECURE_COOKIE=1` và lớp xác thực/kiểm soát truy cập của đơn vị; phiên trình duyệt không thay cho tài khoản đăng nhập.

Cấu hình web trong `.env.example`: `WEB_SESSION_TTL_SEC`, `WEB_JOB_TIMEOUT_SEC`, `WEB_MAX_SESSIONS`, `WEB_QUEUE_SIZE`, `WEB_SECURE_COOKIE`. Có thể đặt `OCR_LANG=vie+eng`. Không đưa token thật vào `.env.example`.

### Kiểm thử và đo thực tế

```bash
source .venv/bin/activate
pip install -r requirements-web.txt -r requirements-dev.txt
python -m pytest -q
# Chạy web ở terminal khác, sau đó:
npm ci
npx playwright install chromium
GPKD_PDF=/duong/dan/gpkd.pdf EPORT_PDF=/duong/dan/eport.pdf npm run test:browser
# Cùng PDF, đo bot cũ và web mới; chỉ in metadata, không in giá trị trích xuất
python -m benchmarks.web_compare /duong/dan/gpkd.pdf /duong/dan/eport.pdf
```

Xem [kết quả nghiệm thu và giới hạn](docs/web-validation.md) và [kết quả cải tiến OCR trước–sau](docs/ocr-improvements.md). Hai PDF người dùng cung cấp và ảnh chụp trình duyệt nằm ngoài Git. `test-results/` bị bỏ qua vì có thể chứa nội dung hồ sơ.

---


Bot Telegram tiếp nhận **chỉ file PDF**, nhận diện dấu mộc doanh nghiệp, đối chiếu MST hoặc tên công ty, kiểm tra tên người ký với tên đại diện được **khai báo trong PDF**, và thông báo chữ ký số nhúng nếu có. Không xác minh dấu thật/giả hoặc thẩm quyền pháp lý ngoài nội dung tài liệu.

## 1. Chạy Docker

Yêu cầu Docker Engine + Compose v2 (không cần GPU, database, n8n hay mở cổng).

```bash
git clone https://github.com/nguyenxtan/ocr.git
cd ocr
cp .env.example .env
# Mở .env và nhập TELEGRAM_BOT_TOKEN từ @BotFather
docker compose up -d --build
```

**Chế độ PUBLIC (mặc định):** Ai nhắn riêng và gửi file PDF cho bot cũng sử dụng được. **Không cần** điền `ALLOWED_USER_IDS`. Với file `.env` đã có từ bản cũ, có thể thêm `BOT_ACCESS_MODE=PUBLIC` để cấu hình tường minh, hoặc cập nhật code và dùng mặc định PUBLIC.

**Chế độ PRIVATE (tùy chọn):** Đặt `BOT_ACCESS_MODE=PRIVATE`, nhắn `/id` để lấy Telegram ID rồi điền `ALLOWED_USER_IDS=1095120130,123456789` (ID minh họa). Danh sách trống trong PRIVATE sẽ chặn tất cả PDF.

Sau khi sửa `.env` hoặc cập nhật code:

```bash
docker compose up -d --build --force-recreate
docker compose logs -f bot
```

Chỉ hỗ trợ tin nhắn riêng, không xử lý PDF trong nhóm Telegram. PUBLIC vẫn giới hạn kích thước file, số trang, thời gian xử lý, số tác vụ đồng thời và giãn cách giữa các lượt gửi. **PUBLIC cho phép người lạ dùng tài nguyên server**, nên theo dõi log/dung lượng khi chia sẻ bot rộng rãi.

Không đưa token, PDF khách hàng, CMND hoặc giấy tờ nội bộ vào repo. Docker dùng container không đặc quyền, read-only, bộ nhớ 2 GB, CPU giới hạn. PDF được tải vào thư mục tạm rồi xóa sau lượt kiểm tra.

## 1.1. Chống treo và trải nghiệm Telegram

- Nhận một PDF: bot tạo **một tin nhắn trạng thái đang xử lý**, sau đó sửa chính tin nhắn đó thành PASS/FAIL/REVIEW và **luôn nêu lý do** nếu REVIEW.
- Khi bot bận: các PDF tiếp theo được đưa vào **hàng đợi hữu hạn** thay vì trả lỗi sau 1 giây; giới hạn theo `MAX_QUEUED_PDFS` (mặc định 3), `QUEUE_WAIT_SEC` (mặc định 300 giây). Mỗi tài khoản chỉ được có một PDF đang chờ/xử lý.
- Nhắn **`/stop`** hoặc **`/cancel`** để hủy PDF đang xử lý/chờ của mình. Tiến trình OCR được kết thúc, giải phóng lượt cho người khác. Lệnh không dừng toàn bộ bot.
- Nút **🔍 Xem bằng chứng** nhận sự kiện `callback_query` độc lập với tin nhắn. Nếu Telegram không gửi được album, bot thử gửi một ảnh con dấu; nếu vẫn thất bại thì báo lỗi thay vì im lặng.
- Tạo ảnh bằng chứng bằng tiến trình riêng tối đa `EVIDENCE_TIMEOUT_SEC` (mặc định 15 giây). Nếu lỗi hoặc quá thời gian, **kết quả OCR chính vẫn giữ nguyên**; nút chỉ xuất hiện khi ảnh JPEG thật đã tạo được.
- Ảnh chỉ mở được bởi người gửi, có hiệu lực tối đa **10 phút**; khởi động lại Docker sẽ làm các nút ảnh cũ hết hiệu lực.

## 2. Quy tắc kiểm tra

1. **Con dấu đỏ/nâu:** Tìm hình tròn hoặc hình elip bị méo do scan ở nhiều trang/vị trí, loại nhiễu chữ đỏ; không thấy dấu thì FAIL, nghi dấu thì REVIEW.
2. **MST:** Đọc MST trên con dấu và MST có nhãn trong chứng từ. Hai MST rõ ràng khác nhau thì FAIL; MST không đọc được **không có nghĩa là sai**.
3. **Tên doanh nghiệp:** Khi MST không đủ dữ liệu, OCR nét mực của dấu riêng, gồm vùng giữa và chữ vòng ngoài được trải phẳng bằng biến đổi cực, rồi so với tên công ty trong PDF. Hỗ trợ công văn, biểu mẫu và tên công ty xuống dòng; sử dụng tỷ lệ khớp từ khóa đặc trưng, không phải xác suất nhận dạng.
4. **Tên người ký:** OCR ở vùng chữ ký (tách khỏi trường đại diện). Trùng tên đại diện được khai báo thì MATCH. Khác tên rõ ràng thì FAIL. Chữ viết tay/trang trí hoặc ảnh mờ không đủ căn cứ thì REVIEW. Thiếu trường đại diện được khai báo thì NOT_DECLARED, không tự đoán quyền đại diện.
5. **Chữ ký số:** Chạy `pdfsig` (Poppler) để kiểm tra chữ ký thực sự nhúng trong PDF, không nhầm ảnh scan dòng chữ “Digitally signed by”. Kiểm tra toàn vẹn mật mã và trạng thái tin cậy chứng thư **riêng biệt**. Chữ ký số không thay thế dấu tròn đỏ nếu tiêu chí nghiệp vụ bắt buộc dấu đỏ.

## 3. Phản hồi Telegram

```text
✅ HỒ SƠ ĐẠT
🔴 Dấu đỏ · Trang 2
🏢 Tên doanh nghiệp: Khớp 86%
🧾 MST: Chưa thấy trên chứng từ
✍️ Người ký: Nguyễn Sơn Hải · Chưa đối chiếu
```

```text
⚠️ CẦN KIỂM TRA
🔴 Dấu đỏ · Trang 1
🏢 Tên doanh nghiệp: Khớp 100%
🧾 MST: Chưa đọc rõ trên dấu
✍️ Người ký: Chưa đọc rõ để đối chiếu
```

Chữ ký số có thể bổ sung dòng `🔏 Chữ ký số: Toàn vẹn · Chưa xác thực chứng thư`. Các dòng phụ chỉ xuất hiện khi có dữ liệu. **% khớp tên là mức bao phủ các từ phân biệt mà OCR nhận được**, không phải cam kết độ chính xác hay xác thực pháp lý.

### 🔍 Xem bằng chứng trực quan (tùy chọn)

Khi bot tìm được vùng con dấu, bên dưới kết quả sẽ có nút **🔍 Xem bằng chứng**. Bot **không gửi ảnh mặc định**; chỉ gửi khi chính người đã nộp PDF bấm nút.

Các ảnh được tạo trong cùng lượt xử lý gồm: **vùng con dấu**, **khu vực ký tên** và **phần đầu chứng từ**. Khi bấm, Telegram gửi chúng thành **một album ảnh**, không làm dài thông báo kết quả. Khi PDF có nhiều dấu, ảnh được liên kết với **chính vùng dấu đã dùng để đối chiếu**, tránh mở nhầm dấu. Nếu không tìm lại được đúng vùng dấu, bot không hiển thị ảnh sai. Các vùng ảnh chỉ dùng để người dùng kiểm tra lại, không tự chứng minh người ký hay thẩm quyền.

- Chỉ lưu ảnh JPEG thu nhỏ trong **RAM tối đa 10 phút**, không lưu PDF trong cache; file PDF và ảnh tạm trên đĩa bị xóa ngay sau lần xử lý.
- Mỗi nút thuộc **Telegram ID và cuộc chat** đã gửi hồ sơ; người khác bấm sẽ bị từ chối. Hết hạn hoặc Docker khởi động lại thì cần gửi PDF mới.
- Cache tối đa **32 hồ sơ / 24 MB**; mỗi hồ sơ tối đa 3 ảnh, mỗi ảnh tối đa 550 KB. Giới hạn này giúp PUBLIC không chiếm RAM vô hạn.
- Không cần API ngoài, database, mở port hay thay đổi `.env`. Dùng được ở cả chế độ OCR thường và PaddleOCR.

## 4. Công nghệ & cấu hình

| Thư viện | Vai trò |
|---|---|
| python-telegram-bot | Nhận file và gửi kết quả |
| PyMuPDF | Đọc / render PDF (cần đánh giá giấy phép AGPL/commercial trước khi thương mại hóa) |
| OpenCV | Tìm vùng con dấu |
| Tesseract OCR (vie+eng) | Nhận dạng thông tin dấu, biểu mẫu, tên ký |
| RapidFuzz | So khớp từ tên doanh nghiệp |
| Poppler `pdfsig` | Kiểm tra chữ ký số PDF |

`.env.example` cung cấp các tham số: bot token, chế độ PUBLIC/PRIVATE, Telegram ID được phép nếu PRIVATE, giới hạn file và trang, thời gian xử lý, bộ nhớ container (trong Compose), số lượt xử lý song song và khoảng cách giữa các lượt gửi.

**An toàn:** Mỗi PDF chạy trong một process riêng. Nếu quá hạn xử lý thì bot dừng process, trả REVIEW; không để OCR chạy mãi dưới nền. Tesseract được giới hạn một luồng CPU. Bộ đọc PDF giới hạn kích thước trang render. Không lưu PDF hay ảnh con dấu lâu dài, không log nội dung OCR.

## 5. Kiểm thử & benchmark

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Bộ kiểm thử chứa ca dương tính, ca âm tính, các tên công ty gần giống, MST mâu thuẫn, nhiều dấu, tên ký không đọc rõ, chữ ký số, xử lý tài nguyên, timeout, path traversal. CI chạy unit tests và build Docker image mặc định (Tesseract). Image PaddleOCR tùy chọn phải được kiểm tra thủ công sau lần tải trọng số đầu tiên.

Đo độ chính xác trên các PDF **thực tế**, không commit file riêng tư, bằng manifest JSON Lines `labels.jsonl`:

```json
{"file":"sample1.pdf","status":"PASS","signer_status":"MATCH"}
{"file":"sample2.pdf","status":"FAIL"}
```

```bash
python -m benchmarks.evaluate --manifest labels.jsonl --base-dir /duong-dan/pdf --out benchmark.json
```

Báo cáo gồm accuracy, false-PASS, signer accuracy, P50/P95 thời gian, confusion matrix. **Số bài unit test không đại diện tỷ lệ nhận dạng đúng trong thực tế.** Hai PDF E-Port và PDF TCIS chỉ là mẫu ban đầu, chưa đủ thay cho benchmark 50–100 PDF đa dạng.

## 6. Giới hạn cần biết

- Chữ ký tay viết nét trang trí có thể không đọc chắc. Trả REVIEW là hành vi đúng, không tự điền tên được khai báo vào vị trí ký.
- Nhận diện con dấu hiện ưu tiên dấu tròn đỏ/nâu và dấu tròn bị bóp elip do scan. Dấu xanh/đen, dấu không tròn hoặc con dấu vỡ nét cần bộ mẫu mở rộng.
- Dữ liệu chứng thư số tin cậy theo môi trường xác minh; không đồng nghĩa người ký có đủ thẩm quyền pháp luật. Phần thẩm quyền chỉ đối chiếu **tên trong hồ sơ**, không tra cứu đăng ký doanh nghiệp hoặc giấy ủy quyền.
- Không có dịch vụ AI trả phí, không dùng GPU. Nếu cần OCR tên ký viết tay chính xác hơn, phải bổ sung mô hình chuyên biệt và đánh giá riêng.

## 7. PaddleOCR nâng cao (tùy chọn)

**Mặc định:** `docker compose up -d --build` vẫn chạy Tesseract, không cần cài PaddleOCR. Nếu có VPS hoặc Docker Desktop đủ RAM, chạy thêm sidecar (dịch vụ OCR phụ, chỉ kết nối trong mạng Docker):

```bash
# Đã điền TELEGRAM_BOT_TOKEN; với PUBLIC không cần ALLOWED_USER_IDS
# Bật Tesseract + PP-OCRv6 + SealRecognition; không cần GPU
 docker compose -f compose.yaml -f compose.paddle.yaml up -d --build
 docker compose -f compose.yaml -f compose.paddle.yaml logs -f paddle bot
```

Lần khởi động đầu tiên **Paddle tải bộ trọng số model từ nguồn công khai** vào Docker volume `paddle_models`; có thể lâu tùy mạng. **Nội dung PDF không được tải lên dịch vụ AI đám mây**: bot gửi **ảnh vùng con dấu** cho sidecar qua mạng Docker riêng. Không publish port 8877 ra Internet. `paddle` dùng Python 3.11, PaddlePaddle 3.2.0, PaddleOCR 3.7.0; giới hạn 6 GB RAM/3 CPU. Chế độ nâng cao không phù hợp VPS RAM quá nhỏ.

- **PP-OCRv6** đọc lại vùng con dấu và phần tiêu đề chứng từ khi Tesseract thiếu chữ.
- **SealRecognition** thử nhận dạng chữ cong trên vòng dấu. Nếu pipeline chuyên biệt không sẵn sàng, bot vẫn xử lý bằng Tesseract/PP-OCRv6.
- **OCR Ensemble (đối chiếu nhiều bộ nhận dạng)** chỉ tăng mức tin cậy khi có bằng chứng độc lập. Hai pipeline Paddle có thể chia sẻ mô hình nhận dạng, vì vậy **chúng đồng thuận nhưng Tesseract không có bằng chứng vẫn không đủ tự PASS**.
- Một MST rõ ràng mâu thuẫn khiến kết quả cần REVIEW/FAIL, tuyệt đối không dùng tên công ty để bỏ qua.
- Khi sidecar ngừng hoạt động, bot tự giữ kết quả Tesseract hiện tại; **không gửi PDF ra API bên ngoài**.

Tắt chế độ nâng cao, dùng lại cấu hình mặc định:

```bash
 docker compose -f compose.yaml -f compose.paddle.yaml down
 docker compose up -d --build
```

### Xác minh sidecar

```bash
# Kiểm tra tình trạng model, không cần mở port ra host
 docker compose -f compose.yaml -f compose.paddle.yaml exec paddle \
   python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8877/health').read().decode())"
```

Kỳ vọng `general=true`, `seal=true` nếu cả hai pipeline tải được. Nếu `seal=false`, phần đọc dấu chuyên biệt chưa hoạt động. **Các bài unit test mô phỏng kết quả AI**, chưa thay thế lần chạy mô hình thật trong Docker và benchmark PDF thực tế.

