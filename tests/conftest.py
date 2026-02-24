"""共享 fixtures — mock 外部依赖"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Stub heavy dependencies that are not installed in test environment
# ---------------------------------------------------------------------------
import sys
import types as _types

for _mod_name in ("neo4j",):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _types.ModuleType(_mod_name)

# aiohttp stub with ClientSession + ClientTimeout
if "aiohttp" not in sys.modules:
    from unittest.mock import MagicMock as _MagicMock

    _aiohttp = _types.ModuleType("aiohttp")
    _aiohttp.ClientSession = _MagicMock  # type: ignore
    _aiohttp.ClientTimeout = _MagicMock  # type: ignore
    _aiohttp.ClientError = Exception  # type: ignore
    sys.modules["aiohttp"] = _aiohttp

# ---------------------------------------------------------------------------

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# helpers: 构造符合 Anthropic Tool Use 格式的 mock 响应
# ---------------------------------------------------------------------------


def _make_tool_use_response(tool_name: str, tool_input: dict[str, Any]):
    """构造一个 anthropic Message 对象（只保留 content block）"""
    block = MagicMock()
    block.type = "tool_use"
    block.id = "toolu_mock_001"
    block.name = tool_name
    block.input = tool_input

    response = MagicMock()
    response.content = [block]
    response.stop_reason = "tool_use"
    return response


# ---------------------------------------------------------------------------
# mock_anthropic_client
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_anthropic_client():
    """
    返回一个 AsyncMock Anthropic 客户端。
    调用方通过 side_effect / return_value 控制每次 messages.create 返回什么。
    """
    client = AsyncMock()
    client.messages = AsyncMock()
    client.messages.create = AsyncMock()
    return client


@pytest.fixture
def tool_response_factory():
    """工厂 fixture：按 tool_name + input 构造 mock 响应"""
    return _make_tool_use_response


# ---------------------------------------------------------------------------
# mock_db_pool (asyncpg)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_pool():
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    return pool


# ---------------------------------------------------------------------------
# mock_neo4j
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_neo4j():
    driver = MagicMock()
    session = AsyncMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    session.run = AsyncMock(return_value=MagicMock(data=MagicMock(return_value=[])))
    return driver


# ---------------------------------------------------------------------------
# mock_redis
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    r.exists = AsyncMock(return_value=0)
    return r


# ---------------------------------------------------------------------------
# mock_skills — 各 Skill 的 mock
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_skills():
    """返回一个 dict，key 为 skill 名，value 为 AsyncMock"""
    return {
        "actionbook": AsyncMock(),
        "neo4j_skill": AsyncMock(),
        "database": AsyncMock(),
        "embedding": AsyncMock(),
        "reranker": AsyncMock(),
        "prophet": AsyncMock(),
        "calculator": AsyncMock(),
        "notifier": AsyncMock(),
    }


# ---------------------------------------------------------------------------
# 预定义 Tool Use 响应数据
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_market_analysis():
    return {
        "analysis_summary": "医疗器械市场整体增长，血压计和血糖仪需求旺盛",
        "keywords": [
            {
                "keyword": "电子血压计",
                "search_volume": 5200,
                "heat_score": 85,
                "trend": "rising",
                "click_rate": 0.12,
                "conversion_rate": 0.08,
                "growth_rate": 0.15,
            },
            {
                "keyword": "血糖试纸",
                "search_volume": 3800,
                "heat_score": 72,
                "trend": "stable",
                "click_rate": 0.1,
                "conversion_rate": 0.06,
                "growth_rate": 0.05,
            },
        ],
        "products": [
            {
                "name": "鱼跃电子血压计",
                "monthly_sales": 320,
                "avg_price": 189,
                "category": "血压计",
                "rank": 1,
            },
            {
                "name": "欧姆龙血压计",
                "monthly_sales": 280,
                "avg_price": 259,
                "category": "血压计",
                "rank": 2,
            },
        ],
        "insights": ["血压计品类增速 15%", "试纸复购率高"],
    }


@pytest.fixture
def sample_competitor_analysis():
    return {
        "competitor_summary": {"total_competitors": 5, "high_threat_count": 2},
        "competitors": [
            {"name": "康复之家", "distance_km": 1.2, "rating": 4.8, "threat_level": "high"},
        ],
        "gap_products": [
            {
                "product_name": "制氧机",
                "competitor_count": 3,
                "avg_price": 2500,
                "estimated_monthly_sales": 15,
                "priority": "high",
            },
        ],
        "stockout_opportunities": [
            {"product_name": "N95口罩", "stockout_competitor_count": 2, "urgency": "urgent"},
        ],
    }


@pytest.fixture
def sample_inventory_analysis():
    return {
        "inventory_summary": {
            "total_sku": 120,
            "total_stock_value": 85000,
            "health_score": 72,
            "fast_moving_percent": 35,
            "dead_stock_percent": 8,
        },
        "covered_keywords": ["血压计", "体温计", "创可贴"],
        "problem_products": [
            {
                "product_id": "P001",
                "name": "某品牌雾化器",
                "status": "slow_moving",
                "days_since_last_sale": 45,
                "action": "促销清仓",
            },
        ],
    }


@pytest.fixture
def sample_seasonal_factors():
    return {
        "seasonal_summary": "冬季流感高发期，呼吸类和防护类产品需求上升",
        "factors": [
            {
                "event_name": "冬季流感",
                "event_type": "season",
                "impact_level": "high",
                "days_away": 0,
                "urgency": "urgent",
                "affected_products": ["口罩", "体温计"],
                "expected_demand_change": 0.3,
            },
        ],
        "weather_impact": {
            "summary": "寒潮来袭",
            "impact_level": "medium",
            "affected_products": ["暖宝宝", "电子体温计"],
        },
        "priority_products": [
            {"product": "N95口罩", "combined_impact": 85, "action": "stock_up"},
        ],
    }


@pytest.fixture
def sample_gap_opportunities():
    return {
        "gap_summary": {"total_opportunities": 3, "high_priority": 1, "medium_priority": 2},
        "opportunities": [
            {
                "rank": 1,
                "keyword": "制氧机",
                "priority": "high",
                "market_heat_score": 78,
                "competitor_coverage": 3,
                "stockout_opportunity": False,
                "reason": "市场需求大，竞品覆盖少",
            },
            {
                "rank": 2,
                "keyword": "雾化器",
                "priority": "medium",
                "market_heat_score": 55,
                "competitor_coverage": 1,
                "stockout_opportunity": True,
                "reason": "竞品缺货",
            },
        ],
    }


@pytest.fixture
def sample_supplier_evaluation():
    return {
        "keyword": "制氧机",
        "recommendation": {
            "best_channel": "alibaba",
            "reason": "资质齐全，价格优势",
            "confidence": 0.85,
        },
        "alibaba_evaluation": {
            "supplier_name": "鱼跃旗舰店",
            "qualification_score": 92,
            "unit_cost": 1200,
            "moq": 5,
            "delivery_days": 3,
            "risk_level": "low",
            "pros": ["品牌正品"],
            "cons": ["MOQ较高"],
            "url": "https://detail.1688.com/xxx",
        },
        "pdd_evaluation": {
            "shop_name": "医疗器械直营",
            "shop_score": 4.6,
            "unit_cost": 1350,
            "sales_count": 500,
            "delivery_days": 2,
            "pros": ["发货快"],
            "cons": ["价格略高"],
            "url": "https://mobile.yangkeduo.com/xxx",
        },
        "cost_comparison": {
            "alibaba_unit_cost": 1200,
            "pdd_unit_cost": 1350,
            "price_difference_percent": 12.5,
            "cheaper_channel": "alibaba",
        },
        "margin_analysis": {
            "market_price": 2500,
            "suggested_price": 2299,
            "gross_margin_percent": 47.8,
            "margin_grade": "excellent",
        },
        "final_suggestion": {
            "should_purchase": True,
            "channel": "alibaba",
            "suggested_quantity": 10,
            "estimated_investment": 12000,
            "url": "https://detail.1688.com/xxx",
        },
    }


@pytest.fixture
def sample_recommendations():
    return {
        "scoring_summary": {
            "total_evaluated": 3,
            "recommended_count": 2,
            "top_score": 87.5,
            "avg_score": 72.3,
        },
        "recommendations": [
            {
                "rank": 1,
                "keyword": "制氧机",
                "final_score": 87.5,
                "score_breakdown": {
                    "market_heat": 85,
                    "competition_gap": 90,
                    "supply_chain": 88,
                    "profit_margin": 92,
                    "category_synergy": 80,
                    "seasonal_fit": 75,
                },
                "recommendation_reason": "高毛利、竞争空白大",
                "key_strengths": ["毛利47.8%", "竞品少"],
                "key_risks": ["客单价高", "周转慢"],
                "purchase_channel": "alibaba",
                "purchase_url": "https://detail.1688.com/xxx",
                "suggested_quantity": 10,
                "suggested_price": 2299,
                "expected_margin": 47.8,
            },
        ],
        "reflection_notes": "经过自我反思，确认评分合理，已考虑季节性和竞争因素",
    }


@pytest.fixture
def sample_intent_product_inquiry():
    return {
        "intent": "product_inquiry",
        "confidence": 0.92,
        "extracted_entities": {"product_mentioned": "血压计", "target_population": "老人"},
        "sentiment": "neutral",
        "requires_human": False,
        "human_reason": "",
    }


@pytest.fixture
def sample_intent_greeting():
    return {
        "intent": "greeting",
        "confidence": 0.98,
        "extracted_entities": {},
        "sentiment": "positive",
        "requires_human": False,
        "human_reason": "",
    }


@pytest.fixture
def sample_intent_complaint():
    return {
        "intent": "complaint",
        "confidence": 0.88,
        "extracted_entities": {"product_mentioned": "体温计"},
        "sentiment": "negative",
        "requires_human": True,
        "human_reason": "用户投诉需人工处理",
    }


@pytest.fixture
def sample_reply():
    return {
        "reply_text": "亲，推荐这款鱼跃电子血压计，大屏显示适合老人使用~",
        "confidence": 0.85,
        "products_mentioned": [
            {"product_id": "P100", "name": "鱼跃电子血压计", "relevance": "直接匹配"},
        ],
        "upsell_suggestions": [
            {"product_id": "P101", "name": "血压计臂带", "price": 39.9, "reason": "配套使用"},
        ],
        "requires_human_review": False,
    }


@pytest.fixture
def sample_anomalies_found():
    return {
        "detection_summary": {
            "total_products_checked": 50,
            "anomalies_found": 2,
            "critical_count": 1,
            "warning_count": 1,
        },
        "anomalies": [
            {
                "anomaly_id": "A001",
                "product_id": "P100",
                "product_name": "鱼跃血压计",
                "anomaly_type": "sales_drop_prophet",
                "severity": "critical",
                "detection_method": "prophet",
                "metrics": {
                    "expected_value": 10,
                    "actual_value": 3,
                    "deviation_percent": -70,
                    "threshold": -30,
                },
                "description": "销量偏离预测值70%",
                "detected_at": "2026-02-11T10:00:00",
            },
            {
                "anomaly_id": "A002",
                "product_id": "P200",
                "product_name": "欧姆龙体温计",
                "anomaly_type": "price_gap",
                "severity": "warning",
                "detection_method": "rule",
                "metrics": {
                    "expected_value": 89,
                    "actual_value": 69,
                    "deviation_percent": -22,
                    "threshold": -15,
                },
                "description": "竞品降价超过阈值",
            },
        ],
    }


@pytest.fixture
def sample_anomalies_none():
    return {
        "detection_summary": {
            "total_products_checked": 50,
            "anomalies_found": 0,
            "critical_count": 0,
            "warning_count": 0,
        },
        "anomalies": [],
    }


@pytest.fixture
def sample_root_cause():
    return {
        "product_id": "P100",
        "anomaly_type": "sales_drop_prophet",
        "root_causes": [
            {
                "cause_type": "competitor",
                "cause_detail": "竞品大幅降价抢量",
                "confidence": 0.8,
                "evidence": ["竞品A降价20%", "竞品B上架同款"],
                "data_support": {
                    "metric": "competitor_price",
                    "before": 199,
                    "after": 159,
                    "change_percent": -20,
                },
            },
        ],
        "primary_cause": "竞品大幅降价抢量",
        "analysis_notes": "建议关注竞品定价策略",
    }


@pytest.fixture
def sample_action():
    return {
        "product_id": "P100",
        "recommended_actions": [
            {
                "action_type": "price_adjust",
                "priority": "P0",
                "action_detail": "将价格下调至179元，匹配竞品价格带",
                "parameters": {"target_price": 179, "discount_percent": 10},
                "expected_outcome": "预计恢复80%销量",
                "estimated_impact": {
                    "sales_change_percent": 80,
                    "margin_change_percent": -5,
                    "investment_required": 0,
                },
                "deadline": "2026-02-12T00:00:00",
            },
        ],
        "monitoring": {
            "metrics_to_watch": ["daily_sales", "conversion_rate"],
            "check_after_hours": 24,
            "success_criteria": "日销量恢复至8单以上",
        },
    }
