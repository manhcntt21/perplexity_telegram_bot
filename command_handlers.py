import logging
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from database import clear_history, get_all_messages
from utils import _build_export_content

logger = logging.getLogger(__name__)


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


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    deleted = await clear_history(user_id)
    if deleted > 0:
        await update.message.reply_text(
            f"Đã xóa <b>{deleted}</b> tin nhắn. Hội thoại mới bắt đầu!",
            parse_mode="HTML",
        )
        logger.info("Đã xóa lịch sử của user_id=%d, %d tin nhắn bị xóa", user_id, deleted)
    else:
        await update.message.reply_text("Không có lịch sử nào để xóa.")


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    username = user.username or user.full_name or str(user_id)

    messages = await get_all_messages(user_id)
    if not messages:
        await update.message.reply_text("Không có lịch sử hội thoại nào để xuất.")
        return

    content = _build_export_content(username, messages)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".md",
                prefix=f"history_{user_id}_",
                encoding="utf-8",
                delete=False,
        ) as f:
            f.write(content)
            tmp_path = Path(f.name)

        with tmp_path.open("rb") as doc:
            await update.message.reply_document(
                document=doc,
                filename=f"history_{username}.md",
                caption=f"Lịch sử hội thoại — {len(messages)} tin nhắn.",
            )
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
