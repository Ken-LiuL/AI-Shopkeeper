"""Medical Device Specific Service - 医疗器械专业功能服务"""

from __future__ import annotations

import logging
from typing import Any

from src.db import postgres as pg

logger = logging.getLogger(__name__)


class MedicalDeviceService:
    """医疗器械专业服务 - 针对医疗器械行业的特殊需求"""

    @staticmethod
    def is_medical_device(category: str, name: str) -> bool:
        """判断是否为医疗器械商品"""
        medical_keywords = [
            "医疗",
            "医用",
            "器械",
            "血压计",
            "体温计",
            "血糖仪",
            "听诊器",
            "雾化器",
            "制氧机",
            "轮椅",
            "拐杖",
            "护理",
            "康复",
            "理疗",
            "监护",
            "检测",
            "诊断",
            "手术",
            "消毒",
            "杀菌",
            "急救",
            "绷带",
            "纱布",
            "创可贴",
            "注射器",
            "输液",
            "导管",
        ]

        category_lower = category.lower()
        name_lower = name.lower()

        return any(
            keyword in category_lower or keyword in name_lower for keyword in medical_keywords
        )

    @staticmethod
    def get_medical_device_margin_requirements() -> dict:
        """获取医疗器械毛利率要求"""
        return {
            "一类器械": 20,  # 一类医疗器械，风险低
            "二类器械": 25,  # 二类医疗器械，风险中等
            "三类器械": 30,  # 三类医疗器械，风险高
            "默认医疗": 25,  # 默认医疗器械要求
        }

    @staticmethod
    def classify_medical_device_type(name: str, category: str) -> str:
        """医疗器械分类"""
        name_category = f"{name} {category}".lower()

        # 三类器械（高风险）
        if any(
            keyword in name_category
            for keyword in [
                "植入",
                "起搏器",
                "人工关节",
                "血管支架",
                "呼吸机",
                "监护仪",
                "除颤器",
                "血透",
                "腹透",
            ]
        ):
            return "三类器械"

        # 二类器械（中风险）
        elif any(
            keyword in name_category
            for keyword in [
                "血压计",
                "血糖仪",
                "体温计",
                "听诊器",
                "雾化器",
                "制氧机",
                "轮椅",
                "x光",
                "超声",
                "心电",
            ]
        ):
            return "二类器械"

        # 一类器械（低风险）
        elif any(
            keyword in name_category
            for keyword in [
                "绷带",
                "纱布",
                "创可贴",
                "棉签",
                "口罩",
                "手套",
                "消毒",
                "拐杖",
                "护腰",
                "护膝",
            ]
        ):
            return "一类器械"

        return "默认医疗"

    @staticmethod
    async def get_medical_device_compliance_info(product_id: str) -> dict[str, Any]:
        """获取医疗器械合规信息"""
        try:
            pool = pg.get_pool()

            # 查询商品基本信息
            product = await pool.fetchrow(
                """
                SELECT spu_id, name, category, retail_price, brand
                FROM qnh_products
                WHERE spu_id = $1
            """,
                product_id,
            )

            if not product:
                return {"error": "商品不存在"}

            name = product["name"]
            category = product["category"] or ""

            # 判断是否医疗器械
            is_medical = MedicalDeviceService.is_medical_device(category, name)

            if not is_medical:
                return {"is_medical_device": False}

            # 医疗器械分类
            device_type = MedicalDeviceService.classify_medical_device_type(name, category)
            margin_requirements = MedicalDeviceService.get_medical_device_margin_requirements()

            # 合规建议
            compliance_suggestions = []

            if "血压计" in name.lower():
                compliance_suggestions.extend(
                    ["需要NMPA注册证", "建议标注使用方法和注意事项", "提供校准服务信息"]
                )
            elif "血糖仪" in name.lower():
                compliance_suggestions.extend(
                    ["需要NMPA注册证", "标注试纸有效期", "提供使用培训视频"]
                )
            elif "体温计" in name.lower():
                compliance_suggestions.extend(["标注测量范围和精度", "提供消毒方法说明"])

            # 销售建议
            sales_suggestions = []
            sales_suggestions.extend(
                [
                    f"建议毛利率不低于{margin_requirements.get(device_type, 25)}%",
                    "提供专业售前咨询服务",
                    "建立售后技术支持渠道",
                ]
            )

            if device_type in ["二类器械", "三类器械"]:
                sales_suggestions.append("建议配备专业销售人员")

            return {
                "is_medical_device": True,
                "device_type": device_type,
                "min_margin_percent": margin_requirements.get(device_type, 25),
                "compliance_suggestions": compliance_suggestions,
                "sales_suggestions": sales_suggestions,
                "category": category,
                "product_name": name,
            }

        except Exception as e:
            logger.error(f"Failed to get medical device compliance info: {e}")
            return {"error": str(e)}

    @staticmethod
    async def get_medical_category_analysis() -> list[dict]:
        """医疗器械品类分析"""
        try:
            pool = pg.get_pool()

            # 查询医疗相关品类
            medical_categories = await pool.fetch("""
                SELECT
                    category,
                    COUNT(*) as product_count,
                    AVG(retail_price) as avg_price,
                    SUM(CASE WHEN retail_price > 0 THEN 1 ELSE 0 END) as priced_products
                FROM qnh_products
                WHERE category LIKE '%医%' OR category LIKE '%急救%'
                   OR category LIKE '%护理%' OR name LIKE '%血压%'
                   OR name LIKE '%体温%' OR name LIKE '%血糖%'
                GROUP BY category
                HAVING COUNT(*) >= 5
                ORDER BY product_count DESC
            """)

            analysis = []
            for row in medical_categories:
                category = row["category"]

                # 分析该品类的器械类型分布
                device_types = {"一类器械": 0, "二类器械": 0, "三类器械": 0, "默认医疗": 0}

                # 获取该品类的商品样本
                samples = await pool.fetch(
                    """
                    SELECT name FROM qnh_products
                    WHERE category = $1 LIMIT 20
                """,
                    category,
                )

                for sample in samples:
                    device_type = MedicalDeviceService.classify_medical_device_type(
                        sample["name"], category
                    )
                    device_types[device_type] += 1

                # 确定主要器械类型
                main_type = max(device_types.items(), key=lambda x: x[1])[0]
                margin_reqs = MedicalDeviceService.get_medical_device_margin_requirements()

                analysis.append(
                    {
                        "category": category,
                        "product_count": int(row["product_count"]),
                        "avg_price": round(float(row["avg_price"] or 0), 2),
                        "priced_products": int(row["priced_products"]),
                        "main_device_type": main_type,
                        "recommended_margin": margin_reqs.get(main_type, 25),
                        "device_type_distribution": device_types,
                        "special_requirements": MedicalDeviceService._get_category_requirements(
                            category
                        ),
                    }
                )

            return analysis

        except Exception as e:
            logger.error(f"Failed to analyze medical categories: {e}")
            return []

    @staticmethod
    def _get_category_requirements(category: str) -> list[str]:
        """获取品类特殊要求"""
        requirements = []

        if "急救" in category:
            requirements.extend(
                ["应急使用场景，要求简单易操作", "包装需标注使用方法", "建议批量采购折扣"]
            )
        elif "口腔" in category:
            requirements.extend(["个人卫生用品，注意包装密封", "建议组合套装销售"])
        elif "消毒" in category or "杀菌" in category:
            requirements.extend(["注意有效期管理", "标注适用范围和浓度", "避免阳光直射存储"])

        return requirements
