"""Embedding Skill — BGE-small-zh-v1.5 文本向量化。"""

from __future__ import annotations

import os


class EmbeddingSkill:
    """文本向量化技能，默认 BAAI/bge-small-zh-v1.5（轻量，~100MB）。"""

    def __init__(self, model_name: str | None = None, device: str = "cpu"):
        self._model_name = model_name or os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
        self._device = device
        self._model = None  # lazy load

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name, device=self._device)

    def embed(self, text: str) -> list[float]:
        """单条文本向量化。"""
        self._load_model()
        embedding = self._model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """批量文本向量化。"""
        self._load_model()
        embeddings = self._model.encode(texts, normalize_embeddings=True, batch_size=batch_size)
        return embeddings.tolist()

    @property
    def dimension(self) -> int:
        """向量维度（bge-small-zh-v1.5 = 512, bge-large-zh-v1.5 = 1024）。"""
        if "small" in self._model_name:
            return 512
        return 1024
