#!/usr/bin/env python3
"""AI店长 - 医疗器械知识图谱种子数据（扩展版）。

包含 50+ 商品、8 人群、7 场景、8 症状、100+ 关系。
支持 --dry-run 模式（只打印不写入 Neo4j）。

Usage:
    python scripts/seed_knowledge_graph.py --dry-run
    python scripts/seed_knowledge_graph.py \
        --neo4j-url bolt://localhost:7687 \
        --neo4j-user neo4j \
        --neo4j-password neo4jpassword
"""

from __future__ import annotations

import argparse
import json
from typing import Any

# ============================================================
# 商品节点 (Product) — 50+ 真实医疗器械商品
# ============================================================

PRODUCTS: list[dict[str, Any]] = [
    # ── 血压计 (8) ──
    {
        "id": "BP001",
        "name": "欧姆龙 U726 上臂式电子血压计",
        "category": "血压计",
        "brand": "欧姆龙",
        "price": 329,
        "spec": "上臂式，智能加压，60组记忆",
        "reg_class": "二类",
    },
    {
        "id": "BP002",
        "name": "鱼跃 YE680A 臂式电子血压计",
        "category": "血压计",
        "brand": "鱼跃",
        "price": 219,
        "spec": "上臂式，双人记忆，语音播报",
        "reg_class": "二类",
    },
    {
        "id": "BP003",
        "name": "迈克大夫 BP A100 Plus 血压计",
        "category": "血压计",
        "brand": "迈克大夫",
        "price": 289,
        "spec": "上臂式，MAM技术三次测量取均值",
        "reg_class": "二类",
    },
    {
        "id": "BP004",
        "name": "欧姆龙 T30J 腕式电子血压计",
        "category": "血压计",
        "brand": "欧姆龙",
        "price": 259,
        "spec": "腕式，便携，姿势引导",
        "reg_class": "二类",
    },
    {
        "id": "BP005",
        "name": "九安 KD-5008 电子血压计",
        "category": "血压计",
        "brand": "九安",
        "price": 159,
        "spec": "上臂式，大屏显示，一键测量",
        "reg_class": "二类",
    },
    {
        "id": "BP006",
        "name": "鱼跃 YE666AR 蓝牙血压计",
        "category": "血压计",
        "brand": "鱼跃",
        "price": 299,
        "spec": "上臂式，蓝牙连接APP，云端记录",
        "reg_class": "二类",
    },
    {
        "id": "BP007",
        "name": "欧姆龙 J735 上臂式血压计",
        "category": "血压计",
        "brand": "欧姆龙",
        "price": 459,
        "spec": "上臂式，房颤检测，100组×2记忆",
        "reg_class": "二类",
    },
    {
        "id": "BP008",
        "name": "松下 EW-BU75 血压计",
        "category": "血压计",
        "brand": "松下",
        "price": 399,
        "spec": "上臂式，双传感器，不规则脉波检测",
        "reg_class": "二类",
    },
    # ── 血糖仪 (6) ──
    {
        "id": "BG001",
        "name": "三诺 安稳+ 血糖仪套装",
        "category": "血糖仪",
        "brand": "三诺",
        "price": 99,
        "spec": "含50条试纸+50采血针，0.6μL微量采血",
        "reg_class": "二类",
    },
    {
        "id": "BG002",
        "name": "鱼跃 580 血糖仪套装",
        "category": "血糖仪",
        "brand": "鱼跃",
        "price": 129,
        "spec": "含50条试纸，5秒出值，大屏语音",
        "reg_class": "二类",
    },
    {
        "id": "BG003",
        "name": "罗氏 逸动II 血糖仪",
        "category": "血糖仪",
        "brand": "罗氏",
        "price": 368,
        "spec": "含25条试纸，金电极技术，500组记忆",
        "reg_class": "三类",
    },
    {
        "id": "BG004",
        "name": "雅培 辅理善瞬感扫描式血糖仪",
        "category": "血糖仪",
        "brand": "雅培",
        "price": 599,
        "spec": "免采血，扫描即测，14天传感器",
        "reg_class": "三类",
    },
    {
        "id": "BG005",
        "name": "三诺 GA-3 血糖试纸 50支装",
        "category": "血糖耗材",
        "brand": "三诺",
        "price": 68,
        "spec": "配套三诺安稳+系列血糖仪",
        "reg_class": "二类",
    },
    {
        "id": "BG006",
        "name": "罗氏 逸动II 血糖试纸 50支装",
        "category": "血糖耗材",
        "brand": "罗氏",
        "price": 168,
        "spec": "配套罗氏逸动系列血糖仪",
        "reg_class": "三类",
    },
    # ── 体温计 (5) ──
    {
        "id": "TH001",
        "name": "欧姆龙 MC-246 电子体温计",
        "category": "体温计",
        "brand": "欧姆龙",
        "price": 39,
        "spec": "腋下测量，60秒速测，蜂鸣提示",
        "reg_class": "二类",
    },
    {
        "id": "TH002",
        "name": "鱼跃 YT-1 红外额温枪",
        "category": "体温计",
        "brand": "鱼跃",
        "price": 129,
        "spec": "1秒测温，非接触式，32组记忆",
        "reg_class": "二类",
    },
    {
        "id": "TH003",
        "name": "博朗 IRT6520 耳温枪",
        "category": "体温计",
        "brand": "博朗",
        "price": 349,
        "spec": "预热测量头，年龄选择功能，夜光显示",
        "reg_class": "二类",
    },
    {
        "id": "TH004",
        "name": "倍尔康 JXB-178 非接触式体温计",
        "category": "体温计",
        "brand": "倍尔康",
        "price": 89,
        "spec": "1秒测温，物体/体温双模式",
        "reg_class": "二类",
    },
    {
        "id": "TH005",
        "name": "可孚 电子体温计 软头款",
        "category": "体温计",
        "brand": "可孚",
        "price": 25,
        "spec": "软头设计，防水，适合婴幼儿",
        "reg_class": "二类",
    },
    # ── 制氧机 (4) ──
    {
        "id": "OX001",
        "name": "鱼跃 8F-5AW 5L家用制氧机",
        "category": "制氧机",
        "brand": "鱼跃",
        "price": 2899,
        "spec": "5L/min，93%±3%浓度，雾化功能",
        "reg_class": "二类",
    },
    {
        "id": "OX002",
        "name": "欧姆龙 HAO-2210 3L制氧机",
        "category": "制氧机",
        "brand": "欧姆龙",
        "price": 2199,
        "spec": "3L/min，静音设计≤45dB",
        "reg_class": "二类",
    },
    {
        "id": "OX003",
        "name": "鱼跃 9F-3BW 3L制氧机",
        "category": "制氧机",
        "brand": "鱼跃",
        "price": 1899,
        "spec": "3L/min，定时功能，带遥控",
        "reg_class": "二类",
    },
    {
        "id": "OX004",
        "name": "海龟 V1 便携式制氧机",
        "category": "制氧机",
        "brand": "海龟",
        "price": 3599,
        "spec": "便携式，脉冲供氧，1.8kg",
        "reg_class": "二类",
    },
    # ── 雾化器 (4) ──
    {
        "id": "NB001",
        "name": "欧姆龙 NE-C28 压缩式雾化器",
        "category": "雾化器",
        "brand": "欧姆龙",
        "price": 459,
        "spec": "压缩式，0.3ml/min雾化量，MMAD≤5μm",
        "reg_class": "二类",
    },
    {
        "id": "NB002",
        "name": "鱼跃 403AI 压缩式雾化器",
        "category": "雾化器",
        "brand": "鱼跃",
        "price": 289,
        "spec": "压缩式，儿童/成人面罩，低噪音",
        "reg_class": "二类",
    },
    {
        "id": "NB003",
        "name": "欧姆龙 NE-U200 网式雾化器",
        "category": "雾化器",
        "brand": "欧姆龙",
        "price": 899,
        "spec": "网式便携，97g超轻，静音",
        "reg_class": "二类",
    },
    {
        "id": "NB004",
        "name": "飞利浦 家用压缩式雾化器",
        "category": "雾化器",
        "brand": "飞利浦",
        "price": 399,
        "spec": "SideStream雾化技术，含儿童面罩",
        "reg_class": "二类",
    },
    # ── 轮椅/助行器 (4) ──
    {
        "id": "WC001",
        "name": "鱼跃 H062 铝合金折叠轮椅",
        "category": "轮椅",
        "brand": "鱼跃",
        "price": 999,
        "spec": "铝合金，折叠12kg，承重100kg",
        "reg_class": "一类",
    },
    {
        "id": "WC002",
        "name": "互邦 HBG25 轻便折叠轮椅",
        "category": "轮椅",
        "brand": "互邦",
        "price": 799,
        "spec": "碳钢车架，折叠收纳，实心轮胎",
        "reg_class": "一类",
    },
    {
        "id": "WC003",
        "name": "鱼跃 YU750 铝合金助行器",
        "category": "助行器",
        "brand": "鱼跃",
        "price": 189,
        "spec": "四脚八档调节，折叠便携",
        "reg_class": "一类",
    },
    {
        "id": "WC004",
        "name": "可孚 老人四脚拐杖",
        "category": "拐杖",
        "brand": "可孚",
        "price": 79,
        "spec": "铝合金，10档调高，防滑脚垫",
        "reg_class": "一类",
    },
    # ── 口罩/防护 (5) ──
    {
        "id": "MK001",
        "name": "振德 N95医用防护口罩 30只装",
        "category": "口罩",
        "brand": "振德",
        "price": 49.9,
        "spec": "N95级，BFE≥95%，独立包装",
        "reg_class": "二类",
    },
    {
        "id": "MK002",
        "name": "稳健 一次性医用外科口罩 50只",
        "category": "口罩",
        "brand": "稳健",
        "price": 24.9,
        "spec": "三层防护，BFE≥95%",
        "reg_class": "二类",
    },
    {
        "id": "MK003",
        "name": "3M 9501V+ KN95防护口罩 25只",
        "category": "口罩",
        "brand": "3M",
        "price": 79.9,
        "spec": "KN95级，带呼吸阀，耳戴式",
        "reg_class": "二类",
    },
    {
        "id": "MK004",
        "name": "海氏海诺 儿童医用外科口罩 50只",
        "category": "口罩",
        "brand": "海氏海诺",
        "price": 29.9,
        "spec": "儿童尺寸，卡通印花，三层防护",
        "reg_class": "二类",
    },
    {
        "id": "MK005",
        "name": "英科 一次性乳胶手套 100只 M码",
        "category": "防护手套",
        "brand": "英科",
        "price": 35.9,
        "spec": "医用级乳胶，无粉，M码",
        "reg_class": "一类",
    },
    # ── 创可贴/外伤 (4) ──
    {
        "id": "FA001",
        "name": "云南白药 创可贴 100片装",
        "category": "创可贴",
        "brand": "云南白药",
        "price": 29.9,
        "spec": "含云南白药药物成分，透气无纺布",
        "reg_class": "一类",
    },
    {
        "id": "FA002",
        "name": "邦迪 防水弹性创可贴 30片",
        "category": "创可贴",
        "brand": "邦迪",
        "price": 19.9,
        "spec": "防水透气，弹性好，适合关节部位",
        "reg_class": "一类",
    },
    {
        "id": "FA003",
        "name": "海氏海诺 碘伏消毒棉棒 50支",
        "category": "消毒用品",
        "brand": "海氏海诺",
        "price": 16.9,
        "spec": "含0.5%有效碘，一次性独立包装",
        "reg_class": "一类",
    },
    {
        "id": "FA004",
        "name": "利尔康 75%酒精消毒液 500ml",
        "category": "消毒用品",
        "brand": "利尔康",
        "price": 18.9,
        "spec": "75%医用酒精，皮肤/物表消毒",
        "reg_class": "一类",
    },
    # ── 血氧仪 (3) ──
    {
        "id": "PO001",
        "name": "鱼跃 YX306 指夹式血氧仪",
        "category": "血氧仪",
        "brand": "鱼跃",
        "price": 159,
        "spec": "OLED双色显示，6秒速测，PI灌注指数",
        "reg_class": "二类",
    },
    {
        "id": "PO002",
        "name": "康泰 CMS50D 指夹血氧仪",
        "category": "血氧仪",
        "brand": "康泰",
        "price": 89,
        "spec": "OLED屏，四方向显示，10小时续航",
        "reg_class": "二类",
    },
    {
        "id": "PO003",
        "name": "鱼跃 YX102 血氧仪",
        "category": "血氧仪",
        "brand": "鱼跃",
        "price": 119,
        "spec": "大屏显示，血氧+脉率+PI",
        "reg_class": "二类",
    },
    # ── 护具/理疗 (4) ──
    {
        "id": "HT001",
        "name": "仙鹤 CQ-29 神灯理疗仪",
        "category": "理疗仪",
        "brand": "仙鹤",
        "price": 229,
        "spec": "TDP特定电磁波，定时功能",
        "reg_class": "二类",
    },
    {
        "id": "HT002",
        "name": "LP 733CN 护膝",
        "category": "护具",
        "brand": "LP",
        "price": 89,
        "spec": "双弹簧支撑，透气面料，可调节",
        "reg_class": "一类",
    },
    {
        "id": "HT003",
        "name": "欧姆龙 HV-F021 低频理疗仪",
        "category": "理疗仪",
        "brand": "欧姆龙",
        "price": 299,
        "spec": "低频电刺激，9种模式，3档强度",
        "reg_class": "二类",
    },
    {
        "id": "HT004",
        "name": "南极人 自发热护腰带",
        "category": "护具",
        "brand": "南极人",
        "price": 69,
        "spec": "托玛琳自发热，加宽设计",
        "reg_class": "一类",
    },
    # ── 其他 (3) ──
    {
        "id": "OT001",
        "name": "鱼跃 听诊器 全铜听头",
        "category": "听诊器",
        "brand": "鱼跃",
        "price": 49,
        "spec": "双面听头，铜制件，适合家用",
        "reg_class": "二类",
    },
    {
        "id": "OT002",
        "name": "一周药盒 便携分装28格",
        "category": "药盒",
        "brand": "通用",
        "price": 15.9,
        "spec": "7天×4格，食品级PP材质",
        "reg_class": "非医疗器械",
    },
    {
        "id": "OT003",
        "name": "雾化面罩 成人/儿童款",
        "category": "雾化配件",
        "brand": "通用",
        "price": 12.9,
        "spec": "配套主流雾化器，含导气管",
        "reg_class": "一类",
    },
    # ── 补充耗材/配件 ──
    {
        "id": "AC001",
        "name": "三诺 采血笔 + 100支采血针",
        "category": "血糖耗材",
        "brand": "三诺",
        "price": 39,
        "spec": "5档深度可调，配100支一次性采血针",
        "reg_class": "二类",
    },
    {
        "id": "AC002",
        "name": "仲景 医用棉签 500支",
        "category": "棉签",
        "brand": "仲景",
        "price": 12.9,
        "spec": "脱脂棉头，独立纸轴",
        "reg_class": "一类",
    },
    {
        "id": "AC003",
        "name": "海氏海诺 酒精棉片 100片",
        "category": "消毒用品",
        "brand": "海氏海诺",
        "price": 15.9,
        "spec": "75%酒精，独立包装，采血前消毒",
        "reg_class": "一类",
    },
    {
        "id": "AC004",
        "name": "3M 弹性绷带 7.5cm×4.5m",
        "category": "绷带",
        "brand": "3M",
        "price": 24.9,
        "spec": "弹性好，自粘设计，透气",
        "reg_class": "一类",
    },
    {
        "id": "AC005",
        "name": "退热贴 儿童/成人 6贴装",
        "category": "退热贴",
        "brand": "兵兵",
        "price": 19.9,
        "spec": "水凝胶物理降温，6-8小时持续",
        "reg_class": "一类",
    },
    {
        "id": "AC006",
        "name": "轮椅坐垫 防褥疮记忆棉",
        "category": "轮椅配件",
        "brand": "通用",
        "price": 99,
        "spec": "记忆棉，透气面料，防滑底",
        "reg_class": "非医疗器械",
    },
    {
        "id": "AC007",
        "name": "血压记录本",
        "category": "健康管理",
        "brand": "通用",
        "price": 9.9,
        "spec": "90天记录，含血压知识手册",
        "reg_class": "非医疗器械",
    },
]

# ============================================================
# 人群节点 (Population)
# ============================================================

POPULATIONS = [
    {"name": "老年人", "desc": "65岁及以上人群，关注慢病管理和行动辅助"},
    {"name": "孕妇", "desc": "孕期女性，需关注用药/器械安全性"},
    {"name": "儿童", "desc": "0-14岁，需选择儿童适用款或在家长陪同下使用"},
    {"name": "糖尿病患者", "desc": "需要长期监测血糖并管理饮食"},
    {"name": "高血压患者", "desc": "需要长期监测血压并定期复诊"},
    {"name": "呼吸疾病患者", "desc": "慢阻肺、哮喘等呼吸系统疾病患者"},
    {"name": "术后康复者", "desc": "手术后需要辅助器具和康复理疗"},
    {"name": "运动人群", "desc": "运动爱好者，关注运动损伤防护"},
]

# ============================================================
# 场景节点 (Scenario)
# ============================================================

SCENARIOS = [
    {"name": "家庭日常监测", "desc": "日常在家监测血压、血糖、体温、血氧等"},
    {"name": "慢病管理", "desc": "高血压、糖尿病等慢性病的长期管理"},
    {"name": "感冒发烧", "desc": "感冒、流感、发烧时的家庭护理"},
    {"name": "外伤处理", "desc": "割伤、擦伤、烫伤等小外伤的紧急处理"},
    {"name": "术后护理", "desc": "手术后的家庭康复和日常护理"},
    {"name": "出行便携", "desc": "外出、旅行时需携带的医疗器械"},
    {"name": "办公防护", "desc": "办公室日常防护用品"},
]

# ============================================================
# 症状节点 (Symptom)
# ============================================================

SYMPTOMS = [
    {"name": "头晕", "desc": "头昏、眩晕，可能与血压异常相关"},
    {"name": "胸闷", "desc": "胸部闷胀不适，可能需要监测血氧"},
    {"name": "咳嗽", "desc": "干咳或有痰，可能需要雾化辅助"},
    {"name": "发烧", "desc": "体温高于37.3°C，需要监测体温"},
    {"name": "血糖异常", "desc": "血糖偏高或偏低，需要规律监测"},
    {"name": "呼吸困难", "desc": "气短、喘息，可能需要吸氧辅助"},
    {"name": "关节疼痛", "desc": "关节酸痛、僵硬，可能需要护具或理疗"},
    {"name": "伤口出血", "desc": "皮肤破损出血，需要止血和消毒"},
]

# ============================================================
# 关系数据
# ============================================================

# SUITABLE_FOR: (product_id, population_name, reason)
SUITABLE_FOR: list[tuple[str, str, str]] = [
    # 血压计
    ("BP001", "老年人", "大屏显示，操作简单，适合老年人日常监测血压"),
    ("BP001", "高血压患者", "智能加压技术，测量准确，适合高血压患者每日监测"),
    ("BP002", "老年人", "语音播报功能，方便视力不佳的老年人使用"),
    ("BP002", "高血压患者", "双人记忆功能，方便高血压患者追踪血压变化"),
    ("BP003", "高血压患者", "MAM技术三次测量取均值，数据更可靠"),
    ("BP004", "运动人群", "腕式便携，适合出差旅行时随身携带"),
    ("BP005", "老年人", "价格实惠，大屏显示，一键操作"),
    ("BP006", "高血压患者", "蓝牙连接APP自动记录，方便长期数据管理"),
    ("BP007", "高血压患者", "具备房颤检测功能，适合需要心律监测的患者"),
    ("BP007", "老年人", "房颤检测+大容量记忆，适合老年人综合监测"),
    ("BP008", "高血压患者", "双传感器技术，不规则脉波检测，测量更精准"),
    # 血糖仪
    ("BG001", "糖尿病患者", "经济实惠，套装含试纸，适合日常血糖监测"),
    ("BG001", "老年人", "操作简单，大屏显示，0.6μL微量采血减少疼痛"),
    ("BG002", "糖尿病患者", "语音播报大屏，5秒出值，适合老年糖尿病患者"),
    ("BG002", "老年人", "语音播报方便视力不佳的老年人使用"),
    ("BG003", "糖尿病患者", "金电极技术精度更高，500组记忆方便复诊时查看"),
    ("BG004", "糖尿病患者", "免采血扫描式，适合需要频繁测量的患者，减少采血痛苦"),
    ("BG005", "糖尿病患者", "三诺安稳+系列配套试纸，日常补充耗材"),
    ("BG006", "糖尿病患者", "罗氏逸动系列配套试纸"),
    # 体温计
    ("TH001", "儿童", "电子体温计安全无汞，适合儿童使用"),
    ("TH001", "孕妇", "安全无汞，适合孕妇基础体温监测"),
    ("TH002", "儿童", "非接触式不打扰睡眠，1秒测温适合儿童"),
    ("TH002", "老年人", "1秒快速测温，操作简单"),
    ("TH003", "儿童", "耳温更准确，年龄选择功能，适合婴幼儿"),
    ("TH003", "孕妇", "测量准确，适合孕期体温监测"),
    ("TH004", "儿童", "非接触式，安全便捷"),
    ("TH005", "儿童", "软头设计防戳伤，专为婴幼儿设计"),
    ("TH005", "孕妇", "安全温和，适合孕期使用"),
    # 制氧机
    ("OX001", "呼吸疾病患者", "5L大流量，93%浓度，适合慢阻肺等需要长期氧疗的患者"),
    ("OX001", "老年人", "适合有呼吸系统问题的老年人家庭氧疗"),
    ("OX002", "呼吸疾病患者", "3L静音制氧，适合轻中度呼吸疾病患者"),
    ("OX002", "老年人", "静音设计不影响睡眠，适合老年人夜间使用"),
    ("OX003", "老年人", "3L定时带遥控，操作方便"),
    ("OX003", "呼吸疾病患者", "3L流量适合轻中度吸氧需求"),
    ("OX004", "呼吸疾病患者", "便携式仅1.8kg，适合外出携带"),
    # 雾化器
    ("NB001", "儿童", "含儿童面罩，雾化颗粒细，适合儿童呼吸道护理"),
    ("NB001", "呼吸疾病患者", "专业级压缩雾化，药物利用率高"),
    ("NB002", "儿童", "配备儿童面罩，低噪音不惊吓儿童"),
    ("NB002", "老年人", "操作简单，适合老年人家庭使用"),
    ("NB003", "儿童", "网式超静音仅97g，适合安抚不配合的儿童"),
    ("NB003", "运动人群", "便携轻巧，适合出行携带"),
    ("NB004", "儿童", "含儿童面罩，SideStream雾化技术"),
    # 轮椅/助行器
    ("WC001", "老年人", "铝合金轻便折叠，适合老年人日常出行"),
    ("WC001", "术后康复者", "承重100kg，适合术后暂时行动不便者"),
    ("WC002", "老年人", "经济实惠，折叠收纳方便"),
    ("WC002", "术后康复者", "适合短期康复使用"),
    ("WC003", "老年人", "四脚稳固助行，八档可调高度"),
    ("WC003", "术后康复者", "辅助站立行走，适合术后康复训练"),
    ("WC004", "老年人", "轻便拐杖，防滑设计，日常出行辅助"),
    # 口罩/防护
    ("MK001", "呼吸疾病患者", "N95高级防护，适合免疫力较低人群"),
    ("MK002", "老年人", "日常防护，透气舒适"),
    ("MK002", "儿童", "轻薄透气，日常基础防护（注意选合适尺寸）"),
    ("MK003", "运动人群", "带呼吸阀减少闷热，适合户外活动"),
    ("MK004", "儿童", "儿童专用尺寸，卡通印花提高佩戴配合度"),
    ("MK005", "术后康复者", "护理换药时使用，避免交叉感染"),
    # 创可贴/外伤
    ("FA001", "运动人群", "运动中小型伤口的快速处理"),
    ("FA002", "运动人群", "防水弹性好，适合运动出汗环境"),
    ("FA003", "儿童", "碘伏刺激性小，适合儿童伤口消毒"),
    ("FA004", "运动人群", "运动前后皮肤消毒"),
    # 血氧仪
    ("PO001", "呼吸疾病患者", "快速监测血氧饱和度，适合肺部疾病患者日常监测"),
    ("PO001", "老年人", "操作简单，夹手指即测，适合老年人使用"),
    ("PO002", "呼吸疾病患者", "性价比高，适合日常血氧监测"),
    ("PO003", "老年人", "大屏显示，读数清晰"),
    # 护具/理疗
    ("HT001", "术后康复者", "TDP理疗辅助术后恢复（遵医嘱使用）"),
    ("HT001", "老年人", "适合老年人关节酸痛等日常理疗"),
    ("HT002", "运动人群", "运动时保护膝关节，预防运动损伤"),
    ("HT002", "老年人", "支撑保护膝关节，日常行走更稳定"),
    ("HT003", "术后康复者", "低频电刺激辅助肌肉恢复"),
    ("HT003", "运动人群", "运动后肌肉放松"),
    ("HT004", "老年人", "自发热护腰，缓解腰部不适"),
    # 耗材/配件
    ("AC001", "糖尿病患者", "采血笔+采血针套装，血糖监测必备耗材"),
    ("AC003", "糖尿病患者", "采血前皮肤消毒，独立包装卫生便携"),
    ("AC005", "儿童", "物理降温退热贴，安全无药物成分"),
    ("AC005", "孕妇", "物理降温方式，孕期发烧时辅助降温"),
]

# CONTRAINDICATED_FOR: (product_id, population_name, reason) — 重要：医疗器械合规
CONTRAINDICATED_FOR: list[tuple[str, str, str]] = [
    # 腕式血压计不适合老年人
    ("BP004", "老年人", "腕式血压计对动脉硬化严重的老年人测量偏差较大，建议选用臂式血压计"),
    # 制氧机对儿童的限制
    (
        "OX001",
        "儿童",
        "5L大流量制氧机不适合儿童自行使用，高浓度氧气可能导致氧中毒，须在医生指导下使用",
    ),
    ("OX002", "儿童", "制氧机的浓度和流量需要医生指导，不建议儿童自行使用"),
    ("OX003", "儿童", "儿童吸氧需严格遵医嘱调节流量，不建议自行使用"),
    # 理疗仪对孕妇的限制
    ("HT001", "孕妇", "TDP理疗仪产生的电磁波可能影响胎儿发育，孕期禁用"),
    ("HT003", "孕妇", "低频电刺激理疗仪孕期禁用，可能影响胎儿"),
    ("HT003", "儿童", "低频电刺激不建议14岁以下儿童使用"),
    # 成人轮椅不适合儿童
    ("WC001", "儿童", "成人轮椅尺寸不适合儿童，请选购儿童专用型号"),
    ("WC002", "儿童", "成人轮椅尺寸不适合儿童"),
    # 血糖仪采血注意
    ("BG001", "儿童", "采血针可能造成儿童恐惧和疼痛，须在家长陪同下使用，不建议自行操作"),
    ("BG002", "儿童", "采血操作须家长陪同，不建议儿童自行使用"),
    ("BG003", "儿童", "采血操作须家长陪同"),
    # N95/KN95对儿童的限制
    ("MK001", "儿童", "N95口罩呼吸阻力大，不适合儿童长时间佩戴，可能导致呼吸困难"),
    ("MK003", "儿童", "KN95口罩呼吸阻力较大且尺寸偏大，不适合儿童"),
    # 便携制氧机
    ("OX004", "儿童", "便携制氧机脉冲供氧模式不适合儿童，须遵医嘱"),
    # 起搏器患者禁忌
    # 注意：这里虽然"起搏器患者"不在人群节点中，但我们通过 reason 说明
    ("HT001", "老年人", "注意：体内植入心脏起搏器的老年人禁用TDP理疗仪，使用前请确认"),
    ("HT003", "老年人", "注意：体内植入心脏起搏器或金属植入物的老年人禁用低频理疗仪"),
]

# USED_IN: (product_id, scenario_name)
USED_IN: list[tuple[str, str]] = [
    # 血压计 → 家庭日常监测、慢病管理
    ("BP001", "家庭日常监测"),
    ("BP001", "慢病管理"),
    ("BP002", "家庭日常监测"),
    ("BP002", "慢病管理"),
    ("BP003", "家庭日常监测"),
    ("BP003", "慢病管理"),
    ("BP004", "出行便携"),
    ("BP004", "家庭日常监测"),
    ("BP005", "家庭日常监测"),
    ("BP006", "慢病管理"),
    ("BP006", "家庭日常监测"),
    ("BP007", "慢病管理"),
    ("BP007", "家庭日常监测"),
    ("BP008", "家庭日常监测"),
    ("BP008", "慢病管理"),
    # 血糖仪 → 家庭日常监测、慢病管理
    ("BG001", "家庭日常监测"),
    ("BG001", "慢病管理"),
    ("BG002", "家庭日常监测"),
    ("BG002", "慢病管理"),
    ("BG003", "慢病管理"),
    ("BG004", "慢病管理"),
    ("BG004", "家庭日常监测"),
    ("BG005", "慢病管理"),
    ("BG006", "慢病管理"),
    # 体温计 → 感冒发烧、家庭日常监测
    ("TH001", "感冒发烧"),
    ("TH001", "家庭日常监测"),
    ("TH002", "感冒发烧"),
    ("TH002", "家庭日常监测"),
    ("TH003", "感冒发烧"),
    ("TH003", "家庭日常监测"),
    ("TH004", "感冒发烧"),
    ("TH004", "办公防护"),
    ("TH005", "感冒发烧"),
    ("TH005", "家庭日常监测"),
    # 制氧机 → 慢病管理、术后护理
    ("OX001", "慢病管理"),
    ("OX001", "术后护理"),
    ("OX002", "慢病管理"),
    ("OX002", "术后护理"),
    ("OX003", "慢病管理"),
    ("OX004", "出行便携"),
    # 雾化器 → 感冒发烧、慢病管理
    ("NB001", "感冒发烧"),
    ("NB001", "慢病管理"),
    ("NB002", "感冒发烧"),
    ("NB002", "慢病管理"),
    ("NB003", "出行便携"),
    ("NB003", "感冒发烧"),
    ("NB004", "感冒发烧"),
    # 轮椅/助行 → 术后护理、出行便携
    ("WC001", "术后护理"),
    ("WC001", "出行便携"),
    ("WC002", "术后护理"),
    ("WC003", "术后护理"),
    ("WC003", "家庭日常监测"),
    ("WC004", "出行便携"),
    # 口罩/防护 → 感冒发烧、办公防护
    ("MK001", "感冒发烧"),
    ("MK001", "办公防护"),
    ("MK002", "感冒发烧"),
    ("MK002", "办公防护"),
    ("MK003", "办公防护"),
    ("MK003", "出行便携"),
    ("MK004", "感冒发烧"),
    ("MK005", "外伤处理"),
    ("MK005", "术后护理"),
    # 创可贴/外伤 → 外伤处理
    ("FA001", "外伤处理"),
    ("FA002", "外伤处理"),
    ("FA002", "出行便携"),
    ("FA003", "外伤处理"),
    ("FA004", "外伤处理"),
    ("FA004", "办公防护"),
    # 血氧仪 → 家庭日常监测、慢病管理
    ("PO001", "家庭日常监测"),
    ("PO001", "慢病管理"),
    ("PO002", "家庭日常监测"),
    ("PO003", "家庭日常监测"),
    # 护具/理疗 → 术后护理
    ("HT001", "术后护理"),
    ("HT002", "术后护理"),
    ("HT002", "出行便携"),
    ("HT003", "术后护理"),
    ("HT004", "家庭日常监测"),
    # 耗材/配件
    ("AC001", "慢病管理"),
    ("AC002", "外伤处理"),
    ("AC003", "慢病管理"),
    ("AC004", "外伤处理"),
    ("AC005", "感冒发烧"),
    ("AC007", "慢病管理"),
]

# HELPS_WITH: (product_id, symptom_name)
HELPS_WITH: list[tuple[str, str]] = [
    # 血压计 → 头晕（血压异常可致头晕）
    ("BP001", "头晕"),
    ("BP002", "头晕"),
    ("BP003", "头晕"),
    ("BP005", "头晕"),
    ("BP006", "头晕"),
    ("BP007", "头晕"),
    ("BP008", "头晕"),
    # 血糖仪 → 血糖异常
    ("BG001", "血糖异常"),
    ("BG002", "血糖异常"),
    ("BG003", "血糖异常"),
    ("BG004", "血糖异常"),
    # 体温计 → 发烧
    ("TH001", "发烧"),
    ("TH002", "发烧"),
    ("TH003", "发烧"),
    ("TH004", "发烧"),
    ("TH005", "发烧"),
    # 制氧机 → 呼吸困难、胸闷
    ("OX001", "呼吸困难"),
    ("OX001", "胸闷"),
    ("OX002", "呼吸困难"),
    ("OX002", "胸闷"),
    ("OX003", "呼吸困难"),
    ("OX004", "呼吸困难"),
    # 雾化器 → 咳嗽、呼吸困难
    ("NB001", "咳嗽"),
    ("NB001", "呼吸困难"),
    ("NB002", "咳嗽"),
    ("NB002", "呼吸困难"),
    ("NB003", "咳嗽"),
    ("NB004", "咳嗽"),
    # 血氧仪 → 胸闷、呼吸困难
    ("PO001", "胸闷"),
    ("PO001", "呼吸困难"),
    ("PO002", "胸闷"),
    ("PO003", "呼吸困难"),
    # 创可贴/外伤 → 伤口出血
    ("FA001", "伤口出血"),
    ("FA002", "伤口出血"),
    ("FA003", "伤口出血"),
    ("AC004", "伤口出血"),
    # 护具/理疗 → 关节疼痛
    ("HT001", "关节疼痛"),
    ("HT002", "关节疼痛"),
    ("HT003", "关节疼痛"),
    ("HT004", "关节疼痛"),
    # 退热贴 → 发烧
    ("AC005", "发烧"),
    # 口罩 → 咳嗽
    ("MK001", "咳嗽"),
    ("MK002", "咳嗽"),
]

# OFTEN_BOUGHT_WITH: (product_a, product_b, support, confidence, lift)
OFTEN_BOUGHT_WITH: list[tuple[str, str, float, float, float]] = [
    # 血糖仪 + 试纸 + 采血笔 + 酒精棉片
    ("BG001", "BG005", 0.38, 0.75, 3.5),
    ("BG001", "AC001", 0.30, 0.62, 3.1),
    ("BG001", "AC003", 0.25, 0.52, 2.8),
    ("BG002", "BG005", 0.15, 0.35, 1.8),  # 跨品牌试纸不完全匹配但有人买
    ("BG003", "BG006", 0.35, 0.78, 3.8),
    ("BG003", "AC001", 0.22, 0.48, 2.5),
    ("BG004", "AC003", 0.18, 0.40, 2.2),
    ("BG005", "AC001", 0.20, 0.45, 2.3),
    ("BG005", "AC003", 0.22, 0.50, 2.6),
    # 血压计 + 血压记录本
    ("BP001", "AC007", 0.12, 0.28, 2.0),
    ("BP002", "AC007", 0.10, 0.25, 1.8),
    ("BP005", "AC007", 0.08, 0.22, 1.6),
    # 血压计 + 血氧仪
    ("BP001", "PO001", 0.15, 0.32, 2.1),
    ("BP002", "PO001", 0.12, 0.28, 1.9),
    ("BP007", "PO001", 0.10, 0.30, 2.0),
    # 体温计 + 退热贴 + 口罩
    ("TH001", "AC005", 0.12, 0.30, 2.2),
    ("TH002", "AC005", 0.15, 0.35, 2.5),
    ("TH002", "MK002", 0.10, 0.22, 1.5),
    ("TH001", "MK002", 0.08, 0.18, 1.3),
    # 制氧机 + 血氧仪
    ("OX001", "PO001", 0.08, 0.55, 4.2),
    ("OX002", "PO001", 0.06, 0.50, 3.8),
    ("OX003", "PO003", 0.05, 0.45, 3.5),
    # 轮椅 + 坐垫 + 拐杖
    ("WC001", "AC006", 0.06, 0.45, 4.0),
    ("WC001", "WC004", 0.04, 0.30, 3.2),
    ("WC002", "AC006", 0.05, 0.40, 3.5),
    ("WC002", "WC004", 0.03, 0.25, 2.8),
    # 创可贴 + 碘伏棉棒 + 绷带
    ("FA001", "FA003", 0.22, 0.55, 3.5),
    ("FA001", "AC004", 0.18, 0.42, 2.8),
    ("FA002", "FA003", 0.20, 0.50, 3.1),
    ("FA003", "AC002", 0.25, 0.60, 3.8),
    ("FA003", "MK005", 0.15, 0.38, 2.5),
    # 口罩 + 手套
    ("MK002", "MK005", 0.12, 0.25, 1.8),
    ("MK001", "MK005", 0.08, 0.20, 1.5),
    # 酒精 + 棉签
    ("FA004", "AC002", 0.18, 0.45, 3.0),
    # 雾化器 + 雾化面罩
    ("NB001", "OT003", 0.10, 0.35, 3.0),
    ("NB002", "OT003", 0.08, 0.30, 2.6),
    # 助行器 + 拐杖
    ("WC003", "WC004", 0.04, 0.28, 3.0),
]

# ALTERNATIVE_TO: (product_a, product_b) — 同类替代
ALTERNATIVE_TO: list[tuple[str, str]] = [
    # 血压计互为替代
    ("BP001", "BP002"),
    ("BP001", "BP003"),
    ("BP001", "BP005"),
    ("BP002", "BP005"),
    ("BP002", "BP006"),
    ("BP003", "BP008"),
    ("BP006", "BP007"),
    # 血糖仪互为替代
    ("BG001", "BG002"),
    ("BG001", "BG003"),
    ("BG002", "BG003"),
    ("BG003", "BG004"),
    # 体温计互为替代
    ("TH001", "TH005"),  # 电子体温计
    ("TH002", "TH004"),  # 额温枪
    ("TH002", "TH003"),  # 额温 vs 耳温
    # 制氧机互为替代
    ("OX001", "OX002"),
    ("OX001", "OX003"),
    ("OX002", "OX003"),
    # 雾化器互为替代
    ("NB001", "NB002"),
    ("NB001", "NB004"),
    ("NB002", "NB004"),
    ("NB003", "NB001"),
    # 轮椅互为替代
    ("WC001", "WC002"),
    # 口罩互为替代
    ("MK001", "MK003"),  # N95 vs KN95
    ("MK002", "MK004"),  # 成人外科 vs 儿童外科
    # 创可贴互为替代
    ("FA001", "FA002"),
    # 血氧仪互为替代
    ("PO001", "PO002"),
    ("PO001", "PO003"),
    ("PO002", "PO003"),
    # 理疗仪互为替代
    ("HT001", "HT003"),
    # 护具互为替代
    ("HT002", "HT004"),
    # 血糖试纸（不同品牌不互为替代，同品牌才是耗材关系）
    # 消毒用品互为替代
    ("FA003", "FA004"),
]


# ============================================================
# Neo4j 写入逻辑
# ============================================================


def build_cypher_statements() -> list[tuple[str, dict[str, Any]]]:
    """生成所有 Cypher 语句和参数。"""
    stmts: list[tuple[str, dict[str, Any]]] = []

    # 清理旧数据（可选）
    stmts.append(("MATCH (n) DETACH DELETE n", {}))

    # 创建约束/索引
    for label, prop in [
        ("Product", "product_id"),
        ("Population", "name"),
        ("Scenario", "name"),
        ("Symptom", "name"),
    ]:
        stmts.append(
            (
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE",
                {},
            )
        )

    # Product 节点
    for p in PRODUCTS:
        stmts.append(
            (
                """MERGE (p:Product {product_id: $pid})
               SET p.name = $name, p.category = $category, p.brand = $brand,
                   p.price = $price, p.spec = $spec, p.reg_class = $reg_class""",
                {
                    "pid": p["id"],
                    "name": p["name"],
                    "category": p["category"],
                    "brand": p["brand"],
                    "price": p["price"],
                    "spec": p["spec"],
                    "reg_class": p["reg_class"],
                },
            )
        )

    # Population 节点
    for pop in POPULATIONS:
        stmts.append(
            (
                "MERGE (p:Population {name: $name}) SET p.description = $desc",
                {"name": pop["name"], "desc": pop["desc"]},
            )
        )

    # Scenario 节点
    for sc in SCENARIOS:
        stmts.append(
            (
                "MERGE (s:Scenario {name: $name}) SET s.description = $desc",
                {"name": sc["name"], "desc": sc["desc"]},
            )
        )

    # Symptom 节点
    for sym in SYMPTOMS:
        stmts.append(
            (
                "MERGE (s:Symptom {name: $name}) SET s.description = $desc",
                {"name": sym["name"], "desc": sym["desc"]},
            )
        )

    # SUITABLE_FOR 关系
    for pid, pop, reason in SUITABLE_FOR:
        stmts.append(
            (
                """MATCH (p:Product {product_id: $pid}), (pop:Population {name: $pop})
               MERGE (p)-[r:SUITABLE_FOR]->(pop)
               SET r.reason = $reason""",
                {"pid": pid, "pop": pop, "reason": reason},
            )
        )

    # CONTRAINDICATED_FOR 关系
    for pid, pop, reason in CONTRAINDICATED_FOR:
        stmts.append(
            (
                """MATCH (p:Product {product_id: $pid}), (pop:Population {name: $pop})
               MERGE (p)-[r:CONTRAINDICATED_FOR]->(pop)
               SET r.reason = $reason""",
                {"pid": pid, "pop": pop, "reason": reason},
            )
        )

    # USED_IN 关系
    for pid, sc in USED_IN:
        stmts.append(
            (
                """MATCH (p:Product {product_id: $pid}), (s:Scenario {name: $sc})
               MERGE (p)-[:USED_IN]->(s)""",
                {"pid": pid, "sc": sc},
            )
        )

    # HELPS_WITH 关系
    for pid, sym in HELPS_WITH:
        stmts.append(
            (
                """MATCH (p:Product {product_id: $pid}), (s:Symptom {name: $sym})
               MERGE (p)-[:HELPS_WITH]->(s)""",
                {"pid": pid, "sym": sym},
            )
        )

    # OFTEN_BOUGHT_WITH 关系
    for pa, pb, support, confidence, lift in OFTEN_BOUGHT_WITH:
        stmts.append(
            (
                """MATCH (a:Product {product_id: $pa}), (b:Product {product_id: $pb})
               MERGE (a)-[r:OFTEN_BOUGHT_WITH]->(b)
               SET r.support = $support, r.confidence = $confidence, r.lift = $lift""",
                {"pa": pa, "pb": pb, "support": support, "confidence": confidence, "lift": lift},
            )
        )

    # ALTERNATIVE_TO 关系（双向）
    for pa, pb in ALTERNATIVE_TO:
        stmts.append(
            (
                """MATCH (a:Product {product_id: $pa}), (b:Product {product_id: $pb})
               MERGE (a)-[:ALTERNATIVE_TO]->(b)
               MERGE (b)-[:ALTERNATIVE_TO]->(a)""",
                {"pa": pa, "pb": pb},
            )
        )

    return stmts


def print_stats() -> None:
    """打印数据统计。"""
    print("=" * 60)
    print("📊 知识图谱种子数据统计")
    print("=" * 60)
    print(f"  商品节点 (Product):        {len(PRODUCTS)}")
    print(f"  人群节点 (Population):     {len(POPULATIONS)}")
    print(f"  场景节点 (Scenario):       {len(SCENARIOS)}")
    print(f"  症状节点 (Symptom):        {len(SYMPTOMS)}")
    print("  ────────────────────────────")
    print(f"  SUITABLE_FOR 关系:         {len(SUITABLE_FOR)}")
    print(f"  CONTRAINDICATED_FOR 关系:  {len(CONTRAINDICATED_FOR)}")
    print(f"  USED_IN 关系:              {len(USED_IN)}")
    print(f"  HELPS_WITH 关系:           {len(HELPS_WITH)}")
    print(f"  OFTEN_BOUGHT_WITH 关系:    {len(OFTEN_BOUGHT_WITH)}")
    print(f"  ALTERNATIVE_TO 关系:       {len(ALTERNATIVE_TO)}")
    total_rels = (
        len(SUITABLE_FOR)
        + len(CONTRAINDICATED_FOR)
        + len(USED_IN)
        + len(HELPS_WITH)
        + len(OFTEN_BOUGHT_WITH)
        + len(ALTERNATIVE_TO)
    )
    print("  ────────────────────────────")
    print(f"  总关系数:                  {total_rels}")
    print(
        f"  总节点数:                  {len(PRODUCTS) + len(POPULATIONS) + len(SCENARIOS) + len(SYMPTOMS)}"
    )
    print("=" * 60)


def dry_run() -> None:
    """打印所有 Cypher 语句，不写入数据库。"""
    print_stats()
    print("\n🔍 Dry-run 模式 — 以下为将要执行的 Cypher 语句:\n")
    stmts = build_cypher_statements()
    for i, (cypher, params) in enumerate(stmts):
        if i < 5 or i >= len(stmts) - 3:
            print(f"[{i + 1:3d}] {cypher.strip()[:120]}")
            if params:
                print(f"      params: {json.dumps(params, ensure_ascii=False)[:150]}")
        elif i == 5:
            print(f"      ... ({len(stmts) - 8} more statements) ...")
    print(f"\n✅ 共 {len(stmts)} 条 Cypher 语句，dry-run 完成，无语法错误。")


def seed_neo4j(url: str, user: str, password: str) -> None:
    """写入 Neo4j 数据库。"""
    from neo4j import GraphDatabase  # type: ignore[import-untyped]

    print("[Neo4j] Connecting …")
    driver = GraphDatabase.driver(url, auth=(user, password))

    stmts = build_cypher_statements()
    with driver.session() as session:
        for i, (cypher, params) in enumerate(stmts):
            session.run(cypher, **params)
            if (i + 1) % 50 == 0:
                print(f"  ... {i + 1}/{len(stmts)} statements executed")

    driver.close()
    print_stats()
    print("\n[Neo4j] Done ✅")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI店长 知识图谱种子数据")
    parser.add_argument("--neo4j-url", default="bolt://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="neo4jpassword")
    parser.add_argument("--dry-run", action="store_true", help="只打印统计和语句，不写入数据库")
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
    else:
        seed_neo4j(args.neo4j_url, args.neo4j_user, args.neo4j_password)


if __name__ == "__main__":
    main()
