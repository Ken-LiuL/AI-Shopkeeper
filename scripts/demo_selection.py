"""
Selection Agent Demo
用 mock 数据 + 真实 Claude API 跑一次完整选品流程
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Setup path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Load .env
from dotenv import load_dotenv
load_dotenv(project_root / ".env")


async def main():
    print("=" * 70)
    print("🏪 Selection Agent Demo — 端到端选品流程")
    print("=" * 70)

    # 1. 初始化 Skills
    print("\n📦 [1/6] 初始化 Skills (mock 模式)...")
    from src.skills.factory import create_skills
    skills = create_skills(mode="mock")

    # 2. 采集 mock 数据（模拟 ActionBook 调用）
    print("📊 [2/6] 采集数据...")
    keywords = await skills.actionbook.meituan_keywords(store_id="STORE001")
    rankings = await skills.actionbook.meituan_rankings(store_id="STORE001")
    competitors = await skills.actionbook.competitor_stores(store_id="STORE001")
    competitor_products = await skills.actionbook.competitor_products(store_id="STORE001")

    print(f"   热搜词: {len(keywords)} 条")
    for kw in keywords:
        print(f"     - {kw.keyword} (搜索量:{kw.search_volume}, 增长:{kw.growth_rate:.0%})")
    print(f"   排行榜: {len(rankings)} 条")
    print(f"   竞品店铺: {len(competitors)} 家")

    # 准备 1688 和拼多多数据
    search_keywords = [kw.keyword for kw in keywords[:3]]
    alibaba_results = {}
    pdd_results = {}
    for kw_text in search_keywords:
        ali = await skills.actionbook.alibaba_search(keyword=kw_text, limit=2)
        pdd = await skills.actionbook.pdd_search(keyword=kw_text, limit=2)
        alibaba_results[kw_text] = json.dumps([p.model_dump() for p in ali], ensure_ascii=False)
        pdd_results[kw_text] = json.dumps([p.model_dump() for p in pdd], ensure_ascii=False)

    # 3. 构建初始 state
    initial_state = {
        "store_id": "STORE001",
        "categories": ["医疗器械", "家用健康"],
        "trigger_type": "manual",
        # 原始数据注入
        "raw_keywords_data": json.dumps([kw.model_dump() for kw in keywords], ensure_ascii=False),
        "raw_products_data": json.dumps([p.model_dump() for p in rankings], ensure_ascii=False),
        "raw_competitor_stores": json.dumps([c.model_dump() for c in competitors], ensure_ascii=False),
        "raw_competitor_products": json.dumps([p.model_dump() for p in competitor_products], ensure_ascii=False),
        "raw_stockouts": "暂无缺货数据",
        "raw_our_products": json.dumps([
            {"product_id": "P001", "name": "鱼跃电子血压计YE680A", "price": 199, "stock": 15, "monthly_sales": 45},
            {"product_id": "P002", "name": "欧姆龙体温计MC-246", "price": 39.9, "stock": 50, "monthly_sales": 120},
        ], ensure_ascii=False),
        "raw_sales_data": json.dumps([
            {"product_id": "P001", "daily_avg": 1.5, "trend": "stable"},
            {"product_id": "P002", "daily_avg": 4.0, "trend": "rising"},
        ], ensure_ascii=False),
        "raw_upcoming_events": "元宵节(3天后), 春季过敏季(已开始)",
        "raw_weather_forecast": "未来7天: 降温8°C，多云转小雨",
        "raw_trending_events": "流感季高峰期",
        "raw_alibaba_results": alibaba_results,
        "raw_pdd_results": pdd_results,
    }

    # 4. 编译并运行 Graph
    print("\n🔧 [3/6] 编译 Selection Graph...")
    from src.agents.selection.graph import compile_selection_graph
    graph = compile_selection_graph()

    print("🚀 [4/6] 运行选品流程 (调用 Claude API)...\n")
    print("-" * 70)

    result = await graph.ainvoke(initial_state)

    # 5. 打印各阶段输出
    print("-" * 70)
    print("\n📈 [5/6] 各阶段输出:\n")

    # Market Analysis
    market = result.get("market_analysis", {})
    print("── 市场分析 ──")
    print(f"   摘要: {market.get('analysis_summary', 'N/A')[:100]}...")
    kws = market.get("keywords", [])
    print(f"   热搜词: {len(kws)} 个")
    for k in kws[:3]:
        print(f"     {k.get('keyword', '?')} — 热度:{k.get('heat_score', 0)} 趋势:{k.get('trend', '?')}")

    # Competitor Analysis
    comp = result.get("competitor_analysis", {})
    print("\n── 竞品分析 ──")
    gaps = comp.get("gap_products", [])
    print(f"   竞品缺口商品: {len(gaps)} 个")
    for g in gaps[:3]:
        print(f"     {g.get('product_name', '?')} — 优先级:{g.get('priority', '?')}")

    # Inventory
    inv = result.get("inventory_analysis", {})
    print("\n── 库存分析 ──")
    inv_sum = inv.get("inventory_summary", {})
    print(f"   健康评分: {inv_sum.get('health_score', 'N/A')}")
    print(f"   已覆盖关键词: {inv.get('covered_keywords', [])}")

    # Seasonal
    season = result.get("seasonal_factors", {})
    print("\n── 季节性因素 ──")
    print(f"   摘要: {season.get('seasonal_summary', 'N/A')[:100]}...")

    # Gap
    gap = result.get("gap_opportunities", {})
    print("\n── 缺品机会 ──")
    opps = gap.get("opportunities", [])
    print(f"   机会总数: {gap.get('gap_summary', {}).get('total_opportunities', 0)}")
    for o in opps[:5]:
        print(f"     #{o.get('rank', '?')} {o.get('keyword', '?')} — 优先级:{o.get('priority', '?')} 热度:{o.get('market_heat_score', 0)}")

    # Supplier
    supps = result.get("supplier_evaluations", [])
    print(f"\n── 供应商评估 ({len(supps)} 个) ──")
    for s in supps[:3]:
        rec = s.get("recommendation", {})
        print(f"   {s.get('keyword', '?')} → 推荐渠道: {rec.get('best_channel', '?')}")

    # 6. 最终推荐 TOP 5
    print("\n" + "=" * 70)
    print("🏆 [6/6] 最终推荐 TOP 5:")
    print("=" * 70)

    recs = result.get("recommendations", {})
    rec_list = recs.get("recommendations", [])
    scoring = recs.get("scoring_summary", {})
    print(f"\n评估总数: {scoring.get('total_evaluated', 0)} | 推荐数: {scoring.get('recommended_count', 0)} | 最高分: {scoring.get('top_score', 0)}")

    for r in rec_list[:5]:
        print(f"\n  #{r.get('rank', '?')} 【{r.get('keyword', '?')}】 总分: {r.get('final_score', 0)}")
        bd = r.get("score_breakdown", {})
        print(f"     市场热度:{bd.get('market_heat', 0):.0f} | 竞争空位:{bd.get('competition_gap', 0):.0f} | 供应链:{bd.get('supply_chain', 0):.0f} | 利润:{bd.get('profit_margin', 0):.0f} | 协同:{bd.get('category_synergy', 0):.0f} | 季节:{bd.get('seasonal_fit', 0):.0f}")
        print(f"     理由: {r.get('recommendation_reason', 'N/A')[:80]}")
        print(f"     渠道: {r.get('purchase_channel', 'N/A')} | 建议价: ¥{r.get('suggested_price', 0)} | 毛利: {r.get('expected_margin', 0):.0%}" if r.get('expected_margin') else "")

    reflection = recs.get("reflection_notes", "")
    if reflection:
        print(f"\n📝 自我反思: {reflection[:200]}")

    # Errors
    errors = result.get("errors", [])
    if errors:
        print(f"\n⚠️ 错误: {errors}")

    print("\n✅ 选品流程完成!")


if __name__ == "__main__":
    asyncio.run(main())
