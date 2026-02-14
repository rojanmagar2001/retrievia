from __future__ import annotations

from app.providers.llm.base import ChatMessage
from app.providers.llm.gemini import GeminiProvider


def run() -> None:
    provider = GeminiProvider()

    embeddings = provider.embed(["Retrievia smoke test.", "Gemini embeddings check."])
    print(f"embedding_count={len(embeddings)}")
    print(f"embedding_dimension={len(embeddings[0]) if embeddings else 0}")

    messages: list[ChatMessage] = [
        {
            "role": "system",
            "content": "You are a concise assistant. Respond in one sentence.",
        },
        {
            "role": "user",
            "content": "What is a retrieval augmented generation system?",
        },
    ]

    non_stream = provider.generate(messages=messages, streaming=False)
    print(f"generate_non_stream={str(non_stream).strip()}")

    stream = provider.generate(messages=messages, streaming=True)
    streamed_text_parts: list[str] = []
    token_events = 0
    for chunk in stream:
        if chunk.event == "token":
            token_events += 1
            streamed_text_parts.append(chunk.delta)
    print(f"stream_token_events={token_events}")
    print(f"generate_stream_text={''.join(streamed_text_parts).strip()}")


if __name__ == "__main__":
    run()
