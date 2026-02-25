import json

import aiosqlite

DB_PATH = "chat_history.db"


async def init_db():
    """Khởi tạo database và tạo bảng nếu chưa tồn tại."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
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
