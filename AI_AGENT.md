# AI coding agent

The repository now contains `ai_agent.py`, a small persistent AI coding agent.

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Set `OPENAI_API_KEY` in the environment. Never commit the key.
3. Optionally set `OPENAI_MODEL` to the model you want to use.
4. Run: `python ai_agent.py`

The agent keeps recent conversation history in `.ai_memory.json`, which should remain local and must not be committed. It can inspect and edit repository text files and run development commands.
