"""
eval/conftest.py — AI Agent 评估框架共享 Fixtures

职责：
  - mock 数据库连接（asyncpg pool）
  - mock LLM 调用（Anthropic client）
  - 共享的 golden data 加载器
  - 所有评估文件可直接使用，无需真实外部服务
"""

from __future__ import annotations

import json
import sys
import types as _types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub 重依赖（与 tests/conftest.py 保持一致，防止 import 错误）
# ---------------------------------------------------------------------------
for _mod_name in ("neo4j", "prophet", "neuralprophet"):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _types.ModuleType(_mod_name)

if "aiohttp" not in sys.modules:
    _aiohttp = _types.ModuleType("aiohttp")
    _aiohttp.ClientSession = MagicMock  # type: ignore
    _aiohttp.ClientTimeout = MagicMock  # type: ignore
    _aiohttp.ClientError = Exception  # type: ignore
    sys.modules["aiohttp"] = _aiohttp

# ---------------------------------------------------------------------------
# Golden data 目录
# ---------------------------------------------------------------------------
GOLDEN_DATA_DIR = Path(__file__).parent / "golden_data"


def load_golden(filename: str) -> Any:
    """从 golden_data/ 目录加载 JSON 测试用例文件。"""
    path = GOLDEN_DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Golden data file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Fixtures: DB Pool (asyncpg)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg 连接池，支持 fetch / fetchrow / execute。"""
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.execute = AsyncMock(return_value="OK")

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value="OK")

    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    pool._conn = conn  # 方便测试直接调整返回值
    return pool


@pytest.fixture
def mock_db_pool_with_products(mock_db_pool):
    """预填充典型商品数据的 DB pool mock。"""
    products = [
        {
            "spu_id": "P100",
            "title": "鱼跃电子血压计",
            "retail_price": 189.0,
            "cost_price": 95.0,
            "stock": 50,
            "category": "血压计",
        },
        {
            "spu_id": "P200",
            "title": "欧姆龙体温计",
            "retail_price": 89.0,
            "cost_price": 42.0,
            "stock": 30,
            "category": "体温计",
        },
        {
            "spu_id": "P300",
            "title": "血糖仪套装",
            "retail_price": 299.0,
            "cost_price": 140.0,
            "stock": 15,
            "category": "血糖仪",
        },
    ]

    async def _fetchrow(query, *args):
        product_id = args[0] if args else None
        for p in products:
            if p["spu_id"] == product_id:
                return p
        return None

    async def _fetch(query, *args):
        return products

    mock_db_pool.fetchrow = AsyncMock(side_effect=_fetchrow)
    mock_db_pool.fetch = AsyncMock(side_effect=_fetch)
    mock_db_pool._conn.fetchrow = AsyncMock(side_effect=_fetchrow)
    mock_db_pool._conn.fetch = AsyncMock(side_effect=_fetch)
    mock_db_pool._products = products
    return mock_db_pool


# ---------------------------------------------------------------------------
# Fixtures: LLM (Anthropic)
# ---------------------------------------------------------------------------


def _make_text_response(text: str) -> MagicMock:
    """构造简单的文本回复 mock（stop_reason=end_turn）。"""
    block = MagicMock()
    block.type = "text"
    block.text = text

    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "end_turn"
    return resp


def _make_tool_use_response(tool_name: str, tool_input: dict) -> MagicMock:
    """构造 tool_use 格式的 mock 响应。"""
    block = MagicMock()
    block.type = "tool_use"
    block.id = "toolu_eval_001"
    block.name = tool_name
    block.input = tool_input

    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "tool_use"
    return resp


@pytest.fixture
def mock_llm_client():
    """通用 mock LLM 客户端（Anthropic）。默认返回空文本。"""
    client = AsyncMock()
    client.messages = AsyncMock()
    client.messages.create = AsyncMock(return_value=_make_text_response("mock reply"))
    client._make_text_response = _make_text_response
    client._make_tool_use_response = _make_tool_use_response
    return client


@pytest.fixture
def llm_response_factory():
    """工厂 fixture，可按需生成 text 或 tool_use 响应。"""
    return {
        "text": _make_text_response,
        "tool_use": _make_tool_use_response,
    }


# ---------------------------------------------------------------------------
# Fixtures: Golden data 加载
# ---------------------------------------------------------------------------


@pytest.fixture
def cs_test_cases():
    """加载客服评估用例。"""
    return load_golden("cs_test_cases.json")


@pytest.fixture
def selection_test_cases():
    """加载选品评估用例。"""
    return load_golden("selection_test_cases.json")


@pytest.fixture
def alert_test_cases():
    """加载预警评估用例。"""
    return load_golden("alert_test_cases.json")


# ---------------------------------------------------------------------------
# Fixtures: 评估指标收集器
# ---------------------------------------------------------------------------


@pytest.fixture
def metrics_collector():
    """轻量指标收集器，供测试内嵌使用。"""
    from tests.eval.eval_metrics import EvalMetrics

    return EvalMetrics()
