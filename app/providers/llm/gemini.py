from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from google import genai

from app.core.config import Settings, get_settings
from app.providers.llm.base import ChatMessage, GenerationChunk, LLMProvider


class GeminiProvider(LLMProvider):
    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required")
        self.client = client or genai.Client(api_key=self.settings.gemini_api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        models_api = getattr(self.client, "models", None)
        if models_api is None or not hasattr(models_api, "embed_content"):
            raise RuntimeError(
                "Gemini embeddings API is unavailable in the current SDK/runtime. "
                "Keep Gemini for generation and use Vertex AI Text Embeddings as the embedding backend."
            )

        response = models_api.embed_content(
            model=self.settings.gemini_embedding_model,
            contents=texts,
        )
        vectors = self._extract_embeddings(response)
        if not vectors:
            raise RuntimeError("Gemini embeddings response did not contain vectors")
        return vectors

    def generate(
        self,
        messages: list[ChatMessage],
        streaming: bool = True,
    ) -> str | Iterable[GenerationChunk]:
        if not messages:
            raise ValueError("messages cannot be empty")

        prompt = self._to_prompt(messages)

        if not streaming:
            response = self.client.models.generate_content(
                model=self.settings.gemini_model,
                contents=prompt,
            )
            return self._extract_text(response)

        return self._stream_generate(prompt)

    def _stream_generate(self, prompt: str) -> Iterator[GenerationChunk]:
        stream = self.client.models.generate_content_stream(
            model=self.settings.gemini_model,
            contents=prompt,
        )
        for chunk in stream:
            text = self._extract_text(chunk)
            if text:
                yield GenerationChunk(event="token", delta=text)
        yield GenerationChunk(event="done", delta="")

    @staticmethod
    def _to_prompt(messages: list[ChatMessage]) -> str:
        prompt_parts: list[str] = []
        for msg in messages:
            role = msg["role"].upper()
            content = msg["content"].strip()
            prompt_parts.append(f"{role}: {content}")
        return "\n\n".join(prompt_parts)

    @staticmethod
    def _extract_text(response: Any) -> str:
        text = getattr(response, "text", None)
        if isinstance(text, str) and text:
            return text

        if isinstance(response, dict):
            dict_text = response.get("text")
            if isinstance(dict_text, str):
                return dict_text

        return ""

    @staticmethod
    def _extract_embeddings(response: Any) -> list[list[float]]:
        raw_embeddings = getattr(response, "embeddings", None)
        if raw_embeddings is None and isinstance(response, dict):
            raw_embeddings = response.get("embeddings", None)

        if not raw_embeddings:
            return []

        vectors: list[list[float]] = []
        for entry in raw_embeddings:
            values = getattr(entry, "values", None)
            if values is None and isinstance(entry, dict):
                values = entry.get("values")
            if values:
                vectors.append([float(x) for x in values])
        return vectors
