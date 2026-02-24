"""Tests for src/agents/customer_service/skills_registry.py."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.agents.customer_service.skills_registry import (
    get_embedding,
    get_neo4j,
    get_reranker,
    register_skills,
)


class TestSkillsRegistry:
    def setup_method(self):
        """Reset global state before each test."""
        import src.agents.customer_service.skills_registry as mod

        mod._neo4j_skill = None
        mod._embedding_skill = None
        mod._reranker_skill = None

    def test_initially_none(self):
        assert get_neo4j() is None
        assert get_embedding() is None
        assert get_reranker() is None

    def test_register_all(self):
        neo4j = MagicMock()
        embedding = MagicMock()
        reranker = MagicMock()
        register_skills(neo4j=neo4j, embedding=embedding, reranker=reranker)
        assert get_neo4j() is neo4j
        assert get_embedding() is embedding
        assert get_reranker() is reranker

    def test_register_partial(self):
        neo4j = MagicMock()
        register_skills(neo4j=neo4j)
        assert get_neo4j() is neo4j
        assert get_embedding() is None

    def test_register_overwrites(self):
        first = MagicMock()
        second = MagicMock()
        register_skills(neo4j=first)
        register_skills(neo4j=second)
        assert get_neo4j() is second

    def test_register_none_does_not_overwrite(self):
        skill = MagicMock()
        register_skills(neo4j=skill)
        register_skills(neo4j=None)
        assert get_neo4j() is skill
