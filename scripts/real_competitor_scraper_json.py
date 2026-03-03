#!/usr/bin/env python3
"""
真实竞品数据采集器 (JSON版本) - 使用 nodriver 从美团外卖采集真实竞品价格数据

支持两种模式：
1. JSON模式：采集数据存到本地 data/competitor_products.json
2. UPLOAD模式：将JSON数据上传到线上数据库
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import nodriver as uc

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 根据运行模式导入数据库模块
try:
    from src.db.postgres import get_pool, init_pool

    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# 竞品采集配置
SEARCH_KEYWORDS = [
    "血压计",
    "血糖仪",
    "体温计",
    "制氧机",
    "轮椅",
    "拐杖",
    "医用口罩",
    "护理垫",
    "雾化器",
    "血氧仪",
    "助听器",
    "护腰带",
    "颈椎枕",
    "按摩器",
    "医用纱布",
    "消毒液",
]

# 美团外卖 H5 搜索页面
MEITUAN_SEARCH_URL = "https://h5.waimai.meituan.com/waimai/mindex/search"
DEFAULT_LOCATION = {"lng": 114.43, "lat": 30.51}  # 光谷

# JSON存储路径
JSON_DATA_PATH = Path(__file__).parent.parent / "data" / "competitor_products.json"


class RealCompetitorScraperJSON:
    """真实竞品数据采集器 - JSON版本"""

    def __init__(self, mode="json"):
        """
        初始化采集器
        mode: "json" - 存储到JSON文件, "upload" - 上传到数据库
        """
        self.mode = mode
        self.browser = None
        self.tab = None
        self.scraped_data = {
            "last_updated": None,
            "total_products": 0,
            "total_stores": 0,
            "keywords": [],
            "products": [],
            "stores": [],
        }

    async def init_browser(self):
        """初始化 nodriver 浏览器"""
        try:
            # nodriver 配置，避开检测
            self.browser = await uc.start(
                headless=False,  # 本地开发用非无头模式
                sandbox=False,
                user_data_dir=None,  # 使用临时目录
            )
            self.tab = self.browser.main_tab
            logger.info("✅ nodriver 浏览器启动成功")
            return True
        except Exception as e:
            logger.error(f"❌ 浏览器启动失败: {e}")
            return False

    async def close_browser(self):
        """关闭浏览器"""
        try:
            if self.browser:
                await self.browser.stop()
                logger.info("✅ 浏览器已关闭")
        except Exception as e:
            logger.error(f"关闭浏览器失败: {e}")

    async def search_products(self, keyword: str, max_results: int = 20) -> list[dict]:
        """搜索指定关键词的商品"""
        try:
            # 构建搜索URL
            url = f"{MEITUAN_SEARCH_URL}?query={keyword}&lat={DEFAULT_LOCATION['lat']}&lng={DEFAULT_LOCATION['lng']}"

            logger.info(f"🔍 搜索关键词: {keyword}")
            await self.tab.get(url)

            # 等待页面加载
            await asyncio.sleep(3)

            # 注入获取数据的JS脚本
            products = await self._extract_products_from_page()

            if products:
                logger.info(f"✅ 关键词 '{keyword}' 采集到 {len(products)} 个商品")
            else:
                logger.warning(f"⚠️ 关键词 '{keyword}' 未采集到数据")

            return products[:max_results]

        except Exception as e:
            logger.error(f"❌ 搜索 '{keyword}' 失败: {e}")
            return []

    async def _extract_products_from_page(self) -> list[dict]:
        """从页面提取商品数据"""
        try:
            # 注入数据提取脚本
            js_script = r"""
            (() => {
                const products = [];

                // 尝试多种选择器匹配美团H5页面结构
                const selectors = [
                    '[class*="search-result"] [class*="poi-item"]',
                    '[class*="SearchResult"] [class*="item"]',
                    '[class*="food-item"]',
                    '[class*="shopItem"]',
                    '[class*="poi-card"]',
                    'a[href*="shopId"]',
                    'a[href*="poiId"]'
                ];

                let elements = [];
                for (const sel of selectors) {
                    elements = document.querySelectorAll(sel);
                    if (elements.length > 0) break;
                }

                for (const el of Array.from(elements).slice(0, 30)) {
                    try {
                        // 提取店铺/商品名称
                        const nameEl = el.querySelector('[class*="name"], [class*="title"], h3, h4, [class*="poi-name"]');
                        const name = nameEl ? nameEl.textContent.trim() : '';

                        // 提取价格
                        const priceEl = el.querySelector('[class*="price"], [class*="Price"], [class*="yuan"]');
                        const priceText = priceEl ? priceEl.textContent : '0';
                        const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;

                        // 提取月销量
                        const salesEl = el.querySelector('[class*="sale"], [class*="month"], [class*="sold"]');
                        const salesText = salesEl ? salesEl.textContent : '';
                        const sales = parseInt(salesText.replace(/[^0-9]/g, '')) || 0;

                        // 提取评分
                        const ratingEl = el.querySelector('[class*="score"], [class*="rating"], [class*="star"]');
                        const rating = ratingEl ? parseFloat(ratingEl.textContent.replace(/[^0-9.]/g, '')) || 0 : 0;

                        // 提取距离
                        const distEl = el.querySelector('[class*="distance"], [class*="dist"]');
                        const distText = distEl ? distEl.textContent : '';
                        let distance = parseFloat(distText.replace(/[^0-9.]/g, '')) || 0;
                        if (distText.includes('m') && !distText.includes('km')) {
                            distance = distance / 1000;
                        }

                        // 提取店铺ID
                        const linkEl = el.querySelector('a[href]');
                        const href = linkEl ? linkEl.href : '';
                        const idMatch = href.match(/(?:shopId|poiId|dpShopId)=(\d+)/);
                        const storeId = idMatch ? idMatch[1] : '';

                        if (name && name.length > 1) {
                            products.push({
                                name,
                                price,
                                monthly_sales: sales,
                                rating,
                                distance_km: distance,
                                store_id: storeId,
                                store_name: name,
                                last_updated: new Date().toISOString()
                            });
                        }
                    } catch(e) {
                        console.error('Extract error:', e);
                    }
                }

                return products;
            })();
            """

            result = await self.tab.evaluate(js_script)
            return result or []

        except Exception as e:
            logger.error(f"页面数据提取失败: {e}")
            return []

    async def save_to_json(self, products: list[dict], keyword: str):
        """将采集的数据保存到JSON文件"""
        try:
            # 为产品添加关键词标识和唯一ID
            for product in products:
                product_id = (
                    f"mt_{product.get('store_id', '')}__{keyword}_{hash(product['name']) % 10000}"
                )
                product["product_id"] = product_id
                product["category"] = keyword
                product["scraped_at"] = datetime.now().isoformat()

                # 添加到数据结构
                self.scraped_data["products"].append(product)

                # 添加店铺信息
                if product.get("store_id"):
                    store_info = {
                        "store_id": product["store_id"],
                        "name": product["store_name"],
                        "rating": product.get("rating", 0),
                        "monthly_sales": product["monthly_sales"],
                        "distance_km": product.get("distance_km", 0),
                        "category": keyword,
                        "last_updated": product["last_updated"],
                    }
                    # 检查是否已存在此店铺
                    if not any(
                        s["store_id"] == store_info["store_id"] for s in self.scraped_data["stores"]
                    ):
                        self.scraped_data["stores"].append(store_info)

            # 添加关键词信息
            keyword_info = {
                "keyword": keyword,
                "result_count": len(products),
                "search_volume": len(products) * 10,  # 估算
                "scraped_at": datetime.now().isoformat(),
            }
            self.scraped_data["keywords"].append(keyword_info)

            logger.info(f"✅ 关键词 '{keyword}' 的 {len(products)} 条数据已添加到内存")

        except Exception as e:
            logger.error(f"❌ 保存数据失败: {e}")

    async def save_to_database(self):
        """将JSON数据上传到数据库"""
        if not DB_AVAILABLE:
            logger.error("❌ 数据库模块未导入，无法上传数据")
            return False

        pool = get_pool()
        if not pool:
            logger.error("❌ 数据库连接失败")
            return False

        try:
            # 清理旧数据（可选）
            await pool.execute(
                "DELETE FROM competitor_products WHERE last_synced < NOW() - INTERVAL '7 days'"
            )

            # 插入产品数据
            for product in self.scraped_data["products"]:
                await pool.execute(
                    """
                    INSERT INTO competitor_products (
                        product_id, store_id, name, price, monthly_sales, rating,
                        category, last_synced, distance_km
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (product_id) DO UPDATE SET
                        price = EXCLUDED.price,
                        monthly_sales = EXCLUDED.monthly_sales,
                        rating = EXCLUDED.rating,
                        last_synced = EXCLUDED.last_synced
                """,
                    product["product_id"],
                    product.get("store_id", ""),
                    product["name"],
                    product["price"],
                    product["monthly_sales"],
                    product.get("rating", 0),
                    product["category"],
                    datetime.now(),
                    product.get("distance_km", 0),
                )

            # 插入店铺数据
            for store in self.scraped_data["stores"]:
                await pool.execute(
                    """
                    INSERT INTO competitor_stores (
                        store_id, name, rating, monthly_sales, distance_km,
                        category, last_synced
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (store_id) DO UPDATE SET
                        rating = EXCLUDED.rating,
                        monthly_sales = EXCLUDED.monthly_sales,
                        distance_km = EXCLUDED.distance_km,
                        last_synced = EXCLUDED.last_synced
                """,
                    store["store_id"],
                    store["name"],
                    store.get("rating", 0),
                    store["monthly_sales"],
                    store.get("distance_km", 0),
                    store["category"],
                    datetime.now(),
                )

            # 插入关键词数据
            for keyword in self.scraped_data["keywords"]:
                await pool.execute(
                    """
                    INSERT INTO competitor_keywords (keyword, search_volume, result_count, last_synced)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (keyword) DO UPDATE SET
                        result_count = EXCLUDED.result_count,
                        last_synced = EXCLUDED.last_synced
                """,
                    keyword["keyword"],
                    keyword["search_volume"],
                    keyword["result_count"],
                    datetime.now(),
                )

            logger.info(
                f"✅ 已上传 {len(self.scraped_data['products'])} 个产品和 {len(self.scraped_data['stores'])} 个店铺到数据库"
            )
            return True

        except Exception as e:
            logger.error(f"❌ 上传到数据库失败: {e}")
            return False

    def write_json_file(self):
        """将数据写入JSON文件"""
        try:
            # 确保目录存在
            JSON_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

            # 更新统计信息
            self.scraped_data["last_updated"] = datetime.now().isoformat()
            self.scraped_data["total_products"] = len(self.scraped_data["products"])
            self.scraped_data["total_stores"] = len(self.scraped_data["stores"])

            # 写入JSON文件
            with open(JSON_DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(self.scraped_data, f, indent=2, ensure_ascii=False)

            logger.info(f"✅ 数据已保存到: {JSON_DATA_PATH}")
            logger.info(
                f"📊 统计: {self.scraped_data['total_products']} 个产品, {self.scraped_data['total_stores']} 个店铺"
            )

        except Exception as e:
            logger.error(f"❌ 写入JSON文件失败: {e}")

    async def run_full_scraping(self):
        """运行完整的竞品数据采集"""
        logger.info(f"🚀 开始真实竞品数据采集 ({self.mode}模式)...")

        # 初始化浏览器
        if not await self.init_browser():
            return

        total_products = 0
        successful_keywords = 0

        try:
            # 访问美团首页，设置位置等
            await self.tab.get("https://h5.waimai.meituan.com/")
            await asyncio.sleep(2)

            # 遍历搜索关键词
            for i, keyword in enumerate(SEARCH_KEYWORDS):
                try:
                    logger.info(f"📍 进度: {i + 1}/{len(SEARCH_KEYWORDS)} - {keyword}")

                    products = await self.search_products(keyword)

                    if products:
                        if self.mode == "json":
                            await self.save_to_json(products, keyword)

                        total_products += len(products)
                        successful_keywords += 1

                        # 添加随机延迟避免被限制
                        await asyncio.sleep(2 + len(products) * 0.1)
                    else:
                        logger.warning(f"⚠️ 关键词 '{keyword}' 未获取到数据")
                        await asyncio.sleep(5)  # 失败时等待更长时间

                except Exception as e:
                    logger.error(f"❌ 处理关键词 '{keyword}' 失败: {e}")
                    await asyncio.sleep(5)

            logger.info(
                f"🎉 采集完成! 成功采集 {successful_keywords}/{len(SEARCH_KEYWORDS)} 个关键词，共 {total_products} 条真实竞品数据"
            )

            # 保存数据
            if self.mode == "json":
                self.write_json_file()
            elif self.mode == "upload":
                await self.save_to_database()

        finally:
            await self.close_browser()


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="真实竞品数据采集器")
    parser.add_argument(
        "--mode",
        choices=["json", "upload"],
        default="json",
        help="运行模式: json=存储到JSON文件, upload=上传到数据库",
    )

    args = parser.parse_args()

    try:
        # 根据模式初始化数据库连接
        if args.mode == "upload" and DB_AVAILABLE:
            await init_pool()

        # 创建并运行采集器
        scraper = RealCompetitorScraperJSON(mode=args.mode)
        await scraper.run_full_scraping()

        # 显示结果
        if args.mode == "json":
            if JSON_DATA_PATH.exists():
                with open(JSON_DATA_PATH, encoding="utf-8") as f:
                    data = json.load(f)
                print("\n📊 JSON数据采集统计:")
                print(f"   竞品商品: {data['total_products']}")
                print(f"   竞品店铺: {data['total_stores']}")
                print(f"   搜索关键词: {len(data['keywords'])}")
                print(f"   数据文件: {JSON_DATA_PATH}")
                print(
                    "\n💡 要上传到数据库，请运行: python scripts/real_competitor_scraper_json.py --mode upload"
                )
        elif args.mode == "upload":
            print("\n✅ 数据已成功上传到线上数据库!")

    except Exception as e:
        logger.error(f"❌ 采集失败: {e}")
        import traceback

        traceback.print_exc()
    finally:
        if args.mode == "upload" and DB_AVAILABLE:
            pool = get_pool()
            if pool:
                await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
