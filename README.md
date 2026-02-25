# Perplexity Telegram Bot

[![python](https://img.shields.io/badge/python-3.11%2B-blue)]()

Lightweight personal Telegram bot that integrates Perplexity.ai to answer questions in Vietnamese and return source citations. The bot is written in Python and is designed to serve a single allowed Telegram user (configured via environment variables).

## What this project does

- Receives text messages from one authorized Telegram user.
- Forwards the question to Perplexity.ai (chat completions) with a small conversation context.
- Returns Perplexity's answer (Markdown) converted to Telegram-safe HTML and includes citation links.
- Persists chat history in a local SQLite database and supports exporting/clearing history.

Key files

- `main.py` — Bot entry point, Telegram handlers and helpers.
- `perplexity_client.py` — Perplexity API client and history sanitization.
- `database.py` — Async SQLite helpers (aiosqlite) for storing chat history.
- `requirements.txt` — Python dependencies.
- `CLAUDE.md` — Project notes and developer documentation.

## Why this project is useful

- Fast way to prototype a Telegram-based assistant using Perplexity's research answers and sources.
- Keeps local chat history for auditing, exporting, or reproducing context.
- Minimal, dependency-light design — runs locally and stores data in `chat_history.db`.

## Quick start

1. Clone the repository.
2. Create a virtual environment and install requirements.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Create a `.env` file in the project root (you can copy from `.env.example` if available) and set the following values:

```env
TELEGRAM_TOKEN=123456:ABC-DEF...       # token from @BotFather
PERPLEXITY_API_KEY=pplx-...           # Perplexity API key
ALLOWED_USER_ID=123456789             # Telegram user ID allowed to use the bot, token from @RawDataBot
```

4. Run the bot:

```bash
python main.py
```

The bot uses polling (python-telegram-bot Application.run_polling). On startup it will create a SQLite database file (`chat_history.db`) if one does not exist.

## Usage (Telegram)

- `/start` — Show welcome and available commands.
- `/export` — Export full chat history to a Markdown file and send it to you via Telegram.
- `/clear` — Delete the stored chat history for the configured user.

Send any text message and the bot will reply with a Perplexity-generated answer and citations.

## Environment and configuration

- `TELEGRAM_TOKEN` — Bot token from BotFather.
- `PERPLEXITY_API_KEY` — Bearer token for Perplexity API.
- `ALLOWED_USER_ID` — Single Telegram user ID that is allowed to interact with the bot, token from @RawDataBot

Notes and defaults

- The Perplexity client uses `MODEL = "sonar"` and a small `CONTEXT_LIMIT = 4` to include context while saving tokens. You can edit `perplexity_client.py` to change the model.
- The SQLite DB path is `chat_history.db` (see `database.py`).

## Implementation details

- The bot converts Markdown responses from Perplexity to Telegram-safe HTML using `md_to_html()` in `main.py`.
- Long messages are split into 4096-character chunks before sending to Telegram to avoid API limits.
- `perplexity_client.ask_perplexity()` runs blocking `requests.post()` inside `asyncio.to_thread(...)` to keep the event loop responsive.
- `database.py` stores citations as JSON-encoded strings in the `citations` column.

## Troubleshooting

- If the bot raises a `ValueError` about missing tokens, verify your `.env` values.
- For 401/429 errors from Perplexity, check `PERPLEXITY_API_KEY` and rate limits; errors are converted to user-friendly messages and logged.
- If you see malformed history errors or HTTP 400 from the API, the history sanitizer `_sanitize_history()` in `perplexity_client.py` handles common ordering issues.

## Where to get help

- Developer notes: `CLAUDE.md` (contains design notes and tips).
- For issues and feature requests: open an issue or a PR in the repository.

## Contributing

Contributions are welcome. Keep changes small and focused. Please:

- Open an issue to discuss larger changes.
- Fork the repository, create a feature branch, and send a pull request.

If you want to add feature-rich docs or contributor guidelines, add `CONTRIBUTING.md` and link it here.

## Security

- Do not commit `.env` or the `chat_history.db` file. Keep `PERPLEXITY_API_KEY` and `TELEGRAM_TOKEN` secret.

## Claude Code

see `CLAUDE.md`.
