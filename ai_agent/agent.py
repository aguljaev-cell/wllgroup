import os
from openai import OpenAI
from memory import recall, remember

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

SYSTEM = """You are a helpful GPT agent. Use the supplied memory when relevant. If the user explicitly asks you to remember a non-sensitive preference or fact, save it. Do not store passwords, API keys, financial credentials, or other highly sensitive secrets."""


def respond(user_text: str) -> str:
    memories = recall()
    context = "\n".join(f"- {m}" for m in memories) or "(no saved memory)"
    prompt = f"Saved memory:\n{context}\n\nUser: {user_text}"
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5"),
        instructions=SYSTEM,
        input=prompt,
    )
    return response.output_text


if __name__ == "__main__":
    while True:
        text = input("You: ").strip()
        if text.lower() in {"exit", "quit"}:
            break
        print("GPT:", respond(text))
