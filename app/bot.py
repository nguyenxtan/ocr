"""Telegram PDF OCR with configurable PUBLIC or PRIVATE access."""
from __future__ import annotations

import asyncio
from io import BytesIO
import logging
import os
from pathlib import Path
import re
import time
from tempfile import TemporaryDirectory

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.analysis import Result
from app.runtime import analyze_isolated
from app.evidence import EVIDENCE_FILES
from app.proof_cache import ProofCache, ProofPhoto

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ACCESS_MODE = os.getenv("BOT_ACCESS_MODE", "PUBLIC").strip().upper()
ALLOWED = {int(x.strip()) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()}
MAX_PDF_MB = int(os.getenv("MAX_PDF_MB", "15"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "10"))
OCR_LANG = os.getenv("OCR_LANG", "vie+eng")
PROCESS_TIMEOUT_SEC = int(os.getenv("PROCESS_TIMEOUT_SEC", "90"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_PDFS", "1"))
COOLDOWN_SEC = int(os.getenv("USER_COOLDOWN_SEC", "10"))
semaphore = asyncio.Semaphore(MAX_CONCURRENT)
last_seen: dict[int, float] = {}
proof_cache = ProofCache(ttl_seconds=600, max_items=32, max_bytes=24 * 1024 * 1024)


def is_allowed(update: Update) -> bool:
    """PUBLIC allows private-chat users; PRIVATE requires an allowlisted ID."""
    if not update.effective_user:
        return False
    if ACCESS_MODE == "PUBLIC":
        return True
    return ACCESS_MODE == "PRIVATE" and update.effective_user.id in ALLOWED


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "📄 Gửi PDF để kiểm tra dấu, MST và người ký.\n"
            + ("🔓 Chế độ PUBLIC: không cần đăng ký Telegram ID."
               if ACCESS_MODE == "PUBLIC" else
               "🔒 Chế độ PRIVATE: dùng /id để đăng ký quyền truy cập.")
        )


async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message and update.effective_user:
        await update.effective_message.reply_text(f"Telegram ID: {update.effective_user.id}")


async def pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    if not is_allowed(update):
        await message.reply_text("⛔ Chưa được cấp quyền. Gõ /id rồi thêm ID vào ALLOWED_USER_IDS.")
        return
    doc = message.document
    if not doc or not doc.file_name or not doc.file_name.lower().endswith(".pdf"):
        await message.reply_text("Chỉ nhận PDF.")
        return
    if doc.file_size and doc.file_size > MAX_PDF_MB * 1024 * 1024:
        await message.reply_text(Result("REVIEW", "PDF vượt giới hạn dung lượng.").telegram_html(), parse_mode=ParseMode.HTML)
        return
    now = time.monotonic()
    user_id = update.effective_user.id
    if now - last_seen.get(user_id, -float("inf")) < COOLDOWN_SEC:
        await message.reply_text("⏳ Vui lòng giãn cách giữa các lượt gửi PDF.")
        return
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=1.0)
    except asyncio.TimeoutError:
        await message.reply_text("⏳ Bot đang xử lý PDF khác, vui lòng thử lại.")
        return
    # Bound in-memory cooldown tracking for a publicly accessible bot.
    if len(last_seen) >= 2000:
        cutoff = now - max(60, COOLDOWN_SEC)
        for uid, seen_at in list(last_seen.items()):
            if seen_at < cutoff:
                last_seen.pop(uid, None)
        if len(last_seen) >= 2000:
            last_seen.pop(min(last_seen, key=last_seen.get), None)
    last_seen[user_id] = now
    try:
        await context.bot.send_chat_action(message.chat_id, ChatAction.TYPING)
        photos: tuple[ProofPhoto, ...] = ()
        with TemporaryDirectory(prefix="ocr-pdf-") as folder:
            file_path = Path(folder) / "upload.pdf"
            remote_file = await doc.get_file()
            await remote_file.download_to_drive(custom_path=file_path)
            if file_path.stat().st_size > MAX_PDF_MB * 1024 * 1024:
                result = Result("REVIEW", "PDF vượt giới hạn dung lượng.")
            else:
                with file_path.open("rb") as stream:
                    valid_pdf = stream.read(5) == b"%PDF-"
                if not valid_pdf:
                    result = Result("REVIEW", "Tệp không phải PDF hợp lệ.")
                else:
                    result = await analyze_isolated(
                        file_path, MAX_PAGES, OCR_LANG, PROCESS_TIMEOUT_SEC,
                        evidence_dir=Path(folder),
                    )
                    # Only JPEG bytes remain after TemporaryDirectory removes the PDF.
                    photos = tuple(
                        ProofPhoto(caption=f"{caption} · Trang "
                                   f"{1 if name == 'proof_header.jpg' else result.stamp_page}",
                                   data=(Path(folder) / name).read_bytes())
                        for name, caption in EVIDENCE_FILES
                        if (Path(folder) / name).is_file()
                    )
        reply_markup = None
        if photos:
            token = proof_cache.add(user_id, message.chat_id, photos)
            if token:
                reply_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔍 Xem bằng chứng", callback_data=f"ev:{token}")
                ]])
        await message.reply_text(result.telegram_html(), parse_mode=ParseMode.HTML,
                                 reply_markup=reply_markup)
        log.info("Processed PDF: status=%s, stamp_page=%s, signer=%s",
                 result.status, result.stamp_page, result.signer_status)
    except Exception as e:
        log.error("PDF failed: error_type=%s", type(e).__name__)
        await message.reply_text(Result("REVIEW", "Không xử lý được PDF.").telegram_html(), parse_mode=ParseMode.HTML)
    finally:
        semaphore.release()


async def show_evidence(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Only the PDF sender may open its cached, short-lived proof images."""
    query = update.callback_query
    if query is None or query.message is None or update.effective_user is None:
        return
    token = (query.data or "").partition(":")[2]
    photos = proof_cache.get(token, update.effective_user.id, query.message.chat.id)
    if not photos:
        await query.answer("Ảnh đã hết hạn hoặc bạn không có quyền xem.", show_alert=True)
        return
    await query.answer()
    for item in photos:
        image = BytesIO(item.data)
        image.name = "bang-chung-ocr.jpg"
        await context.bot.send_photo(chat_id=query.message.chat.id, photo=image,
                                     caption=item.caption)


async def other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text("Chỉ nhận file PDF.")


def validate_config() -> None:
    if not TOKEN or TOKEN == "PASTE_YOUR_TOKEN_HERE":
        raise RuntimeError("Thiếu TELEGRAM_BOT_TOKEN trong .env")
    if ACCESS_MODE not in ("PUBLIC", "PRIVATE"):
        raise RuntimeError("BOT_ACCESS_MODE phải là PUBLIC hoặc PRIVATE")
    if ACCESS_MODE == "PRIVATE" and not ALLOWED:
        log.warning("PRIVATE mode with empty ALLOWED_USER_IDS: PDF processing is disabled")
    if ACCESS_MODE == "PUBLIC":
        if COOLDOWN_SEC < 3:
            raise RuntimeError("PUBLIC mode requires USER_COOLDOWN_SEC >= 3")
        log.warning("PUBLIC mode enabled: any Telegram user can send PDF in private chats")
    if not 1 <= MAX_PDF_MB <= 20 or not 1 <= MAX_PAGES <= 30:
        raise RuntimeError("MAX_PDF_MB phải 1..20 và MAX_PAGES phải 1..30")
    if not 10 <= PROCESS_TIMEOUT_SEC <= 300 or not 1 <= MAX_CONCURRENT <= 3:
        raise RuntimeError("PROCESS_TIMEOUT_SEC phải 10..300, MAX_CONCURRENT_PDFS phải 1..3")
    if not re.fullmatch(r"[a-z]{3}(\+[a-z]{3}){0,3}", OCR_LANG):
        raise RuntimeError("OCR_LANG không hợp lệ")
    mode = os.getenv("OCR_ENGINE", "tesseract").lower()
    if mode not in ("tesseract", "ensemble"):
        raise RuntimeError("OCR_ENGINE phải là tesseract hoặc ensemble")


def main() -> None:
    validate_config()
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(4).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", show_id))
    app.add_handler(CallbackQueryHandler(show_evidence, pattern=r"^ev:[A-Za-z0-9_-]{16,32}$"))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, pdf))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.PRIVATE, other))
    log.info("Starting Telegram PDF OCR bot (access_mode=%s)", ACCESS_MODE)
    app.run_polling(drop_pending_updates=True, allowed_updates=["message"])


if __name__ == "__main__":
    main()
