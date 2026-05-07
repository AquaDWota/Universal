from __future__ import annotations

from pathlib import Path
from typing import Any

from universal_interface.models import UnifiedDataItem


class VectorStore:
    """Thin Chroma wrapper — indexes unified items for cross-source search."""

    def __init__(
        self,
        persist_directory: Path,
        collection_name: str = "unified_items_minilm",
    ) -> None:
        import chromadb
        from chromadb.config import Settings
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        persist_directory.mkdir(parents=True, exist_ok=True)
        cache_folder = str(persist_directory / ".hf-cache")
        embed_fn = SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2",
            cache_folder=cache_folder,
        )
        self._client = chromadb.PersistentClient(
            path=str(persist_directory),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=embed_fn,
        )

    def upsert_items(self, items: list[UnifiedDataItem]) -> None:
        if not items:
            return
        ids = [i.id for i in items]
        documents = [f"{i.title}\n{i.content}".strip() for i in items]
        metadatas: list[dict[str, Any]] = []
        for i in items:
            md: dict[str, Any] = {
                "source": i.source,
                "type": i.type,
                "title": i.title,
                "author": i.author,
                "url": i.url,
            }
            if i.timestamp:
                md["timestamp"] = i.timestamp.isoformat()
            metadatas.append(md)
        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def query(self, text: str, n_results: int = 10) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        res = self._collection.query(query_texts=[text], n_results=n_results)
        out: list[dict[str, Any]] = []
        ids_list = res.get("ids") or []
        docs_list = res.get("documents") or []
        meta_list = res.get("metadatas") or []
        dist_list = res.get("distances") or []
        if not ids_list or not ids_list[0]:
            return []
        for idx, doc_id in enumerate(ids_list[0]):
            out.append(
                {
                    "id": doc_id,
                    "document": docs_list[0][idx] if docs_list and docs_list[0] else "",
                    "metadata": meta_list[0][idx] if meta_list and meta_list[0] else {},
                    "distance": dist_list[0][idx] if dist_list and dist_list[0] else None,
                }
            )
        return out
