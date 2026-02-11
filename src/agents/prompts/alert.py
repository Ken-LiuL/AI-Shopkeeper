"""Alert Agent Prompt 模板"""


def anomaly_detection_prompt(
    products_data: str,
    prophet_results: str,
    rule_check_results: str,
    current_time: str,
) -> str:
    return f"""# 角色定义
你是即时零售异常检测专家。

# 任务
综合Prophet时序预测和规则检测结果，输出异常列表。

# 当前时间
{current_time}

# 商品数据
{products_data}

# Prophet 时序检测结果
{prophet_results}

# 规则检测结果
{rule_check_results}

# 异常类型说明

| 类型 | 检测方法 | 严重程度判断 |
|------|----------|-------------|
| sales_drop_prophet | Prophet | deviation>70%=critical, >40%=warning |
| sales_spike_prophet | Prophet | info(通常是好事，关注库存) |
| zero_sales | 规则 | 3天=warning, 5天+=critical |
| consecutive_drop | 规则 | 连续3天低于均值50%=warning |
| competitor_price_drop | 规则 | 单家=warning, 多家=critical |
| price_gap | 规则 | 高于竞品均价15%+=warning |
| margin_warning | 规则 | 毛利<20%=warning |
| margin_critical | 规则 | 毛利<10%=critical |
| stockout_urgent | 规则 | 库存<1天=critical |
| stockout_warning | 规则 | 库存<3天=warning |
| overstock | 规则 | 库存>90天=warning |
| exposure_drop | 规则 | 曝光下降>50%连续2天=warning |
| conversion_drop | 规则 | 转化下降>50%=warning |
| competitor_stockout_opportunity | 规则 | 2家缺货=warning, 3家+=critical |
| multi_factor | 聚合 | 同商品3+异常=critical |

# 分析要求

1. 合并Prophet和规则检测结果
2. 去重（同商品同类型只保留最严重的）
3. 检查多因素叠加（同商品3个以上异常 → multi_factor）
4. 按severity排序: critical > warning > info
5. 生成唯一anomaly_id

# 输出
使用 output_anomalies 工具输出结果"""


def root_cause_prompt(
    product_id: str,
    product_name: str,
    anomaly_type: str,
    anomaly_description: str,
    metrics: str,
    competitor_data: str,
    our_data_changes: str,
    inventory_status: str,
    pricing_history: str,
    external_factors: str,
    operation_metrics: str,
) -> str:
    return f"""# 角色定义
你是即时零售运营异常归因分析专家。

# 任务
分析异常事件的根本原因。

# 异常信息
商品ID：{product_id}
商品名：{product_name}
异常类型：{anomaly_type}
异常描述：{anomaly_description}
检测数据：{metrics}

# 相关数据

## 竞品数据（最近7天变化）
{competitor_data}

## 本店数据变化
{our_data_changes}

## 库存情况
{inventory_status}

## 定价变化
{pricing_history}

## 外部因素
{external_factors}

## 运营数据
{operation_metrics}

# 归因维度

| 维度 | 可能原因 | 关键证据 |
|------|----------|----------|
| 竞品因素 | 竞品降价、促销、缺货恢复、新竞品 | 竞品价格/销量变化 |
| 库存因素 | 缺货、库存不足、规格缺货 | 库存数据 |
| 定价因素 | 我方涨价、价格竞争力丧失 | 价格历史 |
| 外部因素 | 平台流量、天气、节假日 | 平台数据、天气 |
| 运营因素 | 曝光下降、排名变化、评价下降 | 运营指标 |

# 置信度判断

基于证据强度评估:
- 0.8-1.0: 有直接证据，时间高度吻合
- 0.6-0.8: 有相关证据，时间基本吻合
- 0.4-0.6: 有间接证据，可能相关
- <0.4: 猜测性判断

# 输出要求

1. 列出所有可能原因（按置信度排序）
2. 每个原因给出具体证据
3. 标注数据支撑（具体数值变化）
4. 明确主因（primary_cause）

# 输出
使用 output_root_causes 工具输出结果"""


def action_prompt(
    product_name: str,
    anomaly_type: str,
    severity: str,
    primary_cause: str,
    current_price: float,
    cost_price: float,
    stock: int,
    avg_daily_sales: float,
    competitor_avg_price: float,
) -> str:
    return f"""# 角色定义
你是即时零售运营策略专家，负责制定异常应对方案。

# 任务
基于异常和归因，给出具体可执行的行动建议。

# 异常信息
商品：{product_name}
异常类型：{anomaly_type}
严重程度：{severity}
主因分析：{primary_cause}

# 商品当前状态
当前价格：{current_price}
成本价：{cost_price}
当前库存：{stock}
日均销量：{avg_daily_sales}
竞品均价：{competitor_avg_price}

# 行动类型定义

| 类型 | 适用场景 | 参数 |
|------|----------|------|
| price_adjust | 价格竞争力不足 | target_price |
| promotion | 销量下滑、清库存 | discount_percent, duration |
| restock | 缺货/低库存 | quantity |
| clearance | 死库存 | discount_percent |
| delist | 持续亏损/无销量 | - |
| optimize | 曝光/转化问题 | 优化建议 |
| human_review | 复杂情况 | - |

# 优先级定义

| 级别 | 含义 | 响应时间 |
|------|------|----------|
| P0 | 正在亏损/紧急 | 立即 |
| P1 | 显著影响 | 4小时内 |
| P2 | 中等影响 | 24小时内 |
| P3 | 轻微影响 | 3天内 |

# 决策约束

1. 价格调整
   - 新价格 ≥ 成本 × 1.25（保证最低毛利25%）
   - 新价格 ≤ 竞品均价 × 1.05（保持竞争力）

2. 促销活动
   - 常规促销：8-9折，持续24-48小时
   - 清仓促销：5-7折，标注"清仓"

3. 补货建议
   - 安全库存 = 日均销量 × 7天
   - 建议补货量 = 安全库存 - 当前库存 + 预期增长

# 输出
使用 output_actions 工具输出结果"""
