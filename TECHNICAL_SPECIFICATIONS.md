# Luồng 1

```python
   app = (
           Application.builder()
           .token(TELEGRAM_TOKEN)
           .post_init(post_init)
           .build()
       )
```
1. Application.builder()
Sử dụng Builder Pattern — trả về một ApplicationBuilder object, cho phép cấu hình bot theo kiểu "chuỗi method" (method chaining) thay vì truyền hàng loạt tham số vào constructor.
2. .token(TELEGRAM_TOKEN)
Truyền vào Bot Token — chuỗi xác thực do BotFather cấp, dùng để xác định và xác thực bot với Telegram API.
3. .post_init(post_init)
Đăng ký một callback async function tên post_init, sẽ được gọi sau khi Application được khởi tạo xong nhưng trước khi bot bắt đầu polling/chạy. Thường dùng để:

   1. Set bot commands (set_my_commands)
   2. Kết nối database 
   3. Khởi tạo các tài nguyên cần thiết
---

```python
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
```

1. Tóm tắt luồng: Mở DB → Tạo bảng → Tạo index → Commit → Đóng kết nối
2. await db.commit()
Xác nhận (commit) toàn bộ thay đổi vào file database. Nếu không có bước này, các lệnh CREATE TABLE và CREATE INDEX sẽ không được lưu lại.
3. Khi thoát khỏi block with, kết nối tự động đóng lại.
---
```python
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

allowed = filters.User(user_id=ALLOWED_USER_ID)

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & allowed, handle_message))


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

    # Lưu vào DB sau khi có kết quả — tránh get_recent_messages()
    # bên trong ask_perplexity() bắt gặp tin nhắn hiện tại và tạo ra
    # hai user message liên tiếp gây lỗi 400
    await add_message(user_id, "user", user_text)
    await add_message(user_id, "assistant", answer, citations)

    # Chuyển Markdown → HTML và ghép citations
    html_answer = md_to_html(answer) + format_citations(citations)

    # Gửi (tự động cắt nếu vượt giới hạn 4096 ký tự)
    for part in split_message(html_answer):
        await update.message.reply_text(part, parse_mode="HTML")

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
```
1. Tạo filter chỉ cho phép đúng một user (theo ID) được tương tác với bot — bảo mật, tránh người lạ dùng.
2. Đăng ký handler với 3 điều kiện AND:
   1. filters.TEXT — tin nhắn phải là văn bản
   2. ~filters.COMMAND — không phải lệnh (không bắt đầu bằng /)
   3. đúng user được phép
   
-> Khi thỏa 3 điều kiện, gọi hàm handle_message.
3. handle message
   1. Lấy ID người dùng và nội dung tin nhắn từ update (object chứa toàn bộ thông tin về sự kiện đến).
   2. Chạy song song một task giữ trạng thái "🕐 đang nhập..." hiển thị trên Telegram trong khi bot xử lý. Dùng asyncio.Event để ra hiệu dừng khi xong.
   3. Gọi Perplexity AI để lấy câu trả lời. Dùng try/finally đảm bảo dù thành công hay lỗi, typing indicator cũng sẽ được dừng lại.
   4. Lưu lịch sử vào DB sau 
      1. Lưu tin nhắn sau khi đã có kết quả 
      2. nếu lưu trước, hàm ask_perplexity sẽ đọc lại tin nhắn hiện tại từ DB và tạo ra 2 user message liên tiếp → Telegram API trả lỗi 400.
   5. Chuyển định dạng Markdown của câu trả lời sang HTML để Telegram hiển thị tốt hơn, đồng thời ghép phần trích dẫn (nếu có).

4. Tại sao cần await typing_task ở cuối?
   1. Để đảm bảo background task đã thực sự kết thúc trước khi tiếp tục
   2. Nếu không chờ, có thể xảy ra tình huống bot đã gửi reply rồi mà typing indicator vẫn còn chạy thêm vài giây

5. add_handler: đăng ký quy tắc phân luồng đó.
   1. Khi Telegram gửi một update (tin nhắn, lệnh, bấm nút...) đến bot,
   2. Application sẽ duyệt qua danh sách handlers theo thứ tự và tìm handler đầu tiên khớp điều kiện
   
Tóm tắt luồng: Nhận tin nhắn → Bật typing → Gọi AI → Tắt typing → Lưu DB → Format → Gửi reply

Note:

> typing indicator: Khi bạn nhắn tin Telegram, đôi khi bạn thấy phía dưới tên người kia hiện chữ "đang nhập..." (hoặc biểu tượng 3 chấm nhảy). Đó là typing indicator.
> Telegram cho phép bot giả lập hiệu ứng này bằng cách gọi API sendChatAction. Tuy nhiên, hiệu ứng chỉ kéo dài ~5 giây rồi tự tắt — vì vậy nếu bot cần xử lý lâu hơn, phải gọi lại liên tục.

asyncio.Event() là gì?
> Hãy hình dung nó như một công tắc đèn:
> Mặc định: tắt (not set)
> Khi gọi .set(): bật (set)
> Ai đó đang chờ (await event.wait()) sẽ được "đánh thức" ngay khi công tắc bật

```python 
stop_typing = asyncio.Event()  # Tạo công tắc, mặc định = TẮT
```

asyncio.create_task() là gì?
> cho phép chạy nhiều việc "song song" (thực ra là xen kẽ nhau). create_task tạo một task chạy nền — không cần chờ nó xong mới làm việc khác.
> Trong ví dụ trên: chạy hàm _keep_typing ở nền, tôi sẽ tiếp tục làm việc khác (gọi AI) mà không cần chờ nó.

Hàm _keep_typing trông như thế nào?
> Khi stop_event chưa được bật (mặc định nó tắt) - nghĩa là vẫn đang xử lý câu trả lời.
> Gửi ChatAction.TYPING để Telegram hiển thị "đang nhập..." - hình thức gia hạn vì hiệu ứng mặc định kéo dài 5s rồi tự tắt.
> Sau đó chờ 4s hoặc đến khi stop_event được bật (tùy điều kiện nào đến trước). Hết 4 giây, chưa dừng → lặp lại

---
```python
    # Fallback: log và bỏ qua mọi update từ user không được phép
    app.add_handler(
        MessageHandler(filters.ALL & ~allowed, _handle_unauthorized),
        group=1,
    )

    logger.info("Bot đang chạy — chỉ chấp nhận user_id=%d", ALLOWED_USER_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

   async def _handle_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
       uid = update.effective_user.id if update.effective_user else "?"
       logger.warning("Từ chối truy cập từ user_id=%s", uid)
```

1. xác định điều kiện: filters.ALL & ~allowed — bất kỳ loại update nào (ALL) từ user không nằm trong danh sách cho phép (~allowed).
2. hàm được gọi khi có người lạ nhắn tin, thường chỉ đơn giản là ghi log:
3. app.run_polling() - Đây là lệnh **khởi động bot và giữ nó chạy mãi**. Cơ chế hoạt động:
   1. Bot liên tục hỏi Telegram: "Có tin nhắn mới không?"
   2. Telegram trả về danh sách updates mới
   3. Bot xử lý từng update qua các handlers
   4. Lặp lại... mãi cho đến khi tắt (Ctrl+C)

Note
> **Polling** là cách đơn giản nhất để bot nhận tin nhắn — bot chủ động hỏi Telegram định kỳ (đối lập với **webhook**, nơi Telegram chủ động gửi đến server của bạn).

> **`allowed_updates=Update.ALL_TYPES`** — yêu cầu Telegram gửi **mọi loại update**: tin nhắn, bấm nút inline, thêm vào group, v.v. Nếu không chỉ định, Telegram có thể bỏ qua một số loại update.

# Luồng 2

Có 3 luồng xử lý chính: start, export, clear

### 1 start

```python
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
```
Nếu không gõ `/start` thì nó không hiện

### 2 export

Lưu lại lịch sử, tham khảo kết quả tại [đây](./history_dav1d101.md)

### 3 clear

Xoá hết lịch sử trong database

# Luồng 3

## database

### 1 khởi tạo database

history scheme gồm: 
- id: kiểu integer, tự tăng
- telegram_user_id: integer, not null
- role: là một trong hai giá trị **user** hoặc **assistance**
- content: kiểu Text
- citations: kiểu Text
- timestamp: kiểu DateTime

Sẽ được khởi tạo từ đầu nếu chưa có với sqlite

```sql
CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                citations TEXT DEFAULT '[]',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
```

tạo index dựa trên telegram_user_id
### 2 thêm message

Cần serialization python : citations (nó là list[str]) sang string bằng json.dumps

```sql
INSERT INTO chat_history (telegram_user_id, role, content, citations)
            VALUES (?, ?, ?, ?)
```
### 3 lấy danh sách các messgae gần nhất

Lấy N tin nhắn gần nhất để làm context dựa trên telegram_user_id

```sql
SELECT id, role, content, citations, timestamp
            FROM chat_history
            WHERE telegram_user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
```

Chú ý phải đảo ngược thứ tự để khi sử dụng tuân theo thứ tự từ cũ nhất đến mới nhất
### 4 lấy tất cả các message

Láy danh sách các messages dựa trên telegram_user_id, thứ tự cần phải đảo ngược lại

```sql
SELECT id, role, content, citations, timestamp
FROM chat_history
WHERE telegram_user_id = ?
ORDER BY timestamp ASC
```
### 5 xoá lịch sử

Xoá lịch sử dựa trên telegram_user_id

```sql
DELETE FROM chat_history WHERE telegram_user_id = ?
```
## perplexity client

### 1 system prompt
Để cho đơn giản mình sử dụng một system prompt đơn giản như sau:

```python
SYSTEM_PROMPT = (
    "Bạn là trợ lý nghiên cứu bằng tiếng Việt. "
    "Trả lời ngắn gọn, súc tích, định dạng dễ đọc."
)
```

### 2 logic

mỗi khi gửi câu hỏi đến perplexity cần

1. lấy N tin nhắn gần nhất từ database để làm context
2. sanitize lại lịch sử để đảm bảo tuân thủ định dạng yêu cầu của API (xen kẽ user/assistant, không có 2 tin nhắn cùng role liên tiếp, v.v.)
3. append tin nhắn hiện tại (dưới role "user") vào cuối lịch sử đã được sanitize
4. gửi request đến API và nhận về câu trả lời + citations
   1. Bot Telegram chạy trên async event loop, nhưng requests.post() là synchronous, nó sẽ block event loop để đợi phản hồi —> chạy trong thread riêng bằng asyncio.to_thread() để tránh block event loop. Có nghĩa là nó sẽ không phải đứng chờ cho đến khi server trả về kết quả mà vẫn có thể làm việc khác trong lúc chờ
   2. Chúng ta cần chạy blocking code trong thread riêng biệt để tránh block event loop

*Note*:

Hiện tượng khi Event Loop bị Block: Giả sử bot đang xử lý tin nhắn của bạn, và trong lúc đó requests.post() block event loop 10 giây:
1. Typing indicator biến mất hoặc không xuất hiện — vì task _keep_typing cần event loop để chạy, nhưng event loop đang bị chiếm dụng hoàn toàn.
2. Bot không phản hồi lệnh nào khác — nếu bạn gõ /help hay bất kỳ tin nhắn nào trong lúc chờ, bot hoàn toàn im lặng, không xử lý gì cả.
3. Tin nhắn đến muộn hoặc dồn cục — nếu gửi nhiều tin liên tiếp, bot không xử lý từng cái một mà gom lại rồi xử lý tất cả sau khi event loop được giải phóng.
