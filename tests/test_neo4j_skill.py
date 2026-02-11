"""Tests for Neo4j Skill — models and RRF merge."""

from __future__ import annotations

import pytest

from src.skills.neo4j_skill import (
    Neo4jSkill,
    VectorSearchResult,
    KeywordSearchResult,
    ProductGraph,
    RelatedProduct,
    Population,
)


# ---------------------------------------------------------------------------
# Pydantic Model Tests
# ---------------------------------------------------------------------------

class TestVectorSearchResult:
    """Tests for VectorSearchResult Pydantic model."""

    def test_create_with_required_fields(self):
        """Create result with required fields."""
        result = VectorSearchResult(
            id="P001",
            name="血压计",
            score=0.95,
        )
        assert result.id == "P001"
        assert result.name == "血压计"
        assert result.score == 0.95
        assert result.description == ""

    def test_create_with_all_fields(self):
        """Create result with all fields."""
        result = VectorSearchResult(
            id="P001",
            name="血压计",
            description="电子血压计适合老人使用",
            score=0.95,
        )
        assert result.description == "电子血压计适合老人使用"


class TestKeywordSearchResult:
    """Tests for KeywordSearchResult Pydantic model."""

    def test_create_result(self):
        """Create keyword search result."""
        result = KeywordSearchResult(
            id="P001",
            name="鱼跃血压计",
            description="精准测量",
            score=5.2,
        )
        assert result.id == "P001"
        assert result.score == 5.2


class TestProductGraph:
    """Tests for ProductGraph Pydantic model."""

    def test_create_basic(self):
        """Create basic product graph."""
        graph = ProductGraph(
            product_id="P001",
            name="血压计",
        )
        assert graph.product_id == "P001"
        assert graph.suitable_for == []
        assert graph.related_products == []

    def test_create_full(self):
        """Create full product graph."""
        graph = ProductGraph(
            product_id="P001",
            name="血压计",
            description="电子血压计",
            price=199.0,
            suitable_for=["老人", "高血压患者"],
            contraindicated_for=[{"name": "心脏起搏器患者", "reason": "电磁干扰"}],
            scenarios=["家用"],
            related_products=[{"id": "P002", "name": "臂带"}],
            faqs=[{"question": "如何使用?", "answer": "按开关键"}],
        )
        assert len(graph.suitable_for) == 2
        assert len(graph.contraindicated_for) == 1
        assert len(graph.faqs) == 1


class TestRelatedProduct:
    """Tests for RelatedProduct Pydantic model."""

    def test_create_related_product(self):
        """Create related product."""
        product = RelatedProduct(
            product_id="P002",
            name="血压计臂带",
            price=39.0,
            relation="ACCESSORY",
        )
        assert product.product_id == "P002"
        assert product.relation == "ACCESSORY"


class TestPopulation:
    """Tests for Population Pydantic model."""

    def test_create_population(self):
        """Create population."""
        pop = Population(
            name="老人",
            description="65岁以上",
        )
        assert pop.name == "老人"
        assert pop.description == "65岁以上"


# ---------------------------------------------------------------------------
# Neo4jSkill Instance Tests
# ---------------------------------------------------------------------------

class TestNeo4jSkillInit:
    """Tests for Neo4jSkill initialization."""

    def test_init_without_driver(self):
        """Initialize without driver."""
        skill = Neo4jSkill(driver=None)
        assert skill._driver is None

    def test_init_with_driver(self):
        """Initialize with driver."""
        mock_driver = object()
        skill = Neo4jSkill(driver=mock_driver)
        assert skill._driver is mock_driver


class TestNeo4jSkillNoDriver:
    """Tests for Neo4jSkill methods without driver."""

    async def test_vector_search_no_driver(self):
        """Vector search without driver returns empty."""
        skill = Neo4jSkill(driver=None)
        results = await skill.vector_search([0.1] * 1024)
        assert results == []

    async def test_keyword_search_no_driver(self):
        """Keyword search without driver returns empty."""
        skill = Neo4jSkill(driver=None)
        results = await skill.keyword_search(["test"])
        assert results == []

    async def test_get_product_graph_no_driver(self):
        """Get product graph without driver returns None."""
        skill = Neo4jSkill(driver=None)
        result = await skill.get_product_graph("P001")
        assert result is None

    async def test_get_suitable_population_no_driver(self):
        """Get suitable population without driver returns empty."""
        skill = Neo4jSkill(driver=None)
        results = await skill.get_suitable_population("P001")
        assert results == []

    async def test_get_related_products_no_driver(self):
        """Get related products without driver returns empty."""
        skill = Neo4jSkill(driver=None)
        results = await skill.get_related_products("P001")
        assert results == []

    async def test_add_product_no_driver(self):
        """Add product without driver returns False."""
        skill = Neo4jSkill(driver=None)
        result = await skill.add_product("P001", "Test")
        assert result is False

    async def test_add_relationship_no_driver(self):
        """Add relationship without driver returns False."""
        skill = Neo4jSkill(driver=None)
        result = await skill.add_relationship("P001", "P002", "TEST")
        assert result is False

    async def test_update_embedding_no_driver(self):
        """Update embedding without driver returns False."""
        skill = Neo4jSkill(driver=None)
        result = await skill.update_embedding("P001", [0.1] * 1024)
        assert result is False


# ---------------------------------------------------------------------------
# RRF Merge Tests
# ---------------------------------------------------------------------------

class TestRRFMerge:
    """Tests for _rrf_merge static method."""

    def test_rrf_merge_single_list(self):
        """RRF merge with single list preserves order."""
        vector_results = [
            VectorSearchResult(id="a", name="A", score=0.9),
            VectorSearchResult(id="b", name="B", score=0.8),
        ]
        keyword_results = []
        
        merged = Neo4jSkill._rrf_merge(vector_results, keyword_results)
        
        assert len(merged) == 2
        assert merged[0].id == "a"
        assert merged[1].id == "b"

    def test_rrf_merge_boosts_common_items(self):
        """RRF merge boosts items appearing in both lists."""
        vector_results = [
            VectorSearchResult(id="a", name="A", score=0.9),
            VectorSearchResult(id="b", name="B", score=0.8),
            VectorSearchResult(id="c", name="C", score=0.7),
        ]
        keyword_results = [
            KeywordSearchResult(id="b", name="B", score=5.0),
            KeywordSearchResult(id="d", name="D", score=4.0),
            KeywordSearchResult(id="a", name="A", score=3.0),
        ]
        
        merged = Neo4jSkill._rrf_merge(vector_results, keyword_results)
        
        # a and b appear in both lists, should be boosted
        ids = [r.id for r in merged]
        assert set(ids[:2]) == {"a", "b"}

    def test_rrf_merge_empty_lists(self):
        """RRF merge with empty lists returns empty."""
        merged = Neo4jSkill._rrf_merge([], [])
        assert merged == []

    def test_rrf_merge_preserves_data(self):
        """RRF merge preserves item data."""
        vector_results = [
            VectorSearchResult(id="a", name="Product A", description="Desc A", score=0.9),
        ]
        
        merged = Neo4jSkill._rrf_merge(vector_results, [])
        
        assert merged[0].name == "Product A"
        assert merged[0].description == "Desc A"

    def test_rrf_merge_updates_scores(self):
        """RRF merge updates scores based on RRF formula."""
        vector_results = [
            VectorSearchResult(id="a", name="A", score=0.9),
        ]
        keyword_results = [
            KeywordSearchResult(id="a", name="A", score=5.0),
        ]
        
        merged = Neo4jSkill._rrf_merge(vector_results, keyword_results)
        
        # Score should be 1/(60+1) + 1/(60+1) = 2/61
        expected_score = 2 / 61
        assert abs(merged[0].score - expected_score) < 0.001

    def test_rrf_merge_order_stability(self):
        """RRF merge produces stable ordering."""
        vector_results = [
            VectorSearchResult(id="a", name="A", score=0.9),
            VectorSearchResult(id="b", name="B", score=0.8),
        ]
        
        # Merge twice and verify same order
        merged1 = Neo4jSkill._rrf_merge(vector_results, [])
        merged2 = Neo4jSkill._rrf_merge(vector_results, [])
        
        assert [r.id for r in merged1] == [r.id for r in merged2]
