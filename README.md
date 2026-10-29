# OCR PDF Verification Bot (POC)

Bot Telegram **chỉ nhận PDF**, trả trạng thái **PASS / FAIL / REVIEW** trong tin nhắn Telegram HTML gọn, có chữ đậm và vị trí trang phát hiện dấu. Sau khi đối chiếu dấu, bot còn tìm **tên tại vị trí ký** để so với trường **Đại diện có thẩm quyền** nếu có. Đây là bản thử nghiệm, chưa được nghiệm thu độ chính xác OCR trên nhiều mẫu.

## Chạy bằng Docker

Yêu cầu: Docker Engine + Docker Compose v2, không cần GPU, n8n, database hay mở port HTTP.

1. Tạo bot với @BotFather trên Telegram và lấy token.
2. Trong terminal chạy:

    git clone https://github.com/nguyenxtan/ocr.git
    cd ocr
    cp .env.example .env

3. Sửa file .env: điền TELEGRAM_BOT_TOKEN của bot.
4. Chạy: docker compose up -d --build
5. Xem log: docker compose logs -f bot
6. Gửi một file PDF trong chat riêng với bot. Dừng bằng docker compose down.

**Bảo mật:** Không commit .env và không gửi bot token vào chat. Mặc định ALLOWED_USER_IDS trống nên bất kỳ người dùng Telegram nào tìm được bot đều có thể dùng. Gõ /id trong bot để lấy Telegram ID, điền ALLOWED_USER_IDS=123456789 vào .env và chạy docker compose up -d --force-recreate để chỉ cho phép tài khoản đó. Mỗi bot chỉ nên chạy một tiến trình polling.

## Cấu hình .env

- TELEGRAM_BOT_TOKEN: bắt buộc, token BotFather.
- ALLOWED_USER_IDS: Telegram ID được phép, phân tách dấu phẩy; trống nghĩa là mọi người dùng chat riêng.
- MAX_PDF_MB: giới hạn dung lượng; tối đa 20 MB theo Bot API tải file thông thường, mặc định 15.
- MAX_PAGES: giới hạn số trang, mặc định 10.
- OCR_LANG: ngôn ngữ OCR, mặc định vie+eng.

## Luồng POC

1. Nhận và kiểm tra PDF, mật khẩu, số trang và dung lượng.
2. PyMuPDF render **tất cả trang**; OpenCV phát hiện **nhiều dấu tròn đỏ/đỏ nâu**, kiểm tra vòng trong và ngoài theo tỷ lệ kích thước trang. Không chỉ chọn dấu có hình tròn rõ nhất.
3. Ưu tiên **văn bản PDF** khi có; nếu là scan thì OCR. Tìm tên/MST có nhãn trên **nhiều trang**; nếu thiếu nhãn thì tìm doanh nghiệp ở phần đầu **cột trái, giữa, phải**. Hỗ trợ tên xuống dòng; đối chiếu từng vùng dấu bằng 5 lượt OCR.
4. MST dấu đọc đủ tin cậy và đúng checksum thì so với MST chứng từ. MST mâu thuẫn: **FAIL**, không dùng tên để bỏ qua.
5. Nếu MST trên dấu không đọc chắc, fallback tên doanh nghiệp. Với **tên ngắn**, các từ phân biệt phải khớp chính xác, tránh nhầm MINH/VINH; tên dài cho phép lỗi OCR nhỏ nếu có đủ từ khác xác nhận. Nếu nhiều tên công ty hoặc nhiều dấu mâu thuẫn: **REVIEW**.
6. Không phát hiện vòng dấu: **FAIL**. Nếu chỉ thấy vùng nghi dấu hoặc có dấu nhưng không đủ dữ liệu (ví dụ công văn có dấu của cơ quan, không có trường tên doanh nghiệp để đối chiếu): **REVIEW**, kèm trang phát hiện.

### Đối chiếu người ký (POC)

- Trích **tên đại diện được khai báo** từ ô có nhãn như `Đại diện có thẩm quyền` hoặc `Người được ủy quyền`.
- Đọc **tên in tại vị trí ký** trên các trang, tìm theo vùng tiêu đề ký (`Đại diện khách hàng`, `Giám đốc`, v.v.). Không lấy tên trong ô khai báo tự điền vào khu vực chữ ký.
- Hai tên OCR rõ và trùng: `MATCH`. Rõ nhưng khác: `MISMATCH`. Nét chữ mờ hoặc chữ ký tay không đọc được: `UNREADABLE`. Không có tên đại diện khai báo: `NOT_DECLARED`.
- Nếu đã có trường đại diện mà tên ký không đọc chắc: **REVIEW**; khác rõ: **FAIL**. Nếu không có trường đại diện, bot vẫn báo kết quả đối chiếu dấu riêng và thông tin người ký là **chưa đối chiếu**, không suy luận thẩm quyền pháp lý.
- **Không xác minh** người ký có thẩm quyền ngoài chứng từ, không phân tích tính thật/giả của chữ ký tay hoặc con dấu.

### Mẫu phản hồi Telegram (gọn, có tỷ lệ khớp)

Khi MST không đủ dữ liệu và tên doanh nghiệp khớp:

```text
✅ HỒ SƠ ĐẠT
🔴 Dấu đỏ · Trang 2
🏢 Tên doanh nghiệp: Khớp 86%
🧾 MST: Chưa thấy trên chứng từ
```

Nếu MST có trên chứng từ nhưng không đọc chắc được trên dấu:

```text
✅ HỒ SƠ ĐẠT
🔴 Dấu đỏ · Trang 1
🏢 Tên doanh nghiệp: Khớp 100%
🧾 MST: Chưa đọc rõ trên dấu
```

Tỷ lệ 86% / 100% là kết quả tính trên các PDF mẫu ở lần thử này, **không phải số hardcode**. Công thức: số **từ đặc trưng** trong tên doanh nghiệp được OCR trên dấu và đối chiếu đạt / tổng số từ đặc trưng của tên trong chứng từ, nhân 100%. Đây là tỷ lệ khớp chữ OCR, **không phải xác suất OCR đúng, xác thực con dấu, hay chất lượng hồ sơ**.

Phản hồi bổ sung một dòng người ký:

```text
✍️ Người ký: Khớp tên đại diện
✍️ Người ký: Chưa đọc rõ để đối chiếu
✍️ Người ký: Nguyen Sơn Hai · Chưa đối chiếu
```

Các dòng trên là ví dụ thay thế nhau theo từng trường hợp.

Chỉ hiện `MST: Không khớp` khi có hai MST đọc đủ rõ, đúng cấu trúc nhưng khác nhau. Nếu thiếu MST trên chứng từ hoặc không đọc rõ trên dấu, phải thể hiện rõ thay vì suy đoán. Không tự cho PASS bằng tên khi MST đọc rõ nhưng mâu thuẫn.

Phản hồi thật dùng Telegram HTML để in đậm trạng thái và kết quả. Nội bộ giữ `MST_MATCH` hoặc `NAME_FALLBACK`. PASS chỉ là **khớp thông tin dấu và chứng từ**, không kết luận giá trị pháp lý, không phân biệt dấu thật/giả. Chưa kiểm tra người ký/chức vụ hoặc xác thực chữ ký số nhúng; chữ ký số không được coi là dấu đỏ vật lý.

## Công nghệ

- python-telegram-bot: Telegram long polling, không cần domain hoặc webhook.
- PyMuPDF: đọc/render PDF; cần lưu ý giấy phép AGPL/commercial nếu đưa vào sản phẩm thương mại.
- OpenCV, NumPy: nhận diện con dấu tròn đỏ.
- Tesseract, pytesseract: OCR Việt/Anh chạy trong Docker, đọc 5 vùng cắt của dấu, không gọi AI bên ngoài.
- RapidFuzz: so khớp tên doanh nghiệp gần đúng theo quy tắc.

## Kiểm thử

Chạy: python -m pip install -r requirements-dev.txt rồi python -m pytest -q.

Đã chạy **48 bài kiểm thử pytest đạt trên môi trường thử nghiệm** và thử trực tiếp các PDF mẫu:
- File scan Cypress có dấu: con dấu khớp, nhưng tên ký màu đỏ chưa OCR đủ rõ, nên khi bật kiểm tra người ký sẽ **REVIEW**. Tên được khai báo: QUAN TUNG ANH.
- File PDF không dấu đỏ: FAIL.
- File công văn TCIS, 2 trang: PASS bằng NAME_FALLBACK, dấu trang 2; trước đó REVIEW do chưa OCR đủ chữ ở giữa dấu. Đọc được tên ký Nguyễn Sơn Hải nhưng không có trường đại diện có thẩm quyền để so khớp.
- PDF dạng công văn có tên công ty tại **góc trên trái**: đã trích xuất được tên từ đầu văn bản; nếu chữ trên dấu chưa đủ rõ, kết quả vẫn là REVIEW thay vì tự đoán PASS.
- Ảnh chụp công văn 4 trang có dấu đỏ nâu ở trang 4: thuật toán mới nhận diện được dấu **trên ảnh chụp**; chưa có PDF gốc để kiểm tra toàn bộ luồng Telegram. Với chứng từ không có trường tên doanh nghiệp, kết quả đối chiếu sẽ là REVIEW, không phải PASS.

**Chưa kiểm thử Docker và kết nối Telegram thực tế**, do chưa có token. Kết quả 2 file không chứng minh độ chính xác tổng thể; cần bộ dữ liệu có/không dấu, dấu mờ, sai MST để benchmark. Không đưa hồ sơ khách hàng hoặc thông tin nhạy cảm vào repo công khai. File tải về nằm trong thư mục tạm, được xóa sau khi xử lý. Log không lưu nội dung PDF.

## Hardcode và khả năng thích ứng

- **Không hardcode tên/MST công ty vào thuật toán**. TCIS, Cypress và doanh nghiệp giả định chỉ là dữ liệu ở thư mục `tests/`.
- Nhận diện công văn, biểu mẫu, PDF scan/PDF văn bản, nhiều trang, nhiều con dấu. Nếu không xác định chắc **đúng đơn vị ban hành** hoặc OCR vùng dấu chưa đủ tin cậy thì trả `REVIEW`, không tự suy đoán.
- Vẫn tồn tại **tham số thuật toán** như vùng tiêu đề khoảng 1/3 trang, sắc đỏ/nâu, kích thước dấu, độ tin cậy OCR và 5 vùng cắt. Đó là ngưỡng xử lý ảnh, **chưa phải mô hình nhận dạng mọi loại con dấu**.
- POC hiện chủ yếu dành cho **dấu tròn đỏ**; dấu xanh/đen, con dấu không tròn, scan nghiêng mạnh hoặc bố cục lạ cần thêm dữ liệu để kiểm chuẩn. Không dùng tên doanh nghiệp từ chứng từ để tự điền chữ chưa nhìn thấy trên dấu.
- Giữ thứ tự: `MST_MATCH` → `NAME_FALLBACK` (chỉ nếu MST không đọc rõ) → `REVIEW/FAIL`. MST đọc rõ mà khác nhau không được dùng fallback để lách.

## Trạng thái

POC giai đoạn 2: đã bổ sung so khớp tên ký in và tên đại diện khai báo; khi không chắc sẽ REVIEW. Bot **chưa xác minh thẩm quyền pháp lý** hoặc chữ ký số. Bước sau: benchmark nhiều PDF, tối ưu OCR dấu cong và người ký.
