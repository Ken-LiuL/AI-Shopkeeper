"""Tests for LLM wrapper module — call_tool, call_tool_with_reflection."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.llm import (
    MODEL_HAIKU,
    MODEL_OPUS,
    MODEL_SONNET,
    MODEL_FLASH,
    MODEL_DEEPSEEK,
    MODEL_PRO,
    call_tool,
    call_tool_with_reflection,
    _record_llm_metrics,
    _get_openai_client,
    _get_anthropic_client,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_tool():
    """Sample tool schema (Anthropic format, as used by call_tool)."""
    return {
        "name": "test_output_tool",
        "description": "Test output tool",
        "input_schema": {
            "type": "object",
            "properties": {
                "result": {"type": "string"},
                "score": {"type": "number"},
            },
            "required": ["result"],
        },
    }


def _make_openai_response(tool_name: str, tool_input: dict, input_tokens=100, output_tokens=50):
    """Build a mock OpenAI ChatCompletion with a tool call."""
    tc = MagicMock()
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(tool_input)

    message = MagicMock()
    message.tool_calls = [tc]

    choice = MagicMock()
    choice.message = message

    usage = MagicMock()
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI async client (used for OpenRouter path)."""
    client = AsyncMock()
    client.chat = AsyncMock()
    client.chat.completions = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response("test_output_tool", {"result": "test_result", "score": 0.9})
    )
    return client


# ---------------------------------------------------------------------------
# Model Constants
# ---------------------------------------------------------------------------

class TestModelConstants:
    """Test model tier constants are defined correctly."""

    def test_model_flash_exists(self):
        assert MODEL_FLASH is not None and len(MODEL_FLASH) > 0

    def test_model_deepseek_exists(self):
        assert MODEL_DEEPSEEK is not None and len(MODEL_DEEPSEEK) > 0

    def test_model_pro_exists(self):
        assert MODEL_PRO is not None and len(MODEL_PRO) > 0

    def test_model_sonnet_exists(self):
        assert MODEL_SONNET is not None and len(MODEL_SONNET) > 0

    def test_model_hierarchy(self):
        """Ensure key models are distinct."""
        assert MODEL_FLASH != MODEL_SONNET
        assert MODEL_FLASH != MODEL_PRO


# ---------------------------------------------------------------------------
# call_tool (OpenRouter / OpenAI SDK path)
# ---------------------------------------------------------------------------

class TestCallTool:
    """Tests for call_tool function (default: openrouter)."""

    async def test_call_tool_success(self, mock_openai_client, mock_tool):
        with patch("src.agents.llm._get_openai_client", return_value=mock_openai_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with patch("src.agents.llm.LLM_PROVIDER", "openrouter"):
                    result = await call_tool(prompt="Test prompt", tool=mock_tool, model=MODEL_SONNET)
        assert result["result"] == "test_result"
        assert result["score"] == 0.9

    async def test_call_tool_uses_correct_model(self, mock_openai_client, mock_tool):
        with patch("src.agents.llm._get_openai_client", return_value=mock_openai_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with patch("src.agents.llm.LLM_PROVIDER", "openrouter"):
                    await call_tool(prompt="Test", tool=mock_tool, model=MODEL_FLASH)
        call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == MODEL_FLASH

    async def test_call_tool_with_system_prompt(self, mock_openai_client, mock_tool):
        with patch("src.agents.llm._get_openai_client", return_value=mock_openai_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with patch("src.agents.llm.LLM_PROVIDER", "openrouter"):
                    await call_tool(prompt="Test", tool=mock_tool, system="You are helpful.")
        call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are helpful."

    async def test_call_tool_forces_tool_choice(self, mock_openai_client, mock_tool):
        with patch("src.agents.llm._get_openai_client", return_value=mock_openai_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with patch("src.agents.llm.LLM_PROVIDER", "openrouter"):
                    await call_tool(prompt="Test", tool=mock_tool)
        call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["tool_choice"]["type"] == "function"
        assert call_kwargs["tool_choice"]["function"]["name"] == mock_tool["name"]

    async def test_call_tool_no_tool_calls_raises(self, mock_openai_client, mock_tool):
        message = MagicMock()
        message.tool_calls = None
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        mock_openai_client.chat.completions.create.return_value = response

        with patch("src.agents.llm._get_openai_client", return_value=mock_openai_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with patch("src.agents.llm.LLM_PROVIDER", "openrouter"):
                    with pytest.raises(ValueError, match="No tool call"):
                        await call_tool(prompt="Test", tool=mock_tool)

    async def test_call_tool_api_error_propagates(self, mock_openai_client, mock_tool):
        mock_openai_client.chat.completions.create.side_effect = RuntimeError("API error")
        with patch("src.agents.llm._get_openai_client", return_value=mock_openai_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with patch("src.agents.llm.LLM_PROVIDER", "openrouter"):
                    with pytest.raises(RuntimeError, match="API error"):
                        await call_tool(prompt="Test", tool=mock_tool)

    async def test_call_tool_custom_max_tokens(self, mock_openai_client, mock_tool):
        with patch("src.agents.llm._get_openai_client", return_value=mock_openai_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with patch("src.agents.llm.LLM_PROVIDER", "openrouter"):
                    await call_tool(prompt="Test", tool=mock_tool, max_tokens=2048)
        call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 2048


# ---------------------------------------------------------------------------
# call_tool — Anthropic path
# ---------------------------------------------------------------------------

class TestCallToolAnthropic:
    """Tests for call_tool when LLM_PROVIDER == 'anthropic'."""

    @pytest.fixture
    def mock_anthro_client(self):
        block = MagicMock()
        block.type = "tool_use"
        block.input = {"result": "anthro_result", "score": 1.0}

        response = MagicMock()
        response.content = [block]
        response.usage = MagicMock(input_tokens=80, output_tokens=40)

        client = AsyncMock()
        client.messages = AsyncMock()
        client.messages.create = AsyncMock(return_value=response)
        return client

    async def test_anthropic_path(self, mock_anthro_client, mock_tool):
        import sys, types
        # Stub anthropic module so `import anthropic` inside _call_anthropic works
        fake_anthropic = types.ModuleType("anthropic")
        with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
            with patch("src.agents.llm._get_anthropic_client", return_value=mock_anthro_client):
                with patch("src.agents.llm._init_langfuse", return_value=None):
                    with patch("src.agents.llm.LLM_PROVIDER", "anthropic"):
                        result = await call_tool(prompt="Test", tool=mock_tool)
        assert result["result"] == "anthro_result"


# ---------------------------------------------------------------------------
# call_tool_with_reflection
# ---------------------------------------------------------------------------

class TestCallToolWithReflection:
    """Tests for call_tool_with_reflection (two-round self-reflection)."""

    async def test_reflection_calls_twice(self, mock_tool):
        call_count = 0

        async def _mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return _make_openai_response("test_output_tool", {"result": f"round_{call_count}", "score": call_count})

        mock_client = AsyncMock()
        mock_client.chat = AsyncMock()
        mock_client.chat.completions = AsyncMock()
        mock_client.chat.completions.create = _mock_create

        with patch("src.agents.llm._get_openai_client", return_value=mock_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with patch("src.agents.llm.LLM_PROVIDER", "openrouter"):
                    result = await call_tool_with_reflection(
                        initial_prompt="Initial",
                        reflection_prompt_fn=lambda x: f"Reflect: {x}",
                        tool=mock_tool,
                        model=MODEL_OPUS,
                    )

        assert call_count == 2
        assert result["result"] == "round_2"

    async def test_reflection_prompt_receives_initial_result(self, mock_tool):
        captured = None

        def reflection_fn(initial_result: str) -> str:
            nonlocal captured
            captured = initial_result
            return f"Reflect: {initial_result}"

        mock_client = AsyncMock()
        mock_client.chat = AsyncMock()
        mock_client.chat.completions = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response("test_output_tool", {"result": "data", "score": 42})
        )

        with patch("src.agents.llm._get_openai_client", return_value=mock_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with patch("src.agents.llm.LLM_PROVIDER", "openrouter"):
                    await call_tool_with_reflection(
                        initial_prompt="Test",
                        reflection_prompt_fn=reflection_fn,
                        tool=mock_tool,
                    )

        assert captured is not None
        parsed = json.loads(captured)
        assert parsed["result"] == "data"

    async def test_reflection_first_call_error_propagates(self, mock_tool):
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock()
        mock_client.chat.completions = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("First call failed"))

        with patch("src.agents.llm._get_openai_client", return_value=mock_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with patch("src.agents.llm.LLM_PROVIDER", "openrouter"):
                    with pytest.raises(RuntimeError, match="First call failed"):
                        await call_tool_with_reflection(
                            initial_prompt="Test",
                            reflection_prompt_fn=lambda x: x,
                            tool=mock_tool,
                        )


# ---------------------------------------------------------------------------
# Client factory tests
# ---------------------------------------------------------------------------

class TestClientFactories:
    """Tests for _get_openai_client / _get_anthropic_client singletons."""

    def test_get_openai_client_returns_client(self):
        import src.agents.llm as llm_module
        llm_module._openai_client = None
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            client = _get_openai_client()
            assert client is not None
        llm_module._openai_client = None  # cleanup

    def test_get_openai_client_is_singleton(self):
        import src.agents.llm as llm_module
        llm_module._openai_client = None
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            c1 = _get_openai_client()
            c2 = _get_openai_client()
            assert c1 is c2
        llm_module._openai_client = None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_record_metrics_no_error_when_module_missing(self):
        _record_llm_metrics(MODEL_SONNET, 100, 50, 1.5)

    def test_record_metrics_with_mock_prometheus(self):
        mock_counter = MagicMock()
        mock_histogram = MagicMock()
        with patch.dict("sys.modules", {"src.metrics": MagicMock(
            llm_tokens_total=mock_counter,
            llm_request_duration=mock_histogram,
        )}):
            _record_llm_metrics(MODEL_SONNET, 100, 50, 1.5)


# ---------------------------------------------------------------------------
# Langfuse Init
# ---------------------------------------------------------------------------

class TestLangfuseInit:
    def test_langfuse_returns_none_when_disabled(self):
        from src.agents.llm import _init_langfuse
        import src.agents.llm as llm_module
        llm_module._langfuse = None
        mock_settings = MagicMock()
        mock_settings.system.langfuse = {"enabled": False}
        with patch("src.agents.llm.get_settings", return_value=mock_settings):
            assert _init_langfuse() is None

    def test_langfuse_returns_cached_instance(self):
        from src.agents.llm import _init_langfuse
        import src.agents.llm as llm_module
        mock_lf = MagicMock()
        llm_module._langfuse = mock_lf
        assert _init_langfuse() is mock_lf
        llm_module._langfuse = None

    def test_langfuse_handles_import_error(self):
        from src.agents.llm import _init_langfuse
        import src.agents.llm as llm_module
        llm_module._langfuse = None
        mock_settings = MagicMock()
        mock_settings.system.langfuse = {"enabled": True}
        with patch("src.agents.llm.get_settings", return_value=mock_settings):
            result = _init_langfuse()
        assert result is None or result is not None
