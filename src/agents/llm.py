"""
统一的 LLM 调用封装
支持 OpenRouter (OpenAI SDK) 和 Anthropic 直连两种模式
集成 Langfuse 追踪 + Prometheus 指标
"""

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

from src.config import get_settings

logger = logging.getLogger(__name__)

# LLM 提供商配置
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openrouter")  # "openrouter" | "deepseek" | "anthropic"

# JSON mode: 用 response_format=json_object 替代 tool_choice，DeepSeek 系模型更快
LLM_USE_JSON_MODE = os.environ.get("LLM_USE_JSON_MODE", "true").lower() in ("1", "true", "yes")

# OpenRouter 模型映射（按任务复杂度分层，优化成本）
_OPENROUTER_MODELS = {
    "flash": "google/gemini-2.0-flash-001",  # 意图识别、FAQ匹配、简单分类（最便宜）
    "deepseek": "deepseek/deepseek-chat-v3-0324",  # 文本生成、套餐命名、上架文案（中文强+极便宜）
    "haiku": "google/gemini-2.0-flash-001",  # 兼容旧引用
    "sonnet": "deepseek/deepseek-chat-v3-0324",  # 客服回复（DeepSeek中文强+无区域限制+极低成本）
    "pro": "google/gemini-2.5-pro-preview",  # 选品分析、复杂推理（性价比）
    "opus": "google/gemini-2.5-pro-preview",  # 关键决策（Gemini Pro兜底，无区域限制）
}

# DeepSeek 直连映射（去掉 OpenRouter 中转，降低延迟）
_DEEPSEEK_MODELS = {
    "flash": "deepseek-chat",
    "deepseek": "deepseek-chat",
    "haiku": "deepseek-chat",
    "sonnet": "deepseek-chat",
    "pro": "deepseek-reasoner",
    "opus": "deepseek-reasoner",
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
    if LLM_PROVIDER == "deepseek":
        return _DEEPSEEK_MODELS
    if LLM_PROVIDER == "openrouter":
        return _OPENROUTER_MODELS
    return _ANTHROPIC_MODELS


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
    """OpenAI-compatible client (OpenRouter / DeepSeek 直连)"""
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI

        if LLM_PROVIDER == "deepseek":
            _openai_client = AsyncOpenAI(
                api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-e2c7225a0d714a5185e3c8e5c721a9eb"),
                base_url="https://api.deepseek.com",
            )
        else:
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


def _tool_schema_to_json_instruction(tool: dict) -> str:
    """将 tool schema 转成 JSON mode 的 prompt 指令"""
    schema = tool.get("input_schema", {})
    props = schema.get("properties", {})
    required = schema.get("required", [])

    lines = ["请严格按以下 JSON 格式回复（不要输出任何其他内容）："]
    lines.append("{")
    for key, val in props.items():
        desc = val.get("description", "")
        typ = val.get("type", "string")
        enum_vals = val.get("enum")
        req_mark = " (必填)" if key in required else " (可选)"
        if enum_vals:
            lines.append(f'  "{key}": {typ}, // {desc}{req_mark}, 可选值: {enum_vals}')
        elif typ == "object":
            lines.append(f'  "{key}": {{...}}, // {desc}{req_mark}')
        else:
            lines.append(f'  "{key}": {typ}, // {desc}{req_mark}')
    lines.append("}")
    return "\n".join(lines)


async def _call_openrouter(
    prompt: str | list[dict],
    tool: dict,
    model: str,
    max_tokens: int,
    system: str | None,
) -> tuple[dict[str, Any], int, int]:
    """通过 OpenRouter (OpenAI SDK) 调用，支持 tool_choice 和 JSON mode 两种模式"""
    client = _get_openai_client()

    # JSON mode: 仅直连 DeepSeek 时启用（OpenRouter 对 response_format 支持不稳定）
    use_json = LLM_USE_JSON_MODE and LLM_PROVIDER == "deepseek"

    messages: list[dict] = []

    if use_json:
        # JSON mode: 把 tool schema 转成 system prompt 指令
        json_instruction = _tool_schema_to_json_instruction(tool)
        sys_content = (system or "") + "\n\n" + json_instruction
        messages.append({"role": "system", "content": sys_content.strip()})
    elif system:
        messages.append({"role": "system", "content": system})

    # Support both single prompt string and multi-turn messages list
    if isinstance(prompt, list) and prompt and isinstance(prompt[0], dict) and "role" in prompt[0]:
        messages.extend(prompt)
    else:
        messages.append({"role": "user", "content": prompt})

    if use_json:
        # JSON mode 路径：response_format + 无 tool_choice
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=messages,
                    response_format={"type": "json_object"},
                ),
                timeout=120.0,
            )
        except TimeoutError:
            raise ValueError(f"LLM call timeout after 120s (model={model}, json_mode)") from None

        choice = response.choices[0]
        raw_content = choice.message.content or "{}"
        # 容错：去掉可能的 markdown 包裹
        raw_content = raw_content.strip()
        if raw_content.startswith("```"):
            raw_content = raw_content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            result = json.loads(raw_content)
        except json.JSONDecodeError:
            logger.warning(f"JSON mode parse failed, falling back to tool_choice. Raw: {raw_content[:200]}")
            # fallback 到 tool_choice 模式
            return await _call_openrouter_tool_choice(prompt, tool, model, max_tokens, system)

        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        logger.info(f"[LLM] JSON mode success: model={model}, in={input_tokens}, out={output_tokens}")
        return result, input_tokens, output_tokens
    else:
        # tool_choice 路径（原逻辑，Gemini 等非 DeepSeek 模型）
        return await _call_openrouter_tool_choice(prompt, tool, model, max_tokens, system)


async def _call_openrouter_tool_choice(
    prompt: str | list[dict],
    tool: dict,
    model: str,
    max_tokens: int,
    system: str | None,
) -> tuple[dict[str, Any], int, int]:
    """tool_choice 模式调用（原逻辑）"""
    client = _get_openai_client()

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})

    if isinstance(prompt, list) and prompt and isinstance(prompt[0], dict) and "role" in prompt[0]:
        messages.extend(prompt)
    else:
        messages.append({"role": "user", "content": prompt})

    openai_tool = _anthropic_tool_to_openai_function(tool)

    max_retries = 2
    for attempt in range(1, max_retries + 1):
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=messages,
                    tools=[openai_tool],
                    tool_choice={"type": "function", "function": {"name": tool["name"]}},
                ),
                timeout=120.0,
            )
        except TimeoutError:
            raise ValueError(f"LLM call timeout after 120s (model={model})") from None

        choice = response.choices[0]
        if choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            result = json.loads(tc.function.arguments)
            input_tokens = response.usage.prompt_tokens if response.usage else 0
            output_tokens = response.usage.completion_tokens if response.usage else 0
            return result, input_tokens, output_tokens

        if attempt < max_retries:
            logger.warning(
                f"OpenRouter empty tool_call (attempt {attempt}/{max_retries}), "
                f"model={model}, retrying in 1s..."
            )
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

    # Support both single prompt and multi-turn messages
    if isinstance(prompt, list) and prompt and isinstance(prompt[0], dict) and "role" in prompt[0]:
        msgs = prompt
    else:
        msgs = [{"role": "user", "content": prompt}]

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool["name"]},
        "messages": msgs,
    }
    if system:
        kwargs["system"] = system

    try:
        response = await asyncio.wait_for(
            client.messages.create(**kwargs),
            timeout=120.0,
        )
    except TimeoutError:
        raise ValueError(f"LLM call timeout after 120s (model={model})") from None

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
    experiment_id: str | None = None,
    ab_variant: str | None = None,
) -> dict[str, Any]:
    """
    统一调用接口：根据 LLM_PROVIDER 选择 OpenRouter 或 Anthropic。
    tool 格式统一用 Anthropic 格式（name + input_schema），内部自动转换。

    Args:
        experiment_id: A/B 实验 ID（可选）。若提供，自动将 latency 和 token 用量
                       记录为该实验的 outcome。
        ab_variant:    实验变体名称（配合 experiment_id 使用）。
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
        if LLM_PROVIDER in ("openrouter", "deepseek"):
            result, input_tokens, output_tokens = await _call_openrouter(
                prompt, tool, model, max_tokens, system
            )
        else:
            result, input_tokens, output_tokens = await _call_anthropic(
                prompt, tool, model, max_tokens, system
            )

        elapsed = time.time() - start_time

        if generation:
            generation.end(
                output=result,
                usage={"input": input_tokens, "output": output_tokens},
                level="DEFAULT",
            )

        _record_llm_metrics(model, input_tokens, output_tokens, elapsed)

        # ── A/B 实验：记录 latency 和 token 用量 ──────────────────
        if experiment_id and ab_variant:
            try:
                from src.ab_testing.experiment import get_experiment_manager
                _ab_mgr = get_experiment_manager()
                _ab_mgr.record_outcome(experiment_id, ab_variant, "latency_ms", elapsed * 1000)
                _ab_mgr.record_outcome(experiment_id, ab_variant, "input_tokens", float(input_tokens))
                _ab_mgr.record_outcome(experiment_id, ab_variant, "output_tokens", float(output_tokens))
                _ab_mgr.record_outcome(
                    experiment_id, ab_variant, "total_tokens", float(input_tokens + output_tokens)
                )
            except Exception as _ab_err:
                logger.debug("A/B outcome recording failed: %s", _ab_err)

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


def _add_reflection_fields(tool: dict) -> dict:
    """
    返回一个临时的 tool 副本，在 input_schema 中注入两个自检字段：
    - _reflection_confidence: float 0-1，LLM 对本轮结果的信心
    - _reflection_changes_made: bool，本轮是否做了实质性修改
    这两个字段仅用于收敛判断，调用后会从结果中 pop 掉，不影响下游。
    """
    import copy

    reflection_tool = copy.deepcopy(tool)
    schema = reflection_tool.setdefault("input_schema", {})
    props = schema.setdefault("properties", {})
    required = schema.setdefault("required", [])

    props["_reflection_confidence"] = {
        "type": "number",
        "description": (
            "Your confidence in the quality of this result, as a float between 0 and 1. "
            "1.0 means perfect, no further improvement possible; 0.0 means very low quality."
        ),
    }
    props["_reflection_changes_made"] = {
        "type": "boolean",
        "description": (
            "Whether you made any meaningful changes compared to the previous result. "
            "Set to false if the result is already optimal and you changed nothing substantial."
        ),
    }

    # 将两个字段加入 required，确保模型必须输出
    for field in ("_reflection_confidence", "_reflection_changes_made"):
        if field not in required:
            required.append(field)

    return reflection_tool


async def call_tool_with_reflection(
    initial_prompt: str,
    reflection_prompt_fn,
    tool: dict,
    model: str = MODEL_OPUS,
    max_tokens: int = 4096,
    system: str | None = None,
    trace_name: str | None = None,
    max_rounds: int = 3,
    quality_threshold: float = 0.8,
) -> dict[str, Any]:
    """
    动态多轮自检模式 (Dynamic Self-Reflection)。

    - 第一轮：正常调用，获取初始结果。
    - 后续轮（最多 max_rounds 轮）：每轮注入 _reflection_confidence / _reflection_changes_made
      字段，LLM 填写后由框架提取并决定是否提前收敛。
    - 若 confidence >= quality_threshold 且 changes_made=False，则提前退出。
    - 第一轮失败直接抛出；反思轮失败则降级返回上一轮结果。
    - 保持向后兼容：现有调用方无需改动。
    """
    base_name = trace_name or tool["name"]

    # ── 第一轮 ──────────────────────────────────────────────────────────────
    current_result = await call_tool(
        prompt=initial_prompt,
        tool=tool,
        model=model,
        max_tokens=max_tokens,
        system=system,
        trace_name=f"{base_name}_round1",
        trace_metadata={"stage": "initial", "round": 1},
    )

    last_round = 1

    # ── 反思轮 ──────────────────────────────────────────────────────────────
    reflection_tool = _add_reflection_fields(tool)

    for round_num in range(2, max_rounds + 1):
        try:
            reflection_prompt = reflection_prompt_fn(
                json.dumps(current_result, ensure_ascii=False)
            )
            reflected_result = await call_tool(
                prompt=reflection_prompt,
                tool=reflection_tool,
                model=model,
                max_tokens=max_tokens,
                system=system,
                trace_name=f"{base_name}_round{round_num}",
                trace_metadata={"stage": "reflection", "round": round_num},
            )
        except Exception as exc:
            logger.warning(
                "Self-reflection round %d failed (%s), keeping previous result: %s",
                round_num,
                base_name,
                exc,
            )
            break

        # 提取并移除自检字段，不让它们污染下游结果
        confidence: float = reflected_result.pop("_reflection_confidence", 0.9)
        changes_made: bool = reflected_result.pop("_reflection_changes_made", False)

        current_result = reflected_result
        last_round = round_num

        logger.debug(
            "Self-reflection round %d/%d — confidence=%.2f changes_made=%s (%s)",
            round_num,
            max_rounds,
            confidence,
            changes_made,
            base_name,
        )

        # 收敛判断：高置信度且无改动 → 提前退出
        if confidence >= quality_threshold and not changes_made:
            logger.info(
                "Self-reflection converged at round %d (confidence=%.2f, threshold=%.2f) [%s]",
                round_num,
                confidence,
                quality_threshold,
                base_name,
            )
            break

    # 记录实际轮数，供调用方或日志参考（可选字段，不影响业务逻辑）
    current_result["_reflection_rounds"] = last_round
    return current_result


async def call_chat(
    prompt: str | list[dict],
    model: str = MODEL_SONNET,
    max_tokens: int = 512,
    system: str | None = None,
    response_format: dict | None = None,
    trace_name: str | None = None,
) -> tuple[str, int, int]:
    """
    轻量纯文本调用 — 不使用 tool_choice，直接返回文本。
    比 call_tool 快得多（DeepSeek tool_choice 开销巨大）。

    支持可选 response_format={"type":"json_object"} 让模型输出 JSON。

    Returns:
        (content_str, input_tokens, output_tokens)
    """
    client = _get_openai_client()
    langfuse = _init_langfuse()
    start_time = time.time()

    trace = None
    generation = None
    if langfuse:
        try:
            trace = langfuse.trace(name=trace_name or "call_chat")
            generation = trace.generation(
                name="chat",
                model=model,
                input={"system": (system or "")[:200]},
            )
        except Exception:
            pass

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})

    if isinstance(prompt, list) and prompt and isinstance(prompt[0], dict) and "role" in prompt[0]:
        messages.extend(prompt)
    else:
        messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if response_format:
        kwargs["response_format"] = response_format

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(**kwargs),
            timeout=60.0,
        )
    except TimeoutError:
        raise ValueError(f"call_chat timeout after 60s (model={model})") from None

    choice = response.choices[0]
    content = choice.message.content or ""
    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0

    elapsed = time.time() - start_time

    if generation:
        generation.end(
            output=content[:500],
            usage={"input": input_tokens, "output": output_tokens},
            level="DEFAULT",
        )

    _record_llm_metrics(model, input_tokens, output_tokens, elapsed)
    logger.info(f"[LLM] call_chat: model={model}, in={input_tokens}, out={output_tokens}, {elapsed:.2f}s")

    return content, input_tokens, output_tokens


async def call_chat_stream(
    prompt: str | list[dict],
    model: str = MODEL_SONNET,
    max_tokens: int = 512,
    system: str | None = None,
    trace_name: str | None = None,
) -> AsyncIterator[str]:
    """
    轻量纯文本流式调用。
    逐 token 返回文本片段，用于 SSE 首字加速。
    """
    client = _get_openai_client()
    langfuse = _init_langfuse()
    start_time = time.time()

    trace = None
    generation = None
    if langfuse:
        try:
            trace = langfuse.trace(name=trace_name or "call_chat_stream")
            generation = trace.generation(
                name="chat_stream",
                model=model,
                input={"system": (system or "")[:200]},
            )
        except Exception:
            pass

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})

    if isinstance(prompt, list) and prompt and isinstance(prompt[0], dict) and "role" in prompt[0]:
        messages.extend(prompt)
    else:
        messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    try:
        stream = await asyncio.wait_for(
            client.chat.completions.create(**kwargs),
            timeout=60.0,
        )
    except TimeoutError:
        raise ValueError(f"call_chat_stream timeout after 60s (model={model})") from None
    except Exception as e:
        # 某些网关不支持 stream_options，自动降级重试一次。
        if "stream_options" in str(e):
            kwargs.pop("stream_options", None)
            stream = await asyncio.wait_for(
                client.chat.completions.create(**kwargs),
                timeout=60.0,
            )
        else:
            raise

    reply_parts: list[str] = []
    input_tokens = 0
    output_tokens = 0

    async for chunk in stream:
        usage = getattr(chunk, "usage", None)
        if usage:
            input_tokens = getattr(usage, "prompt_tokens", input_tokens) or input_tokens
            output_tokens = getattr(usage, "completion_tokens", output_tokens) or output_tokens

        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue

        delta = getattr(choices[0], "delta", None)
        if delta is None:
            continue

        content = getattr(delta, "content", "")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )

        if text:
            reply_parts.append(text)
            yield text

    elapsed = time.time() - start_time
    reply_text = "".join(reply_parts)

    if generation:
        generation.end(
            output=reply_text[:500],
            usage={"input": input_tokens, "output": output_tokens},
            level="DEFAULT",
        )

    _record_llm_metrics(model, input_tokens, output_tokens, elapsed)
    logger.info(
        "[LLM] call_chat_stream: model=%s, in=%s, out=%s, %.2fs",
        model,
        input_tokens,
        output_tokens,
        elapsed,
    )
