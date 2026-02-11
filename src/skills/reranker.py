"""Reranker Skill — BGE-reranker-v2-m3 精排。"""

from __future__ import annotations

from typing import Any, Dict, List


class RerankerSkill:
    """BGE Reranker 精排技能。"""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", device: str = "cpu"):
        self._model_name = model_name
        self._device = device
        self._model = None  # lazy load

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self._model_name, device=self._device)

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        text_field: str = "description",
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """对候选文档按相关性重排序。

        Args:
            query: 查询文本。
            documents: 候选文档列表。
            text_field: 用于比较的文本字段名。
            top_k: 返回前 k 个结果。

        Returns:
            按相关性降序排列的文档列表。
        """
        if not documents:
            return []
        self._load_model()
        pairs = [[query, doc.get(text_field, "")] for doc in documents]
        scores = self._model.predict(pairs)  # type: ignore[union-attr]
        ranked = sorted(zip(documents, scores), key=lambda x: -x[1])
        return [item[0] for item in ranked[:top_k]]
