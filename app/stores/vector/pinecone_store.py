from __future__ import annotations

import re
import time
from typing import Any

from pinecone import Pinecone, ServerlessSpec

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class PineconeVectorStore:
    """Pinecone vector store adapter for multi-tenant retrieval."""

    def __init__(
        self, settings: Settings | None = None, client: Pinecone | None = None
    ) -> None:
        self.settings = settings or get_settings()
        print("Pinecone Index Name:", self.settings.pinecone_index_name)
        if not self.settings.pinecone_api_key:
            raise ValueError("PINECONE_API_KEY is required")
        if not self.settings.pinecone_index_name:
            raise ValueError("PINECONE_INDEX_NAME is required")

        self.index_name = self.settings.pinecone_index_name
        self.client = client or Pinecone(api_key=self.settings.pinecone_api_key)
        self._index: Any | None = None

    def build_namespace(self, tenant_id: str) -> str:
        tenant = self._sanitize_namespace_part(tenant_id)
        prefix = self._sanitize_namespace_part(self.settings.pinecone_namespace_prefix)

        if self.settings.pinecone_namespace_strategy == "tenant":
            return f"{prefix}:{tenant}"

        env = self._sanitize_namespace_part(self.settings.app_env)
        return f"{prefix}:{env}:{tenant}"

    def ensure_index_exists(self, wait_timeout_seconds: int = 30) -> None:
        if self._index_exists():
            return

        try:
            self.client.create_index(
                name=self.index_name,
                dimension=self.settings.pinecone_index_dimension,
                metric=self.settings.pinecone_index_metric,
                spec=ServerlessSpec(
                    cloud=self.settings.pinecone_cloud,
                    region=self.settings.pinecone_region,
                ),
            )
            logger.info(
                "pinecone_index_create_started",
                index_name=self.index_name,
                dimension=self.settings.pinecone_index_dimension,
                metric=self.settings.pinecone_index_metric,
                cloud=self.settings.pinecone_cloud,
                region=self.settings.pinecone_region,
            )
        except Exception as exc:
            if "already exists" not in str(exc).lower():
                raise

        deadline = time.monotonic() + wait_timeout_seconds
        while time.monotonic() < deadline:
            description = self.client.describe_index(self.index_name)
            status = getattr(description, "status", None)
            ready = getattr(status, "ready", None)
            if ready is True:
                logger.info("pinecone_index_ready", index_name=self.index_name)
                return
            time.sleep(1)

        raise TimeoutError(
            f"Timed out waiting for Pinecone index '{self.index_name}' to become ready"
        )

    def upsert_vectors(
        self, tenant_id: str, vectors: list[dict[str, Any]], doc_id: str | None = None
    ) -> int:
        namespace = self.build_namespace(tenant_id)
        payload: list[dict[str, Any]] = []

        for vector in vectors:
            metadata = dict(vector.get("metadata") or {})
            metadata["tenant_id"] = tenant_id
            if doc_id:
                metadata.setdefault("doc_id", doc_id)

            payload.append(
                {
                    "id": vector["id"],
                    "values": vector["values"],
                    "metadata": metadata,
                }
            )

        if not payload:
            return 0

        response = self._get_index().upsert(vectors=payload, namespace=namespace)
        return int(getattr(response, "upserted_count", len(payload)))

    def query(
        self,
        tenant_id: str,
        vector: list[float],
        top_k: int = 10,
        doc_id: str | None = None,
        include_values: bool = False,
        include_metadata: bool = True,
    ) -> Any:
        namespace = self.build_namespace(tenant_id)
        metadata_filter: dict[str, dict[str, str]] = {"tenant_id": {"$eq": tenant_id}}
        if doc_id:
            metadata_filter["doc_id"] = {"$eq": doc_id}

        return self._get_index().query(
            namespace=namespace,
            vector=vector,
            top_k=top_k,
            include_values=include_values,
            include_metadata=include_metadata,
            filter=metadata_filter,
        )

    def delete_by_doc_id(self, tenant_id: str, doc_id: str) -> None:
        namespace = self.build_namespace(tenant_id)
        self._get_index().delete(
            namespace=namespace,
            filter={
                "tenant_id": {"$eq": tenant_id},
                "doc_id": {"$eq": doc_id},
            },
        )

    def delete_by_tenant_id(self, tenant_id: str) -> None:
        namespace = self.build_namespace(tenant_id)
        self._get_index().delete(namespace=namespace, delete_all=True)

    def _get_index(self) -> Any:
        if self._index is None:
            self.ensure_index_exists()
            self._index = self.client.Index(self.index_name)
        return self._index

    def _index_exists(self) -> bool:
        try:
            self.client.describe_index(self.index_name)
            return True
        except Exception as exc:
            message = str(exc).lower()
            if "not found" in message or "does not exist" in message:
                return False
            raise

    @staticmethod
    def _sanitize_namespace_part(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_-]", "-", value.strip())
        normalized = normalized.strip("-")
        if not normalized:
            raise ValueError("Namespace part cannot be empty")
        return normalized.lower()
