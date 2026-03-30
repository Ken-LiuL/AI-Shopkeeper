#!/usr/bin/env python3
"""将 sample/ 目录下的 Excel 文件通过 ManualImportService 导入数据库。

用法:
    # 在 Docker 容器内运行（自动使用 DATABASE_URL）
    python3 scripts/seed_sample_data.py

    # 强制重新导入
    python3 scripts/seed_sample_data.py --force
"""

import asyncio
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


async def main():
    force = "--force" in sys.argv

    # 添加项目根目录到 path
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    from src.db import postgres as pg_db
    from src.services.manual_import import ManualImportService

    # 初始化数据库连接
    dsn = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/ai_store")
    await pg_db.init(dsn)

    pool = pg_db.get_pool()
    service = ManualImportService(pool)

    for import_type, filename in SAMPLE_FILES:
        filepath = SAMPLE_DIR / filename
        if not filepath.exists():
            logger.warning("⏩ 文件不存在: %s", filepath)
            continue

        # 检查是否已导入过（查 manual_import_runs 表）
        if not force:
            try:
                existing = await pool.fetchval(
                    "SELECT count(*) FROM manual_import_runs WHERE filename = $1 AND status = 'completed'",
                    filename,
                )
                if existing and existing > 0:
                    logger.info("⏩ 已导入过: %s（使用 --force 强制重新导入）", filename)
                    continue
            except Exception:
                pass  # 表可能不存在

        logger.info("📦 导入 %s: %s (%.1f MB)", import_type, filename, filepath.stat().st_size / 1024 / 1024)

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
    logger.info("🎉 数据导入完成!")


if __name__ == "__main__":
    asyncio.run(main())
