"""
统一的 LLM 调用封装
LLM 模型分层: Haiku(意图识别), Sonnet(常规), Opus(评分/归因)
集成 Langfuse 追踪
"""

import json
import logging
import os
import time
from typing import Any

import anthropic

from src.config import get_settings

logger = logging.getLogger(__name__)

# 模型分层
MODEL_HAIKU = "claude-haiku-3-5-20241022"
MODEL_SONNET = "claude-sonnet-4-20250514"
MODEL_OPUS = "claude-opus-4-20250514"

_client: anthropic.AsyncAnthropic | None = None
_langfuse: Any = None


def _init_langfuse():
    """懒加载 Langfuse 客户端"""
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    
    try:
        settings = get_settings()
        lf_config = settings.system.langfuse
        if not lf_config.get("enabled"):
            return None
        
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=lf_config.get("public_key") or os.environ.get("LANGFUSE_PUBLIC_KEY"),
            secret_key=lf_config.get("secret_key") or os.environ.get("LANGFUSE_SECRET_KEY"),
            host=lf_config.get("host", "https://cloud.langfuse.com"),
        )
        logger.info("Langfuse initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize Langfuse: {e}")
        _langfuse = None
    return _langfuse


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )
    return _client


async def call_tool(
    prompt: str,
    tool: dict,
    model: str = MODEL_SONNET,
    max_tokens: int = 4096,
    system: str | None = None,
    trace_name: str | None = None,
    trace_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    调用 Claude API 并强制使用指定 Tool，返回结构化结果。
    
    tool_choice={"type": "tool", "name": "xxx"} 确保 100% 结构化输出。
    集成 Langfuse 追踪。
    """
    client = get_client()
    langfuse = _init_langfuse()

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool["name"]},
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

    # Langfuse trace
    trace = None
    generation = None
    start_time = time.time()
    
    if langfuse:
        trace = langfuse.trace(
            name=trace_name or f"call_tool_{tool['name']}",
            metadata=trace_metadata or {},
        )
        generation = trace.generation(
            name=tool["name"],
            model=model,
            input={"prompt": prompt[:500], "system": system[:200] if system else None},
        )

    try:
        response = await client.messages.create(**kwargs)
        
        # 提取 tool_use block
        result = None
        for block in response.content:
            if block.type == "tool_use":
                result = block.input
                break
        
        if result is None:
            raise ValueError(f"No tool_use block in response: {response.content}")

        # 记录 Langfuse
        if generation:
            generation.end(
                output=result,
                usage={
                    "input": response.usage.input_tokens,
                    "output": response.usage.output_tokens,
                },
                level="DEFAULT",
            )
        
        # Prometheus 指标
        _record_llm_metrics(model, response.usage.input_tokens, response.usage.output_tokens, time.time() - start_time)
        
        return result
        
    except Exception as e:
        if generation:
            generation.end(level="ERROR", status_message=str(e))
        raise


def _record_llm_metrics(model: str, input_tokens: int, output_tokens: int, duration: float) -> None:
    """记录 Prometheus 指标"""
    try:
        from src.metrics import llm_tokens_total, llm_request_duration
        llm_tokens_total.labels(model=model, type="input").inc(input_tokens)
        llm_tokens_total.labels(model=model, type="output").inc(output_tokens)
        llm_request_duration.labels(model=model).observe(duration)
    except ImportError:
        pass  # metrics module not loaded


async def call_tool_with_reflection(
    initial_prompt: str,
    reflection_prompt_fn,
    tool: dict,
    model: str = MODEL_OPUS,
    max_tokens: int = 4096,
    system: str | None = None,
    trace_name: str | None = None,
) -> dict[str, Any]:
    """
    两轮调用模式 (Self-Reflection):
    1. 第一轮：生成初始结果
    2. 第二轮：自我反思并修正
    """
    # 第一轮
    initial_result = await call_tool(
        prompt=initial_prompt,
        tool=tool,
        model=model,
        max_tokens=max_tokens,
        system=system,
        trace_name=f"{trace_name or tool['name']}_initial",
        trace_metadata={"stage": "initial"},
    )

    # 第二轮：反思
    reflection_prompt = reflection_prompt_fn(json.dumps(initial_result, ensure_ascii=False))
    reflected_result = await call_tool(
        prompt=reflection_prompt,
        tool=tool,
        model=model,
        max_tokens=max_tokens,
        system=system,
        trace_name=f"{trace_name or tool['name']}_reflection",
        trace_metadata={"stage": "reflection"},
    )

    return reflected_result
