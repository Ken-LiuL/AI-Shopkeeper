"""
AI店长 - 所有 Agent 的 Tool Schema 定义
兼容 Anthropic Tool Use API 格式
"""

# =============================================================================
# Selection Agent Tools
# =============================================================================

MARKET_ANALYSIS_TOOL = {
    "name": "output_market_analysis",
    "description": "输出市场分析结果",
    "input_schema": {
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
                        "click_rate": {"type": "number"},
                        "conversion_rate": {"type": "number"},
                        "growth_rate": {"type": "number"},
                        "trend": {"enum": ["rising", "stable", "declining"]},
                        "heat_score": {"type": "number", "minimum": 0, "maximum": 100},
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
                        "category": {"type": "string"},
                        "monthly_sales": {"type": "integer"},
                        "avg_price": {"type": "number"},
                        "rank": {"type": "integer"},
                    },
                    "required": ["name", "monthly_sales"],
                },
            },
            "insights": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["analysis_summary", "keywords", "products"],
    },
}

COMPETITOR_ANALYSIS_TOOL = {
    "name": "output_competitor_analysis",
    "description": "输出竞品分析结果",
    "input_schema": {
        "type": "object",
        "properties": {
            "competitor_summary": {
                "type": "object",
                "properties": {
                    "total_competitors": {"type": "integer"},
                    "high_threat_count": {"type": "integer"},
                },
            },
            "competitors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "distance_km": {"type": "number"},
                        "rating": {"type": "number"},
                        "threat_level": {"enum": ["high", "medium", "low"]},
                    },
                },
            },
            "gap_products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_name": {"type": "string"},
                        "competitor_count": {"type": "integer"},
                        "avg_price": {"type": "number"},
                        "estimated_monthly_sales": {"type": "integer"},
                        "priority": {"enum": ["high", "medium", "low"]},
                    },
                    "required": ["product_name", "priority"],
                },
            },
            "stockout_opportunities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_name": {"type": "string"},
                        "stockout_competitor_count": {"type": "integer"},
                        "urgency": {"enum": ["urgent", "normal"]},
                    },
                },
            },
        },
        "required": ["competitor_summary", "gap_products", "stockout_opportunities"],
    },
}

INVENTORY_ANALYSIS_TOOL = {
    "name": "output_inventory_analysis",
    "description": "输出库存分析结果",
    "input_schema": {
        "type": "object",
        "properties": {
            "inventory_summary": {
                "type": "object",
                "properties": {
                    "total_sku": {"type": "integer"},
                    "total_stock_value": {"type": "number"},
                    "health_score": {"type": "number"},
                    "fast_moving_percent": {"type": "number"},
                    "dead_stock_percent": {"type": "number"},
                },
            },
            "covered_keywords": {"type": "array", "items": {"type": "string"}},
            "problem_products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string"},
                        "name": {"type": "string"},
                        "status": {"enum": ["slow_moving", "dead"]},
                        "days_since_last_sale": {"type": "integer"},
                        "action": {"type": "string"},
                    },
                },
            },
        },
        "required": ["inventory_summary", "covered_keywords"],
    },
}

SEASONAL_FACTORS_TOOL = {
    "name": "output_seasonal_factors",
    "description": "输出季节性因素分析",
    "input_schema": {
        "type": "object",
        "properties": {
            "seasonal_summary": {"type": "string"},
            "factors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event_name": {"type": "string"},
                        "event_type": {"enum": ["season", "holiday", "weather", "trending"]},
                        "days_away": {"type": "integer"},
                        "urgency": {"enum": ["urgent", "soon", "planned"]},
                        "impact_level": {"enum": ["high", "medium", "low"]},
                        "affected_products": {"type": "array", "items": {"type": "string"}},
                        "expected_demand_change": {"type": "number"},
                    },
                    "required": ["event_name", "event_type", "impact_level"],
                },
            },
            "weather_impact": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "impact_level": {"enum": ["high", "medium", "low"]},
                    "affected_products": {"type": "array", "items": {"type": "string"}},
                },
            },
            "priority_products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product": {"type": "string"},
                        "combined_impact": {"type": "number"},
                        "action": {"enum": ["stock_up", "promote", "watch"]},
                    },
                },
            },
        },
        "required": ["seasonal_summary", "factors"],
    },
}

GAP_OPPORTUNITIES_TOOL = {
    "name": "output_gap_opportunities",
    "description": "输出识别到的缺品机会列表",
    "input_schema": {
        "type": "object",
        "properties": {
            "gap_summary": {
                "type": "object",
                "properties": {
                    "total_opportunities": {"type": "integer"},
                    "high_priority": {"type": "integer"},
                    "medium_priority": {"type": "integer"},
                },
                "required": ["total_opportunities", "high_priority", "medium_priority"],
            },
            "opportunities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rank": {"type": "integer"},
                        "keyword": {"type": "string"},
                        "priority": {"enum": ["high", "medium", "low"]},
                        "market_heat_score": {"type": "number", "minimum": 0, "maximum": 100},
                        "competitor_coverage": {"type": "integer"},
                        "stockout_opportunity": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["rank", "keyword", "priority", "market_heat_score", "reason"],
                },
            },
        },
        "required": ["gap_summary", "opportunities"],
    },
}

SUPPLIER_EVALUATION_TOOL = {
    "name": "output_supplier_evaluation",
    "description": "输出供应商评估结果（1688+拼多多双渠道）",
    "input_schema": {
        "type": "object",
        "properties": {
            "keyword": {"type": "string"},
            "recommendation": {
                "type": "object",
                "properties": {
                    "best_channel": {"enum": ["alibaba", "pdd"]},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
            "alibaba_evaluation": {
                "type": "object",
                "properties": {
                    "supplier_name": {"type": "string"},
                    "qualification_score": {"type": "number"},
                    "unit_cost": {"type": "number"},
                    "moq": {"type": "integer"},
                    "delivery_days": {"type": "integer"},
                    "risk_level": {"enum": ["low", "medium", "high"]},
                    "pros": {"type": "array", "items": {"type": "string"}},
                    "cons": {"type": "array", "items": {"type": "string"}},
                    "url": {"type": "string"},
                },
            },
            "pdd_evaluation": {
                "type": "object",
                "properties": {
                    "shop_name": {"type": "string"},
                    "shop_score": {"type": "number"},
                    "unit_cost": {"type": "number"},
                    "sales_count": {"type": "integer"},
                    "delivery_days": {"type": "integer"},
                    "pros": {"type": "array", "items": {"type": "string"}},
                    "cons": {"type": "array", "items": {"type": "string"}},
                    "url": {"type": "string"},
                },
            },
            "cost_comparison": {
                "type": "object",
                "properties": {
                    "alibaba_unit_cost": {"type": "number"},
                    "pdd_unit_cost": {"type": "number"},
                    "price_difference_percent": {"type": "number"},
                    "cheaper_channel": {"enum": ["alibaba", "pdd", "equal"]},
                },
            },
            "margin_analysis": {
                "type": "object",
                "properties": {
                    "market_price": {"type": "number"},
                    "suggested_price": {"type": "number"},
                    "gross_margin_percent": {"type": "number"},
                    "margin_grade": {"enum": ["excellent", "good", "fair", "poor"]},
                },
            },
            "final_suggestion": {
                "type": "object",
                "properties": {
                    "should_purchase": {"type": "boolean"},
                    "channel": {"enum": ["alibaba", "pdd"]},
                    "suggested_quantity": {"type": "integer"},
                    "estimated_investment": {"type": "number"},
                    "url": {"type": "string"},
                },
            },
        },
        "required": ["keyword", "recommendation", "cost_comparison", "margin_analysis", "final_suggestion"],
    },
}

RECOMMENDATIONS_TOOL = {
    "name": "output_recommendations",
    "description": "输出最终选品推荐",
    "input_schema": {
        "type": "object",
        "properties": {
            "scoring_summary": {
                "type": "object",
                "properties": {
                    "total_evaluated": {"type": "integer"},
                    "recommended_count": {"type": "integer"},
                    "top_score": {"type": "number"},
                    "avg_score": {"type": "number"},
                },
            },
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rank": {"type": "integer"},
                        "keyword": {"type": "string"},
                        "final_score": {"type": "number"},
                        "score_breakdown": {
                            "type": "object",
                            "properties": {
                                "market_heat": {"type": "number"},
                                "competition_gap": {"type": "number"},
                                "supply_chain": {"type": "number"},
                                "profit_margin": {"type": "number"},
                                "category_synergy": {"type": "number"},
                                "seasonal_fit": {"type": "number"},
                            },
                        },
                        "recommendation_reason": {"type": "string"},
                        "key_strengths": {"type": "array", "items": {"type": "string"}},
                        "key_risks": {"type": "array", "items": {"type": "string"}},
                        "purchase_channel": {"enum": ["alibaba", "pdd"]},
                        "purchase_url": {"type": "string"},
                        "suggested_quantity": {"type": "integer"},
                        "suggested_price": {"type": "number"},
                        "expected_margin": {"type": "number"},
                    },
                    "required": ["rank", "keyword", "final_score", "score_breakdown", "recommendation_reason"],
                },
            },
            "reflection_notes": {
                "type": "string",
                "description": "自我反思检查结果",
            },
        },
        "required": ["scoring_summary", "recommendations", "reflection_notes"],
    },
}

# =============================================================================
# CustomerService Agent Tools
# =============================================================================

INTENT_TOOL = {
    "name": "output_intent",
    "description": "输出意图识别结果",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "enum": [
                    "product_inquiry", "usage_question", "recommendation",
                    "logistics", "after_sales", "complaint", "greeting", "other",
                ],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "extracted_entities": {
                "type": "object",
                "properties": {
                    "product_mentioned": {"type": "string"},
                    "target_population": {"type": "string"},
                    "scenario": {"type": "string"},
                    "symptom": {"type": "string"},
                    "price_range": {"type": "string"},
                },
            },
            "sentiment": {"enum": ["positive", "neutral", "negative", "urgent"]},
            "requires_human": {"type": "boolean"},
            "human_reason": {"type": "string"},
        },
        "required": ["intent", "confidence", "requires_human"],
    },
}

REPLY_TOOL = {
    "name": "output_reply",
    "description": "输出客服回复",
    "input_schema": {
        "type": "object",
        "properties": {
            "reply_text": {"type": "string", "maxLength": 150},
            "confidence": {"type": "number"},
            "products_mentioned": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string"},
                        "name": {"type": "string"},
                        "relevance": {"type": "string"},
                    },
                },
            },
            "upsell_suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string"},
                        "name": {"type": "string"},
                        "price": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                },
                "maxItems": 2,
            },
            "requires_human_review": {"type": "boolean"},
            "review_reason": {"type": "string"},
        },
        "required": ["reply_text", "confidence"],
    },
}

# =============================================================================
# Alert Agent Tools
# =============================================================================

ANOMALIES_TOOL = {
    "name": "output_anomalies",
    "description": "输出检测到的异常列表",
    "input_schema": {
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
                        "anomaly_type": {
                            "enum": [
                                "sales_drop_prophet", "sales_spike_prophet",
                                "zero_sales", "consecutive_drop",
                                "competitor_price_drop", "price_gap",
                                "margin_warning", "margin_critical",
                                "stockout_urgent", "stockout_warning", "overstock",
                                "exposure_drop", "conversion_drop",
                                "competitor_stockout_opportunity", "multi_factor",
                            ],
                        },
                        "severity": {"enum": ["critical", "warning", "info"]},
                        "detection_method": {"enum": ["prophet", "rule", "isolation_forest"]},
                        "metrics": {
                            "type": "object",
                            "properties": {
                                "expected_value": {"type": "number"},
                                "actual_value": {"type": "number"},
                                "deviation_percent": {"type": "number"},
                                "threshold": {"type": "number"},
                            },
                        },
                        "description": {"type": "string"},
                        "detected_at": {"type": "string", "format": "date-time"},
                    },
                    "required": ["anomaly_id", "product_id", "anomaly_type", "severity", "description"],
                },
            },
        },
        "required": ["detection_summary", "anomalies"],
    },
}

ROOT_CAUSES_TOOL = {
    "name": "output_root_causes",
    "description": "输出归因分析结果",
    "input_schema": {
        "type": "object",
        "properties": {
            "product_id": {"type": "string"},
            "anomaly_type": {"type": "string"},
            "root_causes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cause_type": {
                            "enum": ["competitor", "inventory", "pricing", "external", "operation"],
                        },
                        "cause_detail": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                        "data_support": {
                            "type": "object",
                            "properties": {
                                "metric": {"type": "string"},
                                "before": {"type": "number"},
                                "after": {"type": "number"},
                                "change_percent": {"type": "number"},
                            },
                        },
                    },
                    "required": ["cause_type", "cause_detail", "confidence"],
                },
            },
            "primary_cause": {"type": "string"},
            "analysis_notes": {"type": "string"},
        },
        "required": ["product_id", "root_causes", "primary_cause"],
    },
}

ACTIONS_TOOL = {
    "name": "output_actions",
    "description": "输出行动建议",
    "input_schema": {
        "type": "object",
        "properties": {
            "product_id": {"type": "string"},
            "recommended_actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action_type": {
                            "enum": [
                                "price_adjust", "promotion", "restock",
                                "clearance", "delist", "optimize", "human_review",
                            ],
                        },
                        "priority": {"enum": ["P0", "P1", "P2", "P3"]},
                        "action_detail": {"type": "string"},
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "target_price": {"type": "number"},
                                "discount_percent": {"type": "number"},
                                "restock_quantity": {"type": "integer"},
                                "promotion_duration_hours": {"type": "integer"},
                            },
                        },
                        "expected_outcome": {"type": "string"},
                        "estimated_impact": {
                            "type": "object",
                            "properties": {
                                "sales_change_percent": {"type": "number"},
                                "margin_change_percent": {"type": "number"},
                                "investment_required": {"type": "number"},
                            },
                        },
                        "deadline": {"type": "string"},
                    },
                    "required": ["action_type", "priority", "action_detail"],
                },
            },
            "monitoring": {
                "type": "object",
                "properties": {
                    "metrics_to_watch": {"type": "array", "items": {"type": "string"}},
                    "check_after_hours": {"type": "integer"},
                    "success_criteria": {"type": "string"},
                },
            },
        },
        "required": ["product_id", "recommended_actions"],
    },
}

# =============================================================================
# Bundle Agent Tools
# =============================================================================

ASSOCIATION_RULES_TOOL = {
    "name": "output_association_rules",
    "description": "输出关联规则挖掘结果",
    "input_schema": {
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
                        "order_count": {"type": "integer"},
                        "potential_bundle_value": {"type": "number"},
                    },
                    "required": ["antecedent", "consequent", "support", "confidence", "lift"],
                },
            },
        },
        "required": ["mining_summary", "rules"],
    },
}

BUNDLE_PROPOSALS_TOOL = {
    "name": "output_bundle_proposals",
    "description": "输出套餐提案",
    "input_schema": {
        "type": "object",
        "properties": {
            "bundles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "bundle_id": {"type": "string"},
                        "bundle_name": {"type": "string"},
                        "tagline": {"type": "string"},
                        "products": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "product_id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "unit_price": {"type": "number"},
                                    "role_in_bundle": {"type": "string"},
                                },
                            },
                        },
                        "target_scenario": {"type": "string"},
                        "target_population": {"type": "string"},
                        "value_proposition": {"type": "string"},
                        "confidence_score": {"type": "number"},
                        "recommendation_reason": {"type": "string"},
                    },
                    "required": ["bundle_name", "products", "target_scenario"],
                },
            },
        },
        "required": ["bundles"],
    },
}

BUNDLE_PRICING_TOOL = {
    "name": "output_bundle_pricing",
    "description": "输出套餐定价",
    "input_schema": {
        "type": "object",
        "properties": {
            "bundle_id": {"type": "string"},
            "pricing": {
                "type": "object",
                "properties": {
                    "original_total": {"type": "number"},
                    "bundle_price": {"type": "number"},
                    "discount_percent": {"type": "number"},
                    "savings_amount": {"type": "number"},
                    "gross_margin_percent": {"type": "number"},
                },
            },
            "pricing_rationale": {"type": "string"},
            "approved": {"type": "boolean"},
            "rejection_reason": {"type": "string"},
        },
        "required": ["bundle_id", "pricing", "approved"],
    },
}

# =============================================================================
# Listing Agent Tools
# =============================================================================

PARSED_PRODUCT_TOOL = {
    "name": "output_parsed_product",
    "description": "输出解析后的商品信息",
    "input_schema": {
        "type": "object",
        "properties": {
            "source_platform": {"enum": ["alibaba", "pdd"]},
            "source_url": {"type": "string"},
            "parsed_data": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "brand": {"type": "string"},
                    "barcode": {"type": "string"},
                    "category": {"type": "string"},
                    "specifications": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                    "main_images": {"type": "array", "items": {"type": "string"}},
                    "detail_images": {"type": "array", "items": {"type": "string"}},
                    "price": {"type": "number"},
                    "moq": {"type": "integer"},
                    "weight_kg": {"type": "number"},
                    "package_info": {"type": "string"},
                },
            },
            "cleaned_title": {"type": "string"},
            "parse_confidence": {"type": "number"},
        },
        "required": ["source_platform", "parsed_data", "cleaned_title"],
    },
}

LISTING_INFO_TOOL = {
    "name": "output_listing_info",
    "description": "输出上架信息",
    "input_schema": {
        "type": "object",
        "properties": {
            "optimized_title": {"type": "string", "maxLength": 30},
            "category_path": {"type": "string"},
            "suggested_price": {"type": "number"},
            "price_rationale": {"type": "string"},
            "selling_points": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
            },
            "seo_keywords": {"type": "array", "items": {"type": "string"}},
            "specifications": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["optimized_title", "suggested_price", "selling_points"],
    },
}

COMPLIANCE_CHECK_TOOL = {
    "name": "output_compliance_check",
    "description": "输出合规校验结果",
    "input_schema": {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string"},
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
}

# =============================================================================
# Tool 索引（按 Agent 分组，方便查找）
# =============================================================================

SELECTION_TOOLS = [
    MARKET_ANALYSIS_TOOL,
    COMPETITOR_ANALYSIS_TOOL,
    INVENTORY_ANALYSIS_TOOL,
    SEASONAL_FACTORS_TOOL,
    GAP_OPPORTUNITIES_TOOL,
    SUPPLIER_EVALUATION_TOOL,
    RECOMMENDATIONS_TOOL,
]

CUSTOMER_SERVICE_TOOLS = [
    INTENT_TOOL,
    REPLY_TOOL,
]

ALERT_TOOLS = [
    ANOMALIES_TOOL,
    ROOT_CAUSES_TOOL,
    ACTIONS_TOOL,
]

BUNDLE_TOOLS = [
    ASSOCIATION_RULES_TOOL,
    BUNDLE_PROPOSALS_TOOL,
    BUNDLE_PRICING_TOOL,
]

LISTING_TOOLS = [
    PARSED_PRODUCT_TOOL,
    LISTING_INFO_TOOL,
    COMPLIANCE_CHECK_TOOL,
]

ALL_TOOLS = SELECTION_TOOLS + CUSTOMER_SERVICE_TOOLS + ALERT_TOOLS + BUNDLE_TOOLS + LISTING_TOOLS
