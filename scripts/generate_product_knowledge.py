#!/usr/bin/env python3
"""
批量为商品生成知识库（product_knowledge 表）

用法:
    python scripts/generate_product_knowledge.py [OPTIONS]

选项:
    --limit N       处理商品数量上限，默认 50（避免一次烧太多 token）
    --batch-size N  每批调用 LLM 的商品数，默认 10
    --dry-run       只打印生成内容，不写入数据库
    --offset N      从第 N 个商品开始（配合断点续传手动调整）
    --model MODEL   使用的 LLM 模型（默认 deepseek）

示例:
    # 先试跑 5 个看看效果
    python scripts/generate_product_knowledge.py --limit 5 --dry-run

    # 正式跑前 50 个
    python scripts/generate_product_knowledge.py --limit 50

    # 从第 100 个开始跑 100 个
    python scripts/generate_product_knowledge.py --offset 100 --limit 100
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import asyncpg
import click

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.llm import MODEL_DEEPSEEK, call_tool
from src.db.postgres import init_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── LLM Tool Schema ────────────────────────────────────────────────────────

KNOWLEDGE_TOOL = {
    "name": "generate_product_knowledge",
    "description": "为医疗器械商品生成结构化知识库内容，供客服和选品 Agent 使用",
    "input_schema": {
        "type": "object",
        "properties": {
            "effects": {
                "type": "string",
                "description": "商品的主要功效和用途，200字以内，突出核心卖点和使用场景",
            },
            "suitable_for": {
                "type": "string",
                "description": "适用人群，说明哪些人群最适合使用，包括年龄、症状、健康状态等，150字以内",
            },
            "contraindications": {
                "type": "string",
                "description": "禁忌症和注意事项，列出不适合使用的情况、副作用和风险提示，150字以内",
            },
            "usage_instructions": {
                "type": "string",
                "description": "使用方法和注意事项，说明如何正确使用，包括剂量、频次、时机等，200字以内",
            },
            "faq": {
                "type": "array",
                "description": "3-5条常见问题及解答，覆盖用户最关心的问题",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "常见问题"},
                        "answer": {"type": "string", "description": "专业解答，100字以内"},
                    },
                    "required": ["question", "answer"],
                },
                "minItems": 3,
                "maxItems": 5,
            },
        },
        "required": ["effects", "suitable_for", "contraindications", "usage_instructions", "faq"],
    },
}

SYSTEM_PROMPT = """你是一位专业的医疗器械知识顾问，熟悉各类医疗器械和健康产品。
请根据商品信息，生成准确、专业、对用户友好的知识库内容。
注意：
1. 内容要基于商品本身特性，不要虚构不存在的功效
2. 禁忌症和注意事项要严谨，涉及安全问题不可省略
3. FAQ 要针对医疗器械购买和使用中的真实痛点
4. 语言简洁通俗，避免过度专业术语"""


# ─── 核心逻辑 ────────────────────────────────────────────────────────────────


def _build_product_prompt(product: dict[str, Any]) -> str:
    """构建单个商品的 LLM 提示词"""
    parts = [f"商品名称：{product['name']}"]
    if product.get("brand"):
        parts.append(f"品牌：{product['brand']}")
    if product.get("category"):
        parts.append(f"分类：{product['category']}")
    if product.get("spec"):
        parts.append(f"规格：{product['spec']}")
    if product.get("retail_price"):
        parts.append(f"参考价格：{product['retail_price']} 元")

    # extra 字段中可能有卖点/描述
    extra = product.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}

    if extra.get("selling_points"):
        parts.append(f"卖点：{extra['selling_points']}")
    if extra.get("description"):
        parts.append(f"商品描述：{extra['description'][:500]}")

    return "\n".join(parts)


async def fetch_products_to_process(
    pool: asyncpg.Pool,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """
    从 qnh_products 取出还没有 knowledge 的商品。
    断点续传：通过 LEFT JOIN 跳过已有记录。
    """
    query = """
        SELECT
            p.spu_id,
            p.sku_id,
            p.name,
            p.brand,
            p.category,
            p.spec,
            p.retail_price,
            p.image_url,
            p.status,
            p.extra
        FROM qnh_products p
        LEFT JOIN product_knowledge pk
            ON pk.spu_id = p.spu_id
            AND pk.sku_id = COALESCE(p.sku_id, '')
        WHERE pk.id IS NULL
          AND p.name IS NOT NULL
          AND p.name != ''
        ORDER BY p.id
        LIMIT $1 OFFSET $2
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, limit, offset)
    return [dict(r) for r in rows]


async def generate_knowledge_for_product(
    product: dict[str, Any],
    model: str,
) -> dict[str, Any] | None:
    """调用 LLM 为单个商品生成知识库内容。失败返回 None。"""
    prompt = _build_product_prompt(product)
    try:
        result = await call_tool(
            prompt=prompt,
            tool=KNOWLEDGE_TOOL,
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            trace_name="generate_product_knowledge",
            trace_metadata={"spu_id": product["spu_id"], "name": product["name"]},
        )
        return result
    except Exception as e:
        logger.warning(
            "LLM 调用失败，跳过商品 %s (%s): %s",
            product["spu_id"],
            product["name"][:30],
            e,
        )
        return None


def _build_combined_text(product: dict[str, Any], knowledge: dict[str, Any]) -> str:
    """合并商品基本信息 + LLM 生成内容，用于全文检索"""
    parts = [
        product["name"],
        product.get("brand") or "",
        product.get("category") or "",
        product.get("spec") or "",
        knowledge.get("effects") or "",
        knowledge.get("suitable_for") or "",
        knowledge.get("usage_instructions") or "",
    ]
    # 把 FAQ 也加进去
    for qa in knowledge.get("faq") or []:
        parts.append(qa.get("question") or "")
        parts.append(qa.get("answer") or "")
    return " ".join(p for p in parts if p)


async def upsert_product_knowledge(
    pool: asyncpg.Pool,
    product: dict[str, Any],
    knowledge: dict[str, Any],
) -> None:
    """将生成的知识写入 product_knowledge 表（ON CONFLICT DO UPDATE）"""
    spu_id = product["spu_id"]
    sku_id = product.get("sku_id") or ""
    combined_text = _build_combined_text(product, knowledge)

    # 将结构化知识存进 description 字段（JSON 格式），combined_text 用于检索
    description_json = json.dumps(
        {
            "effects": knowledge.get("effects"),
            "suitable_for": knowledge.get("suitable_for"),
            "contraindications": knowledge.get("contraindications"),
            "usage_instructions": knowledge.get("usage_instructions"),
            "faq": knowledge.get("faq"),
        },
        ensure_ascii=False,
    )

    query = """
        INSERT INTO product_knowledge (
            spu_id, sku_id, name, category, brand, spec,
            description, combined_text,
            image_urls, price, status,
            created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8,
            $9, $10, $11,
            NOW(), NOW()
        )
        ON CONFLICT (spu_id, sku_id) DO UPDATE SET
            name           = EXCLUDED.name,
            category       = EXCLUDED.category,
            brand          = EXCLUDED.brand,
            spec           = EXCLUDED.spec,
            description    = EXCLUDED.description,
            combined_text  = EXCLUDED.combined_text,
            image_urls     = EXCLUDED.image_urls,
            price          = EXCLUDED.price,
            status         = EXCLUDED.status,
            updated_at     = NOW()
    """

    image_urls = []
    if product.get("image_url"):
        image_urls = [product["image_url"]]

    async with pool.acquire() as conn:
        await conn.execute(
            query,
            spu_id,
            sku_id,
            product["name"],
            product.get("category") or "",
            product.get("brand") or "",
            product.get("spec") or "",
            description_json,
            combined_text,
            image_urls,
            product.get("retail_price"),
            product.get("status") or "",
        )


# ─── CLI ─────────────────────────────────────────────────────────────────────


@click.command()
@click.option("--limit", default=50, show_default=True, help="处理商品数量上限")
@click.option("--batch-size", default=10, show_default=True, help="每批并发处理的商品数")
@click.option("--offset", default=0, show_default=True, help="从第 N 个未处理商品开始")
@click.option("--model", default=MODEL_DEEPSEEK, show_default=True, help="LLM 模型名称")
@click.option("--dry-run", is_flag=True, help="只打印生成内容，不写入数据库")
def main(limit: int, batch_size: int, offset: int, model: str, dry_run: bool) -> None:
    """批量用 LLM 为商品生成知识库内容，写入 product_knowledge 表。"""
    asyncio.run(_async_main(limit, batch_size, offset, model, dry_run))


async def _async_main(
    limit: int,
    batch_size: int,
    offset: int,
    model: str,
    dry_run: bool,
) -> None:
    logger.info(
        "启动知识库生成 | limit=%d offset=%d batch_size=%d model=%s dry_run=%s",
        limit, offset, batch_size, model, dry_run,
    )

    pool = await init_pool()

    # 取出待处理商品
    products = await fetch_products_to_process(pool, limit, offset)
    total = len(products)
    if total == 0:
        logger.info("没有找到待处理商品（可能已全部生成，或 qnh_products 为空）")
        return

    logger.info("共找到 %d 个待处理商品，开始处理…", total)

    success_count = 0
    skip_count = 0

    # 按批次处理
    for batch_start in range(0, total, batch_size):
        batch = products[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        batch_total = (total + batch_size - 1) // batch_size
        logger.info(
            "── 批次 %d/%d（商品 %d-%d）──",
            batch_num, batch_total,
            batch_start + 1, min(batch_start + batch_size, total),
        )

        # 批次内串行（避免并发过高、token 浪费）
        for product in batch:
            name_short = product["name"][:40]
            logger.info("处理: %s [%s]", product["spu_id"], name_short)

            knowledge = await generate_knowledge_for_product(product, model)
            if knowledge is None:
                skip_count += 1
                continue

            if dry_run:
                logger.info(
                    "[DRY-RUN] 生成结果:\n%s",
                    json.dumps(knowledge, ensure_ascii=False, indent=2),
                )
                success_count += 1
                continue

            try:
                await upsert_product_knowledge(pool, product, knowledge)
                logger.info("✓ 写入成功: %s", name_short)
                success_count += 1
            except Exception as e:
                logger.error("写入 DB 失败 (%s): %s", product["spu_id"], e)
                skip_count += 1

        # 批次间短暂休眠，避免 rate limit
        if batch_start + batch_size < total:
            await asyncio.sleep(0.5)

    logger.info(
        "完成！成功 %d / 失败或跳过 %d / 总计 %d",
        success_count, skip_count, total,
    )


if __name__ == "__main__":
    main()
