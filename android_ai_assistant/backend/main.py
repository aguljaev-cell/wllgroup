import os
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import httpx

app = FastAPI(title="WorldLogicLine Assistant API", version="0.1.0")

LETTA_URL = os.getenv("LETTA_URL", "http://letta:8283").rstrip("/")
LETTA_AGENT_ID = os.getenv("LETTA_AGENT_ID", "")
API_TOKEN = os.getenv("WLL_API_TOKEN", "")
LETTA_TOKEN = os.getenv("LETTA_API_TOKEN", "")

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)

class ChatResponse(BaseModel):
    reply: str

@app.get("/health")
def health():
    return {"ok": True, "service": "worldlogicline-assistant"}

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, authorization: str | None = Header(default=None)):
    if API_TOKEN and authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not LETTA_AGENT_ID:
        raise HTTPException(status_code=503, detail="LETTA_AGENT_ID is not configured")

    headers = {"Content-Type": "application/json"}
    if LETTA_TOKEN:
        headers["Authorization"] = f"Bearer {LETTA_TOKEN}"

    payload = {"input": req.message, "streaming": False}
    url = f"{LETTA_URL}/v1/agents/{LETTA_AGENT_ID}/messages"

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Letta returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="AI backend unavailable") from exc

    for item in data.get("messages", []):
        if item.get("message_type") == "assistant_message":
            content = item.get("content", "")
            if isinstance(content, str):
                return ChatResponse(reply=content)
            if isinstance(content, list):
                text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
                if text:
                    return ChatResponse(reply=text)

    raise HTTPException(status_code=502, detail="AI backend returned no assistant message")
