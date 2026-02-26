import asyncio
import logging
import re
from datetime import datetime

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from database import add_message
from perplexity_client import ask_perplexity

TELEGRAM_MSG_LIMIT = 4096  # Giới hạn ký tự mỗi tin nhắn của Telegram

logger = logging.getLogger(__name__)


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


async def _handle_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id if update.effective_user else "?"
    logger.warning("Từ chối truy cập từ user_id=%s", uid)


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
