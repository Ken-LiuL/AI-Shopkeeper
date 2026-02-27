"""Embedding Skill — OpenRouter API (text-embedding-3-small)."""

from __future__ import annotations

import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "openai/text-embedding-3-small")


class EmbeddingSkill:
    """文本向量化技能，通过 OpenRouter API 调用 text-embedding-3-small。"""

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or EMBEDDING_MODEL
        self._client = OpenAI(
            base_url=OPENROUTER_BASE,
            api_key=OPENROUTER_KEY,
        )

    def embed(self, text: str) -> list[float]:
        """单条文本向量化。"""
        resp = self._client.embeddings.create(
            model=self._model_name,
            input=text,
        )
        return resp.data[0].embedding

    def embed_batch(self, texts: list[str], batch_size: int = 50) -> list[list[float]]:
        """批量文本向量化。"""
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            resp = self._client.embeddings.create(
                model=self._model_name,
                input=chunk,
            )
            # Sort by index to ensure order
            sorted_data = sorted(resp.data, key=lambda x: x.index)
            all_embeddings.extend([d.embedding for d in sorted_data])
        return all_embeddings

    @property
    def dimension(self) -> int:
        return 1536
