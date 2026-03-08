"""端到端冒烟测试 — 验证系统各模块可加载、API 可响应。"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


def _module_name_from_path(path: Path) -> str:
    rel = path.relative_to(PROJECT_ROOT).with_suffix("")
    return ".".join(rel.parts)


def _import_or_skip(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing and not missing.startswith("src"):
            pytest.skip(f"external dependency not installed: {missing}")
        raise


API_ROUTE_MODULES = sorted(
    _module_name_from_path(path)
    for path in (SRC_ROOT / "api").glob("*.py")
    if path.name != "__init__.py"
)

SYNC_MODULES = sorted(
    _module_name_from_path(path)
    for path in (SRC_ROOT / "sync").glob("*.py")
    if path.name != "__init__.py"
)

ETL_MODULES = [m for m in SYNC_MODULES if ".etl_" in m]

AGENT_GRAPH_BUILDERS: list[tuple[str, str]] = [
    ("src.agents.alert.graph", "build_alert_graph"),
    ("src.agents.bundle.graph", "build_bundle_graph"),
    ("src.agents.business_advisor.graph", "build_business_advisor_graph"),
    ("src.agents.customer_service.graph", "build_customer_service_graph"),
    ("src.agents.listing.graph", "build_listing_graph"),
    ("src.agents.selection.graph", "build_selection_graph"),
]

CONFIG_YAML_FILES = sorted((PROJECT_ROOT / "config").glob("*.yaml"))


@pytest.mark.parametrize("module_name", API_ROUTE_MODULES)
def test_api_route_modules_importable(module_name: str):
    _import_or_skip(module_name)


@pytest.mark.asyncio
async def test_api_health_endpoint_responds():
    httpx = _import_or_skip("httpx")
    main_module = _import_or_skip("src.main")

    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("success") is True


@pytest.mark.parametrize("module_name,builder_name", AGENT_GRAPH_BUILDERS)
def test_agent_graphs_can_build(module_name: str, builder_name: str):
    module = _import_or_skip(module_name)
    builder = getattr(module, builder_name)
    builder()


@pytest.mark.parametrize("module_name", SYNC_MODULES)
def test_sync_modules_importable(module_name: str):
    _import_or_skip(module_name)


@pytest.mark.parametrize("module_name", ETL_MODULES)
def test_etl_modules_importable(module_name: str):
    _import_or_skip(module_name)


class _DummyScheduler:
    def __init__(self) -> None:
        self.jobs: list[tuple[tuple, dict]] = []

    def add_job(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.jobs.append((args, kwargs))
        return None


def test_scheduler_task_registration_smoke():
    scheduler_module = _import_or_skip("src.scheduler")
    dummy = _DummyScheduler()
    tasks: dict[str, str] = {}

    if hasattr(scheduler_module, "_register_tasks"):
        scheduler_module._register_tasks(dummy, tasks)
    else:
        scheduler_module._register_remote_safe_jobs(dummy, tasks)
        scheduler_module._register_local_only_jobs(dummy, tasks)

    assert len(dummy.jobs) > 0


@pytest.mark.parametrize("yaml_file", CONFIG_YAML_FILES)
def test_config_yaml_files_parseable(yaml_file: Path):
    with yaml_file.open("r", encoding="utf-8") as f:
        parsed = yaml.safe_load(f)

    assert parsed is None or isinstance(parsed, (dict, list))
