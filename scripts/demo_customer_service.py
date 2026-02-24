"""
CustomerService Agent Demo
模拟几轮客服对话
"""

import asyncio
import sys
from pathlib import Path

# Setup path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Load .env
from dotenv import load_dotenv

load_dotenv(project_root / ".env")


# ── Mock data injection for search nodes ─────────────────────────────────────


def _patch_search_nodes():
    """
    Patch hybrid_search, reranker, and graphrag nodes to use mock skills
    instead of requiring real Neo4j/Embedding/Reranker services.
    """
    from src.skills.factory import create_skills

    skills = create_skills(mode="mock")

    import src.agents.customer_service.nodes as cs_nodes

    # Save originals
    _orig_hybrid = cs_nodes.hybrid_search_node
    _orig_rerank = cs_nodes.reranker_node
    _orig_graphrag = cs_nodes.graphrag_node

    async def patched_hybrid_search(state):
        """使用 mock skills 的混合检索"""
        intent_data = state.get("intent", {})
        entities = intent_data.get("extracted_entities", {})
        user_msg = state.get("user_message", "")

        # Extract keywords from entities and message
        keywords = []
        if entities.get("product_mentioned"):
            keywords.append(entities["product_mentioned"])
        # Add words from user message
        keywords.extend([w for w in user_msg.split() if len(w) > 1])
        if not keywords:
            keywords = [user_msg]

        # Use mock embedding + neo4j
        query_embedding = skills.embedding.embed(user_msg)
        results = await skills.neo4j.hybrid_search(
            query=user_msg,
            query_embedding=query_embedding,
            keywords=keywords,
            limit=10,
        )
        search_results = [
            {"id": r.id, "name": r.name, "description": r.description, "score": r.score}
            for r in results
        ]
        return {"search_results": search_results}

    async def patched_reranker(state):
        """使用 mock reranker 精排"""
        candidates = state.get("search_results", [])
        reranked = skills.reranker.rerank(
            query=state.get("user_message", ""),
            documents=candidates,
            text_field="description",
            top_k=5,
        )
        return {"reranked_results": reranked}

    async def patched_graphrag(state):
        """使用 mock neo4j 获取商品子图"""
        reranked = state.get("reranked_results", [])
        enriched = []
        for item in reranked:
            product_id = item.get("id", "")
            graph = await skills.neo4j.get_product_graph(product_id)
            if graph:
                enriched_item = {**item, **graph.model_dump()}
            else:
                enriched_item = item
            enriched.append(enriched_item)
        return {"enriched_results": enriched}

    # Patch
    cs_nodes.hybrid_search_node = patched_hybrid_search
    cs_nodes.reranker_node = patched_reranker
    cs_nodes.graphrag_node = patched_graphrag


# ── Demo ─────────────────────────────────────────────────────────────────────


async def main():
    print("=" * 70)
    print("💬 CustomerService Agent Demo — 多轮客服对话")
    print("=" * 70)

    # Patch search nodes with mock data
    _patch_search_nodes()

    # Compile graph
    from src.agents.customer_service.graph import compile_customer_service_graph

    graph = compile_customer_service_graph()

    # Test scenarios
    test_messages = [
        "你好",
        "有没有血压计推荐",
        "老人用哪种好",
        "怎么使用",
        "我要退货",
    ]

    conversation_history = []

    for i, msg in enumerate(test_messages, 1):
        print(f"\n{'─' * 70}")
        print(f"🧑 用户 [{i}/{len(test_messages)}]: {msg}")
        print(f"{'─' * 70}")

        state = {
            "user_message": msg,
            "conversation_history": conversation_history[-6:],  # keep last 3 rounds
            "session_id": "demo-session-001",
        }

        result = await graph.ainvoke(state)

        # Print intent
        intent = result.get("intent", {})
        print(
            f"\n  🎯 意图: {intent.get('intent', '?')} (置信度: {intent.get('confidence', 0):.0%})"
        )
        if intent.get("extracted_entities"):
            ents = intent["extracted_entities"]
            ent_str = ", ".join(f"{k}={v}" for k, v in ents.items() if v)
            if ent_str:
                print(f"  📋 实体: {ent_str}")
        print(f"  🔀 路由: {result.get('route', '?')}")
        if intent.get("requires_human"):
            print(f"  ⚠️  需要转人工: {intent.get('human_reason', '')}")

        # Print reply
        reply = result.get("reply", {})
        reply_text = reply.get("reply_text", "无回复")
        print(f"\n  🤖 回复: {reply_text}")

        if reply.get("products_mentioned"):
            print(f"  📦 提及商品: {[p.get('name', '?') for p in reply['products_mentioned']]}")
        if reply.get("upsell_suggestions"):
            print(f"  💡 推荐: {[s.get('name', '?') for s in reply['upsell_suggestions']]}")
        if reply.get("requires_human_review"):
            print(f"  🔴 需人工审核: {reply.get('review_reason', '')}")

        # Update history
        conversation_history.append({"role": "user", "content": msg})
        conversation_history.append({"role": "assistant", "content": reply_text})

        # Errors
        errors = result.get("errors", [])
        if errors:
            print(f"  ⚠️ 错误: {errors}")

    print(f"\n{'=' * 70}")
    print("✅ 客服对话 Demo 完成!")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
