"""FastAPI application entry point for AI Store Manager."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.alerts import router as alerts_router
from src.api.analytics import router as analytics_router
from src.api.bundles import router as bundles_router
from src.api.chat import router as chat_router
from src.api.competitors import router as competitors_router
from src.api.customer_service import router as cs_router
from src.api.dashboard import router as dashboard_router
from src.api.errors import register_error_handlers
from src.api.insights import router as insights_router
from src.api.inventory import router as inventory_router
from src.api.knowledge import router as knowledge_router
from src.api.listing import router as listing_router
from src.api.metrics_api import router as metrics_router
from src.api.orders import router as orders_router
from src.api.pricing import products_pricing_router
from src.api.pricing import router as pricing_router
from src.api.pricing_intelligence import router as pricing_intel_router
from src.api.products import router as products_router
from src.api.products import v1_router as products_v1_router
from src.api.replenishment import router as replenishment_router
from src.api.reports import router as reports_router
from src.api.store_config import router as store_config_router
from src.api.selection import router as selection_router
from src.api.selection_intelligence import router as selection_intel_router
from src.api.stores import router as stores_router
from src.api.sync import router as sync_router
from src.api.sync_receiver import router as sync_receiver_router
from src.api.sync_status import router as sync_status_router
from src.api.system import router as system_router
from src.auth.router import router as auth_router
from src.config import get_settings
from src.db import neo4j as neo4j_db
from src.db import postgres as pg_db
from src.db import redis as redis_db

logger = logging.getLogger("ai_store_manager")

# 记录当前实际使用的向量检索后端（startup 期间设定，供 /ready 端点暴露）
_VECTOR_BACKEND: str = "unknown"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle hooks."""
    # ── Startup ──────────────────────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting AI Store Manager …")

    settings = get_settings()

    global _VECTOR_BACKEND

    # 强制使用 Neo4j 向量检索后端，不降级
    vector_store_backend = os.environ.get("VECTOR_STORE", "neo4j").lower()
    # 无论环境变量如何，始终保证代码路径走 neo4j
    if vector_store_backend != "neo4j":
        logger.warning(
            "VECTOR_STORE=%s detected but Neo4j-only mode is enforced; overriding to 'neo4j'",
            vector_store_backend,
        )
        vector_store_backend = "neo4j"
        os.environ["VECTOR_STORE"] = "neo4j"

    # Init database connections (graceful — app starts even if PG is down)
    try:
        await pg_db.init_pool()
        await _run_migrations(pg_db.get_pool())
        from src.auth.seed import seed_admin_user

        await seed_admin_user()
    except Exception as e:
        logger.error("PG init failed, app will start without DB: %s", e)
        # Background retry
        import asyncio

        async def _retry_pg():
            for i in range(20):
                delay = 5 if i < 5 else 30
                await asyncio.sleep(delay)
                try:
                    await pg_db.init_pool()
                    logger.info("PG reconnected on retry %d", i + 1)
                    with contextlib.suppress(Exception):
                        await _run_migrations(pg_db.get_pool())
                    # 必须在 migrations 之后执行 seed，否则 admin 密码永远是 __PLACEHOLDER__
                    from src.auth.seed import seed_admin_user
                    with contextlib.suppress(Exception):
                        await seed_admin_user()
                    return
                except Exception:
                    logger.warning("PG retry %d/20 failed", i + 1)

        asyncio.create_task(_retry_pg())

    # ── Neo4j 初始化（强制，失败记 ERROR 但不切换到 postgres）──────────
    _VECTOR_BACKEND = "neo4j"  # 始终声明 neo4j，不论连接状态
    try:
        await neo4j_db.init_driver()
        # Smoke-test: verify Neo4j is actually reachable
        await neo4j_db.query("RETURN 1 AS n")
        logger.info("Neo4j connected successfully — using neo4j vector backend")
        # 自动创建 Product 向量索引（幂等）
        try:
            from src.db.neo4j_setup import ensure_neo4j_indexes
            await ensure_neo4j_indexes()
        except Exception as idx_err:
            logger.error("Neo4j index setup failed: %s", idx_err)
    except Exception as neo4j_err:
        logger.error(
            "Neo4j unavailable (%s) — vector search will be non-functional. "
            "NOT switching to postgres fallback (neo4j-only mode).",
            neo4j_err,
        )

    await redis_db.init_redis()

    # Prometheus metrics endpoint (if enabled)
    if settings.system.prometheus.get("enabled"):
        try:
            from prometheus_client import start_http_server

            prom_port = settings.system.prometheus.get("port", 9090)
            start_http_server(prom_port)
            logger.info("Prometheus metrics server on :%s", prom_port)
        except Exception:
            logger.warning("Failed to start Prometheus metrics server", exc_info=True)

    # Init scheduler (if not in test mode)
    if os.environ.get("TESTING") != "1":
        try:
            from src.scheduler import init_scheduler, start_scheduler

            init_scheduler()
            # Sync jobs removed — data is now pushed by local sync daemon via /api/sync/ingest
            # _init_sync_scheduler()
            start_scheduler()
            logger.info("Scheduler started")
        except Exception:
            logger.warning("Failed to start scheduler", exc_info=True)

        # Run an initial cookie health check in background
        try:
            import asyncio as _asyncio_hc

            async def _startup_cookie_health_check():
                try:
                    from src.scheduler import cookie_health_check_task
                    await cookie_health_check_task()
                except Exception as _e:
                    logger.warning("Startup cookie health check failed: %s", _e)

            _asyncio_hc.create_task(_startup_cookie_health_check())
            logger.info("Startup cookie health check task scheduled")
        except Exception:
            logger.warning("Failed to schedule startup cookie health check", exc_info=True)

        # Check if DB is empty → trigger full sync in background
        try:
            import asyncio as _asyncio

            # Skip sync on server — sync runs locally via nodriver daemon
            if os.environ.get("DISABLE_SYNC", "").lower() in ("1", "true", "yes"):
                logger.info("DISABLE_SYNC=true, skipping initial sync (use local daemon instead)")
            elif pg_db._pool is not None:
                pool = pg_db.get_pool()
                count = await pool.fetchval("SELECT COUNT(*) FROM qnh_products")
                if count == 0:
                    logger.info("Empty database — use Chrome extension or POST /api/sync/trigger to sync data")
                else:
                    logger.info("Database has %d products", count)
            else:
                logger.warning("PG not available, skipping initial sync check")
        except Exception:
            logger.warning("Failed to check DB for initial sync", exc_info=True)

    # Init and register skills for customer service agent (懒加载：后台延迟初始化)
    # 改为后台任务，避免在 512MB 环境启动时阻塞 / OOM
    import asyncio as _asyncio2

    async def _lazy_init_skills():
        """后台延迟初始化 embedding/reranker，确保 scheduler、PG 等核心服务就绪。
        
        EmbeddingSkill 使用 OpenRouter API（无本地模型），RerankerSkill 内部已懒加载
        CrossEncoder。此处仅在首次需要时才真正初始化，使 512MB 环境也能正常启动。
        """
        await _asyncio2.sleep(2)
        try:
            from src.agents.customer_service.skills_registry import register_skills
            from src.skills.embedding import EmbeddingSkill
            from src.skills.reranker import RerankerSkill

            embedding_skill = EmbeddingSkill()
            reranker_skill = RerankerSkill()

            # 强制 Neo4j，不降级到 pgvector
            try:
                from src.skills.neo4j_skill import Neo4jSkill

                vector_skill = Neo4jSkill(driver=neo4j_db.get_driver())
                logger.info("Using Neo4j as vector store backend (neo4j-only mode)")
            except Exception as _neo4j_skill_err:
                vector_skill = None
                logger.error(
                    "Failed to init Neo4jSkill (%s) — vector search will be non-functional",
                    _neo4j_skill_err,
                )

            # Init product knowledge skill
            if pg_db._pool is not None:
                from src.skills.product_knowledge import ProductKnowledgeSkill

                product_knowledge_skill = ProductKnowledgeSkill(
                    pool=pg_db.get_pool(), embedding=embedding_skill
                )
            else:
                product_knowledge_skill = None

            if vector_skill is not None:
                register_skills(
                    vector_store=vector_skill,
                    embedding=embedding_skill,
                    reranker=reranker_skill,
                    product_knowledge=product_knowledge_skill,
                )
                logger.info("Customer service skills registered (with product knowledge) ✓")
            else:
                logger.warning("Skipping skills registration — PG not available")

            # Build embeddings in background (non-blocking)
            if pg_db._pool is not None:
                async def _bg_build_embeddings():
                    try:
                        from src.skills.product_knowledge import build_embeddings

                        await build_embeddings(pg_db.get_pool(), embedding_skill)
                    except Exception as e:
                        logger.error("Background embedding build failed: %s", e)

                _asyncio2.create_task(_bg_build_embeddings())
                logger.info("Background embedding build task started")

            # Initialize product memory for new customer service
            async def _init_product_memory():
                try:
                    from src.agents.customer_service.product_memory import init_product_memory

                    await init_product_memory(pg_db.get_pool())
                    logger.info("Product memory initialized ✓")
                except Exception as e:
                    logger.error("Product memory initialization failed: %s", e)

            _asyncio2.create_task(_init_product_memory())

        except Exception:
            logger.warning("Failed to register customer service skills (lazy init)", exc_info=True)

    _asyncio2.create_task(_lazy_init_skills())
    logger.info("Customer service skill lazy-init scheduled in background ✓")

    logger.info("All services initialised ✓")

    yield

    # ── Shutdown ─────────────────────────────────────────────
    logger.info("Shutting down …")

    # 关闭 Playwright 浏览器（如果已启动）
    try:
        from src.sync.browser_client import _instance as _browser_instance

        if _browser_instance is not None:
            await _browser_instance.close()
            logger.info("Browser client closed ✓")
    except Exception:
        logger.debug("No browser client to close", exc_info=True)

    # Shutdown scheduler
    try:
        from src.scheduler import shutdown_scheduler

        shutdown_scheduler()
    except Exception:
        pass

    await redis_db.close_redis()
    if vector_store_backend == "neo4j":
        await neo4j_db.close_driver()
    await pg_db.close_pool()
    logger.info("Shutdown complete ✓")


def _split_sql_statements(sql: str) -> list[str]:
    """Split SQL text into individual statements, respecting $$ blocks and strings."""
    statements: list[str] = []
    current: list[str] = []
    in_dollar = False
    lines = sql.split("\n")
    for line in lines:
        # Track $$ delimiters (used in PL/pgSQL function bodies)
        count = line.count("$$")
        if count % 2 == 1:
            in_dollar = not in_dollar
        current.append(line)
        # Only split on ; at end of line when not inside $$ block
        stripped = line.rstrip()
        if stripped.endswith(";") and not in_dollar:
            statements.append("\n".join(current))
            current = []
    # Leftover (shouldn't happen in well-formed SQL)
    if current:
        remaining = "\n".join(current).strip()
        if remaining:
            statements.append(remaining)
    return statements


async def _run_migrations(pool: Any) -> None:
    """Auto-run SQL migration files in order."""
    from pathlib import Path

    migrations_dir = Path(__file__).resolve().parent.parent / "migrations" / "postgres"
    if not migrations_dir.exists():
        logger.warning("Migrations directory not found: %s", migrations_dir)
        return

    # Ensure migration tracking table exists
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        applied = {r["filename"] for r in await conn.fetch("SELECT filename FROM _migrations")}

    sql_files = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
    for fname in sql_files:
        if fname in applied:
            continue
        fpath = migrations_dir / fname
        raw_sql = fpath.read_text()
        logger.info("Applying migration: %s", fname)
        try:
            async with pool.acquire() as conn:
                # Strip BEGIN/COMMIT — asyncpg manages transactions itself.
                import re as _re

                cleaned = _re.sub(r"(?mi)^\s*(BEGIN|COMMIT)\s*;\s*$", "", raw_sql)

                # Split into individual statements on semicolons.
                # Handle $$ function bodies by not splitting inside them.
                statements = _split_sql_statements(cleaned)

                async with conn.transaction():
                    for stmt in statements:
                        stmt = stmt.strip()
                        if stmt:
                            await conn.execute(stmt)
                    await conn.execute("INSERT INTO _migrations (filename) VALUES ($1)", fname)
            logger.info("Migration applied: %s ✓", fname)
        except Exception as e:
            logger.error("Migration %s failed: %s", fname, e)
            # Continue with remaining migrations
            continue


async def _initial_full_sync(pool: Any) -> None:
    """Run full sync for all syncers on first deployment, then build vector index."""
    try:
        from src.sync import (
            InventorySyncer,
            MetricsSyncer,
            OrderSyncer,
            ProductSyncer,
            QNHAuth,
            QNHClient,
            ReviewSyncer,
            TrafficSyncer,
        )

        auth = QNHAuth()
        async with QNHClient(auth=auth) as client:
            syncers = [
                ProductSyncer(client, pool),
                OrderSyncer(client, pool),
                InventorySyncer(client, pool),
                ReviewSyncer(client, pool),
                TrafficSyncer(client, pool),
                MetricsSyncer(client, pool),
            ]

            for syncer in syncers:
                logger.info("Initial full sync: %s …", syncer.name)
                try:
                    result = await syncer.full_sync()
                    logger.info("Initial sync %s: %s", syncer.name, result.summary)
                except Exception as e:
                    logger.error("Initial sync %s failed: %s", syncer.name, e)

        # Vector index disabled (Chroma OOM on Fly free tier, using SQL fulltext)
        logger.info("Initial full sync complete ✓")

    except Exception as e:
        logger.error("Initial full sync failed: %s", e, exc_info=True)


async def _build_vector_index(pool: Any) -> None:
    """Build Chroma vector index for all products from qnh_products."""
    try:
        from src.db.chroma import get_collection
        from src.skills.embedding import EmbeddingSkill

        collection = get_collection()
        # Skip if already populated
        if collection.count() > 0:
            logger.info("Chroma already has %d items, skipping rebuild", collection.count())
            return

        embedding_skill = EmbeddingSkill()

        rows = await pool.fetch("SELECT spu_id, name, category, brand, spec FROM qnh_products")
        if not rows:
            logger.info("No products to embed")
            return

        logger.info("Building Chroma vector index for %d products…", len(rows))

        batch_size = 32
        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            texts = []
            ids = []
            metadatas = []

            for row in chunk:
                text = " ".join(
                    filter(
                        None,
                        [
                            row["name"] or "",
                            row.get("category") or "",
                            row.get("brand") or "",
                            row.get("spec") or "",
                        ],
                    )
                )
                texts.append(text)
                ids.append(f"{row['spu_id']}_")
                metadatas.append(
                    {
                        "spu_id": row["spu_id"],
                        "sku_id": "",
                        "name": row["name"] or "",
                        "category": row.get("category") or "",
                        "brand": row.get("brand") or "",
                        "spec": row.get("spec") or "",
                        "description": "",
                        "image_text": "",
                        "image_urls": "[]",
                        "price": 0.0,
                        "status": "",
                    }
                )

            embeddings = embedding_skill.embed_batch(texts, batch_size=batch_size)

            collection.upsert(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=texts,
            )

            logger.info(
                "Chroma: embedded %d–%d / %d",
                i + 1,
                min(i + batch_size, len(rows)),
                len(rows),
            )

        logger.info("Chroma vector index built for %d products ✓", len(rows))

    except Exception as e:
        logger.error("Failed to build Chroma vector index: %s", e, exc_info=True)


def _init_sync_scheduler() -> None:
    """Add QNH data sync jobs to the APScheduler."""
    from apscheduler.triggers.cron import CronTrigger

    from src.scheduler import get_scheduler

    scheduler = get_scheduler()

    # Products + Inventory: every 30 min
    scheduler.add_job(
        _run_incremental_sync,
        args=["products"],
        trigger=CronTrigger.from_crontab("*/30 * * * *"),
        id="sync_products",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_incremental_sync,
        args=["inventory"],
        trigger=CronTrigger.from_crontab("*/30 * * * *"),
        id="sync_inventory",
        replace_existing=True,
    )

    # Orders: every 15 min
    scheduler.add_job(
        _run_incremental_sync,
        args=["orders"],
        trigger=CronTrigger.from_crontab("*/15 * * * *"),
        id="sync_orders",
        replace_existing=True,
    )

    # Reviews: every 1 hour
    scheduler.add_job(
        _run_incremental_sync,
        args=["reviews"],
        trigger=CronTrigger.from_crontab("0 * * * *"),
        id="sync_reviews",
        replace_existing=True,
    )

    # Traffic + Metrics: every 1 hour
    scheduler.add_job(
        _run_incremental_sync,
        args=["traffic"],
        trigger=CronTrigger.from_crontab("5 * * * *"),
        id="sync_traffic",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_incremental_sync,
        args=["metrics"],
        trigger=CronTrigger.from_crontab("10 * * * *"),
        id="sync_metrics",
        replace_existing=True,
    )

    # Competitors: daily at 10:00
    scheduler.add_job(
        _run_incremental_sync,
        args=["competitors"],
        trigger=CronTrigger.from_crontab("0 10 * * *"),
        id="sync_competitors",
        replace_existing=True,
    )

    logger.info("QNH sync scheduler jobs registered ✓")


async def _run_incremental_sync(syncer_name: str) -> None:
    """Run a single syncer's smart sync (incremental or full based on state)."""
    try:
        from src.db import postgres as pg
        from src.sync import (
            InventorySyncer,
            MetricsSyncer,
            OrderSyncer,
            ProductSyncer,
            QNHAuth,
            QNHClient,
            ReviewSyncer,
            TrafficSyncer,
        )
        from src.sync.competitors import CompetitorSyncer

        pool = pg.get_pool()
        auth = QNHAuth()

        syncer_map = {
            "products": ProductSyncer,
            "orders": OrderSyncer,
            "inventory": InventorySyncer,
            "reviews": ReviewSyncer,
            "traffic": TrafficSyncer,
            "metrics": MetricsSyncer,
            "competitors": CompetitorSyncer,
        }

        cls = syncer_map.get(syncer_name)
        if not cls:
            logger.warning("Unknown syncer: %s", syncer_name)
            return

        async with QNHClient(auth=auth) as client:
            syncer = cls(client, pool)
            result = await syncer.sync()
            logger.info("Scheduled sync %s: %s", syncer_name, result.summary)

    except Exception as e:
        logger.error("Scheduled sync %s failed: %s", syncer_name, e, exc_info=True)


app = FastAPI(
    title="AI Store Manager",
    description="美团即时零售（医疗器械）智能运营系统",
    version="0.1.0",
    lifespan=lifespan,
)

ALLOWED_ORIGINS = [
    "https://ai-shopkeeper.vercel.app",
    "https://ai-shopkeeper-kk.fly.dev",
    "http://localhost:3000",
    "http://localhost:3001",
]
# 支持环境变量动态追加
_extra_origins = os.environ.get("ALLOWED_ORIGINS", "")
if _extra_origins:
    ALLOWED_ORIGINS.extend(_extra_origins.split(","))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def ensure_pg_pool(request, call_next):
    """Auto-init PG pool on first API request if startup init failed."""
    if pg_db._pool is None and request.url.path.startswith("/api"):
        try:
            await pg_db.init_pool()
            logger.info("PG pool lazily initialized via middleware")
        except Exception:
            pass  # Will fail at endpoint level with proper error
    return await call_next(request)


# ─── Health check ────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health_check():
    """Basic liveness probe."""
    from src.api.schemas import APIResponse

    return APIResponse(success=True, data={"status": "ok"}, message="System is healthy")


@app.get("/ready", tags=["system"])
async def readiness_check():
    """Deep readiness probe — verify all dependencies."""
    from src.api.schemas import APIResponse

    checks: dict[str, bool] = {}

    # PostgreSQL
    try:
        await pg_db.fetchval("SELECT 1")
        checks["postgres"] = True
    except Exception:
        checks["postgres"] = False

    # Neo4j — 始终检查（vector_backend 固定为 neo4j）
    active_backend = "neo4j"
    try:
        await neo4j_db.query("RETURN 1 AS n")
        checks["neo4j"] = True
    except Exception:
        checks["neo4j"] = False

    # Redis
    try:
        await redis_db.get_redis().ping()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    all_ok = all(checks.values())
    status = "ok" if all_ok else "degraded"

    return APIResponse(
        success=all_ok,
        data={
            "status": status,
            "vector_backend": active_backend,
            **checks,
        },
        message=f"System is {'ready' if all_ok else 'degraded'} (vector={active_backend})",
    )


# ─── Register API routers ───────────────────────────────────
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(selection_router)
app.include_router(cs_router)
app.include_router(alerts_router)
app.include_router(bundles_router)
app.include_router(listing_router)
app.include_router(
    products_pricing_router
)  # Must be before products_router to avoid {product_id} conflict
app.include_router(products_router)
app.include_router(products_v1_router)
app.include_router(dashboard_router)
app.include_router(sync_router)
app.include_router(sync_receiver_router)
app.include_router(sync_status_router)
app.include_router(knowledge_router)
app.include_router(metrics_router)
app.include_router(orders_router)
app.include_router(reports_router)
app.include_router(store_config_router)
app.include_router(system_router)
app.include_router(competitors_router)
app.include_router(replenishment_router)
app.include_router(pricing_router)
app.include_router(pricing_intel_router)
app.include_router(selection_intel_router)
# products_pricing_router moved above products_router
app.include_router(analytics_router)
app.include_router(inventory_router)
app.include_router(insights_router)
app.include_router(stores_router)


# ─── Frontend static files ──────────────────────────────────
frontend_out_path = Path(__file__).resolve().parent.parent / "frontend" / "out"


@app.get("/")
async def read_root():
    """Serve the AI Store Manager home page."""
    index_path = frontend_out_path / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return {
        "message": "AI Store Manager",
        "status": "running",
        "version": "0.1.0",
        "description": "美团即时零售（医疗器械）智能运营系统",
        "api_docs": "/docs",
    }


# Serve Next.js static export pages (e.g., /alerts -> /alerts.html)
@app.get("/{page_name}")
async def serve_page(page_name: str):
    """Serve frontend pages from Next.js static export."""
    # Skip API and system routes
    if page_name.startswith("api") or page_name in (
        "health",
        "ready",
        "docs",
        "openapi.json",
        "debug",
    ):
        return None
    page_path = frontend_out_path / f"{page_name}.html"
    if page_path.exists():
        return FileResponse(str(page_path), media_type="text/html")
    # Fallback to index for client-side routing
    index_path = frontend_out_path / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=404, content={"detail": "Not found"})


# Mount static assets from Next.js export
if frontend_out_path.exists():
    next_static = frontend_out_path / "_next"
    if next_static.exists():
        app.mount("/_next", StaticFiles(directory=str(next_static)), name="nextjs_static")

# ─── Unified error handling ─────────────────────────────────
register_error_handlers(app)
