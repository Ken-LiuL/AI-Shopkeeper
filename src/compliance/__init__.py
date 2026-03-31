"""
共享合规规则包 (Shared Compliance Package)

可被以下模块导入使用：
  - src.agents.customer_service  (客服合规过滤)
  - src.agents.listing           (上架合规校验)
"""

from .medical_device_rules import (
    LISTING_EXAGGERATION,
    LISTING_FALSE_CLAIMS,
    LISTING_PROHIBITED_WORDS,
    PROHIBITED_ABSOLUTE_CLAIMS,
    PROHIBITED_DIAGNOSTIC_PATTERNS,
    PROHIBITED_PRESCRIPTION_PATTERNS,
    PROHIBITED_REPLACE_MEDICAL,
    TITLE_REMOVE_WORDS,
    apply_title_clean,
    check_text_violations,
)

__all__ = [
    "PROHIBITED_DIAGNOSTIC_PATTERNS",
    "PROHIBITED_PRESCRIPTION_PATTERNS",
    "PROHIBITED_ABSOLUTE_CLAIMS",
    "PROHIBITED_REPLACE_MEDICAL",
    "LISTING_PROHIBITED_WORDS",
    "LISTING_FALSE_CLAIMS",
    "LISTING_EXAGGERATION",
    "TITLE_REMOVE_WORDS",
    "apply_title_clean",
    "check_text_violations",
]
