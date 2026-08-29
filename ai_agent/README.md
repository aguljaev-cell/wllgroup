# GPT AI Agent with Memory

A minimal starter architecture for an AI agent backed by OpenAI and GitHub.

## Architecture

- `agent.py` — agent loop and tool dispatch.
- `memory.py` — durable local memory stored as JSON.
- `requirements.txt` — Python dependencies.
- `.env.example` — environment variables.

## Environment

Set `OPENAI_API_KEY` locally. Never commit a real API key to GitHub.

## Memory

The agent stores explicit user facts/preferences in `data/memory.json`. Keep secrets and sensitive data out of this file.

## Next step

Connect `agent.py` to your preferred UI (Telegram, web app, Discord, CLI, etc.).
