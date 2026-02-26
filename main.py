import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, filters, CommandHandler, MessageHandler

from command_handlers import cmd_start, cmd_export, cmd_clear
from database import init_db
from utils import handle_message, _handle_unauthorized

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


async def post_init(application: Application) -> None:
    """Khởi tạo database khi bot khởi động."""
    await init_db()
    logger.info("Database đã sẵn sàng.")


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
    app.add_handler(CommandHandler("export", cmd_export, filters=allowed))
    app.add_handler(CommandHandler("clear", cmd_clear, filters=allowed))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & allowed, handle_message))

    app.add_handler(
        MessageHandler(filters.ALL & ~allowed, _handle_unauthorized),
        group=1,
    )

    logger.info("Bot đang chạy — chỉ chấp nhận user_id=%d", ALLOWED_USER_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
