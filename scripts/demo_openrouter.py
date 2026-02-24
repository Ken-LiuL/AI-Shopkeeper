#!/usr/bin/env python3
"""
AI店长 OpenRouter 端到端 Demo
直接用 OpenAI SDK 调用 OpenRouter，验证多模型策略
完全绕过 langgraph 和 src.agents 的 import chain
"""

import asyncio
import json
import os
import time

# 从 .env 手动加载
from pathlib import Path

# ── OpenAI SDK 直连 OpenRouter ──────────────────────────────────────
from openai import AsyncOpenAI

env_path = Path(__file__).parent.parent / ".env"
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

client = AsyncOpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)

# ── 模型映射 ────────────────────────────────────────────────────────
MODELS = {
    "flash": "google/gemini-2.0-flash-001",
    "deepseek": "deepseek/deepseek-chat-v3-0324",
    "sonnet": "anthropic/claude-sonnet-4",
    "pro": "google/gemini-2.5-pro-preview",
}

# ── 成本表 ($/M tokens, input/output) ──────────────────────────────
COST_TABLE = {
    "google/gemini-2.0-flash-001": (0.10, 0.40),
    "deepseek/deepseek-chat-v3-0324": (0.27, 1.10),
    "anthropic/claude-sonnet-4": (3.00, 15.00),
    "google/gemini-2.5-pro-preview": (1.25, 10.00),
}

# ── Tool Schemas (Anthropic 格式 -> OpenAI function) ────────────────


def to_openai_tool(name, description, schema):
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": schema},
    }


INTENT_TOOL = to_openai_tool(
    "output_intent",
    "输出意图识别结果",
    {
        "type": "object",
        "properties": {
            "intent": {
                "enum": [
                    "product_inquiry",
                    "usage_question",
                    "recommendation",
                    "logistics",
                    "after_sales",
                    "complaint",
                    "greeting",
                    "other",
                ]
            },
            "confidence": {"type": "number"},
            "extracted_entities": {
                "type": "object",
                "properties": {
                    "product_mentioned": {"type": "string"},
                    "target_population": {"type": "string"},
                    "scenario": {"type": "string"},
                },
            },
            "sentiment": {"enum": ["positive", "neutral", "negative", "urgent"]},
            "requires_human": {"type": "boolean"},
        },
        "required": ["intent", "confidence", "requires_human"],
    },
)

REPLY_TOOL = to_openai_tool(
    "output_reply",
    "输出客服回复",
    {
        "type": "object",
        "properties": {
            "reply_text": {"type": "string", "maxLength": 150},
            "confidence": {"type": "number"},
            "products_mentioned": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "relevance": {"type": "string"}},
                },
            },
            "upsell_suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "price": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                },
                "maxItems": 2,
            },
            "requires_human_review": {"type": "boolean"},
        },
        "required": ["reply_text", "confidence"],
    },
)

MARKET_ANALYSIS_TOOL = to_openai_tool(
    "output_market_analysis",
    "输出市场分析结果",
    {
        "type": "object",
        "properties": {
            "analysis_summary": {"type": "string"},
            "keywords": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string"},
                        "search_volume": {"type": "integer"},
                        "heat_score": {"type": "number"},
                        "trend": {"enum": ["rising", "stable", "declining"]},
                    },
                    "required": ["keyword", "search_volume", "heat_score", "trend"],
                },
            },
            "products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "monthly_sales": {"type": "integer"},
                    },
                    "required": ["name", "monthly_sales"],
                },
            },
            "insights": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["analysis_summary", "keywords", "products"],
    },
)

PARSED_PRODUCT_TOOL = to_openai_tool(
    "output_parsed_product",
    "输出解析后的商品信息",
    {
        "type": "object",
        "properties": {
            "source_platform": {"enum": ["alibaba", "pdd"]},
            "parsed_data": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "brand": {"type": "string"},
                    "barcode": {"type": "string"},
                    "category": {"type": "string"},
                    "price": {"type": "number"},
                    "specifications": {"type": "object"},
                },
            },
            "cleaned_title": {"type": "string"},
            "parse_confidence": {"type": "number"},
        },
        "required": ["source_platform", "parsed_data", "cleaned_title"],
    },
)

LISTING_INFO_TOOL = to_openai_tool(
    "output_listing_info",
    "输出上架信息",
    {
        "type": "object",
        "properties": {
            "optimized_title": {"type": "string", "maxLength": 30},
            "suggested_price": {"type": "number"},
            "price_rationale": {"type": "string"},
            "selling_points": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "seo_keywords": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["optimized_title", "suggested_price", "selling_points"],
    },
)

COMPLIANCE_CHECK_TOOL = to_openai_tool(
    "output_compliance_check",
    "输出合规校验结果",
    {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"enum": ["fatal", "error", "warning", "info"]},
                        "field": {"type": "string"},
                        "issue": {"type": "string"},
                        "suggestion": {"type": "string"},
                    },
                },
            },
            "can_proceed": {"type": "boolean"},
            "requires_manual_review": {"type": "boolean"},
        },
        "required": ["passed", "issues", "can_proceed"],
    },
)

ASSOCIATION_RULES_TOOL = to_openai_tool(
    "output_association_rules",
    "输出关联规则挖掘结果",
    {
        "type": "object",
        "properties": {
            "mining_summary": {
                "type": "object",
                "properties": {
                    "total_orders_analyzed": {"type": "integer"},
                    "rules_found": {"type": "integer"},
                    "high_value_rules": {"type": "integer"},
                },
            },
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string"},
                        "antecedent": {"type": "array", "items": {"type": "string"}},
                        "consequent": {"type": "array", "items": {"type": "string"}},
                        "support": {"type": "number"},
                        "confidence": {"type": "number"},
                        "lift": {"type": "number"},
                    },
                    "required": ["antecedent", "consequent", "support", "confidence", "lift"],
                },
            },
        },
        "required": ["mining_summary", "rules"],
    },
)

BUNDLE_PROPOSALS_TOOL = to_openai_tool(
    "output_bundle_proposals",
    "输出套餐提案",
    {
        "type": "object",
        "properties": {
            "bundles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "bundle_name": {"type": "string"},
                        "tagline": {"type": "string"},
                        "products": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "unit_price": {"type": "number"},
                                    "role_in_bundle": {"type": "string"},
                                },
                            },
                        },
                        "target_scenario": {"type": "string"},
                        "target_population": {"type": "string"},
                        "value_proposition": {"type": "string"},
                    },
                    "required": ["bundle_name", "products", "target_scenario"],
                },
            },
        },
        "required": ["bundles"],
    },
)

ANOMALIES_TOOL = to_openai_tool(
    "output_anomalies",
    "输出检测到的异常列表",
    {
        "type": "object",
        "properties": {
            "detection_summary": {
                "type": "object",
                "properties": {
                    "total_products_checked": {"type": "integer"},
                    "anomalies_found": {"type": "integer"},
                    "critical_count": {"type": "integer"},
                    "warning_count": {"type": "integer"},
                },
            },
            "anomalies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "anomaly_id": {"type": "string"},
                        "product_id": {"type": "string"},
                        "product_name": {"type": "string"},
                        "anomaly_type": {"type": "string"},
                        "severity": {"enum": ["critical", "warning", "info"]},
                        "description": {"type": "string"},
                    },
                    "required": [
                        "anomaly_id",
                        "product_id",
                        "anomaly_type",
                        "severity",
                        "description",
                    ],
                },
            },
        },
        "required": ["detection_summary", "anomalies"],
    },
)

# ── 统一调用函数 ────────────────────────────────────────────────────
results_log: list[dict] = []


async def call(
    label: str, agent: str, prompt: str, tool: dict, model_key: str, system: str | None = None
):
    model = MODELS[model_key]
    print(f"\n{'=' * 60}")
    print(f"▶ {agent} / {label}")
    print(f"  模型: {model}")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    t0 = time.time()
    try:
        response = await client.chat.completions.create(
            model=model,
            max_tokens=2048,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": tool["function"]["name"]}},
        )
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ❌ 失败 ({elapsed:.1f}s): {e}")
        results_log.append(
            {
                "agent": agent,
                "label": label,
                "model": model,
                "elapsed": elapsed,
                "in_tok": 0,
                "out_tok": 0,
                "cost": 0,
                "status": "FAIL",
                "error": str(e),
            }
        )
        return None

    elapsed = time.time() - t0
    choice = response.choices[0]

    if choice.message.tool_calls:
        result = json.loads(choice.message.tool_calls[0].function.arguments)
    else:
        print(
            f"  ⚠️  无 tool_call，原始回复: {choice.message.content[:200] if choice.message.content else 'None'}"
        )
        result = {}

    in_tok = response.usage.prompt_tokens if response.usage else 0
    out_tok = response.usage.completion_tokens if response.usage else 0
    cost_in, cost_out = COST_TABLE.get(model, (0, 0))
    cost = in_tok * cost_in / 1e6 + out_tok * cost_out / 1e6

    summary = json.dumps(result, ensure_ascii=False)
    if len(summary) > 200:
        summary = summary[:200] + "..."

    print(f"  ✅ 耗时: {elapsed:.2f}s | tokens: {in_tok}/{out_tok} | 成本: ${cost:.6f}")
    print(f"  结果: {summary}")

    results_log.append(
        {
            "agent": agent,
            "label": label,
            "model": model,
            "elapsed": elapsed,
            "in_tok": in_tok,
            "out_tok": out_tok,
            "cost": cost,
            "status": "OK",
        }
    )
    return result


async def main():
    print("🚀 AI店长 OpenRouter 多模型端到端 Demo")
    print(f"   Models: flash={MODELS['flash']}")
    print(f"           deepseek={MODELS['deepseek']}")
    print(f"           sonnet={MODELS['sonnet']}")
    print(f"           pro={MODELS['pro']}")

    # 1. 客服 Agent
    await call(
        "意图分类",
        "客服Agent",
        "用户消息: '你好，我想买个血压计，家里老人用的，有推荐吗？'\n对话历史: []",
        INTENT_TOOL,
        "flash",
    )

    await call(
        "回复生成",
        "客服Agent",
        "用户消息: '你好，我想买个血压计，家里老人用的，有推荐吗？'\n"
        '意图: {"intent": "recommendation", "confidence": 0.95}\n'
        '检索到的商品: [{"name": "欧姆龙U726J上臂式血压计", "price": 399, "特点": "大屏幕，语音播报"},{"name": "鱼跃YE680A电子血压计", "price": 199, "特点": "经济实惠，操作简单"}]',
        REPLY_TOOL,
        "sonnet",
        system="你是一个美团药店的AI客服，回复要亲切自然，像真人客服一样，150字以内。",
    )

    # 2. 选品 Agent
    await call(
        "市场分析",
        "选品Agent",
        "请分析以下医疗器械市场数据:\n"
        "关键词数据: 血压计(月搜索1.2万,增长15%), 血糖仪(月搜索8千,增长8%), 体温计(月搜索2万,增长-5%)\n"
        "热销商品: 欧姆龙血压计(月销500), 鱼跃血糖仪(月销300), 可孚体温枪(月销800)\n品类: 医疗器械",
        MARKET_ANALYSIS_TOOL,
        "pro",
    )

    # 3. 上架 Agent
    await call(
        "商品解析",
        "上架Agent",
        "请解析以下1688商品信息:\n平台: alibaba\n"
        "原始数据: 标题='欧姆龙电子血压计U726J上臂式智能加压家用全自动血压测量仪', "
        "价格=280元, 最小起订量=1台, 品牌=欧姆龙, 条码=4975479416934, "
        "规格={型号: U726J, 测量方式: 上臂式, 电源: 4节AA电池/USB, 记忆: 2x100组}",
        PARSED_PRODUCT_TOOL,
        "sonnet",
    )

    await call(
        "SEO优化+文案",
        "上架Agent",
        "请为以下商品生成美团上架信息:\n商品: 欧姆龙血压计U726J\n"
        '解析数据: {"cleaned_title": "欧姆龙U726J上臂式电子血压计", '
        '"parsed_data": {"brand": "欧姆龙", "category": "血压计", "price": 280}}\n'
        "竞品价格: 均价389元\n市场均价: 350元",
        LISTING_INFO_TOOL,
        "deepseek",
    )

    await call(
        "合规校验",
        "上架Agent",
        "请校验以下上架信息的合规性:\n"
        '上架信息: {"optimized_title": "欧姆龙U726J血压计 老人家用 上臂式 智能语音", '
        '"suggested_price": 369, "selling_points": ["大品牌欧姆龙","智能加压","双人记忆"]}\n'
        "商品品类: 医疗器械",
        COMPLIANCE_CHECK_TOOL,
        "flash",
    )

    # 4. 套餐 Agent
    await call(
        "关联分析",
        "套餐Agent",
        "请分析以下订单数据的关联规则:\n"
        "订单摘要: 最近30天共1200单，涉及SKU 85个\n"
        "高频组合: 血压计+血糖仪(同买率12%), 体温计+口罩(同买率18%), "
        "血糖仪+血糖试纸(同买率45%), 创可贴+碘伏+棉签(同买率8%)\n"
        'FP-Growth配置: {"min_support": 0.01, "min_confidence": 0.30, "min_lift": 1.5}',
        ASSOCIATION_RULES_TOOL,
        "pro",
    )

    await call(
        "套餐命名",
        "套餐Agent",
        "请为以下关联规则设计套餐:\n"
        '关联规则: [{"antecedent": ["血糖仪"], "consequent": ["血糖试纸"], '
        '"support": 0.045, "confidence": 0.78, "lift": 8.2},'
        '{"antecedent": ["创可贴"], "consequent": ["碘伏","棉签"], '
        '"support": 0.012, "confidence": 0.35, "lift": 2.1}]\n'
        "商品详情: 鱼跃血糖仪(89元), 三诺血糖试纸50片(69元), 云南白药创可贴(12元), 海氏海诺碘伏(8元), 棉签(5元)",
        BUNDLE_PROPOSALS_TOOL,
        "deepseek",
    )

    # 5. 异常 Agent
    await call(
        "异常检测",
        "异常Agent",
        "请分析以下商品数据，检测异常:\n"
        '商品数据: [{"product_id": "P001", "name": "欧姆龙血压计", '
        '"近7天日均销量": [5,4,5,3,1,0,0], "近7天曝光": [200,180,190,100,50,30,20], '
        '"价格": 369, "库存": 3},'
        '{"product_id": "P002", "name": "鱼跃血糖仪", '
        '"近7天日均销量": [3,3,4,3,3,8,12], "近7天曝光": [150,160,155,160,170,300,450], '
        '"价格": 89, "库存": 50}]\n'
        "Prophet预测: P001预期日销4.2, P002预期日销3.5\n"
        "规则检测: P001连续2天零销量，库存预警; P002销量激增\n"
        "当前时间: 2026-02-12T10:00:00",
        ANOMALIES_TOOL,
        "sonnet",
    )

    # ═══════════════════════════════════════════════════════════════
    # 汇总
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("📊 汇总报告")
    print("=" * 60)

    total_cost = total_in = total_out = 0
    total_time = 0.0
    ok = fail = 0

    print(
        f"\n{'Agent':<10} {'任务':<14} {'模型':<35} {'耗时':>6} {'In':>6} {'Out':>6} {'成本':>10} {'状态':>4}"
    )
    print("-" * 100)
    for r in results_log:
        ms = r["model"].split("/")[-1][:32]
        status = r.get("status", "OK")
        print(
            f"{r['agent']:<10} {r['label']:<14} {ms:<35} {r['elapsed']:>5.1f}s {r['in_tok']:>6} {r['out_tok']:>6} ${r['cost']:>8.6f} {status:>4}"
        )
        total_cost += r["cost"]
        total_in += r["in_tok"]
        total_out += r["out_tok"]
        total_time += r["elapsed"]
        if status == "OK":
            ok += 1
        else:
            fail += 1

    print("-" * 100)
    print(
        f"{'合计':<10} {'':<14} {'':<35} {total_time:>5.1f}s {total_in:>6} {total_out:>6} ${total_cost:>8.6f} {ok}✅{fail}❌"
    )

    # 模型维度
    print("\n📈 模型维度:")
    by_model: dict[str, list] = {}
    for r in results_log:
        by_model.setdefault(r["model"], []).append(r)
    for m, rs in by_model.items():
        c = sum(r["cost"] for r in rs)
        t = sum(r["in_tok"] + r["out_tok"] for r in rs)
        print(f"  {m}: {len(rs)}次, {t} tokens, ${c:.6f}")

    print(f"\n✅ Demo 完成！{ok}/{ok + fail} 成功，总成本 ${total_cost:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
