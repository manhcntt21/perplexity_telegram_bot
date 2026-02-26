import os
import asyncio
import logging
import requests
from dotenv import load_dotenv

from prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

load_dotenv()

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
MODEL = "sonar"
CONTEXT_LIMIT = 4  # Số tin nhắn lịch sử gửi kèm để tiết kiệm token


async def ask_perplexity(
        user_id: int, current_message: str
) -> tuple[str, list[str]]:
    """Gửi câu hỏi đến Perplexity API kèm lịch sử chat gần nhất.

    Args:
        user_id: Telegram user ID để tra cứu lịch sử.
        current_message: Tin nhắn hiện tại của người dùng.

    Returns:
        Tuple (answer, citations):
            - answer: Chuỗi trả lời từ AI.
            - citations: Danh sách URL trích dẫn (có thể rỗng).
    """
    # Xây dựng danh sách messages theo format OpenAI-compatible
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "user", "content": current_message})

    payload = {
        "model": MODEL,
        "messages": messages,
    }
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    logger.info("Gửi request Perplexity | model=%s | messages=%d", MODEL, len(messages))

    try:
        # Chạy requests (sync) trong thread pool để không block event loop
        def _call_api() -> dict:
            response = requests.post(
                PERPLEXITY_API_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()

        data = await asyncio.to_thread(_call_api)

        answer: str = data["choices"][0]["message"]["content"]
        citations: list[str] = data.get("citations", [])
        logger.info("Perplexity OK | citations=%d", len(citations))
        return answer, citations

    except requests.exceptions.Timeout:
        logger.error("Perplexity timeout")
        return "Yêu cầu bị timeout. Vui lòng thử lại sau.", []

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        body = e.response.text if e.response is not None else ""
        logger.error("Perplexity HTTPError %s | body: %s", status, body)
        if status == 401:
            return "Lỗi xác thực: PERPLEXITY_API_KEY không hợp lệ.", []
        if status == 429:
            return "Đã vượt quá giới hạn request. Vui lòng thử lại sau ít phút.", []
        return f"Perplexity API trả về lỗi HTTP {status}.", []

    except (KeyError, IndexError) as e:
        logger.error("Perplexity parse error: %s | data: %s", e, data)
        return "Phản hồi từ API không đúng định dạng mong đợi.", []

    except Exception as e:
        logger.error("Perplexity unknown error: %s", e, exc_info=True)
        return f"Đã xảy ra lỗi khi gọi API: {e}", []


def _sanitize_history(history: list[dict]) -> list[dict]:
    """Đảm bảo history hợp lệ cho API: bắt đầu bằng user, xen kẽ user/assistant,
    kết thúc bằng assistant (vì current_message sẽ là user tiếp theo).

    Các lần gọi API thất bại trước có thể để lại dữ liệu sai thứ tự trong DB.
    """
    # 1. Bỏ assistant message đứng đầu — sau system phải là user
    while history and history[0]["role"] == "assistant":
        history = history[1:]

    # 2. Loại bỏ consecutive same-role: giữ message mới hơn
    clean: list[dict] = []
    for msg in history:
        if clean and clean[-1]["role"] == msg["role"]:
            clean[-1] = msg
        else:
            clean.append(msg)

    # 3. Bỏ user message cuối — current_message sẽ là user, tránh hai user liên tiếp
    while clean and clean[-1]["role"] == "user":
        clean.pop()

    return clean
