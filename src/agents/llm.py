"""
统一的 LLM 调用封装
支持 OpenRouter (OpenAI SDK) 和 Anthropic 直连两种模式
集成 Langfuse 追踪 + Prometheus 指标
"""

import json
import logging
import os
import time
from typing import Any

from src.config import get_settings

logger = logging.getLogger(__name__)

# LLM 提供商配置
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openrouter")  # "openrouter" | "anthropic"

# OpenRouter 模型映射（按任务复杂度分层，优化成本）
_OPENROUTER_MODELS = {
    "flash": "google/gemini-2.0-flash-001",  # 意图识别、FAQ匹配、简单分类（最便宜）
    "deepseek": "deepseek/deepseek-chat-v3-0324",  # 文本生成、套餐命名、上架文案（中文强+极便宜）
    "haiku": "google/gemini-2.0-flash-001",  # 兼容旧引用
    "sonnet": "anthropic/claude-sonnet-4",  # 客服回复、需要高质量的任务
    "pro": "google/gemini-2.5-pro-preview",  # 选品分析、复杂推理（性价比）
    "opus": "anthropic/claude-sonnet-4",  # 降级：Sonnet 够用
}

# Anthropic 直连模型
_ANTHROPIC_MODELS = {
    "flash": "claude-haiku-3-5-20241022",
    "deepseek": "claude-haiku-3-5-20241022",
    "haiku": "claude-haiku-3-5-20241022",
    "sonnet": "claude-sonnet-4-20250514",
    "pro": "claude-sonnet-4-20250514",
    "opus": "claude-opus-4-20250514",
}


def _get_models() -> dict[str, str]:
    return _OPENROUTER_MODELS if LLM_PROVIDER == "openrouter" else _ANTHROPIC_MODELS


# 模块级常量
MODEL_FLASH = _get_models()["flash"]
MODEL_DEEPSEEK = _get_models()["deepseek"]
MODEL_HAIKU = _get_models()["haiku"]
MODEL_SONNET = _get_models()["sonnet"]
MODEL_PRO = _get_models()["pro"]
MODEL_OPUS = _get_models()["opus"]

_openai_client: Any = None
_anthropic_client: Any = None
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


def _get_openai_client():
    """OpenRouter 使用 OpenAI SDK"""
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI

        _openai_client = AsyncOpenAI(
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            base_url="https://openrouter.ai/api/v1",
        )
    return _openai_client


def _get_anthropic_client():
    """Anthropic 直连"""
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.AsyncAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        )
    return _anthropic_client


def _anthropic_tool_to_openai_function(tool: dict) -> dict:
    """将 Anthropic tool 格式转为 OpenAI function 格式"""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }


async def _call_openrouter(
    prompt: str | list[dict],
    tool: dict,
    model: str,
    max_tokens: int,
    system: str | None,
) -> tuple[dict[str, Any], int, int]:
    """通过 OpenRouter (OpenAI SDK) 调用"""
    client = _get_openai_client()

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    openai_tool = _anthropic_tool_to_openai_function(tool)

    max_retries = 2
    for attempt in range(1, max_retries + 1):
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            tools=[openai_tool],
            tool_choice={"type": "function", "function": {"name": tool["name"]}},
        )

        choice = response.choices[0]
        if choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            result = json.loads(tc.function.arguments)
            input_tokens = response.usage.prompt_tokens if response.usage else 0
            output_tokens = response.usage.completion_tokens if response.usage else 0
            return result, input_tokens, output_tokens

        # Empty tool_call — known issue with Gemini 2.5 Pro, retry
        if attempt < max_retries:
            logger.warning(
                f"OpenRouter empty tool_call (attempt {attempt}/{max_retries}), "
                f"model={model}, retrying in 1s..."
            )
            import asyncio

            await asyncio.sleep(1)

    raise ValueError(f"No tool call in response after {max_retries} attempts: {choice.message}")


async def _call_anthropic(
    prompt: str | list[dict],
    tool: dict,
    model: str,
    max_tokens: int,
    system: str | None,
) -> tuple[dict[str, Any], int, int]:
    """通过 Anthropic 直连调用"""
    client = _get_anthropic_client()

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool["name"]},
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

    response = await client.messages.create(**kwargs)

    result = None
    for block in response.content:
        if block.type == "tool_use":
            result = block.input
            break

    if result is None:
        raise ValueError(f"No tool_use block in response: {response.content}")

    return result, response.usage.input_tokens, response.usage.output_tokens


async def call_tool(
    prompt: str | list[dict],
    tool: dict,
    model: str = MODEL_SONNET,
    max_tokens: int = 4096,
    system: str | None = None,
    trace_name: str | None = None,
    trace_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    统一调用接口：根据 LLM_PROVIDER 选择 OpenRouter 或 Anthropic。
    tool 格式统一用 Anthropic 格式（name + input_schema），内部自动转换。
    """
    langfuse = _init_langfuse()

    trace = None
    generation = None
    start_time = time.time()

    if langfuse:
        try:
            trace = langfuse.trace(
                name=trace_name or f"call_tool_{tool['name']}",
                metadata=trace_metadata or {},
            )
            generation = trace.generation(
                name=tool["name"],
                model=model,
                input={"prompt": prompt[:500], "system": system[:200] if system else None},
            )
        except Exception as e:
            logger.debug(f"Langfuse trace failed: {e}")

    try:
        if LLM_PROVIDER == "openrouter":
            result, input_tokens, output_tokens = await _call_openrouter(
                prompt, tool, model, max_tokens, system
            )
        else:
            result, input_tokens, output_tokens = await _call_anthropic(
                prompt, tool, model, max_tokens, system
            )

        if generation:
            generation.end(
                output=result,
                usage={"input": input_tokens, "output": output_tokens},
                level="DEFAULT",
            )

        _record_llm_metrics(model, input_tokens, output_tokens, time.time() - start_time)
        return result

    except Exception as e:
        if generation:
            generation.end(level="ERROR", status_message=str(e))
        raise


def _record_llm_metrics(model: str, input_tokens: int, output_tokens: int, duration: float) -> None:
    """记录 Prometheus 指标"""
    try:
        from src.metrics import llm_request_duration, llm_tokens_total

        llm_tokens_total.labels(model=model, type="input").inc(input_tokens)
        llm_tokens_total.labels(model=model, type="output").inc(output_tokens)
        llm_request_duration.labels(model=model).observe(duration)
    except ImportError:
        pass


def build_multimodal_content(text: str, images: list[str]) -> list[dict]:
    """Build multimodal message content with text and images."""
    content = [{"type": "text", "text": text}]

    for image in images:
        # Ensure proper data URI format
        if not image.startswith("data:"):
            image = f"data:image/jpeg;base64,{image}"

        content.append({"type": "image_url", "image_url": {"url": image}})

    return content


async def call_vision(
    text: str,
    images: list[str],
    tool: dict,
    model: str = "google/gemini-2.0-flash-001",  # Default to vision model
    max_tokens: int = 4096,
    system: str | None = None,
    trace_name: str | None = None,
) -> dict[str, Any]:
    """
    Specialized function for vision + tool calling.
    Combines text and images into multimodal content.
    """
    multimodal_content = build_multimodal_content(text, images)

    return await call_tool(
        prompt=multimodal_content,
        tool=tool,
        model=model,
        max_tokens=max_tokens,
        system=system,
        trace_name=trace_name,
    )


async def call_tool_with_reflection(
    initial_prompt: str,
    reflection_prompt_fn,
    tool: dict,
    model: str = MODEL_OPUS,
    max_tokens: int = 4096,
    system: str | None = None,
    trace_name: str | None = None,
) -> dict[str, Any]:
    """两轮调用模式 (Self-Reflection)"""
    initial_result = await call_tool(
        prompt=initial_prompt,
        tool=tool,
        model=model,
        max_tokens=max_tokens,
        system=system,
        trace_name=f"{trace_name or tool['name']}_initial",
        trace_metadata={"stage": "initial"},
    )

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
