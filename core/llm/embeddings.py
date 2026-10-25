"""Embeddings and reranking. All embedding calls go through here (CLAUDE.md rule 6).

Providers:
- local: ONNX models via fastembed, run on this machine. No key, no per-call cost. Models
  download once into MODEL_CACHE_DIR.
- voyage: hosted Voyage AI API (EMBEDDING_API_KEY / RERANK_API_KEY).
EMBEDDING_DIM must match the vector(...) columns; it is checked on every call.
"""

import asyncio
from functools import lru_cache
from typing import Any, Literal

import httpx

from core.config import get_settings

VOYAGE_URL = "https://api.voyageai.com/v1"
BATCH = 64

InputType = Literal["document", "query"]


class EmbeddingDimMismatch(Exception):
    pass


@lru_cache
def _local_embedder() -> Any:
    from fastembed import TextEmbedding

    s = get_settings()
    return TextEmbedding(model_name=s.embedding_model, cache_dir=s.model_cache_dir)


@lru_cache
def _local_reranker() -> Any:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    s = get_settings()
    return TextCrossEncoder(model_name=s.rerank_model, cache_dir=s.model_cache_dir)


def _local_embed(texts: list[str], input_type: InputType) -> list[list[float]]:
    model = _local_embedder()
    # query_embed adds the model's query instruction prefix (e.g. for BGE models).
    vectors = model.query_embed(texts) if input_type == "query" else model.passage_embed(texts)
    return [v.tolist() for v in vectors]


async def _voyage(path: str, body: dict[str, Any], key: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{VOYAGE_URL}/{path}", json=body, headers={"Authorization": f"Bearer {key}"}
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


async def embed(texts: list[str], input_type: InputType = "document") -> list[list[float]]:
    if not texts:
        return []
    s = get_settings()
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i : i + BATCH]
        if s.embedding_provider == "voyage":
            data = await _voyage(
                "embeddings",
                {
                    "input": batch,
                    "model": s.embedding_model,
                    "input_type": input_type,
                    "output_dimension": s.embedding_dim,
                },
                s.embedding_api_key.get_secret_value(),
            )
            out.extend(item["embedding"] for item in data["data"])
        else:
            out.extend(await asyncio.to_thread(_local_embed, batch, input_type))
    for v in out:
        if len(v) != s.embedding_dim:
            raise EmbeddingDimMismatch(f"got {len(v)} dims, EMBEDDING_DIM={s.embedding_dim}")
    return out


async def embed_one(text: str, input_type: InputType = "query") -> list[float]:
    return (await embed([text], input_type))[0]


async def rerank(query: str, documents: list[str]) -> list[float]:
    """Relevance score per document (same order). With provider 'none', returns zeros."""
    if not documents:
        return []
    s = get_settings()
    if s.rerank_provider == "none":
        return [0.0] * len(documents)
    if s.rerank_provider == "voyage":
        data = await _voyage(
            "rerank",
            {"query": query, "documents": documents, "model": s.rerank_model},
            s.rerank_api_key.get_secret_value(),
        )
        scores = [0.0] * len(documents)
        for item in data["data"]:
            scores[item["index"]] = float(item["relevance_score"])
        return scores
    return await asyncio.to_thread(
        lambda: [float(x) for x in _local_reranker().rerank(query, documents)]
    )


def to_pgvector(v: list[float]) -> str:
    """Literal for CAST(:v AS vector) in raw SQL."""
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"
