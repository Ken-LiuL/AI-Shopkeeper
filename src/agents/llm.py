"""
统一的 LLM 调用封装
LLM 模型分层: Haiku(意图识别), Sonnet(常规), Opus(评分/归因)
"""

import json
import os
from typing import Any

import anthropic

# 模型分层
MODEL_HAIKU = "claude-haiku-3-5-20241022"
MODEL_SONNET = "claude-sonnet-4-20250514"
MODEL_OPUS = "claude-opus-4-20250514"

_client: anthropic.AsyncAnthropic | None = None


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
) -> dict[str, Any]:
    """
    调用 Claude API 并强制使用指定 Tool，返回结构化结果。
    
    tool_choice={"type": "tool", "name": "xxx"} 确保 100% 结构化输出。
    """
    client = get_client()

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

    # 提取 tool_use block
    for block in response.content:
        if block.type == "tool_use":
            return block.input

    raise ValueError(f"No tool_use block in response: {response.content}")


async def call_tool_with_reflection(
    initial_prompt: str,
    reflection_prompt_fn,
    tool: dict,
    model: str = MODEL_OPUS,
    max_tokens: int = 4096,
    system: str | None = None,
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
    )

    # 第二轮：反思
    reflection_prompt = reflection_prompt_fn(json.dumps(initial_result, ensure_ascii=False))
    reflected_result = await call_tool(
        prompt=reflection_prompt,
        tool=tool,
        model=model,
        max_tokens=max_tokens,
        system=system,
    )

    return reflected_result
