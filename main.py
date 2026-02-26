import asyncio
from datetime import datetime
import logging
import os
import re
import tempfile
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, filters, CommandHandler, MessageHandler, ContextTypes
from dotenv import load_dotenv

from database import init_db, add_message, clear_history, get_all_messages
from perplexity_client import ask_perplexity

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
        answer, citations = await ask_perplexity(user_id, user_text)
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


def _build_export_content(username: str, messages: list[dict]) -> str:
    """Tạo nội dung file Markdown từ danh sách tin nhắn."""
    exported_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    lines: list[str] = [
        "# Lịch sử hội thoại — Perplexity Bot",
        f"> Người dùng : {username}",
        f"> Xuất lúc   : {exported_at}",
        f"> Tổng số    : {len(messages)} tin nhắn",
        "",
    ]

    # Nhóm từng cặp user/assistant thành một "lượt"
    i = 0
    turn = 1
    while i < len(messages):
        msg = messages[i]
        ts = _fmt_timestamp(msg["timestamp"])

        if msg["role"] == "user":
            lines += [
                "---",
                "",
                f"### Lượt {turn}",
                "",
                f"**[{ts}] Bạn**",
                "",
                msg["content"],
                "",
            ]
            # Kiểm tra xem tin tiếp theo có phải assistant không
            if i + 1 < len(messages) and messages[i + 1]["role"] == "assistant":
                i += 1
                reply = messages[i]
                ts_r = _fmt_timestamp(reply["timestamp"])
                lines += [
                    f"**[{ts_r}] Trợ lý**",
                    "",
                    reply["content"],
                    "",
                ]
                if reply["citations"]:
                    lines.append("**Nguồn tham khảo:**")
                    for idx, url in enumerate(reply["citations"], 1):
                        lines.append(f"[{idx}] {url}")
                    lines.append("")
            turn += 1
        else:
            # Tin nhắn assistant đứng riêng (không có cặp user)
            lines += [
                "---",
                "",
                f"**[{ts}] Trợ lý**",
                "",
                msg["content"],
                "",
            ]
            if msg["citations"]:
                lines.append("**Nguồn tham khảo:**")
                for idx, url in enumerate(msg["citations"], 1):
                    lines.append(f"[{idx}] {url}")
                lines.append("")

        i += 1

    lines += ["---", "", "*Được tạo bởi Perplexity Telegram Bot*"]
    return "\n".join(lines)


def _fmt_timestamp(ts: str) -> str:
    """Chuyển chuỗi timestamp SQLite sang định dạng dd/mm/yyyy HH:MM."""
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return ts


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


async def _handle_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id if update.effective_user else "?"
    logger.warning("Từ chối truy cập từ user_id=%s", uid)


if __name__ == "__main__":
    main()
