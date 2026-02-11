"""全局 Skills 注册表 — 由 app startup 注入，LangGraph 节点通过此模块获取 skill 实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.skills.embedding import EmbeddingSkill
    from src.skills.neo4j_skill import Neo4jSkill
    from src.skills.reranker import RerankerSkill

_neo4j_skill: Optional["Neo4jSkill"] = None
_embedding_skill: Optional["EmbeddingSkill"] = None
_reranker_skill: Optional["RerankerSkill"] = None


def register_skills(
    neo4j: Optional["Neo4jSkill"] = None,
    embedding: Optional["EmbeddingSkill"] = None,
    reranker: Optional["RerankerSkill"] = None,
) -> None:
    """注册 skill 实例（在 app lifespan startup 中调用）。"""
    global _neo4j_skill, _embedding_skill, _reranker_skill
    if neo4j is not None:
        _neo4j_skill = neo4j
    if embedding is not None:
        _embedding_skill = embedding
    if reranker is not None:
        _reranker_skill = reranker


def get_neo4j() -> Optional["Neo4jSkill"]:
    return _neo4j_skill


def get_embedding() -> Optional["EmbeddingSkill"]:
    return _embedding_skill


def get_reranker() -> Optional["RerankerSkill"]:
    return _reranker_skill
