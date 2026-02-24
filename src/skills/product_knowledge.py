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
from typing import Any

import aiohttp

from .embedding import EmbeddingSkill

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_KEY = "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"
VISION_MODEL = "anthropic/claude-sonnet-4"


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
        """搜索商品知识库，返回最相关的商品信息。

        Args:
            query: 用户查询文本
            limit: 返回数量
            hybrid: 是否使用向量+全文混合检索

        Returns:
            [{"spu_id", "name", "category", "brand", "spec",
              "description", "image_text", "price", "score"}, ...]
        """
        if not self._pool:
            return []

        # Generate query embedding
        query_emb = self._embedding.embed(f"查询: {query}")
        emb_str = "[" + ",".join(str(x) for x in query_emb) + "]"

        if hybrid:
            # Hybrid: vector similarity + full-text search, RRF fusion
            rows = await self._pool.fetch(
                """
                WITH vector_results AS (
                    SELECT id, spu_id, name, category, brand, spec, description,
                           image_text, price, status, image_urls,
                           1 - (embedding <=> $1::vector) AS vec_score,
                           ROW_NUMBER() OVER (ORDER BY embedding <=> $1::vector) AS vec_rank
                    FROM product_knowledge
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> $1::vector
                    LIMIT $2 * 3
                ),
                fts_results AS (
                    SELECT id,
                           ts_rank(fts, plainto_tsquery('simple', $3)) AS fts_score,
                           ROW_NUMBER() OVER (
                               ORDER BY ts_rank(fts, plainto_tsquery('simple', $3)) DESC
                           ) AS fts_rank
                    FROM product_knowledge
                    WHERE fts @@ plainto_tsquery('simple', $3)
                    LIMIT $2 * 3
                )
                SELECT v.*, COALESCE(f.fts_score, 0) AS fts_score,
                       -- RRF fusion score
                       (1.0 / (60 + v.vec_rank)) +
                       (1.0 / (60 + COALESCE(f.fts_rank, 1000))) AS rrf_score
                FROM vector_results v
                LEFT JOIN fts_results f ON v.id = f.id
                ORDER BY rrf_score DESC
                LIMIT $2
                """,
                emb_str,
                limit,
                query,
            )
        else:
            rows = await self._pool.fetch(
                """
                SELECT spu_id, name, category, brand, spec, description,
                       image_text, price, status, image_urls,
                       1 - (embedding <=> $1::vector) AS vec_score
                FROM product_knowledge
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                emb_str,
                limit,
            )

        return [
            {
                "spu_id": r["spu_id"],
                "name": r["name"],
                "category": r.get("category", ""),
                "brand": r.get("brand", ""),
                "spec": r.get("spec", ""),
                "description": r.get("description", ""),
                "image_text": r.get("image_text", ""),
                "price": float(r["price"]) if r.get("price") else None,
                "status": r.get("status", ""),
                "image_urls": r.get("image_urls", []),
                "score": float(r.get("rrf_score", r.get("vec_score", 0))),
            }
            for r in rows
        ]

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

            # Upsert to product_knowledge
            for rec, emb in zip(records, embeddings, strict=True):
                try:
                    emb_str = "[" + ",".join(str(x) for x in emb) + "]"
                    await self._pool.execute(
                        """
                        INSERT INTO product_knowledge
                            (spu_id, sku_id, name, category, brand, spec,
                             description, image_text, combined_text, embedding,
                             image_urls, price, status, updated_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                                $10::vector, $11, $12, $13, now())
                        ON CONFLICT (spu_id, sku_id) DO UPDATE SET
                            name = EXCLUDED.name,
                            category = EXCLUDED.category,
                            brand = EXCLUDED.brand,
                            spec = EXCLUDED.spec,
                            description = EXCLUDED.description,
                            image_text = EXCLUDED.image_text,
                            combined_text = EXCLUDED.combined_text,
                            embedding = EXCLUDED.embedding,
                            image_urls = EXCLUDED.image_urls,
                            price = EXCLUDED.price,
                            status = EXCLUDED.status,
                            updated_at = now()
                        """,
                        rec["spu_id"],
                        rec["sku_id"],
                        rec["name"],
                        rec["category"],
                        rec["brand"],
                        rec["spec"],
                        rec["description"],
                        rec["image_text"],
                        rec["combined_text"],
                        emb_str,
                        rec["image_urls"],
                        rec["price"],
                        rec["status"],
                    )
                    updated += 1
                except Exception as e:
                    logger.error(f"Upsert failed for {rec['spu_id']}: {e}")
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
        async with aiohttp.ClientSession() as session:
            for url in image_urls:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            ct = resp.content_type or "image/jpeg"
                            b64 = base64.b64encode(data).decode()
                            image_contents.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{ct};base64,{b64}"},
                                }
                            )
                except Exception as e:
                    logger.debug(f"Image download failed {url}: {e}")

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
