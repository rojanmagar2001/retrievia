from __future__ import annotations

from app.prompting.prompt_builder import build_prompt_package, validate_model_output
from app.retrieval.types import RetrievalItem, RetrievalResult


def _sample_retrieval_result() -> RetrievalResult:
    items = [
        RetrievalItem(
            citation_id="1",
            citation_tag="[1]",
            chunk_id="chunk-1",
            doc_id="doc-abc",
            score=0.91,
            content="RAG combines retrieval from a knowledge base with generation for grounded answers.",
            page=2,
            section="Overview",
            metadata={"title": "RAG Architecture Guide"},
        ),
        RetrievalItem(
            citation_id="2",
            citation_tag="[2]",
            chunk_id="chunk-2",
            doc_id="doc-abc",
            score=0.85,
            content="Citations should point to source passages used to support each claim.",
            page=5,
            section="Best Practices",
            metadata={"title": "RAG Architecture Guide"},
        ),
    ]
    return RetrievalResult(
        query="What is RAG and why citations matter?",
        items=items,
        retrieval_debug={"scores": [0.91, 0.85], "chunk_ids": ["chunk-1", "chunk-2"], "doc_ids": ["doc-abc"]},
    )


def run() -> None:
    retrieval_result = _sample_retrieval_result()
    package = build_prompt_package(retrieval_result)

    print("=== SYSTEM PROMPT ===")
    print(package.system_prompt)
    print("\n=== CONTEXT PROMPT ===")
    print(package.context_prompt)
    print("\n=== OUTPUT FORMAT SPEC ===")
    print(package.output_format_spec)

    sample_model_output = """Answer
RAG improves reliability by grounding generation in retrieved sources [1].

Citations
- [1] RAG Architecture Guide | doc-abc | page=2 | section=Overview
"""
    is_valid, errors = validate_model_output(sample_model_output)
    print("\n=== OUTPUT VALIDATION ===")
    print(f"valid={is_valid}")
    if errors:
        for err in errors:
            print(f"error={err}")


if __name__ == "__main__":
    run()
