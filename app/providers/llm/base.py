from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, Literal, TypedDict


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(slots=True)
class GenerationChunk:
    event: Literal["token", "done", "error"]
    delta: str = ""
    metadata: dict[str, Any] | None = None

    def to_sse_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": self.event,
            "data": self.delta,
        }
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


class LLMProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @abstractmethod
    def generate(
        self,
        messages: list[ChatMessage],
        streaming: bool = True,
    ) -> str | Iterable[GenerationChunk]:
        raise NotImplementedError
