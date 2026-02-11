"""Listing Agent Prompt 模板"""


TITLE_REMOVE_WORDS = [
    "厂家直销", "批发", "爆款", "热卖", "新款",
    "包邮", "特价", "促销", "一件代发",
]

PROHIBITED_WORDS = ["处方", "抗生素", "激素", "麻醉", "毒品"]
FALSE_CLAIM_WORDS = ["治愈", "根治", "100%有效", "无副作用", "包治"]
EXAGGERATION_WORDS = ["最好", "第一", "顶级", "国际领先"]


def parser_prompt(
    source_platform: str,
    raw_product_data: str,
) -> str:
    return f"""# 角色定义
你是商品信息解析专家。

# 任务
解析{source_platform}商品数据，提取结构化信息。

# 原始数据
{raw_product_data}

# 标题清洗规则

去除以下无意义词汇：
厂家直销、批发、爆款、热卖、新款、包邮、特价、促销、一件代发

保留关键信息：
- 品牌名
- 型号
- 规格参数
- 核心功能
- 材质

# 解析要求

1. 提取标题、品牌、条形码、类目
2. 提取规格参数（尺寸、材质、适用人群等）
3. 提取主图和详情图URL
4. 提取价格、起订量、重量
5. 清洗标题（去除营销词汇）
6. 评估解析置信度 (0-1)

# 输出
使用 output_parsed_product 工具输出结果"""


def matcher_prompt(
    cleaned_title: str,
    barcode: str,
    specifications: str,
    meituan_candidates: str,
) -> str:
    return f"""# 角色定义
你是美团标品库匹配专家。

# 任务
将解析的商品与美团标品库匹配。

# 待匹配商品
清洗后标题：{cleaned_title}
条形码：{barcode}
规格：{specifications}

# 美团标品库候选
{meituan_candidates}

# 匹配优先级

1. 条形码完全匹配 → 置信度 0.99
2. 品牌+型号完全匹配 → 置信度 0.90
3. 品牌+品类+核心规格匹配 → 置信度 0.75
4. 品类+规格模糊匹配 → 置信度 0.50
5. 无匹配 → 需要新建标品

# 输出
返回最佳匹配的标品信息和置信度"""


def filler_prompt(
    parsed_product: str,
    matched_standard: str,
    competitor_prices: str,
    market_avg_price: float,
) -> str:
    return f"""# 角色定义
你是美团商品上架专家。

# 任务
填充上架信息，优化标题和定价。

# 商品信息
{parsed_product}

# 匹配的标品
{matched_standard}

# 竞品价格
{competitor_prices}

# 市场均价
{market_avg_price}

# 标题优化规则

格式: {{品类词}} {{品牌}} {{核心功能}} {{规格}} {{附加卖点}}
长度: ≤30字

示例:
- 原标题: "欧姆龙家用电子血压计上臂式全自动智能语音播报老人用正品HEM-7121"
- 优化后: "欧姆龙血压计 上臂式智能语音 老人家用HEM-7121"

# 定价建议公式

建议售价 = MAX(
    成本 × 2.5,
    竞品均价 × 0.95,
    美团同标品均价 × 0.98
)
建议售价 = MIN(建议售价, 竞品最高价)
尾数调整: 调整为.9或.8

# 卖点提炼

从商品信息中提取3-5个核心卖点:
- 品牌优势
- 功能特点
- 材质/技术
- 适用场景
- 售后保障

# SEO关键词

提取5-8个搜索关键词:
- 品类词（如：血压计）
- 品牌词（如：欧姆龙）
- 场景词（如：家用）
- 人群词（如：老人）
- 功能词（如：语音播报）

# 输出
使用 output_listing_info 工具输出结果"""


def compliance_prompt(
    listing_info: str,
    product_category: str,
) -> str:
    return f"""# 角色定义
你是医疗器械合规审核专家。

# 任务
对上架信息进行合规校验。

# 上架信息
{listing_info}

# 商品类目
{product_category}

# 合规规则

## C1 - 医疗器械资质（fatal）
医疗器械需要对应分类资质:
- 一类：备案凭证
- 二类：注册证
- 三类：注册证 + 经营许可证

## C2 - 禁售词检查（fatal）
标题和卖点中不得出现:
处方、抗生素、激素、麻醉、毒品

## C3 - 虚假宣传（error）
不得出现:
治愈、根治、100%有效、无副作用、包治

## C4 - 夸大宣传（warning）
不建议出现:
最好、第一、顶级、国际领先

## C5 - 价格异常（warning）
价格偏离市场均价>50%需确认

## C6 - 图片检查（info）
主图数量<3张建议补充

# 审核流程

1. 逐条检查所有规则
2. 标注违规字段和具体位置
3. 给出修改建议
4. 判断是否可继续上架:
   - 有fatal → can_proceed=false
   - 只有error → can_proceed=false, 修改后重试
   - 只有warning/info → can_proceed=true

# 输出
使用 output_compliance_check 工具输出结果"""
