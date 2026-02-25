import asyncio
import logging
import os
import re

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, filters, CommandHandler, MessageHandler, ContextTypes
from dotenv import load_dotenv

from database import init_db, add_message

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_MSG_LIMIT = 4096  # Giới hạn ký tự mỗi tin nhắn của Telegram

_raw_uid = os.getenv("ALLOWED_USER_ID", "")
ALLOWED_USER_ID: int | None = int(_raw_uid) if _raw_uid.strip().lstrip("-").isdigit() else None

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def md_to_html(text: str) -> str:
    """Chuyển đổi Markdown (Perplexity trả về) sang HTML hợp lệ cho Telegram.

    Quy trình:
      1. Escape ký tự HTML đặc biệt trong toàn bộ văn bản thô.
      2. Áp dụng các pattern Markdown → HTML (thứ tự quan trọng).
    """
    # --- Bước 1: Escape HTML ------------------------------------------------
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # --- Bước 2: Fenced code block ```lang\ncode\n``` -----------------------
    text = re.sub(
        r"```(?:\w+)?\n?(.*?)```",
        lambda m: f"<pre><code>{m.group(1).strip()}</code></pre>",
        text,
        flags=re.DOTALL,
    )

    # --- Bước 3: Inline code `code` -----------------------------------------
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)

    # --- Bước 4: Bold **text** hoặc __text__ --------------------------------
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text, flags=re.DOTALL)

    # --- Bước 5: Italic *text* (đơn, không phải **) -------------------------
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)

    # --- Bước 6: Headings # / ## / ### → in đậm + xuống dòng ---------------
    text = re.sub(r"^#{1,3} +(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    return text


async def _keep_typing(chat, stop_event: asyncio.Event) -> None:
    """Gửi ChatAction.TYPING mỗi 4 giây cho đến khi stop_event được set."""
    while not stop_event.is_set():
        try:
            await chat.send_action(ChatAction.TYPING)
        except Exception:
            pass  # Không để lỗi mạng nhỏ dừng vòng lặp
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=4.0)
        except asyncio.TimeoutError:
            pass


def split_message(text: str, limit: int = TELEGRAM_MSG_LIMIT) -> list[str]:
    """Cắt tin nhắn dài thành nhiều phần ≤ limit ký tự, ưu tiên cắt tại dòng trống."""
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut == -1:
            cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_text = update.message.text
    logger.info("Nhận tin nhắn từ user %d: %s", user_id, user_text[:80])

    # Bắt đầu typing indicator chạy nền
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        _keep_typing(update.message.chat, stop_typing)
    )

    try:
        # mock perplexity API call
        answer = "Đây là câu trả lời mẫu từ Perplexity API. Thay thế bằng logic gọi API thực tế."
        citations = []
        pass
    finally:
        stop_typing.set()
        await typing_task

    await add_message(user_id, "user", user_text)
    await add_message(user_id, "assistant", answer, citations)

    html_answer = md_to_html(answer)

    for part in split_message(html_answer):
        await update.message.reply_text(part, parse_mode="HTML")

async def post_init(application: Application) -> None:
    """Khởi tạo database khi bot khởi động."""
    await init_db()
    logger.info("Database đã sẵn sàng.")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Xin chào! Tôi là trợ lý nghiên cứu AI tích hợp Perplexity.\n\n"
        "Hãy gửi bất kỳ câu hỏi nào, tôi sẽ tìm kiếm và trả lời bằng tiếng Việt "
        "kèm các nguồn trích dẫn.\n\n"
        "<b>Lệnh có sẵn:</b>\n"
        "/start  – Hiển thị tin nhắn này\n"
        "/export – Xuất toàn bộ lịch sử hội thoại ra file .md\n"
        "/clear  – Xóa lịch sử hội thoại, bắt đầu cuộc trò chuyện mới",
        parse_mode="HTML",
    )


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN chưa được thiết lập trong file .env")
    if ALLOWED_USER_ID is None:
        raise ValueError("ALLOWED_USER_ID chưa được thiết lập hoặc không hợp lệ trong file .env")

    # Filter cấp framework: chỉ xử lý update từ đúng user_id
    allowed = filters.User(user_id=ALLOWED_USER_ID)

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start, filters=allowed))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & allowed, handle_message))

    app.add_handler(
        MessageHandler(filters.ALL & ~allowed, _handle_unauthorized),
        group=1,
    )

    logger.info("Bot đang chạy — chỉ chấp nhận user_id=%d", ALLOWED_USER_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


async def _handle_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id if update.effective_user else "?"
    logger.warning("Từ chối truy cập từ user_id=%s", uid)


if __name__ == "__main__":
    main()
