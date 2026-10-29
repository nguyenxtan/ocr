"""Telegram bot entrypoint: only PDF, only brief result status."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from app.analysis import Result, analyze_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()}
MAX_PDF_MB = int(os.getenv("MAX_PDF_MB", "15"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "10"))
OCR_LANG = os.getenv("OCR_LANG", "vie+eng")


def is_allowed(update: Update) -> bool:
    return bool(update.effective_user and (not ALLOWED or update.effective_user.id in ALLOWED))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text("Gửi một file PDF để kiểm tra. Kết quả: PASS / FAIL / REVIEW.\nDùng /id để xem Telegram ID.")


async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message and update.effective_user:
        await update.effective_message.reply_text(f"Telegram ID: {update.effective_user.id}")


async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not is_allowed(update):
        if message:
            await message.reply_text("⛔ Không có quyền sử dụng bot.")
        return
    document = message.document
    if document is None:
        return
    if not document.file_name or not document.file_name.lower().endswith(".pdf"):
        await message.reply_text("Chỉ hỗ trợ file PDF.")
        return
    if document.file_size and document.file_size > MAX_PDF_MB * 1024 * 1024:
        await message.reply_text("⚠️ REVIEW\nPDF vượt giới hạn dung lượng.")
        return
    await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
    try:
        with TemporaryDirectory(prefix="ocr-pdf-") as temp_dir:
            path = Path(temp_dir) / "upload.pdf"
            remote_file = await document.get_file()
            await remote_file.download_to_drive(custom_path=path)
            if path.stat().st_size > MAX_PDF_MB * 1024 * 1024:
                await message.reply_text("⚠️ REVIEW\nPDF vượt giới hạn dung lượng.")
                return
            with path.open("rb") as f:
                if f.read(5) != b"%PDF-":
                    await message.reply_text("⚠️ REVIEW\nFile không đúng định dạng PDF.")
                    return
            result = await asyncio.to_thread(analyze_pdf, path, MAX_PAGES, OCR_LANG)
            await message.reply_text(result.telegram_text())
    except Exception:
        logger.exception("PDF processing failed")
        await message.reply_text(Result("REVIEW", "Có lỗi khi phân tích PDF.").telegram_text())


async def other_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text("Chỉ nhận file PDF.")


def main() -> None:
    if not TOKEN or TOKEN == "PASTE_YOUR_TOKEN_HERE":
        raise RuntimeError("Vui lòng điền TELEGRAM_BOT_TOKEN trong .env")
    if not 1 <= MAX_PDF_MB <= 20:
        raise RuntimeError("MAX_PDF_MB phải trong khoảng 1..20 (giới hạn tải file Telegram Bot API).")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", show_id))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, handle_pdf))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.PRIVATE, other_message))
    logger.info("Starting Telegram PDF bot (polling)")
    app.run_polling(drop_pending_updates=True, allowed_updates=["message"])


if __name__ == "__main__":
    main()
