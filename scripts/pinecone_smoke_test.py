from __future__ import annotations

import uuid

from app.stores.vector.pinecone_store import PineconeVectorStore


def run() -> None:
    tenant_id = "smoke-tenant"
    doc_id = "smoke-doc"
    vector_id = f"smoke-{uuid.uuid4()}"

    store = PineconeVectorStore()

    values = [0.01] * store.settings.pinecone_index_dimension
    upserted_count = store.upsert_vectors(
        tenant_id=tenant_id,
        doc_id=doc_id,
        vectors=[
            {
                "id": vector_id,
                "values": values,
                "metadata": {"source": "smoke-test", "chunk": 0},
            }
        ],
    )
    print(f"upserted_count={upserted_count}")

    query_result = store.query(tenant_id=tenant_id, doc_id=doc_id, vector=values, top_k=1)
    match_count = len(getattr(query_result, "matches", []) or [])
    print(f"match_count={match_count}")

    store.delete_by_doc_id(tenant_id=tenant_id, doc_id=doc_id)
    post_delete_result = store.query(tenant_id=tenant_id, doc_id=doc_id, vector=values, top_k=1)
    post_delete_match_count = len(getattr(post_delete_result, "matches", []) or [])
    print(f"post_delete_match_count={post_delete_match_count}")

    store.delete_by_tenant_id(tenant_id=tenant_id)
    print("tenant_cleanup=ok")


if __name__ == "__main__":
    run()
