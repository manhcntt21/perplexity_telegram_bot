import json

import aiosqlite

DB_PATH = "chat_history.db"


async def init_db():
    """Khởi tạo database và tạo bảng nếu chưa tồn tại."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
                         CREATE TABLE IF NOT EXISTS chat_history
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY
                             AUTOINCREMENT,
                             telegram_user_id
                             INTEGER
                             NOT
                             NULL,
                             role
                             TEXT
                             NOT
                             NULL
                             CHECK (
                             role
                             IN
                         (
                             'user',
                             'assistant'
                         )),
                             content TEXT NOT NULL,
                             citations TEXT DEFAULT '[]',
                             timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                             )
                         """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_id ON chat_history (telegram_user_id)"
        )
        await db.commit()


async def add_message(
        telegram_user_id: int,
        role: str,
        content: str,
        citations: list[str] | None = None,
):
    """Thêm một tin nhắn mới vào lịch sử chat.

    Args:
        telegram_user_id: ID của người dùng Telegram.
        role: 'user' hoặc 'assistant'.
        content: Nội dung tin nhắn.
        citations: Danh sách URL trích dẫn (chỉ dùng cho role='assistant').
    """
    citations_json = json.dumps(citations or [], ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO chat_history (telegram_user_id, role, content, citations)
            VALUES (?, ?, ?, ?)
            """,
            (telegram_user_id, role, content, citations_json),
        )
        await db.commit()


async def get_recent_messages(telegram_user_id: int, limit: int = 10) -> list[dict]:
    """Lấy N tin nhắn gần nhất của một user để làm context.

    Args:
        telegram_user_id: ID của người dùng Telegram.
        limit: Số lượng tin nhắn cần lấy (mặc định 10).

    Returns:
        Danh sách dict với các key: id, role, content, citations, timestamp.
        Được sắp xếp từ cũ đến mới (chronological order).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
                """
                SELECT id, role, content, citations, timestamp
                FROM chat_history
                WHERE telegram_user_id = ?
                ORDER BY timestamp DESC
                    LIMIT ?
                """,
                (telegram_user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()

    # Đảo ngược để có thứ tự từ cũ → mới
    messages = []
    for row in reversed(rows):
        messages.append({
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "citations": json.loads(row["citations"]),
            "timestamp": row["timestamp"],
        })
    return messages


async def clear_history(telegram_user_id: int) -> int:
    """Xóa toàn bộ lịch sử chat của một user.

    Args:
        telegram_user_id: ID của người dùng Telegram.

    Returns:
        Số lượng bản ghi đã xóa.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "DELETE FROM chat_history WHERE telegram_user_id = ?",
                (telegram_user_id,),
        ) as cursor:
            deleted_count = cursor.rowcount
        await db.commit()
    return deleted_count
