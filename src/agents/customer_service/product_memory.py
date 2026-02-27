"""
商品内存搜索模块
启动时加载商品 + embedding 到内存，运行时纯内存 cosine similarity 搜索
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


class ProductMemory:
    """商品内存搜索引擎"""

    def __init__(self):
        self.products: list[dict[str, Any]] = []
        self.loaded = False

    async def load_products(self, pool) -> None:
        """从数据库加载所有商品+embedding到内存"""
        if self.loaded:
            return

        try:
            # 从 qnh_products 表加载商品基础信息和 embedding
            rows = await pool.fetch("""
                SELECT
                    spu_id, name, category, brand, spec, retail_price as price,
                    extra->>'description' as description,
                    extra->>'image_text' as image_text,
                    status, extra->>'stock' as stock,
                    embedding
                FROM qnh_products
                WHERE status != 'disabled'
                ORDER BY retail_price DESC NULLS LAST
                LIMIT 2000
            """)

            self.products = []
            for row in rows:
                product = {
                    "id": row["spu_id"],
                    "name": row["name"] or "",
                    "category": row["category"] or "",
                    "brand": row["brand"] or "",
                    "spec": row["spec"] or "",
                    "price": float(row["price"] or 0),
                    "description": row["description"] or "",
                    "image_text": row["image_text"] or "",
                    "status": row["status"] or "",
                    "stock": row["stock"] or 0,
                    "embedding": (
                        json.loads(row["embedding"])
                        if isinstance(row["embedding"], str)
                        else row["embedding"]
                    )  # 1536维的embedding列表
                }

                # 如果没有 embedding，生成搜索文本用于fallback
                if not product["embedding"]:
                    search_text = " ".join([
                        product["name"],
                        product["category"],
                        product["brand"],
                        product["spec"],
                        product["description"]
                    ]).strip()
                    product["search_text"] = search_text.lower()

                self.products.append(product)

            logger.info(f"Loaded {len(self.products)} products to memory")
            self.loaded = True

        except Exception as e:
            logger.error(f"Failed to load products to memory: {e}")
            self.products = []

    def cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """计算两个向量的余弦相似度"""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2, strict=True))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(a * a for a in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    async def search_products(
        self,
        query_embedding: list[float] | None = None,
        query_text: str = "",
        top_k: int = 5
    ) -> list[dict[str, Any]]:
        """搜索商品 - 优先embedding，fallback到关键词匹配"""
        if not self.loaded or not self.products:
            return []

        results = []

        # 如果有 query_embedding，使用向量相似度搜索
        if query_embedding:
            for product in self.products:
                if product["embedding"]:
                    similarity = self.cosine_similarity(query_embedding, product["embedding"])
                    if similarity > 0.1:  # 过滤低相似度结果
                        result = product.copy()
                        result["score"] = similarity
                        results.append(result)

            # 按相似度降序排序
            results.sort(key=lambda x: x["score"], reverse=True)

        # 如果没有向量结果且有查询文本，使用关键词fallback
        if not results and query_text:
            query_lower = query_text.lower()
            query_words = query_lower.split()

            for product in self.products:
                search_text = product.get("search_text") or ""
                if not search_text:
                    # 动态生成搜索文本
                    search_text = " ".join([
                        product["name"],
                        product["category"],
                        product["brand"],
                        product["spec"],
                        product["description"]
                    ]).strip().lower()

                # 计算关键词匹配分数
                score = 0.0
                for word in query_words:
                    if word in search_text:
                        score += 1.0

                # 完整匹配加分
                if query_lower in search_text:
                    score += 2.0

                if score > 0:
                    result = product.copy()
                    result["score"] = score / len(query_words)  # 标准化分数
                    results.append(result)

            # 按关键词分数降序排序
            results.sort(key=lambda x: x["score"], reverse=True)

        # 返回前 top_k 个结果，格式化输出
        top_results = results[:top_k]
        formatted_results = []

        for result in top_results:
            formatted = {
                "id": result["id"],
                "name": result["name"],
                "category": result["category"],
                "brand": result["brand"],
                "price": result["price"],
                "score": round(result["score"], 3),
                "description": f"【{result['category']}】{result['brand']} {result['name']}"
            }

            # 添加规格信息
            if result["spec"]:
                formatted["description"] += f" | 规格：{result['spec']}"

            # 添加价格信息
            if result["price"] > 0:
                formatted["description"] += f" | 价格：¥{result['price']:.1f}"

            formatted_results.append(formatted)

        return formatted_results


# 全局单例
_product_memory: ProductMemory | None = None


def get_product_memory() -> ProductMemory:
    """获取全局商品内存实例"""
    global _product_memory
    if _product_memory is None:
        _product_memory = ProductMemory()
    return _product_memory


async def init_product_memory(pool) -> None:
    """初始化商品内存（在应用启动时调用）"""
    product_memory = get_product_memory()
    await product_memory.load_products(pool)
