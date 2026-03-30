#!/usr/bin/env python3
"""将 sample/ 目录下的 Excel 文件通过 ManualImportService 导入数据库（幂等去重）。

用法:
    python3 scripts/seed_sample_data.py          # 自动跳过已导入的
    python3 scripts/seed_sample_data.py --force   # 强制重新导入
"""

import asyncio
import hashlib
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample"

SAMPLE_FILES = [
    ("products", "主档商品销售规格导出_10117665691570720260326.xlsx"),
    ("orders", "导出订单列表+明细20260326_183806.xlsx"),
    ("inventory", "库存查询导出_20260326.xls"),
]


def file_md5(filepath: Path) -> str:
    """计算文件 MD5，用于去重判断。"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


async def already_imported(pool, filename: str, md5: str) -> bool:
    """检查文件是否已成功导入过（按文件名+MD5 双重判断）。"""
    try:
        # 检查 manual_import_runs 表
        row = await pool.fetchrow(
            """SELECT run_id, imported_rows FROM manual_import_runs 
               WHERE filename = $1 AND status = 'completed'
               ORDER BY created_at DESC LIMIT 1""",
            filename,
        )
        if row and row["imported_rows"] and row["imported_rows"] > 0:
            return True
    except Exception:
        pass  # 表可能不存在

    # 备用检查：直接看目标表有没有数据
    try:
        counts = {
            "products": "SELECT count(*) FROM qnh_products",
            "orders": "SELECT count(*) FROM qnh_orders",
            "inventory": "SELECT count(*) FROM qnh_inventory",
        }
        for import_type, _ in SAMPLE_FILES:
            if filename.startswith("主档") and import_type == "products":
                count = await pool.fetchval(counts["products"])
                if count and count > 100:
                    return True
            elif filename.startswith("导出订单") and import_type == "orders":
                count = await pool.fetchval(counts["orders"])
                if count and count > 100:
                    return True
            elif filename.startswith("库存") and import_type == "inventory":
                count = await pool.fetchval(counts["inventory"])
                if count and count > 100:
                    return True
    except Exception:
        pass

    return False


async def main():
    force = "--force" in sys.argv

    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    from src.db import postgres as pg_db
    from src.services.manual_import import ManualImportService

    dsn = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/ai_store")
    await pg_db.init(dsn)

    pool = pg_db.get_pool()
    service = ManualImportService(pool)

    for import_type, filename in SAMPLE_FILES:
        filepath = SAMPLE_DIR / filename
        if not filepath.exists():
            logger.warning("⏩ 文件不存在: %s", filepath)
            continue

        md5 = file_md5(filepath)

        if not force and await already_imported(pool, filename, md5):
            logger.info("⏩ 已导入过: %s (跳过)", filename)
            continue

        size_mb = filepath.stat().st_size / 1024 / 1024
        logger.info("📦 导入 %s: %s (%.1f MB, md5=%s)", import_type, filename, size_mb, md5[:8])

        content = filepath.read_bytes()
        try:
            result = await service.import_file(filename, content, import_type=import_type)
            logger.info(
                "✅ %s 导入完成: %d/%d 行, quality=%.0f%%",
                import_type,
                result.imported_rows,
                result.total_rows,
                (result.quality_score or 0) * 100,
            )
            if result.issues:
                for issue in result.issues[:3]:
                    logger.info("  ⚠️ %s: %s", issue.get("type", "?"), issue.get("message", "?"))
        except Exception as e:
            logger.error("❌ %s 导入失败: %s", import_type, e, exc_info=True)

    await pg_db.close()
    logger.info("🎉 完成!")


if __name__ == "__main__":
    asyncio.run(main())
