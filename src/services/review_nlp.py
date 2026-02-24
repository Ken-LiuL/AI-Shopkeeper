"""评价 NLP 分析服务 — 对同步的评价做情感分析、关键词提取、问题分类。

使用 LLM 进行批量分析，结果写入 qnh_review_analysis 表。
被 Alert Agent（差评预警）和 Selection Agent（选品负面信号）调用。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

pg = None  # lazy import to avoid circular/missing deps at import time


def _get_pg():
    global pg
    if pg is None:
        from src.db import postgres as _pg

        pg = _pg
    return pg


logger = logging.getLogger(__name__)


@dataclass
class ReviewAnalysis:
    review_id: str
    sentiment: str  # positive / neutral / negative
    sentiment_score: float  # -1.0 to 1.0
    keywords: list[str]
    issue_categories: list[str]  # 质量 / 物流 / 服务 / 包装 / 价格 / 其他
    summary: str


# LLM 分析 prompt
REVIEW_ANALYSIS_PROMPT = """你是一个电商评价分析专家。请分析以下评价，输出JSON格式结果。

评价列表:
{reviews}

对每条评价输出:
{{
  "review_id": "...",
  "sentiment": "positive|neutral|negative",
  "sentiment_score": -1.0到1.0的浮点数,
  "keywords": ["关键词1", "关键词2"],
  "issue_categories": ["质量","物流","服务","包装","价格"],  // 仅negative/neutral时提取
  "summary": "一句话摘要"
}}

只输出JSON数组，不要其他内容。"""


class ReviewNLPService:
    """评价NLP分析服务"""

    BATCH_SIZE = 20

    async def analyze_pending_reviews(self, limit: int = 200) -> list[ReviewAnalysis]:
        """分析尚未做过NLP的评价。"""
        pool = _get_pg().get_pool()

        # 获取未分析的评价
        rows = await pool.fetch(
            """
            SELECT r.review_id, r.content, r.rating
            FROM qnh_reviews r
            LEFT JOIN qnh_review_analysis a ON r.review_id = a.review_id
            WHERE a.review_id IS NULL
              AND r.content IS NOT NULL AND r.content != ''
            ORDER BY r.review_time DESC
            LIMIT $1
            """,
            limit,
        )

        if not rows:
            logger.info("No pending reviews to analyze")
            return []

        all_results: list[ReviewAnalysis] = []

        # 分批处理
        for i in range(0, len(rows), self.BATCH_SIZE):
            batch = rows[i : i + self.BATCH_SIZE]
            results = await self._analyze_batch(batch)
            all_results.extend(results)

            # 写入DB
            await self._save_results(pool, results)

        logger.info(f"Analyzed {len(all_results)} reviews")
        return all_results

    async def _analyze_batch(self, rows: list[Any]) -> list[ReviewAnalysis]:
        """用 LLM 分析一批评价。"""
        from src.agents.llm import MODEL_FLASH, _get_openai_client

        reviews_text = json.dumps(
            [
                {
                    "review_id": r["review_id"],
                    "content": r["content"],
                    "rating": r["rating"],
                }
                for r in rows
            ],
            ensure_ascii=False,
        )

        prompt = REVIEW_ANALYSIS_PROMPT.format(reviews=reviews_text)

        try:
            client = _get_openai_client()
            completion = await client.chat.completions.create(
                model=MODEL_FLASH,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            response = completion.choices[0].message.content or "[]"
            # 解析JSON
            results_raw = json.loads(response)
            if not isinstance(results_raw, list):
                results_raw = [results_raw]

            results = []
            for item in results_raw:
                results.append(
                    ReviewAnalysis(
                        review_id=item.get("review_id", ""),
                        sentiment=item.get("sentiment", "neutral"),
                        sentiment_score=float(item.get("sentiment_score", 0)),
                        keywords=item.get("keywords", []),
                        issue_categories=item.get("issue_categories", []),
                        summary=item.get("summary", ""),
                    )
                )
            return results
        except Exception as e:
            logger.error(f"LLM review analysis failed: {e}")
            # Fallback: 基于评分的简单分析
            results = []
            for r in rows:
                rating = r["rating"] or 5
                if rating >= 4:
                    sentiment = "positive"
                    score = 0.5
                elif rating >= 3:
                    sentiment = "neutral"
                    score = 0.0
                else:
                    sentiment = "negative"
                    score = -0.5
                results.append(
                    ReviewAnalysis(
                        review_id=r["review_id"],
                        sentiment=sentiment,
                        sentiment_score=score,
                        keywords=[],
                        issue_categories=[],
                        summary="",
                    )
                )
            return results

    async def _save_results(self, pool: Any, results: list[ReviewAnalysis]) -> None:
        """保存分析结果到DB。"""
        for r in results:
            try:
                await pool.execute(
                    """
                    INSERT INTO qnh_review_analysis
                        (review_id, sentiment, sentiment_score, keywords,
                         issue_categories, summary, analyzed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    ON CONFLICT (review_id) DO UPDATE SET
                        sentiment = EXCLUDED.sentiment,
                        sentiment_score = EXCLUDED.sentiment_score,
                        keywords = EXCLUDED.keywords,
                        issue_categories = EXCLUDED.issue_categories,
                        summary = EXCLUDED.summary,
                        analyzed_at = NOW()
                    """,
                    r.review_id,
                    r.sentiment,
                    r.sentiment_score,
                    json.dumps(r.keywords, ensure_ascii=False),
                    json.dumps(r.issue_categories, ensure_ascii=False),
                    r.summary,
                )
            except Exception as e:
                logger.warning(f"Failed to save review analysis for {r.review_id}: {e}")

    async def get_negative_reviews_by_sku(self, sku_id: str, days: int = 30) -> list[dict]:
        """获取指定SKU的差评分析结果。被选品Agent和Alert Agent调用。"""
        pool = _get_pg().get_pool()
        rows = await pool.fetch(
            """
            SELECT r.review_id, r.content, r.rating, r.review_time,
                   a.sentiment, a.sentiment_score, a.keywords, a.issue_categories, a.summary
            FROM qnh_reviews r
            JOIN qnh_review_analysis a ON r.review_id = a.review_id
            JOIN qnh_orders o ON r.order_id = o.order_id
            WHERE a.sentiment = 'negative'
              AND r.review_time >= CURRENT_DATE - $2 * INTERVAL '1 day'
              AND o.extra::jsonb @> $1::jsonb
            ORDER BY r.review_time DESC
            """,
            json.dumps({"skuId": sku_id}),
            days,
        )
        return [dict(r) for r in rows]

    async def get_issue_distribution(self, days: int = 30) -> dict[str, int]:
        """获取问题类别分布统计。"""
        pool = _get_pg().get_pool()
        rows = await pool.fetch(
            """
            SELECT category, COUNT(*) as cnt
            FROM qnh_review_analysis a
            JOIN qnh_reviews r ON a.review_id = r.review_id,
                 jsonb_array_elements_text(a.issue_categories::jsonb) AS category
            WHERE r.review_time >= CURRENT_DATE - $1 * INTERVAL '1 day'
              AND a.sentiment = 'negative'
            GROUP BY category
            ORDER BY cnt DESC
            """,
            days,
        )
        return {r["category"]: r["cnt"] for r in rows}
