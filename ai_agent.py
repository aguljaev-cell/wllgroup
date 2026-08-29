"""Simple persistent AI coding agent with local conversation memory.

Environment:
    OPENAI_API_KEY=...
    OPENAI_MODEL=gpt-5.6 (or another Responses API model available to you)

Usage:
    python ai_agent.py

Memory is stored in .ai_memory.json. The agent can read/write files in the
repository and run safe, user-requested development commands.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from openai import OpenAI

ROOT = Path(__file__).resolve().parent
MEMORY_FILE = ROOT / ".ai_memory.json"
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6")
MAX_MEMORY = 80

SYSTEM = """You are a practical software-development agent working inside the current repository.
You remember prior conversations through the supplied persistent memory.
You may inspect and modify repository files and run development commands.
Be conservative: never expose secrets, never delete files unless explicitly asked,
and explain important changes briefly. Prefer small, testable edits.
"""


def load_memory() -> list[dict[str, str]]:
    if not MEMORY_FILE.exists():
        return []
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_memory(messages: list[dict[str, str]]) -> None:
    MEMORY_FILE.write_text(
        json.dumps(messages[-MAX_MEMORY:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def safe_path(path: str) -> Path:
    p = (ROOT / path).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise ValueError("Path escapes repository root")
    return p


def read_file(path: str) -> str:
    p = safe_path(path)
    return p.read_text(encoding="utf-8")[:50000]


def write_file(path: str, content: str) -> str:
    p = safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {p.relative_to(ROOT)}"


def run_command(command: str) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        shell=True,
        text=True,
        capture_output=True,
        timeout=120,
    )
    output = (result.stdout + "\n" + result.stderr).strip()
    return f"exit={result.returncode}\n{output[-12000:]}"


TOOLS = [
    {"type": "function", "name": "read_file", "description": "Read a UTF-8 text file in the repository.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"type": "function", "name": "write_file", "description": "Create or replace a UTF-8 text file in the repository.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"type": "function", "name": "run_command", "description": "Run a development command in the repository and return its output.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
]


def call_tool(name: str, args: dict[str, Any]) -> str:
    if name == "read_file":
        return read_file(args["path"])
    if name == "write_file":
        return write_file(args["path"], args["content"])
    if name == "run_command":
        return run_command(args["command"])
    raise ValueError(f"Unknown tool: {name}")


def chat() -> None:
    client = OpenAI()
    memory = load_memory()
    print(f"AI coding agent ready. Model: {MODEL}")
    print("Memory: .ai_memory.json | type 'exit' to quit")

    while True:
        try:
            user = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user.lower() in {"exit", "quit"}:
            break

        memory.append({"role": "user", "content": user})
        input_messages = [{"role": "system", "content": SYSTEM}]
        input_messages.extend(memory[-MAX_MEMORY:])

        while True:
            response = client.responses.create(
                model=MODEL,
                input=input_messages,
                tools=TOOLS,
            )
            tool_calls = [x for x in response.output if getattr(x, "type", None) == "function_call"]
            if not tool_calls:
                answer = response.output_text
                print(f"\nAgent> {answer}")
                memory.append({"role": "assistant", "content": answer})
                save_memory(memory)
                break

            input_messages += response.output
            for call in tool_calls:
                try:
                    args = json.loads(call.arguments)
                    result = call_tool(call.name, args)
                except Exception as exc:
                    result = f"ERROR: {type(exc).__name__}: {exc}"
                input_messages.append({
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": result,
                })


if __name__ == "__main__":
    chat()
