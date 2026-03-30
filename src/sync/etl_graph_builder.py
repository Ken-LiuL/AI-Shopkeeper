from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from typing import Any

import asyncpg
from neo4j import AsyncDriver

from src.agents.llm import MODEL_DEEPSEEK, call_tool

logger = logging.getLogger(__name__)

BATCH_SIZE = 500
DEFAULT_EMBEDDING_DIM = int(os.environ.get("PRODUCT_EMBEDDING_DIM", "1536"))

MEDICAL_SCENARIOS: dict[str, tuple[str, list[str]]] = {
    "血压": ("慢病管理", ["中老年", "高血压患者"]),
    "血糖": ("慢病管理", ["糖尿病患者"]),
    "体温": ("发热护理", ["婴幼儿家庭", "全人群"]),
    "口罩": ("防护", ["全人群"]),
    "制氧": ("呼吸护理", ["老年人", "COPD患者"]),
    "轮椅": ("康复辅助", ["行动不便者", "老年人"]),
    "拐杖": ("康复辅助", ["骨伤恢复期", "老年人"]),
    "雾化": ("呼吸治疗", ["支气管炎患者", "儿童"]),
    "血氧": ("健康监测", ["老年人", "慢性病患者"]),
    "助听": ("听力辅助", ["听力障碍者"]),
    "护腰": ("骨骼护理", ["腰椎病患者", "办公族"]),
    "护膝": ("骨骼护理", ["关节炎患者", "运动人群"]),
    "理疗": ("康复理疗", ["颈椎病患者", "腰椎病患者"]),
    "消毒": ("消毒清洁", ["医疗机构", "家庭"]),
    "纱布": ("伤口护理", ["外伤处理"]),
    "创可贴": ("伤口护理", ["全人群"]),
    "避孕": ("计生用品", ["成年人"]),
    "验孕": ("孕期护理", ["备孕女性"]),
}

_PRODUCT_SCENARIO_TOOL: dict[str, Any] = {
    "name": "infer_product_scenarios",
    "description": "批量推断医疗器械商品的场景与适用人群",
    "input_schema": {
        "type": "object",
        "properties": {
            "products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "scenario": {"type": "string"},
                        "populations": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["name", "scenario", "populations"],
                },
            }
        },
        "required": ["products"],
    },
}


def _quote_ident(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_embedding(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, list | tuple):
        parsed: list[float] = []
        for item in value:
            try:
                parsed.append(float(item))
            except (TypeError, ValueError):
                return None
        return parsed or None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [float(item) for item in parsed]
        except Exception:
            return None
    return None


def _chunked(items: list[dict[str, Any]], size: int = BATCH_SIZE) -> Iterable[list[dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def _table_exists(conn: asyncpg.Connection, table_name: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = $1
            )
            """,
            table_name,
        )
    )


async def _table_columns(conn: asyncpg.Connection, table_name: str) -> set[str]:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = $1
        """,
        table_name,
    )
    return {row["column_name"] for row in rows}


def _pick_column(columns: set[str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _normalize_season(value: Any) -> str | None:
    text = (_safe_text(value) or "").replace("季", "")
    if not text:
        return None
    if "春" in text:
        return "春"
    if "夏" in text:
        return "夏"
    if "秋" in text:
        return "秋"
    if "冬" in text:
        return "冬"
    return None


async def _fetch_products(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    columns = await _table_columns(conn, "qnh_products")

    product_id_col = _pick_column(columns, ["spu_id", "product_id", "id"])
    if not product_id_col:
        raise RuntimeError("qnh_products missing product id column (spu_id/product_id/id)")

    name_col = _pick_column(columns, ["title", "name", "product_name"])
    if not name_col:
        raise RuntimeError("qnh_products missing name column (title/name/product_name)")

    category_col = _pick_column(columns, ["category", "category_name"])
    price_col = _pick_column(columns, ["retail_price", "price"])
    cost_price_col = _pick_column(columns, ["cost_price", "purchase_price"])
    stock_col = _pick_column(columns, ["stock", "stock_quantity"])
    description_col = _pick_column(columns, ["description", "desc"])
    embedding_col = _pick_column(columns, ["embedding", "embedding_vector"])

    def expr(col: str | None, alias: str, cast: str | None = None) -> str:
        if col:
            ident = _quote_ident(col)
            if cast:
                return f"{ident}::{cast} AS {alias}"
            return f"{ident} AS {alias}"
        if cast:
            return f"NULL::{cast} AS {alias}"
        return f"NULL AS {alias}"

    sql = f"""
        SELECT
            {_quote_ident(product_id_col)}::text AS product_id,
            {_quote_ident(name_col)}::text AS name,
            {_quote_ident(name_col)}::text AS title,
            {expr(category_col, 'category', 'text')},
            {expr(price_col, 'price', 'numeric')},
            {expr(cost_price_col, 'cost_price', 'numeric')},
            {expr(stock_col, 'stock', 'bigint')},
            {expr(description_col, 'description', 'text')},
            {expr(embedding_col, 'embedding')}
        FROM qnh_products
        WHERE {_quote_ident(product_id_col)} IS NOT NULL
          AND {_quote_ident(name_col)} IS NOT NULL
    """

    rows = await conn.fetch(sql)
    products: list[dict[str, Any]] = []
    for row in rows:
        product_id = _safe_text(row["product_id"])
        name = _safe_text(row["name"])
        if not product_id or not name:
            continue
        products.append(
            {
                "product_id": product_id,
                "name": name,
                "title": _safe_text(row["title"]) or name,
                "category": _safe_text(row["category"]),
                "price": _to_float(row["price"]),
                "cost_price": _to_float(row["cost_price"]),
                "stock": _to_int(row["stock"]),
                "description": _safe_text(row["description"]),
                "embedding": _parse_embedding(row["embedding"]),
            }
        )
    return products


async def _fetch_categories(
    conn: asyncpg.Connection,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    categories: dict[str, dict[str, Any]] = {}
    hierarchy: dict[tuple[str, str], dict[str, str]] = {}

    if await _table_exists(conn, "category_mapping"):
        columns = await _table_columns(conn, "category_mapping")
        name_col = _pick_column(columns, ["meituan_category", "category_name", "category"])
        if name_col:
            rows = await conn.fetch(
                f"""
                SELECT DISTINCT {_quote_ident(name_col)}::text AS name
                FROM category_mapping
                WHERE {_quote_ident(name_col)} IS NOT NULL
                  AND {_quote_ident(name_col)} <> ''
                """
            )
            for row in rows:
                name = _safe_text(row["name"])
                if not name:
                    continue
                categories.setdefault(name, {"name": name, "level": None, "parent_name": None})

    if await _table_exists(conn, "store_category_tree"):
        columns = await _table_columns(conn, "store_category_tree")
        name_col = _pick_column(columns, ["category_name", "name"])
        level_col = _pick_column(columns, ["level", "category_level"])
        parent_name_col = _pick_column(columns, ["parent_name", "parent_category"])

        if name_col:
            level_expr = f"{_quote_ident(level_col)}::int AS level" if level_col else "NULL::int AS level"
            parent_expr = (
                f"{_quote_ident(parent_name_col)}::text AS parent_name"
                if parent_name_col
                else "NULL::text AS parent_name"
            )
            rows = await conn.fetch(
                f"""
                SELECT
                    {_quote_ident(name_col)}::text AS name,
                    {level_expr},
                    {parent_expr}
                FROM store_category_tree
                WHERE {_quote_ident(name_col)} IS NOT NULL
                  AND {_quote_ident(name_col)} <> ''
                """
            )
            for row in rows:
                name = _safe_text(row["name"])
                if not name:
                    continue
                level = _to_int(row["level"])
                parent_name = _safe_text(row["parent_name"])

                existing = categories.get(name)
                if not existing:
                    categories[name] = {
                        "name": name,
                        "level": level,
                        "parent_name": parent_name,
                    }
                else:
                    if existing.get("level") is None and level is not None:
                        existing["level"] = level
                    if existing.get("parent_name") is None and parent_name is not None:
                        existing["parent_name"] = parent_name

                if parent_name and parent_name != name:
                    categories.setdefault(
                        parent_name,
                        {"name": parent_name, "level": None, "parent_name": None},
                    )
                    hierarchy[(parent_name, name)] = {
                        "parent_name": parent_name,
                        "child_name": name,
                    }

    return list(categories.values()), list(hierarchy.values())


async def _fetch_product_associations(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    if not await _table_exists(conn, "product_associations"):
        return []
    columns = await _table_columns(conn, "product_associations")
    product_a_col = _pick_column(columns, ["product_a", "left_product", "product_id_a"])
    product_b_col = _pick_column(columns, ["product_b", "right_product", "product_id_b"])
    co_occurrence_col = _pick_column(columns, ["co_occurrence", "count", "weight"])
    if not (product_a_col and product_b_col):
        return []

    co_expr = (
        f"{_quote_ident(co_occurrence_col)}::bigint AS co_occurrence"
        if co_occurrence_col
        else "1::bigint AS co_occurrence"
    )
    rows = await conn.fetch(
        f"""
        SELECT
            {_quote_ident(product_a_col)}::text AS product_a,
            {_quote_ident(product_b_col)}::text AS product_b,
            {co_expr}
        FROM product_associations
        WHERE {_quote_ident(product_a_col)} IS NOT NULL
          AND {_quote_ident(product_b_col)} IS NOT NULL
        """
    )

    records: list[dict[str, Any]] = []
    for row in rows:
        product_a = _safe_text(row["product_a"])
        product_b = _safe_text(row["product_b"])
        if not product_a or not product_b or product_a == product_b:
            continue
        records.append(
            {
                "product_a": product_a,
                "product_b": product_b,
                "co_occurrence": _to_int(row["co_occurrence"]) or 1,
            }
        )
    return records


async def _fetch_competitor_links(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    if not (await _table_exists(conn, "competitor_products") and await _table_exists(conn, "qnh_products")):
        return []

    cp_cols = await _table_columns(conn, "competitor_products")
    q_cols = await _table_columns(conn, "qnh_products")

    cp_product_col = _pick_column(cp_cols, ["product_name", "name"])
    cp_store_col = _pick_column(cp_cols, ["store_name", "competitor_name", "store_id"])
    cp_price_col = _pick_column(cp_cols, ["price", "retail_price"])

    q_title_col = _pick_column(q_cols, ["title", "name", "product_name"])
    q_id_col = _pick_column(q_cols, ["spu_id", "product_id", "id"])

    if not (cp_product_col and cp_store_col and q_title_col and q_id_col):
        return []

    cp_price_expr = (
        f"cp.{_quote_ident(cp_price_col)}::numeric AS price"
        if cp_price_col
        else "NULL::numeric AS price"
    )

    rows = await conn.fetch(
        f"""
        SELECT
            cp.{_quote_ident(cp_product_col)}::text AS product_name,
            cp.{_quote_ident(cp_store_col)}::text AS store_name,
            {cp_price_expr},
            p.{_quote_ident(q_id_col)}::text AS product_id
        FROM competitor_products cp
        LEFT JOIN qnh_products p
          ON p.{_quote_ident(q_title_col)} ILIKE '%' || cp.{_quote_ident(cp_product_col)} || '%'
        WHERE cp.{_quote_ident(cp_product_col)} IS NOT NULL
          AND cp.{_quote_ident(cp_store_col)} IS NOT NULL
        """
    )

    records: list[dict[str, Any]] = []
    for row in rows:
        product_id = _safe_text(row["product_id"])
        product_name = _safe_text(row["product_name"])
        store_name = _safe_text(row["store_name"])
        if not product_id or not product_name or not store_name:
            continue
        records.append(
            {
                "product_id": product_id,
                "product_name": product_name,
                "store_name": store_name,
                "price": _to_float(row["price"]),
            }
        )
    return records


async def _fetch_brands(
    conn: asyncpg.Connection,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """从 qnh_products 提取品牌节点和 Product→Brand 关系。

    Returns:
        (brand_nodes, product_brand_links)
        brand_nodes: [{"name": "欧姆龙"}, ...]
        product_brand_links: [{"product_id": "...", "brand_name": "欧姆龙"}, ...]
    """
    columns = await _table_columns(conn, "qnh_products")
    brand_col = _pick_column(columns, ["brand", "brand_name"])
    product_id_col = _pick_column(columns, ["spu_id", "product_id", "id"])
    if not (brand_col and product_id_col):
        return [], []

    rows = await conn.fetch(
        f"""
        SELECT DISTINCT
            {_quote_ident(product_id_col)}::text AS product_id,
            {_quote_ident(brand_col)}::text AS brand_name
        FROM qnh_products
        WHERE {_quote_ident(brand_col)} IS NOT NULL
          AND {_quote_ident(brand_col)} <> ''
          AND {_quote_ident(product_id_col)} IS NOT NULL
        """
    )

    brands: dict[str, dict[str, str]] = {}
    links: list[dict[str, str]] = []
    for row in rows:
        product_id = _safe_text(row["product_id"])
        brand_name = _safe_text(row["brand_name"])
        if not product_id or not brand_name:
            continue
        brands.setdefault(brand_name, {"name": brand_name})
        links.append({"product_id": product_id, "brand_name": brand_name})

    return list(brands.values()), links


async def _fetch_symptoms_from_knowledge(
    conn: asyncpg.Connection,
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
]:
    """从 product_knowledge 提取 Symptom/Usage 节点及关系。

    Returns:
        (
            symptom_nodes,
            product_symptom_links,
            usage_nodes,
            product_usage_links,
        )
    """
    if not await _table_exists(conn, "product_knowledge"):
        return [], [], [], []

    columns = await _table_columns(conn, "product_knowledge")
    spu_id_col = _pick_column(columns, ["spu_id", "product_id", "id"])
    suitable_col = _pick_column(columns, ["suitable_for", "indications"])
    effects_col = _pick_column(columns, ["effects", "main_effects"])
    usage_col = _pick_column(columns, ["usage_instructions", "usage"])

    if not spu_id_col:
        return [], [], [], []

    def safe_col(col: str | None, alias: str) -> str:
        if col:
            return f"{_quote_ident(col)}::text AS {alias}"
        return f"NULL::text AS {alias}"

    def _split_phrases(text: str | None) -> list[str]:
        raw = _safe_text(text)
        if not raw:
            return []
        for sep in ("、", "，", ",", "；", ";", "。", "\n", "；", ":", "："):
            raw = raw.replace(sep, "|")
        seen_local: set[str] = set()
        out: list[str] = []
        for part in raw.split("|"):
            part = part.strip()
            if 2 <= len(part) <= 24 and part not in seen_local:
                seen_local.add(part)
                out.append(part)
        return out

    rows = await conn.fetch(
        f"""
        SELECT
            {_quote_ident(spu_id_col)}::text AS product_id,
            {safe_col(suitable_col, 'suitable_for')},
            {safe_col(effects_col, 'effects')},
            {safe_col(usage_col, 'usage_instructions')}
        FROM product_knowledge
        WHERE {_quote_ident(spu_id_col)} IS NOT NULL
        LIMIT 10000
        """
    )

    symptoms: dict[str, dict[str, str]] = {}
    symptom_links: list[dict[str, str]] = []
    usages: dict[str, dict[str, str]] = {}
    usage_links: list[dict[str, str]] = []

    for row in rows:
        product_id = _safe_text(row["product_id"])
        if not product_id:
            continue

        # Symptom 来源：suitable_for / effects
        symptom_seen: set[str] = set()
        symptom_text = "|".join(
            [
                _safe_text(row["suitable_for"]) or "",
                _safe_text(row["effects"]) or "",
            ]
        )
        for phrase in _split_phrases(symptom_text):
            if phrase in symptom_seen:
                continue
            symptom_seen.add(phrase)
            symptoms.setdefault(phrase, {"name": phrase, "description": ""})
            symptom_links.append({"product_id": product_id, "symptom_name": phrase})

        # Usage 来源：usage_instructions
        usage_seen: set[str] = set()
        for phrase in _split_phrases(row["usage_instructions"]):
            if phrase in usage_seen:
                continue
            usage_seen.add(phrase)
            usages.setdefault(phrase, {"name": phrase, "description": ""})
            usage_links.append({"product_id": product_id, "usage_name": phrase})

    return list(symptoms.values()), symptom_links, list(usages.values()), usage_links


async def _fetch_seasonality(conn: asyncpg.Connection) -> list[dict[str, str]]:
    if not await _table_exists(conn, "product_seasonality"):
        return []

    columns = await _table_columns(conn, "product_seasonality")
    name_col = _pick_column(columns, ["product_name", "name"])
    season_col = _pick_column(columns, ["seasonal_tag", "season"])
    if not (name_col and season_col):
        return []

    rows = await conn.fetch(
        f"""
        SELECT
            {_quote_ident(name_col)}::text AS product_name,
            {_quote_ident(season_col)}::text AS seasonal_tag
        FROM product_seasonality
        WHERE {_quote_ident(name_col)} IS NOT NULL
          AND {_quote_ident(season_col)} IS NOT NULL
        """
    )

    records: list[dict[str, str]] = []
    for row in rows:
        product_name = _safe_text(row["product_name"])
        season_name = _normalize_season(row["seasonal_tag"])
        if not product_name or not season_name:
            continue
        records.append({"product_name": product_name, "season_name": season_name})
    return records


async def _infer_product_scenarios(product_names: list[str]) -> dict[str, tuple[str, list[str]]]:
    names = [name.strip() for name in product_names if isinstance(name, str) and name.strip()]
    if not names:
        return {}

    # Keep order while de-duplicating to reduce LLM calls.
    unique_names = list(dict.fromkeys(names))
    inferred: dict[str, tuple[str, list[str]]] = {}

    for i in range(0, len(unique_names), 20):
        batch = unique_names[i : i + 20]
        prompt = (
            "你是医疗器械知识图谱助手。请为每个商品名推断一个最主要使用场景和适用人群。"
            "若不确定，请返回场景“通用护理”，人群至少包含“全人群”。\n"
            f"商品名列表：{json.dumps(batch, ensure_ascii=False)}"
        )
        try:
            result = await call_tool(
                prompt,
                _PRODUCT_SCENARIO_TOOL,
                model=MODEL_DEEPSEEK,
                trace_name="etl_graph_builder_infer_product_scenarios",
            )
            if not isinstance(result, dict):
                raise ValueError("LLM scenarios result is not dict")
            items = result.get("products")
            if not isinstance(items, list):
                raise ValueError("LLM scenarios products field is not list")
        except Exception as exc:
            logger.warning("Product scenarios LLM infer failed for batch size=%d: %s", len(batch), exc)
            continue

        batch_set = set(batch)
        for item in items:
            if not isinstance(item, dict):
                continue
            name = _safe_text(item.get("name"))
            scenario = _safe_text(item.get("scenario"))
            populations_raw = item.get("populations")

            if not name or name not in batch_set or not scenario:
                continue
            if not isinstance(populations_raw, list):
                populations_raw = []

            populations = [_safe_text(pop) for pop in populations_raw]
            populations = [pop for pop in populations if pop]
            if not populations:
                populations = ["全人群"]

            inferred[name] = (scenario, populations)

    return inferred


async def _infer_scenario_population(
    products: list[dict[str, Any]],
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
]:
    scenarios: dict[str, dict[str, str]] = {}
    populations: dict[str, dict[str, str]] = {}
    product_scenarios: dict[tuple[str, str], dict[str, str]] = {}
    product_populations: dict[tuple[str, str], dict[str, str]] = {}
    unmatched_products: list[tuple[str, str]] = []

    for product in products:
        product_id = product.get("product_id")
        title = (product.get("title") or product.get("name") or "").strip()
        if not product_id or not title:
            continue

        matched = False
        for keyword, (scenario_name, population_names) in MEDICAL_SCENARIOS.items():
            if keyword not in title:
                continue
            matched = True

            scenarios.setdefault(
                scenario_name,
                {
                    "name": scenario_name,
                    "description": f"由商品关键词“{keyword}”推断的使用场景",
                },
            )
            product_scenarios[(product_id, scenario_name)] = {
                "product_id": product_id,
                "scenario_name": scenario_name,
            }

            for pop_name in population_names:
                populations.setdefault(
                    pop_name,
                    {
                        "name": pop_name,
                        "description": f"由商品关键词“{keyword}”推断的适用人群",
                    },
                )
                product_populations[(product_id, pop_name)] = {
                    "product_id": product_id,
                    "population_name": pop_name,
                }

        if not matched:
            unmatched_products.append((str(product_id), title))

    if unmatched_products:
        unmatched_names = [title for _, title in unmatched_products]
        llm_mapping = await _infer_product_scenarios(unmatched_names)
        for product_id, title in unmatched_products:
            inferred = llm_mapping.get(title)
            if not inferred:
                continue
            scenario_name, population_names = inferred
            scenarios.setdefault(
                scenario_name,
                {
                    "name": scenario_name,
                    "description": "由LLM推断的使用场景",
                },
            )
            product_scenarios[(product_id, scenario_name)] = {
                "product_id": product_id,
                "scenario_name": scenario_name,
            }
            for pop_name in population_names:
                populations.setdefault(
                    pop_name,
                    {
                        "name": pop_name,
                        "description": "由LLM推断的适用人群",
                    },
                )
                product_populations[(product_id, pop_name)] = {
                    "product_id": product_id,
                    "population_name": pop_name,
                }

    return (
        list(scenarios.values()),
        list(populations.values()),
        list(product_scenarios.values()),
        list(product_populations.values()),
    )


async def _run_neo4j_batches(
    neo4j_driver: AsyncDriver,
    cypher: str,
    rows: list[dict[str, Any]],
) -> tuple[int, int]:
    nodes_created = 0
    relationships_created = 0

    if not rows:
        return nodes_created, relationships_created

    async with neo4j_driver.session() as session:
        for batch in _chunked(rows):
            result = await session.run(cypher, {"rows": batch})
            summary = await result.consume()
            counters = summary.counters
            nodes_created += counters.nodes_created
            relationships_created += counters.relationships_created

    return nodes_created, relationships_created


async def _run_neo4j_query(
    neo4j_driver: AsyncDriver,
    cypher: str,
    params: dict[str, Any] | None = None,
) -> tuple[int, int]:
    async with neo4j_driver.session() as session:
        result = await session.run(cypher, params or {})
        summary = await result.consume()
        counters = summary.counters
        return counters.nodes_created, counters.relationships_created


async def _ensure_indexes(neo4j_driver: AsyncDriver, errors: list[str]) -> tuple[int, int]:
    nodes_created = 0
    relationships_created = 0

    index_queries = [
        (
            """
            CREATE VECTOR INDEX product_embedding_index IF NOT EXISTS
            FOR (p:Product)
            ON (p.embedding)
            OPTIONS {indexConfig: {
                `vector.dimensions`: $embedding_dim,
                `vector.similarity_function`: 'cosine'
            }}
            """,
            {"embedding_dim": DEFAULT_EMBEDDING_DIM},
        ),
        (
            """
            CREATE FULLTEXT INDEX product_fulltext_index IF NOT EXISTS
            FOR (p:Product)
            ON EACH [p.name, p.title, p.category, p.description]
            """,
            None,
        ),
    ]

    for cypher, params in index_queries:
        try:
            n, r = await _run_neo4j_query(neo4j_driver, cypher, params)
            nodes_created += n
            relationships_created += r
        except Exception as exc:
            msg = f"index creation failed: {type(exc).__name__}: {exc}"
            logger.warning(msg)
            errors.append(msg)

    return nodes_created, relationships_created


async def run_graph_builder_etl(pg_pool: asyncpg.Pool, neo4j_driver: AsyncDriver) -> dict:
    """从 PostgreSQL 构建 Neo4j 知识图谱。

    Returns: {"nodes_created": N, "relationships_created": N, "errors": [...]}
    """
    result: dict[str, Any] = {
        "nodes_created": 0,
        "relationships_created": 0,
        "errors": [],
    }

    errors: list[str] = result["errors"]

    products: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    category_hierarchy: list[dict[str, str]] = []
    associations: list[dict[str, Any]] = []
    competitor_links: list[dict[str, Any]] = []
    seasonality: list[dict[str, str]] = []
    brand_nodes: list[dict[str, str]] = []
    product_brand_links: list[dict[str, str]] = []
    symptom_nodes: list[dict[str, str]] = []
    product_symptom_links: list[dict[str, str]] = []
    usage_nodes: list[dict[str, str]] = []
    product_usage_links: list[dict[str, str]] = []

    try:
        async with pg_pool.acquire() as conn:
            products = await _fetch_products(conn)
            categories, category_hierarchy = await _fetch_categories(conn)
            associations = await _fetch_product_associations(conn)
            competitor_links = await _fetch_competitor_links(conn)
            seasonality = await _fetch_seasonality(conn)
            brand_nodes, product_brand_links = await _fetch_brands(conn)
            (
                symptom_nodes,
                product_symptom_links,
                usage_nodes,
                product_usage_links,
            ) = await _fetch_symptoms_from_knowledge(conn)
    except Exception as exc:
        errors.append(f"postgres fetch failed: {type(exc).__name__}: {exc}")
        logger.exception("Graph builder ETL failed while fetching source data")
        return result

    scenario_nodes, population_nodes, product_scenarios, product_populations = (
        await _infer_scenario_population(products)
    )

    belongs_to_rows = [
        {"product_id": p["product_id"], "category_name": p["category"]}
        for p in products
        if p.get("product_id") and p.get("category")
    ]

    steps: list[tuple[str, str, list[dict[str, Any]] | None, dict[str, Any] | None]] = [
        (
            "ensure indexes",
            "",
            None,
            None,
        ),
        (
            "seed seasons",
            "UNWIND ['春', '夏', '秋', '冬'] AS name MERGE (:Season {name: name})",
            None,
            None,
        ),
        (
            "product nodes",
            """
            UNWIND $rows AS row
            MERGE (p:Product {product_id: row.product_id})
            SET p.name = row.name,
                p.title = coalesce(row.title, row.name),
                p.category = row.category,
                p.price = row.price,
                p.cost_price = row.cost_price,
                p.stock = row.stock,
                p.description = row.description
            FOREACH (_ IN CASE WHEN row.embedding IS NULL THEN [] ELSE [1] END |
                SET p.embedding = row.embedding
            )
            """,
            products,
            None,
        ),
        (
            "category nodes",
            """
            UNWIND $rows AS row
            MERGE (c:Category {name: row.name})
            SET c.level = row.level,
                c.parent_name = row.parent_name
            """,
            categories,
            None,
        ),
        (
            "category hierarchy",
            """
            UNWIND $rows AS row
            MATCH (parent:Category {name: row.parent_name})
            MATCH (child:Category {name: row.child_name})
            MERGE (parent)-[:PARENT_OF]->(child)
            """,
            category_hierarchy,
            None,
        ),
        (
            "belongs to",
            """
            UNWIND $rows AS row
            MATCH (p:Product {product_id: row.product_id})
            MATCH (c:Category {name: row.category_name})
            MERGE (p)-[:BELONGS_TO]->(c)
            """,
            belongs_to_rows,
            None,
        ),
        (
            "scenario nodes",
            """
            UNWIND $rows AS row
            MERGE (s:Scenario {name: row.name})
            SET s.description = row.description
            """,
            scenario_nodes,
            None,
        ),
        (
            "population nodes",
            """
            UNWIND $rows AS row
            MERGE (p:Population {name: row.name})
            SET p.description = row.description
            """,
            population_nodes,
            None,
        ),
        (
            "used in",
            """
            UNWIND $rows AS row
            MATCH (p:Product {product_id: row.product_id})
            MATCH (s:Scenario {name: row.scenario_name})
            MERGE (p)-[:USED_IN]->(s)
            """,
            product_scenarios,
            None,
        ),
        (
            "suitable for",
            """
            UNWIND $rows AS row
            MATCH (p:Product {product_id: row.product_id})
            MATCH (pop:Population {name: row.population_name})
            MERGE (p)-[:SUITABLE_FOR]->(pop)
            """,
            product_populations,
            None,
        ),
        (
            "often bought with",
            """
            UNWIND $rows AS row
            CALL {
              WITH row
              MATCH (a:Product)
              WHERE a.product_id = row.product_a
                 OR a.name = row.product_a
                 OR a.title = row.product_a
              RETURN a
              LIMIT 1
            }
            CALL {
              WITH row
              MATCH (b:Product)
              WHERE b.product_id = row.product_b
                 OR b.name = row.product_b
                 OR b.title = row.product_b
              RETURN b
              LIMIT 1
            }
            WITH row, a, b
            WHERE a.product_id <> b.product_id
            MERGE (a)-[r:OFTEN_BOUGHT_WITH]->(b)
            SET r.co_occurrence = toInteger(row.co_occurrence)
            MERGE (a)-[r2:RELATED_TO]->(b)
            SET r2.weight = toInteger(row.co_occurrence)
            """,
            associations,
            None,
        ),
        (
            "competes with",
            """
            UNWIND $rows AS row
            MATCH (p:Product {product_id: row.product_id})
            MERGE (c:Competitor {store_name: row.store_name, product_name: row.product_name})
            SET c.price = row.price
            MERGE (p)-[r:COMPETES_WITH]->(c)
            SET r.price_diff = coalesce(toFloat(p.price), 0.0) - coalesce(toFloat(row.price), 0.0)
            """,
            competitor_links,
            None,
        ),
        (
            "peaks in",
            """
            UNWIND $rows AS row
            CALL {
              WITH row
              MATCH (p:Product)
              WHERE p.name = row.product_name
                 OR p.title = row.product_name
                 OR p.name CONTAINS row.product_name
                 OR p.title CONTAINS row.product_name
              WITH p, row,
                   CASE WHEN p.name = row.product_name OR p.title = row.product_name THEN 0 ELSE 1 END AS score
              ORDER BY score ASC
              RETURN p
              LIMIT 1
            }
            MATCH (s:Season {name: row.season_name})
            MERGE (p)-[:PEAKS_IN]->(s)
            """,
            seasonality,
            None,
        ),
        # ── Brand 节点 ────────────────────────────────────────────────────
        (
            "brand nodes",
            """
            UNWIND $rows AS row
            MERGE (b:Brand {name: row.name})
            RETURN b.name AS brand
            """,
            brand_nodes,
            None,
        ),
        (
            "has brand",
            """
            UNWIND $rows AS row
            MATCH (p:Product {product_id: row.product_id})
            MATCH (b:Brand {name: row.brand_name})
            MERGE (p)-[:HAS_BRAND]->(b)
            """,
            product_brand_links,
            None,
        ),
        # ── Symptom/Usage 节点（来自 product_knowledge）──────────────────
        (
            "symptom nodes",
            """
            UNWIND $rows AS row
            MERGE (s:Symptom {name: row.name})
            SET s.description = coalesce(row.description, '')
            RETURN s.name AS symptom
            """,
            symptom_nodes,
            None,
        ),
        (
            "has symptom",
            """
            UNWIND $rows AS row
            MATCH (p:Product {product_id: row.product_id})
            MATCH (s:Symptom {name: row.symptom_name})
            MERGE (p)-[:HAS_SYMPTOM]->(s)
            """,
            product_symptom_links,
            None,
        ),
        (
            "usage nodes",
            """
            UNWIND $rows AS row
            MERGE (u:Usage {name: row.name})
            SET u.description = coalesce(row.description, '')
            RETURN u.name AS usage
            """,
            usage_nodes,
            None,
        ),
        (
            "has usage",
            """
            UNWIND $rows AS row
            MATCH (p:Product {product_id: row.product_id})
            MATCH (u:Usage {name: row.usage_name})
            MERGE (p)-[:HAS_USAGE]->(u)
            """,
            product_usage_links,
            None,
        ),
    ]

    # Indexes first
    n, r = await _ensure_indexes(neo4j_driver, errors)
    result["nodes_created"] += n
    result["relationships_created"] += r

    for step_name, cypher, rows, params in steps[1:]:
        try:
            if rows is None:
                n, r = await _run_neo4j_query(neo4j_driver, cypher, params)
            else:
                n, r = await _run_neo4j_batches(neo4j_driver, cypher, rows)
            result["nodes_created"] += n
            result["relationships_created"] += r
        except Exception as exc:
            msg = f"{step_name} failed: {type(exc).__name__}: {exc}"
            logger.exception(msg)
            errors.append(msg)

    logger.info(
        "Graph builder ETL done: nodes_created=%d relationships_created=%d errors=%d",
        result["nodes_created"],
        result["relationships_created"],
        len(errors),
    )
    return result
