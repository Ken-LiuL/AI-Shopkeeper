"""Product Knowledge Pipeline — build & search product knowledge base.

Pipeline:
  1. Read products from qnh_products
  2. Download product images → extract text via OpenRouter vision model
  3. Merge text (name + spec + description + image text) → generate embedding
  4. Store in pgvector (product_knowledge table)
  5. Provide search_product(query) for agent use

Uses:
  - OpenRouter API (OpenAI SDK format) for vision extraction
  - sentence-transformers (BGE-large-zh-v1.5) for embeddings
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import aiohttp

from .embedding import EmbeddingSkill

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
VISION_MODEL = os.environ.get("VISION_MODEL", "anthropic/claude-sonnet-4")


class ProductKnowledgeSkill:
    """商品知识库构建与检索。"""

    def __init__(self, pool: Any = None, embedding: EmbeddingSkill | None = None):
        self._pool = pool
        self._embedding = embedding or EmbeddingSkill()

    # ── Search (for agent use) ──────────────────────────────────────────

    async def search_product(
        self,
        query: str,
        limit: int = 5,
        hybrid: bool = True,
    ) -> list[dict[str, Any]]:
        """搜索商品知识库（SQL 全文检索）。

        Args:
            query: 用户查询文本
            limit: 返回数量
            hybrid: ignored (kept for API compat)

        Returns:
            [{"spu_id", "name", "category", "brand", "spec",
              "description", "image_text", "price", "score"}, ...]
        """
        from src.db import postgres as pg

        pool = self._pool or pg.get_pool()
        if pool is None:
            return []

        like_query = f"%{query}%"
        rows = await pool.fetch(
            """SELECT spu_id, name, category, brand, spec, retail_price, status, image_url
               FROM qnh_products
               WHERE name ILIKE $1 OR brand ILIKE $1 OR spec ILIKE $1 OR category ILIKE $1
               LIMIT $2""",
            like_query,
            limit,
        )

        items = []
        for r in rows:
            items.append(
                {
                    "spu_id": r["spu_id"],
                    "name": r["name"] or "",
                    "category": r["category"] or "",
                    "brand": r["brand"] or "",
                    "spec": r["spec"] or "",
                    "description": "",
                    "image_text": "",
                    "price": float(r["retail_price"]) if r["retail_price"] else None,
                    "status": r["status"] or "",
                    "image_urls": [r["image_url"]] if r.get("image_url") else [],
                    "score": 1.0,
                }
            )
        return items

    # ── Build Pipeline ──────────────────────────────────────────────────

    async def build_knowledge_base(
        self,
        batch_size: int = 10,
        extract_images: bool = True,
        max_images_per_product: int = 3,
    ) -> dict[str, int]:
        """从 qnh_products 构建商品知识库。

        Returns:
            {"total": N, "updated": N, "errors": N}
        """
        if not self._pool:
            return {"total": 0, "updated": 0, "errors": 0}

        # Fetch all products
        products = await self._pool.fetch(
            """
            SELECT spu_id, sku_id, name, category, brand, spec,
                   image_url, extra, retail_price, status
            FROM qnh_products
            ORDER BY spu_id
            """
        )

        total = len(products)
        updated = 0
        errors = 0

        # Process in batches
        for i in range(0, total, batch_size):
            batch = products[i : i + batch_size]
            texts = []
            records = []

            for prod in batch:
                extra = prod["extra"]
                if isinstance(extra, str):
                    try:
                        extra = json.loads(extra)
                    except Exception:
                        extra = {}
                extra = extra or {}

                description = extra.get("description", "")
                image_urls = self._collect_image_urls(prod["image_url"], extra)

                # Vision extraction
                image_text = ""
                if extract_images and image_urls:
                    image_text = await self._extract_image_text(
                        image_urls[:max_images_per_product],
                        prod["name"],
                    )

                # Combine text
                combined = self._build_combined_text(
                    name=prod["name"],
                    category=prod["category"] or "",
                    brand=prod["brand"] or "",
                    spec=prod["spec"] or "",
                    description=description,
                    image_text=image_text,
                )

                texts.append(combined)
                records.append(
                    {
                        "spu_id": prod["spu_id"],
                        "sku_id": prod["sku_id"] or "",
                        "name": prod["name"],
                        "category": prod["category"] or "",
                        "brand": prod["brand"] or "",
                        "spec": prod["spec"] or "",
                        "description": description,
                        "image_text": image_text,
                        "combined_text": combined,
                        "image_urls": image_urls,
                        "price": prod["retail_price"],
                        "status": prod["status"] or "",
                    }
                )

            # Batch embed
            try:
                embeddings = self._embedding.embed_batch(texts)
            except Exception as e:
                logger.error(f"Embedding batch failed: {e}")
                errors += len(batch)
                continue

            # Upsert to Chroma
            from src.db.chroma import get_collection

            collection = get_collection()
            for rec, emb in zip(records, embeddings, strict=True):
                try:
                    doc_id = f"{rec['spu_id']}_{rec['sku_id']}"
                    # Chroma metadata values must be str/int/float/bool
                    meta = {
                        "spu_id": rec["spu_id"],
                        "sku_id": rec["sku_id"],
                        "name": rec["name"],
                        "category": rec["category"],
                        "brand": rec["brand"],
                        "spec": rec["spec"],
                        "description": rec["description"][:1000] if rec["description"] else "",
                        "image_text": rec["image_text"][:1000] if rec["image_text"] else "",
                        "image_urls": json.dumps(rec["image_urls"]),
                        "price": float(rec["price"]) if rec["price"] else 0.0,
                        "status": rec["status"],
                    }
                    collection.upsert(
                        ids=[doc_id],
                        embeddings=[emb],
                        metadatas=[meta],
                        documents=[rec["combined_text"]],
                    )
                    updated += 1
                except Exception as e:
                    logger.error(f"Chroma upsert failed for {rec['spu_id']}: {e}")
                    errors += 1

            logger.info(f"Knowledge base: {i + len(batch)}/{total} processed")

        return {"total": total, "updated": updated, "errors": errors}

    # ── Vision extraction ───────────────────────────────────────────────

    async def _extract_image_text(
        self,
        image_urls: list[str],
        product_name: str,
    ) -> str:
        """Use OpenRouter vision model to extract text/parameters from product images."""
        if not image_urls:
            return ""

        # Build image content for vision API
        image_contents: list[dict[str, Any]] = []
        max_image_size = 5 * 1024 * 1024  # 5MB per image
        async with aiohttp.ClientSession() as session:
            for url in image_urls:
                for attempt in range(2):  # 1 retry
                    try:
                        async with session.get(
                            url, timeout=aiohttp.ClientTimeout(total=20)
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                if len(data) > max_image_size:
                                    logger.debug(
                                        f"Image too large ({len(data)} bytes), skipping: {url}"
                                    )
                                    break
                                if len(data) < 100:
                                    logger.debug(
                                        f"Image too small ({len(data)} bytes), skipping: {url}"
                                    )
                                    break
                                ct = resp.content_type or "image/jpeg"
                                b64 = base64.b64encode(data).decode()
                                image_contents.append(
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:{ct};base64,{b64}"},
                                    }
                                )
                                break  # success
                            elif resp.status in (404, 403):
                                logger.debug(f"Image {resp.status}: {url}")
                                break  # don't retry
                    except TimeoutError:
                        if attempt == 0:
                            logger.debug(f"Image download timeout, retrying: {url}")
                        else:
                            logger.debug(f"Image download timeout after retry: {url}")
                    except Exception as e:
                        logger.debug(f"Image download failed {url}: {e}")
                        break  # don't retry on unknown errors

        if not image_contents:
            return ""

        # Call OpenRouter vision API (OpenAI SDK format)
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"这是商品「{product_name}」的图片。"
                            "请提取图片中所有可见的文字信息，包括：\n"
                            "1. 商品名称、品牌\n"
                            "2. 规格参数（容量、重量、尺寸等）\n"
                            "3. 成分表、配料表\n"
                            "4. 使用说明、功效描述\n"
                            "5. 其他有用的文字信息\n\n"
                            "直接输出提取到的文字，不需要解释。如果没有文字，输出「无文字信息」。"
                        ),
                    },
                    *image_contents,
                ],
            }
        ]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{OPENROUTER_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": VISION_MODEL,
                        "messages": messages,
                        "max_tokens": 1000,
                    },
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result["choices"][0]["message"]["content"].strip()
                    else:
                        text = await resp.text()
                        logger.warning(f"Vision API error {resp.status}: {text[:200]}")
                        return ""
        except Exception as e:
            logger.warning(f"Vision extraction failed for {product_name}: {e}")
            return ""

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _collect_image_urls(main_image: str | None, extra: dict) -> list[str]:
        """Collect all image URLs from product data."""
        urls = []
        if main_image:
            urls.append(main_image)
        for key in ("imageUrls", "images", "picUrls"):
            imgs = extra.get(key, [])
            if isinstance(imgs, list):
                for u in imgs:
                    if isinstance(u, str) and u not in urls:
                        urls.append(u)
        return urls

    @staticmethod
    def _build_combined_text(
        name: str,
        category: str,
        brand: str,
        spec: str,
        description: str,
        image_text: str,
    ) -> str:
        """Build combined text for embedding."""
        parts = [f"商品名称: {name}"]
        if category:
            parts.append(f"分类: {category}")
        if brand:
            parts.append(f"品牌: {brand}")
        if spec:
            parts.append(f"规格: {spec}")
        if description:
            parts.append(f"描述: {description}")
        if image_text and image_text != "无文字信息":
            parts.append(f"图片信息: {image_text}")
        return "\n".join(parts)
