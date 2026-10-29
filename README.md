# OCR PDF Verification Bot (POC)

Bot Telegram **chỉ nhận PDF**, trả trạng thái **PASS / FAIL / REVIEW** trong tin nhắn Telegram HTML gọn, có chữ đậm và vị trí trang phát hiện dấu. Đây là bản thử nghiệm, chưa được nghiệm thu độ chính xác OCR trên nhiều mẫu.

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
2. PyMuPDF render **từng trang**; OpenCV nhận cả dấu **đỏ nhạt/đỏ nâu**, xác nhận hình học vòng ngoài và vòng trong. Không lấy chữ đỏ đơn lẻ làm con dấu.
3. OCR trang đầu: ưu tiên trường tên/MST; nếu không có thì đọc **tiêu đề công văn góc trên bên trái**, hỗ trợ tên xuống nhiều dòng. Với con dấu, dùng **5 lượt OCR các vùng cắt nét mực đỏ**, nhấn mạnh chữ ở tâm dấu để giảm nhiễu vòng tròn.
4. MST dấu đọc đủ tin cậy và đúng checksum thì so với MST chứng từ. MST mâu thuẫn: **FAIL**, không dùng tên để bỏ qua.
5. Nếu MST dấu không đọc chắc, dùng RapidFuzz so khớp **nhiều từ đặc trưng** trong tên công ty; có từ mâu thuẫn được OCR rõ thì không tự PASS.
6. Không phát hiện vòng dấu: **FAIL**. Nếu chỉ thấy vùng nghi dấu hoặc có dấu nhưng không đủ dữ liệu (ví dụ công văn có dấu của cơ quan, không có trường tên doanh nghiệp để đối chiếu): **REVIEW**, kèm trang phát hiện.

### Mẫu trả lời Telegram (tối đa 3 dòng khi phát hiện dấu)

**Đạt bằng tên doanh nghiệp:**

```text
✅ HỒ SƠ ĐẠT
🔴 Dấu đỏ · Trang 2
🏢 Tên doanh nghiệp khớp · Dự phòng
```

**Không phát hiện dấu:**

```text
❌ KHÔNG ĐẠT
🔎 Không phát hiện dấu tròn đỏ.
```

**Cần kiểm tra:**

```text
⚠️ CẦN KIỂM TRA
🔴 Dấu đỏ · Trang 2
🔎 Tên trên dấu chưa đủ rõ để đối chiếu.
```

Phản hồi thật dùng Telegram HTML để in đậm trạng thái và kết quả. Nội bộ giữ `MST_MATCH` hoặc `NAME_FALLBACK`. PASS chỉ là **khớp thông tin dấu và chứng từ**, không kết luận giá trị pháp lý, không phân biệt dấu thật/giả. Chưa kiểm tra người ký/chức vụ hoặc xác thực chữ ký số nhúng; chữ ký số không được coi là dấu đỏ vật lý.

## Công nghệ

- python-telegram-bot: Telegram long polling, không cần domain hoặc webhook.
- PyMuPDF: đọc/render PDF; cần lưu ý giấy phép AGPL/commercial nếu đưa vào sản phẩm thương mại.
- OpenCV, NumPy: nhận diện con dấu tròn đỏ.
- Tesseract, pytesseract: OCR Việt/Anh chạy trong Docker, đọc 5 vùng cắt của dấu, không gọi AI bên ngoài.
- RapidFuzz: so khớp tên doanh nghiệp gần đúng theo quy tắc.

## Kiểm thử

Chạy: python -m pip install -r requirements-dev.txt rồi python -m pytest -q.

Đã kiểm thử logic **17 bài đạt** và thử trực tiếp các PDF mẫu:
- File scan có dấu: PASS bằng NAME_FALLBACK.
- File PDF không dấu đỏ: FAIL.
- File công văn TCIS, 2 trang: PASS bằng NAME_FALLBACK, dấu trang 2; trước đó REVIEW do chưa OCR đủ chữ ở giữa dấu.
- PDF dạng công văn có tên công ty tại **góc trên trái**: đã trích xuất được tên từ đầu văn bản; nếu chữ trên dấu chưa đủ rõ, kết quả vẫn là REVIEW thay vì tự đoán PASS.
- Ảnh chụp công văn 4 trang có dấu đỏ nâu ở trang 4: thuật toán mới nhận diện được dấu **trên ảnh chụp**; chưa có PDF gốc để kiểm tra toàn bộ luồng Telegram. Với chứng từ không có trường tên doanh nghiệp, kết quả đối chiếu sẽ là REVIEW, không phải PASS.

**Chưa kiểm thử Docker và kết nối Telegram thực tế**, do chưa có token. Kết quả 2 file không chứng minh độ chính xác tổng thể; cần bộ dữ liệu có/không dấu, dấu mờ, sai MST để benchmark. Không đưa hồ sơ khách hàng hoặc thông tin nhạy cảm vào repo công khai. File tải về nằm trong thư mục tạm, được xóa sau khi xử lý. Log không lưu nội dung PDF.

## Trạng thái

POC giai đoạn 1: bot trả trạng thái, OCR/con dấu ở mức sơ bộ; chưa kết luận thẩm quyền và chữ ký số. Bước sau: benchmark nhiều PDF, tối ưu OCR dấu cong và người ký.
