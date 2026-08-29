import os
from pathlib import Path
from typing import Dict, List

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

app = FastAPI(title="WorldLogicLine Assistant API", version="1.0.0")
DATA = Path(os.getenv("WLL_DATA_DIR", "./data"))
DATA.mkdir(parents=True, exist_ok=True)
memories: Dict[str, List[str]] = {}

class ChatRequest(BaseModel):
    user_id: str
    message: str

class ChatResponse(BaseModel):
    reply: str

@app.get("/health")
def health():
    return {"status": "ok", "service": "WorldLogicLine Assistant"}

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(400, "message is required")
    history = memories.setdefault(req.user_id, [])
    history.append(req.message.strip())
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return ChatResponse(reply="AI backend настроен, но OPENAI_API_KEY ещё не задан администратором.")
    payload = {
        "model": os.getenv("WLL_MODEL", "gpt-4.1-mini"),
        "input": req.message,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post("https://api.openai.com/v1/responses", json=payload, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(502, "AI provider request failed")
    data = response.json()
    reply = data.get("output_text", "").strip()
    if not reply:
        raise HTTPException(502, "AI provider returned an empty response")
    history.append(reply)
    return ChatResponse(reply=reply)

@app.post("/v1/memory/{user_id}/documents")
async def upload_document(user_id: str, file: UploadFile = File(...)):
    safe_name = Path(file.filename or "document.bin").name
    user_dir = DATA / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    destination = user_dir / safe_name
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "file is too large")
    destination.write_bytes(content)
    return {"status": "stored", "filename": safe_name, "bytes": len(content)}
