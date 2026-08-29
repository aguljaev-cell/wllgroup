# WorldLogicLine Assistant

Production architecture for a persistent company AI assistant.

## Architecture
- Android client: `android_ai_assistant/`
- Stateful agent backend: `worldlogicline-assistant/backend/`
- PostgreSQL is the production persistence target.
- Agent memory is server-side, so replacing a phone does not erase company context.
- Android never contains provider API secrets.

## Memory model
1. Working memory: current conversation and active task.
2. Long-term semantic memory: durable facts, decisions, preferences and project context.
3. Episodic memory: important past conversations/events with timestamps.
4. Company knowledge: documents and indexed business material.
5. User scope: private employee memories separated from company/shared memories.

The backend is designed around a stateful-agent runtime such as Letta, which is specifically built for persistent agents and long-term memory. The Android app talks only to our backend API.

## First production milestone
- authenticated chat API
- persistent agent per employee
- shared company agent/knowledge scope
- memory search
- conversation history
- health check
- Docker/PostgreSQL deployment
