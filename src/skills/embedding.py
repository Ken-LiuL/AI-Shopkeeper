"""Embedding Skill — BGE-large-zh-v1.5 文本向量化。"""

from __future__ import annotations

from typing import List


class EmbeddingSkill:
    """文本向量化技能，使用 BAAI/bge-large-zh-v1.5。"""

    def __init__(self, model_name: str = "BAAI/bge-large-zh-v1.5", device: str = "cpu"):
        self._model_name = model_name
        self._device = device
        self._model = None  # lazy load

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name, device=self._device)

    def embed(self, text: str) -> List[float]:
        """单条文本向量化。"""
        self._load_model()
        embedding = self._model.encode(text, normalize_embeddings=True)  # type: ignore[union-attr]
        return embedding.tolist()

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """批量文本向量化。"""
        self._load_model()
        embeddings = self._model.encode(texts, normalize_embeddings=True, batch_size=batch_size)  # type: ignore[union-attr]
        return embeddings.tolist()

    @property
    def dimension(self) -> int:
        """向量维度（bge-large-zh-v1.5 = 1024）。"""
        return 1024
