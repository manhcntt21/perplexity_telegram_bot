# Telegram Bot + Perplexity API

Bot Telegram cá nhân bằng Python, tích hợp Perplexity API để trả lời câu hỏi bằng tiếng Việt kèm nguồn trích dẫn. Chỉ phục vụ một Telegram user duy nhất.

---

## Cấu trúc dự án

```
.
├── main.py               # Entry point: bot handlers, logic chính
├── perplexity_client.py  # Gọi Perplexity API
├── database.py           # Lớp truy cập SQLite (aiosqlite)
├── requirements.txt      # Dependencies
├── .env.example          # Template biến môi trường
└── .env                  # Biến môi trường thật (không commit)
```

---

## Biến môi trường (`.env`)

| Biến | Mô tả |
|------|-------|
| `TELEGRAM_TOKEN` | Token bot từ @BotFather |
| `PERPLEXITY_API_KEY` | API key từ Perplexity |
| `ALLOWED_USER_ID` | Telegram user ID duy nhất được phép dùng bot |

> Lấy `ALLOWED_USER_ID`: nhắn `/start` cho `@userinfobot` trên Telegram.

---

## Cài đặt & chạy

```bash
cp .env.example .env
# Điền đầy đủ 3 giá trị vào .env
pip install -r requirements.txt
python main.py
```

---

## Database (`database.py`)

- File SQLite: `chat_history.db` (tự tạo khi chạy lần đầu)
- Bảng `chat_history`: `id`, `telegram_user_id`, `role`, `content`, `citations` (JSON string), `timestamp`

| Hàm | Mô tả |
|-----|-------|
| `init_db()` | Tạo bảng + index nếu chưa có |
| `add_message(user_id, role, content, citations)` | Thêm tin nhắn |
| `get_recent_messages(user_id, limit=10)` | Lấy N tin nhắn gần nhất (dùng làm context API) |
| `get_all_messages(user_id)` | Lấy toàn bộ lịch sử (dùng cho `/export`) |
| `clear_history(user_id)` | Xóa toàn bộ lịch sử, trả về số dòng đã xóa |

---

## Perplexity Client (`perplexity_client.py`)

- Model: `sonar` (đổi hằng `MODEL` để dùng `sonar-pro`)
- Context gửi kèm: 4 tin nhắn gần nhất (`CONTEXT_LIMIT = 4`)
- System prompt: `"Bạn là trợ lý nghiên cứu bằng tiếng Việt. Trả lời ngắn gọn, súc tích, định dạng dễ đọc."`
- `requests` chạy qua `asyncio.to_thread` để không block event loop
- Luôn trả về `tuple[str, list[str]]` — lỗi trả về message string + `[]`, không raise
- Mọi lỗi đều được log ở mức ERROR kèm HTTP status và response body

### `_sanitize_history(history)` — quan trọng
Perplexity API yêu cầu messages **xen kẽ** user/assistant. DB có thể tích lũy
dữ liệu lỗi từ các lần gọi API thất bại trước. Hàm này sanitize history trước khi gửi:
1. Drop leading `assistant` message (sau system phải là `user`)
2. Drop consecutive same-role (giữ message mới hơn)
3. Drop trailing `user` (vì `current_message` sẽ được append là `user`)

### Lưu ý thứ tự lưu DB
`add_message(user)` phải được gọi **sau** khi `ask_perplexity()` trả về, không phải trước.
Nếu lưu trước, `get_recent_messages()` bên trong `ask_perplexity` sẽ lấy ra tin nhắn hiện tại
và `append current_message` tạo ra hai `user` liên tiếp → HTTP 400.

---

## Bot (`main.py`)

### Lệnh

| Lệnh | Mô tả |
|------|-------|
| `/start` | Chào mừng, liệt kê lệnh |
| `/export` | Xuất toàn bộ lịch sử ra file `history_<username>.md`, gửi qua Telegram rồi xóa file local |
| `/clear` | Xóa lịch sử hội thoại |

### Xử lý tin nhắn text
1. Chạy typing indicator nền (`_keep_typing`, gửi lại mỗi 4s)
2. Gọi `ask_perplexity()`
3. Lưu tin nhắn user + câu trả lời AI vào DB (sau khi có kết quả)
4. Convert Markdown → HTML (`md_to_html()`), ghép citations
5. Gửi (tự cắt nếu > 4096 ký tự)

### Bảo mật — `ALLOWED_USER_ID`
- `filters.User(user_id=ALLOWED_USER_ID)` áp dụng ở cấp framework PTB cho tất cả handlers
- User lạ bị drop hoàn toàn, không nhận phản hồi
- Fallback handler (`group=1`) log `WARNING` khi có truy cập trái phép

### Helpers
- `md_to_html(text)`: escape HTML → convert code block/inline code/bold/italic/heading
- `split_message(text, limit=4096)`: cắt tại `\n\n` hoặc `\n`, tránh cắt giữa câu
- `_fmt_timestamp(ts)`: SQLite timestamp → `dd/mm/yyyy HH:MM`

---

## Bugs đã gặp & cách fix

| Lỗi | Nguyên nhân | Fix |
|-----|-------------|-----|
| HTTP 400 `return_citations` | Tham số không tồn tại trong Perplexity API | Xóa khỏi payload — citations trả về tự động |
| HTTP 400 duplicate `user` | `add_message(user)` gọi trước API → history chứa tin hiện tại → append lại → 2 `user` liên tiếp | Chuyển `add_message` xuống sau API call |
| HTTP 400 non-alternating | DB tích lũy data xấu từ lỗi trước → history bắt đầu bằng `assistant` hoặc kết thúc bằng `user` | Thêm `_sanitize_history()` |

---

## Dependencies (`requirements.txt`)

```
python-telegram-bot==21.6
requests==2.32.3
python-dotenv==1.0.1
aiosqlite==0.20.0
```
