"""变体执行器 — 根据变体名称选择不同的 prompt/model/策略并执行。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 变体执行函数类型：接受 **kwargs，返回任意结果
VariantFn = Callable[..., Awaitable[Any] | Any]


class VariantExecutor:
    """注册并执行变体函数。

    用法::

        executor = VariantExecutor()
        executor.register("control", my_fn_a)
        executor.register("treatment", my_fn_b)
        result = await executor.execute("control", prompt="hello")
    """

    def __init__(self) -> None:
        self._registry: dict[str, VariantFn] = {}

    def register(self, variant_name: str, fn: VariantFn) -> None:
        """注册一个变体函数。"""
        self._registry[variant_name] = fn
        logger.debug("Variant registered: %s → %s", variant_name, fn.__name__ if hasattr(fn, "__name__") else fn)

    def list_variants(self) -> list[str]:
        return list(self._registry.keys())

    async def execute(self, variant_name: str, **kwargs: Any) -> Any:
        """执行对应的变体函数，自动适配同步/异步。"""
        if variant_name not in self._registry:
            raise KeyError(f"Unknown variant: '{variant_name}'. Registered: {list(self._registry)}")
        fn = self._registry[variant_name]
        import inspect
        result = fn(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result


# ──────────────────────────────────────────────────────────────
# 内置变体类型
# ──────────────────────────────────────────────────────────────


@dataclass
class ModelVariant:
    """不同模型对比（如 Sonnet vs DeepSeek）。

    每个变体绑定一个 model 名称，执行时调用 call_fn(model=..., **kwargs)。

    示例::

        mv = ModelVariant(
            call_fn=call_tool,
            variants={
                "sonnet": "anthropic/claude-sonnet-4",
                "deepseek": "deepseek/deepseek-chat-v3-0324",
            },
        )
        executor = mv.build_executor()
    """

    call_fn: VariantFn
    variants: dict[str, str]  # variant_name → model_id

    def build_executor(self) -> VariantExecutor:
        executor = VariantExecutor()
        for variant_name, model_id in self.variants.items():
            # 闭包捕获 model_id
            def _make_fn(m: str) -> VariantFn:
                async def _fn(**kwargs: Any) -> Any:
                    return await self.call_fn(model=m, **kwargs)
                _fn.__name__ = f"model_variant_{m}"
                return _fn

            executor.register(variant_name, _make_fn(model_id))
        return executor


@dataclass
class PromptVariant:
    """不同 prompt 模板对比。

    每个变体绑定一个 prompt 模板（字符串或可调用对象）。
    执行时将模板渲染后传给 call_fn。

    示例::

        pv = PromptVariant(
            call_fn=call_tool,
            templates={
                "v1": "请分析以下商品：{product}",
                "v2": "作为专业选品师，请分析：{product}",
            },
        )
        executor = pv.build_executor()
        result = await executor.execute("v1", product="口罩")
    """

    call_fn: VariantFn
    templates: dict[str, str | Callable[..., str]]

    def build_executor(self) -> VariantExecutor:
        executor = VariantExecutor()
        for variant_name, template in self.templates.items():
            def _make_fn(t: str | Callable[..., str], vname: str) -> VariantFn:
                async def _fn(**kwargs: Any) -> Any:
                    if callable(t):
                        prompt = t(**kwargs)
                    else:
                        prompt = t.format(**{k: v for k, v in kwargs.items() if isinstance(v, str)})
                    # 从 kwargs 里分离 call_fn 专有参数
                    call_kwargs = {k: v for k, v in kwargs.items() if k not in ("prompt",)}
                    return await self.call_fn(prompt=prompt, **call_kwargs)
                _fn.__name__ = f"prompt_variant_{vname}"
                return _fn

            executor.register(variant_name, _make_fn(template, variant_name))
        return executor


@dataclass
class StrategyVariant:
    """不同策略对比（如 Self-Reflection 开/关）。

    每个变体对应一个完整的策略函数，接口统一为 **kwargs → result。

    示例::

        sv = StrategyVariant(
            variants={
                "no_reflection": call_tool,
                "with_reflection": call_tool_with_reflection,
            },
        )
        executor = sv.build_executor()
    """

    variants: dict[str, VariantFn]

    def build_executor(self) -> VariantExecutor:
        executor = VariantExecutor()
        for variant_name, fn in self.variants.items():
            executor.register(variant_name, fn)
        return executor
