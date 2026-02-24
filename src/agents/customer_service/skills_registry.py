"""全局 Skills 注册表 — 由 app startup 注入，LangGraph 节点通过此模块获取 skill 实例。

vector_store skill 可以是 Neo4jSkill 或 PgVectorSkill，接口兼容。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.skills.embedding import EmbeddingSkill
    from src.skills.reranker import RerankerSkill

_vector_store: Any | None = None  # Neo4jSkill | PgVectorSkill
_embedding_skill: EmbeddingSkill | None = None
_reranker_skill: RerankerSkill | None = None


def register_skills(
    neo4j: Any | None = None,
    embedding: EmbeddingSkill | None = None,
    reranker: RerankerSkill | None = None,
    *,
    vector_store: Any | None = None,
) -> None:
    """注册 skill 实例（在 app lifespan startup 中调用）。

    Args:
        neo4j: 向后兼容参数，等同于 vector_store。
        vector_store: 向量检索后端（Neo4jSkill 或 PgVectorSkill）。
        embedding: EmbeddingSkill 实例。
        reranker: RerankerSkill 实例。
    """
    global _vector_store, _embedding_skill, _reranker_skill
    # vector_store 优先，fallback 到 neo4j 参数（向后兼容）
    if vector_store is not None:
        _vector_store = vector_store
    elif neo4j is not None:
        _vector_store = neo4j
    if embedding is not None:
        _embedding_skill = embedding
    if reranker is not None:
        _reranker_skill = reranker


def get_neo4j() -> Any | None:
    """返回向量检索后端（Neo4jSkill 或 PgVectorSkill，接口兼容）。"""
    return _vector_store


def get_embedding() -> EmbeddingSkill | None:
    return _embedding_skill


def get_reranker() -> RerankerSkill | None:
    return _reranker_skill
