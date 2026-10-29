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

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.analysis import Result
from app.runtime import analyze_isolated, build_evidence_isolated
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
MAX_QUEUED = int(os.getenv("MAX_QUEUED_PDFS", "3"))
QUEUE_WAIT_SEC = int(os.getenv("QUEUE_WAIT_SEC", "300"))
EVIDENCE_TIMEOUT_SEC = int(os.getenv("EVIDENCE_TIMEOUT_SEC", "15"))
semaphore = asyncio.Semaphore(MAX_CONCURRENT)
last_seen: dict[int, float] = {}
active_jobs: dict[int, asyncio.Task] = {}
proof_cache = ProofCache(ttl_seconds=600, max_items=32, max_bytes=24 * 1024 * 1024)


def evidence_page_for(filename: str, result: Result) -> int | None:
    """Page label for a proof image, without assuming signer and stamp coincide."""
    if filename == "proof_header.jpg":
        return 1
    if filename == "proof_signer.jpg":
        return result.signer_page or result.stamp_page
    return result.stamp_page


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


async def cancel_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel only the request created by this user, including its OCR process."""
    if update.effective_user is None or update.effective_message is None:
        return
    task = active_jobs.get(update.effective_user.id)
    if task is None or task.done():
        await update.effective_message.reply_text("ℹ️ Không có PDF nào đang chờ hoặc xử lý.")
        return
    task.cancel()
    await update.effective_message.reply_text("🛑 Đã yêu cầu hủy PDF của bạn.")


async def _finish_status(progress, message, result: Result, markup=None) -> None:
    """Always show a reason and replace the existing progress bubble."""
    html = result.telegram_html()
    try:
        if progress is not None:
            await progress.edit_text(html, parse_mode=ParseMode.HTML, reply_markup=markup)
            return
    except Exception as e:
        log.warning("Editing status failed: type=%s", type(e).__name__)
    await message.reply_text(html, parse_mode=ParseMode.HTML, reply_markup=markup)


async def pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if not is_allowed(update):
        await message.reply_text("⛔ Chưa được cấp quyền. Gõ /id rồi thêm ID vào ALLOWED_USER_IDS.")
        return
    document = message.document
    if not document or not document.file_name or not document.file_name.lower().endswith(".pdf"):
        await message.reply_text("Chỉ nhận PDF.")
        return
    if document.file_size and document.file_size > MAX_PDF_MB * 1024 * 1024:
        await _finish_status(None, message, Result("REVIEW", "PDF vượt giới hạn dung lượng."))
        return

    user_id = user.id
    if user_id in active_jobs:
        await message.reply_text("⏳ Bạn đang có PDF trong hàng đợi hoặc đang xử lý. Dùng /stop để hủy.")
        return
    now = time.monotonic()
    if now - last_seen.get(user_id, -float("inf")) < COOLDOWN_SEC:
        await message.reply_text("⏳ Vui lòng giãn cách giữa các lượt gửi PDF.")
        return

    # PTB processes these callbacks in one asyncio event loop. Register the
    # request BEFORE awaiting Telegram so the queue length stays bounded.
    if len(active_jobs) >= MAX_CONCURRENT + MAX_QUEUED:
        await message.reply_text("⏳ Hàng đợi đã đầy. Vui lòng thử lại sau.")
        return
    position = max(0, len(active_jobs) - MAX_CONCURRENT + 1)
    active_jobs[user_id] = asyncio.current_task()
    last_seen[user_id] = now
    acquired = False
    progress = None
    try:
        progress_text = ("⏳ Đã nhận PDF · Đang chờ đến lượt..."
                         if position else "🔎 Đang kiểm tra PDF...")
        progress = await message.reply_text(progress_text)
        await asyncio.wait_for(semaphore.acquire(), timeout=QUEUE_WAIT_SEC)
        acquired = True
        if position:
            try:
                await progress.edit_text("🔎 Đang kiểm tra PDF...")
            except Exception:
                pass
        await context.bot.send_chat_action(message.chat_id, ChatAction.TYPING)
        photos: tuple[ProofPhoto, ...] = ()
        with TemporaryDirectory(prefix="ocr-pdf-") as folder:
            file_path = Path(folder) / "upload.pdf"
            remote_file = await document.get_file()
            await remote_file.download_to_drive(custom_path=file_path)
            if file_path.stat().st_size > MAX_PDF_MB * 1024 * 1024:
                result = Result("REVIEW", "PDF vượt giới hạn dung lượng.")
            else:
                with file_path.open("rb") as stream:
                    valid_pdf = stream.read(5) == b"%PDF-"
                if not valid_pdf:
                    result = Result("REVIEW", "Tệp không phải PDF hợp lệ.")
                else:
                    # Main verdict is independent of optional proof rendering.
                    result = await analyze_isolated(file_path, MAX_PAGES, OCR_LANG,
                                                    PROCESS_TIMEOUT_SEC)
                    if result.stamp_page is not None:
                        filenames = await build_evidence_isolated(
                            file_path, result, EVIDENCE_TIMEOUT_SEC)
                        captions = dict(EVIDENCE_FILES)
                        photos = tuple(
                            ProofPhoto(
                                caption=f"{captions[name]} · Trang {evidence_page_for(name, result)}",
                                data=(Path(folder) / name).read_bytes())
                            for name in filenames if name in captions
                            and (Path(folder) / name).is_file()
                        )

        reply_markup = None
        if photos:
            token = proof_cache.add(user_id, message.chat_id, photos)
            if token:
                reply_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔍 Xem bằng chứng", callback_data=f"ev:{token}")
                ]])
        await _finish_status(progress, message, result, reply_markup)
        log.info("PDF status=%s, stamp_page=%s, signer=%s, proof_count=%d",
                 result.status, result.stamp_page, result.signer_status, len(photos))
    except asyncio.TimeoutError:
        await _finish_status(progress, message,
                             Result("REVIEW", "Hàng đợi quá lâu. Gửi lại PDF sau."))
    except asyncio.CancelledError:
        await _finish_status(progress, message,
                             Result("REVIEW", "Đã hủy xử lý PDF theo yêu cầu."))
    except Exception as e:
        log.error("PDF processing failed: error_type=%s", type(e).__name__)
        await _finish_status(progress, message,
                             Result("REVIEW", "Không xử lý được PDF. Hãy thử lại."))
    finally:
        if acquired:
            semaphore.release()
        active_jobs.pop(user_id, None)
        # Public access must have a bounded per-user cooldown cache.
        if len(last_seen) > 2000:
            cutoff = time.monotonic() - max(60, COOLDOWN_SEC)
            for uid, seen in list(last_seen.items()):
                if seen < cutoff:
                    last_seen.pop(uid, None)
            if len(last_seen) > 2000:
                last_seen.pop(min(last_seen, key=last_seen.get), None)


async def show_evidence(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Every button click gets an answer, including failed/expired photos."""
    query = update.callback_query
    if query is None or query.message is None or update.effective_user is None:
        return
    token = (query.data or "").partition(":")[2]
    photos = proof_cache.get(token, update.effective_user.id, query.message.chat.id)
    if not photos:
        await query.answer("Ảnh hết hạn hoặc không thuộc hồ sơ của bạn.", show_alert=True)
        return
    await query.answer()
    streams = []
    for item in photos:
        image = BytesIO(item.data)
        image.name = "bang-chung-ocr.jpg"
        streams.append(image)
    try:
        if len(photos) == 1:
            await context.bot.send_photo(chat_id=query.message.chat.id,
                                         photo=streams[0], caption=photos[0].caption)
        else:
            album = [InputMediaPhoto(media=stream, caption=item.caption)
                     for stream, item in zip(streams, photos)]
            await context.bot.send_media_group(chat_id=query.message.chat.id, media=album)
    except Exception as exc:
        log.warning("Sending proof album failed: type=%s", type(exc).__name__)
        # Graceful fallback to one stamp photo, not a silent failure.
        try:
            one = BytesIO(photos[0].data)
            one.name = "bang-chung-dau.jpg"
            await context.bot.send_photo(chat_id=query.message.chat.id,
                                         photo=one, caption=photos[0].caption)
        except Exception as fallback_error:
            log.warning("Sending proof photo failed: type=%s", type(fallback_error).__name__)
            await context.bot.send_message(chat_id=query.message.chat.id,
                                           text="⚠️ Không gửi được ảnh. Vui lòng gửi lại PDF để kiểm tra.")


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
    if not 0 <= MAX_QUEUED <= 8 or not 10 <= QUEUE_WAIT_SEC <= 900 or not 3 <= EVIDENCE_TIMEOUT_SEC <= 60:
        raise RuntimeError("MAX_QUEUED_PDFS phải 0..8, QUEUE_WAIT_SEC 10..900, EVIDENCE_TIMEOUT_SEC 3..60")
    if not 10 <= PROCESS_TIMEOUT_SEC <= 300 or not 1 <= MAX_CONCURRENT <= 3:
        raise RuntimeError("PROCESS_TIMEOUT_SEC phải 10..300, MAX_CONCURRENT_PDFS phải 1..3")
    if not re.fullmatch(r"[a-z]{3}(\+[a-z]{3}){0,3}", OCR_LANG):
        raise RuntimeError("OCR_LANG không hợp lệ")
    mode = os.getenv("OCR_ENGINE", "tesseract").lower()
    if mode not in ("tesseract", "ensemble"):
        raise RuntimeError("OCR_ENGINE phải là tesseract hoặc ensemble")


def main() -> None:
    validate_config()
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(16).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", show_id))
    app.add_handler(CommandHandler(["stop", "cancel"], cancel_job))
    app.add_handler(CallbackQueryHandler(show_evidence, pattern=r"^ev:[A-Za-z0-9_-]{16,32}$"))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, pdf))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.PRIVATE, other))
    log.info("Starting Telegram PDF OCR bot (access_mode=%s)", ACCESS_MODE)
    app.run_polling(drop_pending_updates=True, allowed_updates=["message"])


if __name__ == "__main__":
    main()
