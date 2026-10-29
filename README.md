# OCR PDF Bot · Telegram (POC)

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

**Cấp quyền:** Sau khi bot khởi động, gõ `/id` trong Telegram để lấy Telegram ID, rồi điền `ALLOWED_USER_IDS=<ID>` trong `.env`. Nếu danh sách này trống, bot **không xử lý bất kỳ PDF nào** (chế độ an toàn). Khởi động lại:

```bash
docker compose up -d --force-recreate
# Xem log
docker compose logs -f bot
```

Không đưa token, PDF khách hàng, CMND hoặc giấy tờ nội bộ vào repo. Docker dùng container không đặc quyền, read-only, bộ nhớ 2 GB, CPU giới hạn. PDF được tải vào thư mục tạm rồi xóa sau lượt kiểm tra.

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

## 4. Công nghệ & cấu hình

| Thư viện | Vai trò |
|---|---|
| python-telegram-bot | Nhận file và gửi kết quả |
| PyMuPDF | Đọc / render PDF (cần đánh giá giấy phép AGPL/commercial trước khi thương mại hóa) |
| OpenCV | Tìm vùng con dấu |
| Tesseract OCR (vie+eng) | Nhận dạng thông tin dấu, biểu mẫu, tên ký |
| RapidFuzz | So khớp từ tên doanh nghiệp |
| Poppler `pdfsig` | Kiểm tra chữ ký số PDF |

`.env.example` cung cấp các tham số: bot token, Telegram ID được phép, giới hạn file và trang, thời gian xử lý, bộ nhớ container (trong Compose), số lượt xử lý song song và khoảng cách giữa các lượt gửi.

**An toàn:** Mỗi PDF chạy trong một process riêng. Nếu quá hạn xử lý thì bot dừng process, trả REVIEW; không để OCR chạy mãi dưới nền. Tesseract được giới hạn một luồng CPU. Bộ đọc PDF giới hạn kích thước trang render. Không lưu PDF hay ảnh con dấu lâu dài, không log nội dung OCR.

## 5. Kiểm thử & benchmark

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Bộ kiểm thử chứa ca dương tính, ca âm tính, các tên công ty gần giống, MST mâu thuẫn, nhiều dấu, tên ký không đọc rõ, chữ ký số, xử lý tài nguyên, timeout, path traversal. CI chạy unit tests và build Docker image.

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
