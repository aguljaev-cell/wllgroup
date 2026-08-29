"""Mobile web UI backend for the AI coding agent."""
from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
MEMORY_FILE = ROOT / ".ai_memory.json"
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6")
app = Flask(__name__, static_folder="static")

SYSTEM = """You are a persistent software-development agent for this repository. Use the conversation memory supplied by the server. Help the user build software, inspect project files, write code, run tests, and explain changes. Never reveal API keys or other secrets. Never delete files or perform destructive operations unless explicitly requested."""

TOOLS = [
    {"type": "function", "name": "read_file", "description": "Read a UTF-8 text file from the repository.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"type": "function", "name": "write_file", "description": "Write a UTF-8 text file in the repository.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
]


def load_memory():
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_memory(data):
    MEMORY_FILE.write_text(json.dumps(data[-80:], ensure_ascii=False, indent=2), encoding="utf-8")


def safe_path(name: str) -> Path:
    p = (ROOT / name).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise ValueError("Path escapes repository")
    return p


def call_tool(name, args):
    p = safe_path(args["path"])
    if name == "read_file":
        return p.read_text(encoding="utf-8")[:50000]
    if name == "write_file":
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"], encoding="utf-8")
        return f"Updated {p.relative_to(ROOT)}"
    raise ValueError("Unknown tool")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(app.static_folder, "manifest.webmanifest")


@app.get("/sw.js")
def sw():
    return send_from_directory(app.static_folder, "sw.js")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "model": MODEL, "memory_items": len(load_memory())})


@app.post("/api/chat")
def chat():
    body = request.get_json(silent=True) or {}
    text = str(body.get("message", "")).strip()
    if not text:
        return jsonify({"error": "message is required"}), 400

    memory = load_memory()
    memory.append({"role": "user", "content": text})
    messages = [{"role": "system", "content": SYSTEM}] + memory[-80:]
    client = OpenAI()

    while True:
        response = client.responses.create(model=MODEL, input=messages, tools=TOOLS)
        calls = [x for x in response.output if getattr(x, "type", None) == "function_call"]
        if not calls:
            answer = response.output_text
            memory.append({"role": "assistant", "content": answer})
            save_memory(memory)
            return jsonify({"answer": answer, "memory_items": len(memory)})
        messages += response.output
        for call in calls:
            try:
                result = call_tool(call.name, json.loads(call.arguments))
            except Exception as exc:
                result = f"ERROR: {type(exc).__name__}: {exc}"
            messages.append({"type": "function_call_output", "call_id": call.call_id, "output": result})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
