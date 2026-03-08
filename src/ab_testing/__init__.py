"""A/B 测试框架 — 导出核心类。"""

from src.ab_testing.experiment import (
    ExperimentConfig,
    ExperimentManager,
    get_experiment_manager,
)
from src.ab_testing.variants import (
    ModelVariant,
    PromptVariant,
    StrategyVariant,
    VariantExecutor,
)
from src.ab_testing.stats import (
    calculate_confidence_interval,
    calculate_sample_size,
    chi_square_test,
    t_test,
)

__all__ = [
    # experiment
    "ExperimentConfig",
    "ExperimentManager",
    "get_experiment_manager",
    # variants
    "VariantExecutor",
    "ModelVariant",
    "PromptVariant",
    "StrategyVariant",
    # stats
    "t_test",
    "chi_square_test",
    "calculate_confidence_interval",
    "calculate_sample_size",
]
