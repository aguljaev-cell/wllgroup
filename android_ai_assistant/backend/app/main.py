import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from letta_client import Letta

app = FastAPI(title="WorldLogicLine Assistant API")
client = Letta(base_url=os.environ.get("LETTA_BASE_URL", "http://letta:8283"))
AGENT_ID = os.environ.get("LETTA_AGENT_ID")

class ChatRequest(BaseModel):
    user_id: str
    message: str

@app.get("/health")
def health():
    return {"ok": True, "agent_configured": bool(AGENT_ID)}

@app.post("/v1/chat")
def chat(req: ChatRequest):
    if not AGENT_ID:
        raise HTTPException(503, "LETTA_AGENT_ID is not configured")
    try:
        response = client.agents.messages.create(agent_id=AGENT_ID, input=req.message)
        messages = getattr(response, "messages", [])
        text = "\n".join(str(getattr(m, "content", "")) for m in messages if getattr(m, "content", None))
        return {"text": text}
    except Exception as exc:
        raise HTTPException(502, f"Agent backend error: {exc}")
