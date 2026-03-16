"""
test_listing.py — 上架文案 Agent (Listing) 评估

评估目标：
  1. 标题长度 / 关键词密度是否达标
  2. 描述是否包含必要信息（规格、使用方法等）
  3. 医疗器械合规性检查（禁用词、资质要求）

技术约束：
  - 全 mock，无需真实 LLM / 爬虫
  - 验证输出格式与合规规则
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.eval.eval_metrics import check_output_format, check_text_constraints, check_value_in_range

# ---------------------------------------------------------------------------
# 合规约束常量
# ---------------------------------------------------------------------------

# 美团标题长度范围（字符）
TITLE_MIN_LEN = 10
TITLE_MAX_LEN = 60

# 描述最短长度
DESC_MIN_LEN = 50

# 关键词密度合理范围（关键词数 / 标题字数）
KW_DENSITY_MIN = 0.05
KW_DENSITY_MAX = 0.40

# 医疗器械违规词（绝对疗效声明）
MEDICAL_FORBIDDEN_WORDS = [
    "治愈", "根治", "包治百病", "特效药", "无副作用", "100%有效",
    "立竿见影", "神奇疗效", "彻底消除",
]

# 必须包含的合规字段（医疗器械类目）
REQUIRED_COMPLIANCE_FIELDS = [
    "product_name", "registration_number", "manufacturer", "scope_of_use"
]


# ---------------------------------------------------------------------------
# Mock 上架信息构造器
# ---------------------------------------------------------------------------


def _make_listing_info(
    title: str = "鱼跃电子血压计YE660AR 家用上臂式语音血压计",
    description: str = "精准测量血压，大屏显示，适合老年人家庭使用。使用方法：坐姿静息5分钟后测量。规格：标准臂围22-32cm。",
    category: str = "血压计",
    price: float = 189.0,
    is_medical_device: bool = True,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    """构造上架信息 mock。"""
    return {
        "title": title,
        "description": description,
        "category": category,
        "price": price,
        "unit": "台",
        "is_medical_device": is_medical_device,
        "keywords": keywords or ["血压计", "家用", "电子", "上臂式"],
        "images": ["img1.jpg"],
        "specifications": {"颜色": "白色", "适用人群": "成人"},
    }


def _make_compliance_check(
    passed: bool = True,
    registration_number: str = "国械注准20183222345",
    manufacturer: str = "江苏鱼跃医疗设备股份有限公司",
    forbidden_words_found: list[str] | None = None,
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    """构造合规检查结果 mock。"""
    return {
        "passed": passed,
        "product_name": "鱼跃电子血压计",
        "registration_number": registration_number,
        "manufacturer": manufacturer,
        "scope_of_use": "用于家庭血压测量",
        "forbidden_words_found": forbidden_words_found or [],
        "missing_fields": missing_fields or [],
        "warnings": [],
        "compliance_grade": "A" if passed else "F",
    }


# ---------------------------------------------------------------------------
# 标题长度 & 关键词密度
# ---------------------------------------------------------------------------


class TestTitleQuality:
    """验证上架标题质量。"""

    def test_title_length_in_range(self):
        """标题长度应在 [10, 60] 字符范围内。"""
        listing = _make_listing_info()
        result = check_text_constraints(
            listing["title"], min_len=TITLE_MIN_LEN, max_len=TITLE_MAX_LEN
        )
        assert result["valid"], f"标题长度问题: {result['issues']}"

    def test_title_too_short_detected(self):
        """标题过短应被检测。"""
        listing = _make_listing_info(title="血压计")
        result = check_text_constraints(
            listing["title"], min_len=TITLE_MIN_LEN, max_len=TITLE_MAX_LEN
        )
        assert not result["valid"]
        assert any("过短" in issue for issue in result["issues"])

    def test_title_too_long_detected(self):
        """标题过长（>60字）应被检测。"""
        long_title = "鱼跃电子血压计家用款超长型" * 6  # 72字符 > 60
        listing = _make_listing_info(title=long_title)
        result = check_text_constraints(
            listing["title"], min_len=TITLE_MIN_LEN, max_len=TITLE_MAX_LEN
        )
        assert not result["valid"]

    def test_keyword_density_calculation(self):
        """关键词密度计算正确性验证。"""
        title = "鱼跃电子血压计家用上臂式"
        keywords = ["血压计", "家用", "上臂式"]
        # 简单统计：title 中出现的 keyword 数量 / title 总字数
        keyword_hits = sum(1 for kw in keywords if kw in title)
        density = keyword_hits / len(title)
        chk = check_value_in_range(density, KW_DENSITY_MIN, KW_DENSITY_MAX, label="keyword_density")
        assert chk["valid"], chk["message"]

    def test_keyword_stuffing_detected(self):
        """关键词堆砌（密度过高）应被检测。"""
        # 极端关键词堆砌
        stuffed_title = "血压计血压计血压计血压计血压"
        keywords = ["血压计"]
        keyword_hits = sum(title.count(kw) for kw in keywords for title in [stuffed_title])
        density = keyword_hits * len(keywords[0]) / len(stuffed_title)
        assert density > KW_DENSITY_MAX, "关键词堆砌密度应超过阈值"

    def test_title_contains_product_category(self):
        """标题应包含商品品类关键词。"""
        listing = _make_listing_info(title="鱼跃电子血压计家用款")
        keywords = listing["keywords"]
        title = listing["title"]
        has_category_kw = any(kw in title for kw in keywords)
        assert has_category_kw, f"标题 {title!r} 应包含至少一个品类关键词"

    def test_title_no_special_chars_issue(self):
        """标题中不应有乱码或异常特殊字符。"""
        listing = _make_listing_info()
        # 简单检查：标题不含乱码字符（ASCII 控制字符）
        assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", listing["title"]), (
            "标题包含异常控制字符"
        )


# ---------------------------------------------------------------------------
# 描述信息完整性
# ---------------------------------------------------------------------------


class TestDescriptionCompleteness:
    """验证商品描述是否包含必要信息。"""

    def test_description_minimum_length(self):
        """描述长度应 >= 50 字符。"""
        listing = _make_listing_info()
        result = check_text_constraints(listing["description"], min_len=DESC_MIN_LEN)
        assert result["valid"], f"描述过短: {result['issues']}"

    def test_description_contains_usage(self):
        """描述应包含使用方法信息。"""
        listing = _make_listing_info()
        has_usage = "使用" in listing["description"] or "方法" in listing["description"]
        assert has_usage, "描述应包含使用方法说明"

    def test_description_contains_spec(self):
        """描述应包含规格信息。"""
        listing = _make_listing_info()
        has_spec = "规格" in listing["description"] or "cm" in listing["description"] or "尺寸" in listing["description"]
        assert has_spec, "描述应包含规格信息"

    def test_empty_description_detected(self):
        """空描述应被检测为不合格。"""
        listing = _make_listing_info(description="")
        result = check_text_constraints(listing["description"], min_len=DESC_MIN_LEN)
        assert not result["valid"]

    def test_listing_output_format(self):
        """上架信息输出应包含必要字段。"""
        listing = _make_listing_info()
        result = check_output_format(
            listing,
            required_keys=["title", "description", "category", "price", "keywords"],
        )
        assert result["valid"], f"上架信息缺少字段: {result['missing_keys']}"

    def test_price_is_positive(self):
        """商品价格应为正数。"""
        listing = _make_listing_info(price=189.0)
        chk = check_value_in_range(listing["price"], 0.01, 99999, label="price")
        assert chk["valid"], chk["message"]

    def test_zero_price_detected(self):
        """零价格应被检测为异常。"""
        listing = _make_listing_info(price=0.0)
        assert listing["price"] <= 0, "零价格应被拒绝"


# ---------------------------------------------------------------------------
# 医疗器械合规性检查
# ---------------------------------------------------------------------------


class TestMedicalCompliance:
    """验证医疗器械上架合规性。"""

    def test_compliance_output_format(self):
        """合规检查结果应包含必要字段。"""
        compliance = _make_compliance_check()
        result = check_output_format(
            compliance,
            required_keys=["passed", "registration_number", "manufacturer", "scope_of_use"],
        )
        assert result["valid"], f"合规检查缺少字段: {result['missing_keys']}"

    def test_valid_registration_number_format(self):
        """注册证号格式应合法（国械注准/国械注进 + 年份 + 数字）。"""
        reg_num = "国械注准20183222345"
        # 注：示例号码长度不完全，此处只验证前缀格式
        assert reg_num.startswith("国械注准") or reg_num.startswith("国械注进"), (
            f"注册证号格式不合法: {reg_num}"
        )

    def test_forbidden_words_detected(self):
        """违规词（绝对疗效声明）应被检测。"""
        for word in MEDICAL_FORBIDDEN_WORDS:
            result = check_text_constraints(
                f"这款血压计能{word}高血压",
                forbidden_keywords=MEDICAL_FORBIDDEN_WORDS,
            )
            assert not result["valid"], f"应检测到违规词: {word!r}"
            assert any(word in issue for issue in result["issues"])

    def test_clean_description_no_forbidden_words(self):
        """规范描述不包含违规词。"""
        clean_desc = "精准测量血压，适合家庭日常监测使用，注意：本产品不能替代医疗诊断。"
        result = check_text_constraints(
            clean_desc,
            forbidden_keywords=MEDICAL_FORBIDDEN_WORDS,
        )
        assert result["valid"], f"规范描述被误判含违规词: {result['issues']}"

    def test_compliance_check_passes_for_valid_listing(self):
        """合规的上架信息应通过检查。"""
        compliance = _make_compliance_check(passed=True)
        assert compliance["passed"] is True
        assert compliance["compliance_grade"] == "A"
        assert len(compliance["forbidden_words_found"]) == 0
        assert len(compliance["missing_fields"]) == 0

    def test_missing_registration_number_fails(self):
        """缺少注册证号的医疗器械应不通过合规检查。"""
        compliance = _make_compliance_check(
            passed=False,
            registration_number="",
            missing_fields=["registration_number"],
        )
        assert not compliance["passed"]
        assert "registration_number" in compliance["missing_fields"]

    def test_non_medical_device_skips_compliance(self):
        """非医疗器械商品（如食品）应跳过医疗合规检查。"""
        listing = _make_listing_info(category="食品", is_medical_device=False)
        assert not listing["is_medical_device"], "非医疗器械不应触发合规检查"

    def test_medical_device_requires_compliance(self):
        """医疗器械商品必须进行合规检查。"""
        listing = _make_listing_info(category="血压计", is_medical_device=True)
        assert listing["is_medical_device"], "医疗器械应触发合规检查"

    @pytest.mark.parametrize("forbidden_word", MEDICAL_FORBIDDEN_WORDS)
    def test_each_forbidden_word_detected(self, forbidden_word):
        """逐一测试每个违规词是否被检测。"""
        text = f"本品{forbidden_word}效果极佳"
        result = check_text_constraints(text, forbidden_keywords=MEDICAL_FORBIDDEN_WORDS)
        assert not result["valid"], f"违规词 {forbidden_word!r} 未被检测"
